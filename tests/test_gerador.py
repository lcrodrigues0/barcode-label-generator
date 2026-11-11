"""Testes das funções de geração de códigos e do PDF (labels/gerador.py)."""

import subprocess
import sys
from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from labels import gerador
from labels.gerador import (
    FONT_SIZE,
    FONT_TYPE,
    LARGURA_IMAGEM,
    MAX_CODIGOS,
    MAX_ORGAO,
    ORGAO_PADRAO,
    gerar_codigos_intervalo,
    gerar_pdf,
    ler_codigos_csv,
    ler_codigos_planilha,
    tamanho_fonte_ajustado,
)
from auxiliares_pdf import contar_codigos_de_barras
from planilhas import ods, xlsx

ETIQUETAS_POR_PAGINA = 50  # 5 colunas x 10 linhas em A4


def _pdf(codigos, **kwargs):
    destino = BytesIO()
    gerar_pdf(codigos, destino=destino, **kwargs)
    destino.seek(0)
    return PdfReader(destino)


def _texto(reader):
    return "\n".join(pagina.extract_text() for pagina in reader.pages)


# --------------------------------------------------------------------------
# gerar_codigos_intervalo
# --------------------------------------------------------------------------


class TestGerarCodigosIntervalo:
    def test_intervalo_simples(self):
        assert gerar_codigos_intervalo("10", "13") == ["10", "11", "12", "13"]

    def test_inicio_igual_fim_gera_um_codigo(self):
        assert gerar_codigos_intervalo("12385319", "12385319") == ["12385319"]

    def test_aceita_inteiros(self):
        assert gerar_codigos_intervalo(5, 7) == ["5", "6", "7"]

    def test_remove_espacos(self):
        assert gerar_codigos_intervalo("  8 ", " 9\n") == ["8", "9"]

    def test_preserva_zeros_a_esquerda(self):
        assert gerar_codigos_intervalo("0098", "0101") == [
            "0098",
            "0099",
            "0100",
            "0101",
        ]

    def test_largura_usa_o_maior_dos_dois(self):
        assert gerar_codigos_intervalo("8", "010") == ["008", "009", "010"]

    def test_bate_com_primeiro_bloco_do_csv_oficial(self):
        # O CSV oficial tem vários blocos; o primeiro vai de 12385319 a 12385338.
        esperados = ler_codigos_csv(gerador.CSV_PADRAO)[:20]
        assert esperados[-1] == "12385338"
        gerados = gerar_codigos_intervalo(esperados[0], esperados[-1])
        assert gerados == esperados

    def test_limite_maximo_permitido(self):
        codigos = gerar_codigos_intervalo("1", str(MAX_CODIGOS))
        assert len(codigos) == MAX_CODIGOS

    def test_acima_do_limite(self):
        with pytest.raises(ValueError, match="mais de"):
            gerar_codigos_intervalo("1", str(MAX_CODIGOS + 1))

    @pytest.mark.parametrize(
        "inicio, fim",
        [("", "10"), ("10", ""), ("   ", "10"), ("", "")],
    )
    def test_campos_vazios(self, inicio, fim):
        with pytest.raises(ValueError, match="Informe"):
            gerar_codigos_intervalo(inicio, fim)

    @pytest.mark.parametrize(
        "inicio, fim",
        [
            ("abc", "10"),
            ("10", "2x"),
            ("-5", "10"),
            ("1.5", "10"),
            ("1 2", "20"),
            ("1e3", "2000"),
        ],
    )
    def test_valores_nao_numericos(self, inicio, fim):
        with pytest.raises(ValueError, match="apenas números"):
            gerar_codigos_intervalo(inicio, fim)

    @pytest.mark.parametrize("inicio, fim", [("²", "5"), ("1", "³"), ("١٢", "13")])
    def test_digitos_unicode_sao_rejeitados(self, inicio, fim):
        with pytest.raises(ValueError, match="apenas números"):
            gerar_codigos_intervalo(inicio, fim)

    def test_fim_menor_que_inicio(self):
        with pytest.raises(ValueError, match="maior ou igual"):
            gerar_codigos_intervalo("20", "10")

    def test_numero_com_o_maximo_de_digitos(self):
        maximo = "1" * gerador.MAX_TAMANHO_CODIGO
        assert gerar_codigos_intervalo(maximo, maximo) == [maximo]

    @pytest.mark.parametrize("inicio, fim", [("1" * 41, "1" * 41), ("1", "1" * 41), ("9" * 5000, "9" * 5000)])
    def test_numero_longo_demais(self, inicio, fim):
        with pytest.raises(ValueError, match="no máximo 40 dígitos"):
            gerar_codigos_intervalo(inicio, fim)


