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


def ler_codigos_csv(caminho_csv):
    codigos = []
    with open(caminho_csv, newline="") as csvfile:
        for linha in csv.reader(csvfile):
            if not linha:
                continue
            codigo = linha[0].strip()
            if codigo:
                codigos.append(codigo)
    return codigos


def gerar_codigos_intervalo(inicio, fim):
    inicio_txt = str(inicio).strip()
    fim_txt = str(fim).strip()

    if not inicio_txt or not fim_txt:
        raise ValueError("Informe o número inicial e o número final.")
    if not re.fullmatch(r"[0-9]+", inicio_txt) or not re.fullmatch(r"[0-9]+", fim_txt):
        raise ValueError("O intervalo deve conter apenas números.")

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
        description="Gera um PDF de etiquetas Code 128 a partir de um CSV ou de um intervalo."
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        help="Arquivo CSV com um código por linha (ainda disponível via script).",
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
            raise SystemExit("Use CSV ou intervalo, não os dois ao mesmo tempo.")
        try:
            codigos = gerar_codigos_intervalo(args.inicio, args.fim)
        except ValueError as erro:
            raise SystemExit(str(erro))
    else:
        caminho_csv = args.csv_path or CSV_PADRAO
        if not os.path.exists(caminho_csv):
            raise SystemExit(f"Arquivo CSV não encontrado: {caminho_csv}")
        codigos = ler_codigos_csv(caminho_csv)

    Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
    try:
        pdf_path = gerar_pdf(codigos, destino=args.saida, nome_do_orgao=args.orgao)
    except ValueError as erro:
        raise SystemExit(str(erro))
    print(f"✅ PDF gerado com sucesso: {pdf_path}")
