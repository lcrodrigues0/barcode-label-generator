"""Testes de segurança e robustez, pensando no app aberto na internet.

Cobrem o que um usuário mal-intencionado (ou só descuidado) pode enviar:
arquivos que "explodem" ao descompactar, XML malicioso, números gigantes,
HTML/JS nos campos, nomes de arquivo estranhos, métodos HTTP inesperados, etc.

Se um problema conhecido precisar ficar para depois, marque o teste com
@pytest.mark.xfail(reason="PRODUÇÃO: ..."); como o pytest.ini usa xfail_strict,
o teste avisa (XPASS) quando o problema for corrigido.
"""

import re
import time
import tracemalloc
import zipfile
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest
from pypdf import PdfReader

import labels.web as web
from labels.gerador import MAX_CODIGOS, MAX_TAMANHO_CODIGO
from labels.web import app as flask_app
from planilhas import ods, xlsx

pytestmark = pytest.mark.seguranca

RAIZ = Path(__file__).resolve().parent.parent

_NS_ODS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
)


# --------------------------------------------------------------------------
# Auxiliares
# --------------------------------------------------------------------------


def _arquivo(conteudo, nome):
    return (BytesIO(conteudo), nome)


def _ods_comprimido(linhas_xml, prefixo=""):
    """ODS com content.xml compactado (DEFLATE), como faz o LibreOffice."""
    conteudo = (
        f"{prefixo}<office:document-content {_NS_ODS}><office:body><office:spreadsheet>"
        f"<table:table>{linhas_xml}</table:table>"
        "</office:spreadsheet></office:body></office:document-content>"
    )
    destino = BytesIO()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as arquivo:
        arquivo.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        arquivo.writestr("content.xml", conteudo)
    return destino.getvalue()


def _xlsx_com_planilha(sheet_xml):
    """XLSX válido gerado pelo openpyxl, com a planilha substituída por sheet_xml."""
    livro = openpyxl.Workbook()
    livro.active.append(["1"])
    original = BytesIO()
    livro.save(original)
    destino = BytesIO()
    with zipfile.ZipFile(BytesIO(original.getvalue())) as origem, zipfile.ZipFile(
        destino, "w", zipfile.ZIP_DEFLATED
    ) as saida:
        for item in origem.infolist():
            dados = origem.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                dados = sheet_xml
            saida.writestr(item.filename, dados)
    return destino.getvalue()


def _medir_memoria(funcao):
    """Executa funcao() e devolve (resultado, pico de memória Python em MB)."""
    tracemalloc.start()
    try:
        resultado = funcao()
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return resultado, pico / 1e6


def _medir_tempo(funcao):
    inicio = time.perf_counter()
    resultado = funcao()
    return resultado, time.perf_counter() - inicio


@pytest.fixture
def client_producao(monkeypatch):
    """Cliente com o comportamento de produção para erros: exceções viram 500."""
    monkeypatch.setitem(flask_app.config, "TESTING", False)
    monkeypatch.setitem(flask_app.config, "PROPAGATE_EXCEPTIONS", False)
    with flask_app.test_client() as client:
        yield client


# --------------------------------------------------------------------------
# Configuração de produção
# --------------------------------------------------------------------------


class TestConfiguracao:
    def test_debug_desligado_ao_importar(self):
        # Em produção o app é importado (ex.: gunicorn labels.web:app); o
        # debug=True do app.run() só vale quando o arquivo é executado direto.
        assert flask_app.debug is False

    def test_debug_true_so_no_bloco_main(self):
        fonte = (RAIZ / "labels" / "web.py").read_text()
        antes_do_main, _, depois = fonte.partition('if __name__ == "__main__":')
        assert "debug=True" not in antes_do_main
        assert "debug=True" in depois

    def test_limite_do_corpo_da_requisicao(self):
        assert flask_app.config["MAX_CONTENT_LENGTH"] == 5 * 1024 * 1024

    def test_nenhum_cookie_de_sessao(self, client):
        # O app não usa sessão; não deve haver cookies além do token de download.
        assert client.get("/").headers.getlist("Set-Cookie") == []

    def test_erro_interno_nao_vaza_detalhes(self, client_producao, monkeypatch):
        def explode(*_args, **_kwargs):
            raise ZeroDivisionError("detalhe interno secreto")

        monkeypatch.setattr(web, "gerar_pdf", explode)
        r = client_producao.post("/gerar", data={"inicio": "1", "fim": "1"})
        assert r.status_code == 500
        corpo = r.get_data(as_text=True)
        for vazamento in ("Traceback", "ZeroDivisionError", "detalhe interno", "web.py", str(RAIZ)):
            assert vazamento not in corpo

    def test_erro_interno_no_preview_nao_vaza_detalhes(self, client_producao, monkeypatch):
        monkeypatch.setattr(web, "gerar_pdf", lambda *a, **k: 1 / 0)
        r = client_producao.post("/preview", data={"inicio": "1", "fim": "1"})
        assert r.status_code == 500
        assert "ZeroDivisionError" not in r.get_data(as_text=True)


