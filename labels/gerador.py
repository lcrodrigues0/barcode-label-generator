import argparse
import barcode
import csv
import os
import re
from io import BytesIO
from itertools import takewhile
from math import ceil
from pathlib import Path

from barcode.writer import ImageWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


LARGURA_PAGINA, ALTURA_PAGINA = A4
ALTURA_IMAGEM = 0.65 * (1.5 * 28.35)
LARGURA_IMAGEM = 0.8 * (5 * 28.35)
MARGEM_ESQUERDA = 7.5
MARGEM_DIREITA = LARGURA_PAGINA - 100
MARGEM_SUPERIOR = ALTURA_PAGINA - 80
MARGEM_INFERIOR = 0
ESPACO_VERTICAL = 80
ESPACO_HORIZONTAL = LARGURA_IMAGEM + 5
FONT_TYPE = "Helvetica-Bold"
FONT_SIZE = 0.8 * 10
BARCODE_OPTIONS = {"write_text": False}
RAIZ_PROJETO = Path(__file__).resolve().parent.parent
CSV_PADRAO = str(RAIZ_PROJETO / "data" / "codigos-oficiais.csv")
PDF_PADRAO = str(RAIZ_PROJETO / "output" / "codigos_barras.pdf")
ORGAO_PADRAO = "MTE - SRTE/ES"
MAX_CODIGOS = 10_000
MAX_ORGAO = 40
MAX_TAMANHO_CODIGO = 40  # caracteres por código (planilha) ou dígitos (intervalo)


# --------------------------------------------------------------------------
# Leitura de planilhas (um código por linha, na primeira coluna)
# --------------------------------------------------------------------------

FORMATOS_PLANILHA = (".csv", ".txt", ".xlsx", ".ods")
# XLSX e ODS são arquivos ZIP. Um arquivo pequeno pode se expandir para centenas de MB
# ao ser descompactado ("zip bomb"); por isso o tamanho descompactado é limitado antes
# de abrir o conteúdo. 10.000 códigos ocupam cerca de 2 MB descompactados.
MAX_DESCOMPACTADO_MB = 10

_NS_ODS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
}
_TIPOS_NUMERICOS_ODS = {"float", "percentage", "currency"}