# --------------------------------------------------------------------------
# ler_codigos_csv
# --------------------------------------------------------------------------


class TestLerCodigosCsv:
    def test_ignora_linhas_vazias_e_espacos(self, tmp_path):
        arquivo = tmp_path / "c.csv"
        arquivo.write_text("123\n\n  456  \n,\n789,extra\n")
        assert ler_codigos_csv(arquivo) == ["123", "456", "789"]

    def test_csv_oficial(self):
        codigos = ler_codigos_csv(gerador.CSV_PADRAO)
        assert codigos
        assert all(c.isdigit() for c in codigos)

    def test_le_xlsx_do_disco(self, tmp_path):
        arquivo = tmp_path / "c.xlsx"
        arquivo.write_bytes(xlsx([1, 2]))
        assert ler_codigos_csv(arquivo) == ["1", "2"]


# --------------------------------------------------------------------------
# ler_codigos_planilha
# --------------------------------------------------------------------------


class TestLerCodigosPlanilha:
    @pytest.mark.parametrize(
        "conteudo",
        [
            b"111\n222\n",
            b"111,a\n222,b\n",
            b"111;a\n222;b\n",
            b"111\ta\n222\tb\n",
            b"\xef\xbb\xbf111\r\n222\r\n",  # UTF-8 com BOM e quebra de linha do Windows
        ],
    )
    def test_csv_primeira_coluna(self, conteudo):
        assert ler_codigos_planilha(conteudo, "a.csv") == ["111", "222"]

    def test_txt(self):
        assert ler_codigos_planilha(b"001\n002", "a.TXT") == ["001", "002"]

    def test_csv_latin1(self):
        conteudo = "Código\n10\n".encode("latin-1")
        assert ler_codigos_planilha(conteudo, "a.csv") == ["10"]

    def test_xlsx_numeros_e_texto(self):
        conteudo = xlsx([12385319, 12385320.0, None, "000123", "  A-1  "])
        assert ler_codigos_planilha(conteudo, "a.xlsx") == ["12385319", "12385320", "000123", "A-1"]

    def test_ods_com_linhas_repetidas_no_fim(self):
        conteudo = ods([12385319, None, "0007"], linhas_vazias_no_fim=1_048_000)
        assert ler_codigos_planilha(conteudo, "a.ods") == ["12385319", "0007"]

    @pytest.mark.parametrize("gerar", [xlsx, ods])
    def test_cabecalho_ignorado(self, gerar):
        assert ler_codigos_planilha(gerar(["codigo", 1, 2]), "a.xlsx" if gerar is xlsx else "a.ods") == ["1", "2"]

    def test_cabecalho_mantido_se_ha_outros_textos(self):
        assert ler_codigos_planilha(b"ABC\nDEF\n12\n", "a.csv") == ["ABC", "DEF", "12"]

    def test_codigo_unico_com_letras_nao_e_cabecalho(self):
        assert ler_codigos_planilha(b"ABC\n", "a.csv") == ["ABC"]

    def test_sem_codigos(self):
        with pytest.raises(ValueError, match="Nenhum código"):
            ler_codigos_planilha(b"\n \n", "a.csv")

    def test_somente_cabecalho_vira_codigo(self):
        # Uma linha só não tem como ser identificada como cabeçalho.
        assert ler_codigos_planilha(b"codigo\n", "a.csv") == ["codigo"]

    def test_caractere_nao_aceito_indica_linha(self):
        with pytest.raises(ValueError, match="Linha 3"):
            ler_codigos_planilha("1\n2\nação\n".encode(), "a.csv")

    def test_codigo_longo_demais(self):
        with pytest.raises(ValueError, match="no máximo 40"):
            ler_codigos_planilha(b"1\n" + b"9" * 41 + b"\n", "a.csv")

    def test_acima_do_limite(self):
        conteudo = "\n".join(str(n) for n in range(MAX_CODIGOS + 1)).encode()
        with pytest.raises(ValueError, match="mais de"):
            ler_codigos_planilha(conteudo, "a.csv")

    @pytest.mark.parametrize("nome", ["a.pdf", "a.xls", "sem_extensao", ""])
    def test_formato_nao_suportado(self, nome):
        with pytest.raises(ValueError, match="Formato não suportado"):
            ler_codigos_planilha(b"1", nome)

    @pytest.mark.parametrize("nome", ["a.xlsx", "a.ods"])
    def test_arquivo_corrompido(self, nome):
        with pytest.raises(ValueError, match="Não foi possível ler"):
            ler_codigos_planilha(b"isto nao e um zip", nome)