class TestCabecalhosDeSeguranca:
    @pytest.mark.parametrize("rota", ["/", "/static/style.css"])
    def test_get(self, client, rota):
        self._verificar(client.get(rota))

    def test_preview(self, client):
        self._verificar(client.post("/preview", data={"inicio": "1", "fim": "1"}))

    def _verificar(self, r):
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("Referrer-Policy")
        # Proteção contra o site ser embutido por terceiros (clickjacking).
        # Precisa permitir a mesma origem, porque a prévia é um iframe do próprio app.
        csp = r.headers.get("Content-Security-Policy", "")
        assert r.headers.get("X-Frame-Options") == "SAMEORIGIN" or "frame-ancestors 'self'" in csp

    @pytest.mark.parametrize("dados", [{"inicio": "9", "fim": "1"}, {}])
    def test_paginas_de_erro_tambem_tem_cabecalhos(self, client, dados):
        r = client.post("/gerar", data=dados)
        assert r.status_code == 400
        self._verificar(r)
        assert "Content-Security-Policy" in r.headers

    def test_csp_so_nas_paginas_html(self, client):
        assert "Content-Security-Policy" in client.get("/").headers
        # No PDF a CSP poderia impedir o leitor de PDF do navegador de abrir a prévia.
        pdf = client.post("/preview", data={"inicio": "1", "fim": "1"})
        assert "Content-Security-Policy" not in pdf.headers
        assert "Content-Security-Policy" not in client.get("/static/style.css").headers

    def test_csp_bloqueia_scripts_inline_e_de_terceiros(self, client):
        csp = client.get("/").headers["Content-Security-Policy"]
        diretivas = dict(d.strip().split(" ", 1) for d in csp.split(";"))
        assert diretivas["script-src"] == "'self'"
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert diretivas["object-src"] == "'none'"
        assert diretivas["frame-ancestors"] == "'self'"

    def test_csp_permite_tudo_que_a_pagina_carrega(self, client):
        """Se o template ganhar um recurso externo novo, a CSP precisa acompanhar."""
        html = client.get("/").get_data(as_text=True)
        csp = client.get("/").headers["Content-Security-Policy"]
        diretivas = {
            nome: valores.split()
            for nome, valores in (d.strip().split(" ", 1) for d in csp.split(";"))
        }

        def permitido(diretiva, url):
            fontes = diretivas.get(diretiva, diretivas["default-src"])
            if url.startswith("/"):
                return "'self'" in fontes
            origem = re.match(r"https://[^/]+", url).group(0)
            return origem in fontes

        for url in re.findall(r'<script[^>]+src="([^"]+)"', html):
            assert permitido("script-src", url), url
        for url in re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html):
            assert permitido("style-src", url), url
        # As fontes vêm do CSS do Google Fonts, que aponta para fonts.gstatic.com.
        if "fonts.googleapis.com" in html:
            assert "https://fonts.gstatic.com" in diretivas["font-src"]
        # A prévia: o formulário é enviado para o iframe e o JS consulta /preview/info.
        assert "'self'" in diretivas["frame-src"]
        assert "'self'" in diretivas["form-action"]
        assert "'self'" in diretivas["connect-src"]
        assert not re.search(r"<script>(?!\s*</script>)", html), "script inline seria bloqueado"
        assert ' style="' not in html, "estilo inline seria bloqueado"


# --------------------------------------------------------------------------
# Rotas e métodos HTTP
# --------------------------------------------------------------------------