def _normalizar_valor(valor):
    """Converte o valor de uma célula em texto (12385319.0 -> "12385319")."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def _linhas_texto(conteudo):
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1")
    try:
        dialeto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t")
    except csv.Error:
        dialeto = csv.excel  # uma coluna só: não há delimitador para detectar
    for linha in csv.reader(texto.splitlines(), dialeto):
        yield linha[0] if linha else ""


def _linhas_xlsx(conteudo):
    import openpyxl

    livro = openpyxl.load_workbook(BytesIO(conteudo), read_only=True, data_only=True)
    try:
        for linha in livro.worksheets[0].iter_rows(max_col=1, values_only=True):
            yield linha[0] if linha else None
    finally:
        livro.close()


def _verificar_tamanho_descompactado(conteudo):
    """Recusa ZIPs (XLSX/ODS) que ficariam grandes demais ao descompactar.

    O zipfile do Python não entrega mais bytes do que o tamanho declarado de cada
    arquivo interno, então somar os tamanhos declarados é suficiente.
    """
    import zipfile

    try:
        with zipfile.ZipFile(BytesIO(conteudo)) as arquivo:
            total = sum(item.file_size for item in arquivo.infolist())
    except zipfile.BadZipFile as erro:
        raise ValueError(
            "Não foi possível ler a planilha. Verifique se o arquivo não está corrompido."
        ) from erro
    if total > MAX_DESCOMPACTADO_MB * 1024 * 1024:
        raise ValueError(
            "A planilha é grande demais depois de descompactada "
            f"(máximo de {MAX_DESCOMPACTADO_MB} MB). Remova linhas ou colunas que não são usadas."
        )


def _linhas_ods(conteudo):
    """Lê a 1ª coluna da 1ª tabela do ODS em fluxo (sem montar o XML inteiro na memória)."""
    import xml.etree.ElementTree as ET
    import zipfile

    t = "{%s}" % _NS_ODS["table"]
    o = "{%s}" % _NS_ODS["office"]
    tag_tabela, tag_linha = f"{t}table", f"{t}table-row"
    tags_celula = (f"{t}table-cell", f"{t}covered-table-cell")

    with zipfile.ZipFile(BytesIO(conteudo)) as arquivo, arquivo.open("content.xml") as xml:
        tabela = None
        for evento, elemento in ET.iterparse(xml, events=("start", "end")):
            if evento == "start":
                if elemento.tag == tag_tabela and tabela is None:
                    tabela = elemento
                continue
            if elemento is tabela:
                return  # só a primeira tabela (aba)
            if tabela is None or elemento.tag != tag_linha:
                continue

            celula = next((c for c in elemento if c.tag in tags_celula), None)
            valor = None
            if celula is not None:
                if celula.get(f"{o}value-type") in _TIPOS_NUMERICOS_ODS:
                    valor = float(celula.get(f"{o}value"))
                else:
                    valor = "".join(celula.itertext())
            # Linhas repetidas: o LibreOffice grava as linhas vazias do fim assim.
            repeticoes = int(elemento.get(f"{t}number-rows-repeated", "1"))
            if not _normalizar_valor(valor):
                repeticoes = 1
            # Libera as linhas já lidas (mantém a memória constante).
            tabela.clear()
            for _ in range(min(repeticoes, MAX_CODIGOS + 2)):
                yield valor


def _coletar_linhas(valores):
    """(número da linha, texto) das linhas preenchidas, parando logo após o limite.

    Para cedo de propósito: com o cabeçalho, até MAX_CODIGOS + 1 linhas são válidas;
    qualquer coisa além disso já basta para recusar a planilha.
    """
    linhas = []
    for numero, valor in enumerate(valores, start=1):
        texto = _normalizar_valor(valor)
        if texto:
            linhas.append((numero, texto))
            if len(linhas) > MAX_CODIGOS + 1:
                break
    return linhas


def _validar_codigos(linhas):
    """Recebe (número da linha, texto) das linhas preenchidas e devolve os códigos válidos."""

    # Cabeçalho: 1ª linha com texto e todas as outras só com números.
    if len(linhas) > 1 and not linhas[0][1].isdigit() and all(t.isdigit() for _, t in linhas[1:]):
        linhas = linhas[1:]

    if not linhas:
        raise ValueError("Nenhum código encontrado na planilha.")
    if len(linhas) > MAX_CODIGOS:
        raise ValueError(f"A planilha não pode ter mais de {MAX_CODIGOS} códigos.")

    for numero, texto in linhas:
        if len(texto) > MAX_TAMANHO_CODIGO:
            raise ValueError(
                f"Linha {numero}: o código deve ter no máximo {MAX_TAMANHO_CODIGO} caracteres."
            )
        if not all(32 <= ord(ch) < 127 for ch in texto):
            raise ValueError(
                f"Linha {numero}: o código \"{texto}\" tem caracteres não aceitos "
                "(use só letras sem acento, números e símbolos comuns)."
            )
    return [texto for _, texto in linhas]


def ler_codigos_planilha(conteudo, nome_arquivo):
    """Lê os códigos da 1ª coluna de um .csv, .txt, .xlsx ou .ods (em bytes)."""
    extensao = Path(nome_arquivo or "").suffix.lower()
    leitores = {
        ".csv": _linhas_texto,
        ".txt": _linhas_texto,
        ".xlsx": _linhas_xlsx,
        ".ods": _linhas_ods,
    }
    if extensao not in leitores:
        raise ValueError("Formato não suportado. Use .csv, .txt, .xlsx ou .ods.")
    if extensao in (".xlsx", ".ods"):
        _verificar_tamanho_descompactado(conteudo)
    try:
        linhas = _coletar_linhas(leitores[extensao](conteudo))
    except Exception as erro:  # arquivo corrompido ou com outro formato
        raise ValueError(
            "Não foi possível ler a planilha. Verifique se o arquivo não está corrompido."
        ) from erro
    return _validar_codigos(linhas)


def ler_codigos_csv(caminho_csv):
    """Lê os códigos de uma planilha em disco (qualquer formato aceito)."""
    with open(caminho_csv, "rb") as arquivo:
        return ler_codigos_planilha(arquivo.read(), caminho_csv)


def gerar_codigos_intervalo(inicio, fim):
    inicio_txt = str(inicio).strip()
    fim_txt = str(fim).strip()

    if not inicio_txt or not fim_txt:
        raise ValueError("Informe o número inicial e o número final.")
    if not re.fullmatch(r"[0-9]+", inicio_txt) or not re.fullmatch(r"[0-9]+", fim_txt):
        raise ValueError("O intervalo deve conter apenas números.")
    # Antes de converter: evita números gigantes (e a mensagem interna do Python
    # para inteiros com milhares de dígitos) e códigos longos demais para a etiqueta.
    if max(len(inicio_txt), len(fim_txt)) > MAX_TAMANHO_CODIGO:
        raise ValueError(f"Os números devem ter no máximo {MAX_TAMANHO_CODIGO} dígitos.")

    inicio_n = int(inicio_txt)
    fim_n = int(fim_txt)
    if fim_n < inicio_n:
        raise ValueError("O número final deve ser maior ou igual ao inicial.")

    quantidade = fim_n - inicio_n + 1
    if quantidade > MAX_CODIGOS:
        raise ValueError(f"O intervalo não pode ter mais de {MAX_CODIGOS} códigos.")

    largura = max(len(inicio_txt), len(fim_txt))
    return [str(n).zfill(largura) for n in range(inicio_n, fim_n + 1)]


def tamanho_fonte_ajustado(texto, largura_maxima=LARGURA_IMAGEM, tamanho=FONT_SIZE):
    """Reduz o tamanho da fonte, se preciso, para o texto caber na largura da etiqueta."""
    largura = stringWidth(texto, FONT_TYPE, tamanho)
    if largura <= largura_maxima:
        return tamanho
    return tamanho * largura_maxima / largura


def _desenhar_centralizado(c, texto, x, y, tamanho):
    c.setFont(FONT_TYPE, tamanho)
    largura = c.stringWidth(texto, FONT_TYPE, tamanho)
    c.drawString(x + (LARGURA_IMAGEM - largura) / 2, y, texto)


def _posicoes():
    """Gera (página, x, y) de cada etiqueta, na ordem em que são impressas."""
    pagina = 0
    x = MARGEM_ESQUERDA
    y = MARGEM_SUPERIOR
    while True:
        if y < MARGEM_INFERIOR:
            pagina += 1
            y = MARGEM_SUPERIOR
        yield pagina, x, y
        x += ESPACO_HORIZONTAL
        if x > MARGEM_DIREITA:
            y -= ESPACO_VERTICAL
            x = MARGEM_ESQUERDA


ETIQUETAS_POR_PAGINA = sum(1 for _ in takewhile(lambda p: p[0] == 0, _posicoes()))


def contar_paginas(quantidade_codigos):
    return ceil(quantidade_codigos / ETIQUETAS_POR_PAGINA)


def gerar_pdf(codigos, destino=PDF_PADRAO, nome_do_orgao=ORGAO_PADRAO):
    if not codigos:
        raise ValueError("Nenhum código para gerar.")
    if len(codigos) > MAX_CODIGOS:
        raise ValueError(f"Não é possível gerar mais de {MAX_CODIGOS} códigos.")

    # Órgão vazio: a etiqueta sai sem texto acima do código (posições não mudam).
    nome_do_orgao = (nome_do_orgao or "").strip()
    tamanho_orgao = tamanho_fonte_ajustado(nome_do_orgao) if nome_do_orgao else None

    c = canvas.Canvas(destino, pagesize=A4)

    pagina_atual = 0
    for codigo_num, (pagina, x, y) in zip(codigos, _posicoes()):
        if pagina != pagina_atual:
            c.showPage()
            pagina_atual = pagina

        imagem = BytesIO()
        barcode.get("code128", codigo_num, writer=ImageWriter()).write(
            imagem, BARCODE_OPTIONS
        )
        imagem.seek(0)

        mt = ALTURA_IMAGEM + 4
        mb = -10

        if nome_do_orgao:
            _desenhar_centralizado(c, nome_do_orgao, x, y + mt, tamanho_orgao)
        c.drawImage(
            ImageReader(imagem),
            x,
            y,
            width=LARGURA_IMAGEM,
            height=ALTURA_IMAGEM,
        )
        _desenhar_centralizado(
            c, codigo_num, x, y + mb, tamanho_fonte_ajustado(codigo_num)
        )

    c.save()
    return destino


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Gera um PDF de etiquetas Code 128 a partir de uma planilha ou de um intervalo."
    )
    parser.add_argument(
        "--planilha",
        "--csv",
        dest="csv_path",
        help="Planilha (.csv, .txt, .xlsx ou .ods) com um código por linha, na 1ª coluna.",
    )
    parser.add_argument("--inicio", help="Primeiro número do intervalo.")
    parser.add_argument("--fim", help="Último número do intervalo.")
    parser.add_argument(
        "--saida",
        default=PDF_PADRAO,
        help="Caminho do PDF gerado (padrão: output/codigos_barras.pdf).",
    )
    parser.add_argument(
        "--orgao",
        default=ORGAO_PADRAO,
        help=f'Texto impresso acima do código (padrão: {ORGAO_PADRAO}). Use --orgao "" para não imprimir texto.',
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.inicio or args.fim:
        if not (args.inicio and args.fim):
            raise SystemExit("Informe --inicio e --fim juntos.")
        if args.csv_path:
            raise SystemExit("Use planilha (CSV) ou intervalo, não os dois ao mesmo tempo.")
        try:
            codigos = gerar_codigos_intervalo(args.inicio, args.fim)
        except ValueError as erro:
            raise SystemExit(str(erro))
    else:
        caminho_csv = args.csv_path or CSV_PADRAO
        if not os.path.exists(caminho_csv):
            raise SystemExit(f"Arquivo não encontrado: {caminho_csv}")
        try:
            codigos = ler_codigos_csv(caminho_csv)
        except ValueError as erro:
            raise SystemExit(str(erro))

    Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
    try:
        pdf_path = gerar_pdf(codigos, destino=args.saida, nome_do_orgao=args.orgao)
    except ValueError as erro:
        raise SystemExit(str(erro))
    print(f"✅ PDF gerado com sucesso: {pdf_path}")