# --------------------------------------------------------------------------
# gerar_pdf
# --------------------------------------------------------------------------


class TestGerarPdf:
    def test_gera_pdf_valido(self):
        destino = BytesIO()
        retorno = gerar_pdf(["123"], destino=destino)
        assert retorno is destino
        assert destino.getvalue().startswith(b"%PDF")

    def test_conteudo_tem_codigos_e_orgao(self):
        codigos = gerar_codigos_intervalo("12385319", "12385323")
        texto = _texto(_pdf(codigos))
        for codigo in codigos:
            assert codigo in texto
        assert texto.count(ORGAO_PADRAO) == len(codigos)

    def test_orgao_personalizado(self):
        texto = _texto(_pdf(["1", "2"], nome_do_orgao="PREFEITURA X"))
        assert texto.count("PREFEITURA X") == 2
        assert ORGAO_PADRAO not in texto

    @pytest.mark.parametrize("orgao", ["", "   ", None])
    def test_orgao_vazio_sem_texto(self, orgao):
        reader = _pdf(["123"], nome_do_orgao=orgao)
        assert _texto(reader).strip() == "123"
        assert contar_codigos_de_barras(reader.pages[0]) == 1

    def test_orgao_vazio_mantem_posicao_do_numero(self):
        com = [t for t in _textos_com_posicao(_pdf(["123"]).pages[0]) if t[0] == "123"]
        sem = _textos_com_posicao(_pdf(["123"], nome_do_orgao="").pages[0])
        assert sem == com

    def test_uma_imagem_por_codigo(self):
        reader = _pdf(["1", "2", "3"])
        assert contar_codigos_de_barras(reader.pages[0]) == 3

    def test_pagina_a4(self):
        pagina = _pdf(["1"]).pages[0]
        assert round(float(pagina.mediabox.width)) == 595
        assert round(float(pagina.mediabox.height)) == 842

    @pytest.mark.parametrize(
        "quantidade, paginas",
        [
            (1, 1),
            (ETIQUETAS_POR_PAGINA, 1),
            (ETIQUETAS_POR_PAGINA + 1, 2),
            (ETIQUETAS_POR_PAGINA * 2, 2),
            (ETIQUETAS_POR_PAGINA * 2 + 1, 3),
        ],
    )
    def test_quebra_de_pagina(self, quantidade, paginas):
        codigos = [str(n) for n in range(1, quantidade + 1)]
        reader = _pdf(codigos)
        assert len(reader.pages) == paginas
        assert sum(contar_codigos_de_barras(p) for p in reader.pages) == quantidade

    def test_etiquetas_dentro_da_pagina(self):
        """Nenhum texto pode sair dos limites da folha A4."""
        codigos = [str(n).zfill(8) for n in range(ETIQUETAS_POR_PAGINA)]
        reader = _pdf(codigos)
        pagina = reader.pages[0]
        largura = float(pagina.mediabox.width)
        altura = float(pagina.mediabox.height)
        posicoes = []

        def visitor(text, cm, tm, font_dict, font_size):
            if text.strip():
                posicoes.append((tm[4], tm[5]))

        pagina.extract_text(visitor_text=visitor)
        assert len(posicoes) == ETIQUETAS_POR_PAGINA * 2
        for x, y in posicoes:
            assert 0 <= x <= largura
            assert 0 <= y <= altura

    def test_lista_vazia(self):
        with pytest.raises(ValueError, match="Nenhum código"):
            gerar_pdf([], destino=BytesIO())

    def test_acima_do_limite(self):
        with pytest.raises(ValueError, match="mais de"):
            gerar_pdf(["1"] * (MAX_CODIGOS + 1), destino=BytesIO())

    def test_grava_em_arquivo(self, tmp_path):
        saida = tmp_path / "saida.pdf"
        gerar_pdf(["42"], destino=str(saida))
        assert saida.read_bytes().startswith(b"%PDF")


# --------------------------------------------------------------------------
# Ajuste do tamanho da fonte
# --------------------------------------------------------------------------