class TestRotas:
    @pytest.mark.parametrize("metodo", ["put", "delete", "patch"])
    @pytest.mark.parametrize("rota", ["/gerar", "/preview", "/preview/info"])
    def test_metodos_nao_permitidos(self, client, metodo, rota):
        assert getattr(client, metodo)(rota).status_code == 405

    @pytest.mark.parametrize("rota", ["/gerar", "/preview", "/preview/info"])
    def test_get_em_rotas_post(self, client, rota):
        assert client.get(rota).status_code == 405

    @pytest.mark.parametrize(
        "url",
        [
            "/static/../web.py",
            "/static/%2e%2e/web.py",
            "/static/..%2fweb.py",
            "/static/../../requirements.txt",
            "/static/%2e%2e/%2e%2e/requirements.txt",
            "/static/templates/index.html",
        ],
    )
    def test_static_nao_expoe_outros_arquivos(self, client, url):
        assert client.get(url).status_code == 404

    def test_post_sem_corpo(self, client):
        r = client.post("/gerar")
        assert r.status_code == 400
        assert client.post("/preview/info").status_code == 400

    def test_post_com_json_em_vez_de_formulario(self, client):
        r = client.post("/preview/info", json={"inicio": "1", "fim": "2"})
        assert r.status_code == 400
        assert r.is_json


# --------------------------------------------------------------------------
# Campos do formulário
# --------------------------------------------------------------------------


class TestCamposDoFormulario:
    @pytest.mark.parametrize(
        "inicio, fim",
        [
            ("-5", "1"),
            ("1", "+3"),
            ("1e3", "2000"),
            ("0x10", "20"),
            ("1.5", "2"),
            ("1 2", "3"),
            ("١٢", "١٣"),  # dígitos arábicos
        ],
    )
    def test_intervalo_so_aceita_digitos_ascii(self, client, inicio, fim):
        r = client.post("/preview/info", data={"inicio": inicio, "fim": fim})
        assert r.status_code == 400

    def test_numero_gigante_tem_mensagem_amigavel(self, client):
        r = client.post("/preview/info", data={"inicio": "9" * 5000, "fim": "9" * 5000})
        assert r.status_code == 400
        erro = r.get_json()["erro"]
        assert "set_int_max_str_digits" not in erro
        assert "4300" not in erro

    def test_intervalo_limita_tamanho_do_codigo(self, client):
        longo = "1" * (MAX_TAMANHO_CODIGO + 1)
        r = client.post("/preview/info", data={"inicio": longo, "fim": longo})
        assert r.status_code == 400

    @pytest.mark.parametrize(
        "orgao",
        ["\x00\x1b\x7f", "日本語 😀", "\u202eLTR", "a\r\nb", "' OR 1=1 --", "%s%n%x", "{{ 7*7 }}"],
    )
    def test_texto_acima_com_caracteres_estranhos_nao_quebra(self, client, orgao):
        r = client.post("/gerar", data={"inicio": "1", "fim": "1", "orgao": orgao})
        assert r.status_code == 200
        assert r.data.startswith(b"%PDF")

    def test_template_injection_nao_e_avaliada(self, client):
        r = client.post("/gerar", data={"inicio": "9", "fim": "1", "orgao": "{{ 7*7 }}"})
        html = r.get_data(as_text=True)
        assert "{{ 7*7 }}" in html
        assert ">49<" not in html

    def test_texto_acima_com_xss_e_escapado(self, client):
        ataque = '"><script>alert(1)</script>'
        r = client.post("/gerar", data={"inicio": "9", "fim": "1", "orgao": ataque[:40]})
        html = r.get_data(as_text=True)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_campos_repetidos_usam_o_primeiro(self, client):
        r = client.post("/preview/info", data={"inicio": ["1", "500"], "fim": ["2", "900"]})
        assert r.get_json()["codigos"] == 2

    def test_token_de_download_nao_aparece_na_pagina(self, client):
        token = "<script>x</script>"
        r = client.post("/gerar", data={"inicio": "9", "fim": "1", "download_token": token})
        assert token not in r.get_data(as_text=True)


# --------------------------------------------------------------------------
# Upload de planilhas
# --------------------------------------------------------------------------


class TestUploadDePlanilha:
    def test_codigo_com_html_na_mensagem_de_erro_e_escapado(self, client):
        conteudo = "<img src=x onerror=alert(1)>é\n".encode()
        r = client.post("/gerar", data={"planilha": _arquivo(conteudo, "a.csv")})
        assert r.status_code == 400
        html = r.get_data(as_text=True)
        assert "<img src=x" not in html
        assert "&lt;img src=x" in html

    def test_js_nunca_insere_html_cru(self):
        # As mensagens de erro (JSON) são exibidas pelo JS; precisam ir como texto.
        for js in (RAIZ / "labels" / "static").glob("*.js"):
            fonte = js.read_text()
            for api in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
                assert api not in fonte, f"{js.name} usa {api}"

    @pytest.mark.parametrize(
        "nome",
        [
            '"><script>alert(1)</script>.csv',
            "a\r\nSet-Cookie: x=1.csv",
            "../../etc/passwd.csv",
            "C:\\Windows\\a.csv",
            "planilha;.csv",
            "ação ç 日本.csv",
            "." * 300 + ".csv",
        ],
    )
    def test_nome_de_arquivo_malicioso(self, client, nome):
        r = client.post("/gerar", data={"planilha": _arquivo(b"123\n", nome)})
        assert r.status_code in (200, 400)
        disposicao = r.headers.get("Content-Disposition", "")
        assert "\r" not in disposicao and "\n" not in disposicao
        assert all(not c.startswith("x=") for c in r.headers.getlist("Set-Cookie"))
        if r.status_code == 200:
            nome_pdf = re.search(r"filename=(\S+)", disposicao).group(1)
            assert re.fullmatch(r"codigos_[A-Za-z0-9_-]+\.pdf", nome_pdf)

    def test_extensao_falsa(self, client):
        # PDF renomeado para .xlsx: não pode quebrar o servidor.
        r = client.post("/preview/info", data={"planilha": _arquivo(b"%PDF-1.4 ...", "a.xlsx")})
        assert r.status_code == 400

    def test_zip_sem_content_xml(self, client):
        destino = BytesIO()
        with zipfile.ZipFile(destino, "w") as arquivo:
            arquivo.writestr("outra.txt", "x")
        r = client.post("/preview/info", data={"planilha": _arquivo(destino.getvalue(), "a.ods")})
        assert r.status_code == 400

    def test_ods_com_valor_numerico_invalido(self, client):
        linha = (
            '<table:table-row><table:table-cell office:value-type="float" office:value="abc">'
            "</table:table-cell></table:table-row>"
        )
        r = client.post("/preview/info", data={"planilha": _arquivo(_ods_comprimido(linha), "a.ods")})
        assert r.status_code == 400

    def test_xml_com_entidades_em_cascata_billion_laughs(self, client):
        entidades = '<!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">' + "".join(
            f'<!ENTITY {chr(98 + i)} "{("&" + chr(97 + i) + ";") * 10}">' for i in range(8)
        ) + "]>"
        linha = "<table:table-row><table:table-cell><text:p>&i;</text:p></table:table-cell></table:table-row>"
        conteudo = _ods_comprimido(linha, prefixo=entidades)
        (r, segundos) = _medir_tempo(
            lambda: client.post("/preview/info", data={"planilha": _arquivo(conteudo, "a.ods")})
        )
        assert r.status_code == 400
        assert segundos < 2

    def test_xml_com_entidade_externa_xxe(self, client):
        alvo = RAIZ / "requirements.txt"
        prefixo = f'<!DOCTYPE x [<!ENTITY xxe SYSTEM "file://{alvo}">]>'
        linha = "<table:table-row><table:table-cell><text:p>&xxe;</text:p></table:table-cell></table:table-row>"
        conteudo = _ods_comprimido(linha, prefixo=prefixo)
        r = client.post("/preview/info", data={"planilha": _arquivo(conteudo, "a.ods")})
        # Não pode ler o arquivo do servidor: ou recusa, ou trata como vazio.
        assert r.status_code == 400
        assert "flask" not in r.get_data(as_text=True)

    def test_limite_de_codigos_na_planilha(self, client):
        no_limite = "\n".join(str(n) for n in range(MAX_CODIGOS)).encode()
        r = client.post("/preview/info", data={"planilha": _arquivo(no_limite, "a.csv")})
        assert r.get_json()["codigos"] == MAX_CODIGOS

        acima = no_limite + b"\n99999999"
        r = client.post("/preview/info", data={"planilha": _arquivo(acima, "a.csv")})
        assert r.status_code == 400

    def test_ods_zip_bomb(self, client):
        linhas = "<table:table-row><table:table-cell/></table:table-row>" * 400_000
        conteudo = _ods_comprimido(linhas)
        assert len(conteudo) < 200 * 1024  # menos de 200 KB enviados...
        r, pico_mb = _medir_memoria(
            lambda: client.post("/preview/info", data={"planilha": _arquivo(conteudo, "a.ods")})
        )
        assert r.status_code == 400
        assert pico_mb < 64  # ...não podem custar centenas de MB no servidor
        assert "grande demais depois de descompactada" in r.get_json()["erro"]

    def test_zip_com_tamanho_declarado_falso_nao_passa(self, client):
        # Declarar um tamanho menor que o real não engana: o zipfile para no tamanho
        # declarado e acusa erro de CRC, que vira a mensagem de arquivo corrompido.
        conteudo = bytearray(_ods_comprimido("<table:table-row/>" * 50_000))
        assinatura_central = conteudo.rfind(b"PK\x01\x02")
        posicao_tamanho = assinatura_central + 24  # campo "uncompressed size"
        conteudo[posicao_tamanho:posicao_tamanho + 4] = (100).to_bytes(4, "little")
        r = client.post("/preview/info", data={"planilha": _arquivo(bytes(conteudo), "a.ods")})
        assert r.status_code == 400

    def test_planilha_real_com_o_maximo_de_codigos_cabe_no_limite(self, client):
        # Um XLSX legítimo com 10.000 códigos não pode ser barrado pelo limite anti zip bomb.
        conteudo = xlsx(["codigo"] + [12_000_000 + n for n in range(MAX_CODIGOS)])
        r = client.post("/preview/info", data={"planilha": _arquivo(conteudo, "a.xlsx")})
        assert r.status_code == 200
        assert r.get_json()["codigos"] == MAX_CODIGOS

    def test_ods_real_com_o_maximo_de_codigos_cabe_no_limite(self, client):
        conteudo = ods([12_000_000 + n for n in range(MAX_CODIGOS)], linhas_vazias_no_fim=1_048_000)
        r = client.post("/preview/info", data={"planilha": _arquivo(conteudo, "a.ods")})
        assert r.status_code == 200
        assert r.get_json()["codigos"] == MAX_CODIGOS

    def test_ods_muitas_linhas_repetidas(self, client):
        linha = (
            f'<table:table-row table:number-rows-repeated="{MAX_CODIGOS + 1}">'
            '<table:table-cell office:value-type="string"><text:p>1</text:p></table:table-cell>'
            "</table:table-row>"
        )
        conteudo = _ods_comprimido(linha * 60)
        r, pico_mb = _medir_memoria(
            lambda: client.post("/preview/info", data={"planilha": _arquivo(conteudo, "a.ods")})
        )
        assert r.status_code == 400
        assert pico_mb < 32

    def test_xlsx_muitas_linhas_vazias(self, client):
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        # ~4,7 MB: o maior arquivo que passa no limite de 5 MB do upload.
        linhas = "".join(f'<row r="{i}"><c r="A{i}"/></row>' for i in range(1, 1_000_001))
        conteudo = _xlsx_com_planilha(f"<worksheet {ns}><sheetData>{linhas}</sheetData></worksheet>")
        assert len(conteudo) < flask_app.config["MAX_CONTENT_LENGTH"]
        r, segundos = _medir_tempo(
            lambda: client.post("/preview/info", data={"planilha": _arquivo(conteudo, "a.xlsx")})
        )
        assert r.status_code == 400
        assert segundos < 1.5