def _textos_com_posicao(pagina):
    """Lista (texto, x, tamanho da fonte) de cada texto desenhado na página."""
    textos = []

    def visitor(text, cm, tm, font_dict, font_size):
        if text.strip():
            textos.append((text.strip(), tm[4], font_size))

    pagina.extract_text(visitor_text=visitor)
    return textos


class TestTamanhoFonte:
    def test_texto_curto_mantem_tamanho(self):
        assert tamanho_fonte_ajustado(ORGAO_PADRAO) == FONT_SIZE

    @pytest.mark.parametrize(
        "texto",
        ["MINISTÉRIO DO TRABALHO - ES", "W" * MAX_ORGAO, "1" * 60],
    )
    def test_texto_longo_cabe_na_etiqueta(self, texto):
        tamanho = tamanho_fonte_ajustado(texto)
        assert tamanho < FONT_SIZE
        assert stringWidth(texto, FONT_TYPE, tamanho) <= LARGURA_IMAGEM + 0.01

    @pytest.mark.parametrize(
        "orgao", [ORGAO_PADRAO, "MINISTÉRIO DO TRABALHO - ES", "W" * MAX_ORGAO]
    )
    def test_orgaos_vizinhos_nao_se_sobrepoem(self, orgao):
        """Na mesma linha, cada órgão termina antes do próximo começar."""
        pagina = _pdf([str(n) for n in range(5)], nome_do_orgao=orgao).pages[0]
        faixas = sorted(
            (x, x + stringWidth(t, FONT_TYPE, tam))
            for t, x, tam in _textos_com_posicao(pagina)
            if t == orgao
        )
        assert len(faixas) == 5
        for (_, fim), (inicio_prox, _) in zip(faixas, faixas[1:]):
            assert fim <= inicio_prox
        assert faixas[-1][1] <= float(pagina.mediabox.width)

    def test_orgao_curto_usa_fonte_normal_no_pdf(self):
        pagina = _pdf(["1"]).pages[0]
        tamanhos = {tam for t, _, tam in _textos_com_posicao(pagina)}
        assert tamanhos == {FONT_SIZE}

    def test_orgao_longo_nao_afeta_fonte_do_numero(self):
        pagina = _pdf(["12385319"], nome_do_orgao="W" * MAX_ORGAO).pages[0]
        fontes = {t: tam for t, _, tam in _textos_com_posicao(pagina)}
        assert fontes["12385319"] == FONT_SIZE
        assert fontes["W" * MAX_ORGAO] < FONT_SIZE

    def test_fonte_ajustada_mantida_apos_quebra_de_pagina(self):
        orgao = "W" * MAX_ORGAO
        reader = _pdf([str(n) for n in range(51)], nome_do_orgao=orgao)
        segunda = _textos_com_posicao(reader.pages[1])
        tamanhos = [tam for t, _, tam in segunda if t == orgao]
        assert tamanhos
        assert tamanhos == pytest.approx([tamanho_fonte_ajustado(orgao)] * len(tamanhos))


# --------------------------------------------------------------------------
# Linha de comando
# --------------------------------------------------------------------------