# --------------------------------------------------------------------------
# Cookie do token de download
# --------------------------------------------------------------------------


class TestCookieDeDownload:
    @pytest.mark.parametrize("rota", ["/preview", "/preview/info"])
    def test_preview_nao_define_cookie(self, client, rota):
        r = client.post(rota, data={"inicio": "1", "fim": "1", "download_token": "abc"})
        assert r.headers.getlist("Set-Cookie") == []

    def test_cookie_expira_e_nao_tem_dados_sensiveis(self, client):
        r = client.post("/gerar", data={"inicio": "1", "fim": "1", "download_token": "abc"})
        cookie = r.headers.get("Set-Cookie")
        assert "Max-Age=60" in cookie
        assert cookie.startswith("download_pronto=abc;")


# --------------------------------------------------------------------------
# Saída: o PDF
# --------------------------------------------------------------------------


class TestPdfGerado:
    def test_pdf_nao_tem_javascript_nem_acoes(self, client):
        r = client.post("/gerar", data={"inicio": "1", "fim": "3", "orgao": "<script>alert(1)</script>"[:40]})
        bruto = r.data
        for marcador in (b"/JavaScript", b"/JS", b"/OpenAction", b"/Launch", b"/EmbeddedFile"):
            assert marcador not in bruto
        assert PdfReader(BytesIO(bruto)).pages