class TestCli:
    def _rodar(self, *args, cwd):
        return subprocess.run(
            [sys.executable, gerador.__file__, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
        )

    def test_intervalo(self, tmp_path):
        saida = tmp_path / "out.pdf"
        r = self._rodar("--inicio", "1", "--fim", "3", "--saida", str(saida), cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert contar_codigos_de_barras(PdfReader(saida).pages[0]) == 3

    def test_csv(self, tmp_path):
        csv = tmp_path / "c.csv"
        csv.write_text("111\n222\n")
        saida = tmp_path / "out.pdf"
        r = self._rodar(
            "--csv", str(csv), "--saida", str(saida), "--orgao", "TESTE", cwd=tmp_path
        )
        assert r.returncode == 0, r.stderr
        texto = _texto(PdfReader(saida))
        assert "111" in texto and "222" in texto and "TESTE" in texto

    def test_orgao_vazio(self, tmp_path):
        saida = tmp_path / "out.pdf"
        r = self._rodar("--inicio", "5", "--fim", "5", "--orgao", "", "--saida", str(saida), cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert _texto(PdfReader(saida)).strip() == "5"

    def test_inicio_sem_fim(self, tmp_path):
        r = self._rodar("--inicio", "1", cwd=tmp_path)
        assert r.returncode != 0
        assert "juntos" in r.stderr

    def test_csv_e_intervalo_juntos(self, tmp_path):
        r = self._rodar("--csv", "x.csv", "--inicio", "1", "--fim", "2", cwd=tmp_path)
        assert r.returncode != 0
        assert "não os dois" in r.stderr

    def test_csv_vazio_mostra_mensagem(self, tmp_path):
        csv = tmp_path / "vazio.csv"
        csv.write_text("\n")
        r = self._rodar("--csv", str(csv), cwd=tmp_path)
        assert r.returncode != 0
        assert "Nenhum código" in r.stderr
        assert "Traceback" not in r.stderr

    def test_csv_inexistente(self, tmp_path):
        r = self._rodar("--csv", "nao_existe.csv", cwd=tmp_path)
        assert r.returncode != 0
        assert "não encontrado" in r.stderr

    def test_intervalo_invalido_mostra_mensagem(self, tmp_path):
        r = self._rodar("--inicio", "10", "--fim", "1", cwd=tmp_path)
        assert r.returncode != 0
        assert "maior ou igual" in r.stderr
        assert "Traceback" not in r.stderr

    def test_planilha_xlsx(self, tmp_path):
        planilha = tmp_path / "c.xlsx"
        planilha.write_bytes(xlsx(["codigo", 31, 32]))
        saida = tmp_path / "out.pdf"
        r = self._rodar("--planilha", str(planilha), "--saida", str(saida), cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        texto = _texto(PdfReader(saida))
        assert "31" in texto and "32" in texto and "codigo" not in texto

    def test_planilha_invalida_mostra_mensagem(self, tmp_path):
        planilha = tmp_path / "c.pdf"
        planilha.write_bytes(b"x")
        r = self._rodar("--planilha", str(planilha), cwd=tmp_path)
        assert r.returncode != 0
        assert "Formato não suportado" in r.stderr
        assert "Traceback" not in r.stderr


class TestCliEmProcesso:
    """Mesma CLI, executada no processo do pytest (assim entra na medição de cobertura)."""

    def _rodar(self, monkeypatch, *args):
        import runpy

        monkeypatch.setattr(sys, "argv", ["gerador.py", *args])
        try:
            runpy.run_path(gerador.__file__, run_name="__main__")
        except SystemExit as saida:
            return str(saida.code) if saida.code not in (None, 0) else None
        return None

    def test_intervalo(self, monkeypatch, tmp_path, capsys):
        saida = tmp_path / "sub" / "out.pdf"  # pasta inexistente: a CLI cria
        assert self._rodar(monkeypatch, "--inicio", "1", "--fim", "2", "--saida", str(saida)) is None
        assert contar_codigos_de_barras(PdfReader(saida).pages[0]) == 2
        assert "PDF gerado" in capsys.readouterr().out

    def test_planilha_padrao_do_projeto(self, monkeypatch, tmp_path):
        saida = tmp_path / "out.pdf"
        assert self._rodar(monkeypatch, "--saida", str(saida)) is None
        assert PdfReader(saida).pages

    @pytest.mark.parametrize(
        "args, mensagem",
        [
            (["--inicio", "1"], "juntos"),
            (["--fim", "1"], "juntos"),
            (["--inicio", "1", "--fim", "2", "--csv", "x.csv"], "não os dois"),
            (["--inicio", "9", "--fim", "1"], "maior ou igual"),
            (["--csv", "nao_existe.csv"], "não encontrado"),
            (["--inicio", "1", "--fim", "1", "--orgao", "X" * 200], None),
        ],
    )
    def test_erros(self, monkeypatch, tmp_path, args, mensagem):
        erro = self._rodar(monkeypatch, *args, "--saida", str(tmp_path / "o.pdf"))
        if mensagem is None:
            assert erro is None  # texto longo na CLI: só reduz a fonte
        else:
            assert mensagem in erro

    def test_planilha_invalida(self, monkeypatch, tmp_path):
        planilha = tmp_path / "vazia.csv"
        planilha.write_text("\n")
        assert "Nenhum código" in self._rodar(monkeypatch, "--planilha", str(planilha))


class TestDetalhesDaLeitura:
    def test_valor_booleano_da_planilha(self):
        assert ler_codigos_planilha(xlsx([5, True]), "a.xlsx") == ["5", "True"]

    def test_ods_sem_tabela(self):
        import zipfile

        destino = BytesIO()
        with zipfile.ZipFile(destino, "w") as arquivo:
            arquivo.writestr(
                "content.xml",
                '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0">'
                "<office:body/></office:document-content>",
            )
        with pytest.raises(ValueError, match="Nenhum código"):
            ler_codigos_planilha(destino.getvalue(), "a.ods")
