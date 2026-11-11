"""Testes da interface web (labels/web.py)."""

from io import BytesIO

import pytest
from pypdf import PdfReader

from labels.gerador import ETIQUETAS_POR_PAGINA, MAX_CODIGOS, ORGAO_PADRAO
from auxiliares_pdf import contar_codigos_de_barras
from planilhas import ods, xlsx


def _ler_pdf(resposta):
    return PdfReader(BytesIO(resposta.data))


def _texto(reader):
    return "\n".join(p.extract_text() for p in reader.pages)


class TestIndex:
    def test_pagina_carrega(self, client):
        r = client.get("/")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "Códigos de barras em PDF" in html
        assert 'name="inicio"' in html
        assert 'name="fim"' in html
        assert f'value="{ORGAO_PADRAO}"' in html
        assert 'maxlength="40"' in html
        assert 'role="alert"' not in html

    def test_css_estatico(self, client):
        r = client.get("/static/style.css")
        assert r.status_code == 200
        assert "text/css" in r.content_type

    def test_gerar_aceita_apenas_post(self, client):
        assert client.get("/gerar").status_code == 405

    def test_rota_inexistente(self, client):
        assert client.get("/nao-existe").status_code == 404


class TestGerar:
    def test_gera_pdf_para_download(self, client):
        r = client.post("/gerar", data={"inicio": "100", "fim": "104", "orgao": "ÓRGÃO X"})
        assert r.status_code == 200
        assert r.mimetype == "application/pdf"
        disposicao = r.headers["Content-Disposition"]
        assert "attachment" in disposicao
        assert "codigos_100_104.pdf" in disposicao
        assert r.data.startswith(b"%PDF")

        reader = _ler_pdf(r)
        texto = _texto(reader)
        for n in range(100, 105):
            assert str(n) in texto
        assert texto.count("ÓRGÃO X") == 5
        assert contar_codigos_de_barras(reader.pages[0]) == 5

    def test_orgao_vazio_sem_texto(self, client):
        r = client.post("/gerar", data={"inicio": "1", "fim": "1", "orgao": "   "})
        assert r.status_code == 200
        reader = _ler_pdf(r)
        assert _texto(reader).strip() == "1"
        assert contar_codigos_de_barras(reader.pages[0]) == 1

    def test_erro_preserva_orgao_vazio(self, client):
        r = client.post("/gerar", data={"inicio": "10", "fim": "1", "orgao": ""})
        assert r.status_code == 400
        html = r.get_data(as_text=True)
        assert 'name="orgao" value=""' in html
        assert f'value="{ORGAO_PADRAO}"' not in html

    def test_orgao_ausente_usa_padrao(self, client):
        r = client.post("/gerar", data={"inicio": "1", "fim": "1"})
        assert r.status_code == 200
        assert ORGAO_PADRAO in _texto(_ler_pdf(r))

    def test_espacos_sao_removidos(self, client):
        r = client.post("/gerar", data={"inicio": " 7 ", "fim": " 8 "})
        assert r.status_code == 200
        assert "codigos_7_8.pdf" in r.headers["Content-Disposition"]

    def test_zeros_a_esquerda(self, client):
        r = client.post("/gerar", data={"inicio": "0009", "fim": "0011"})
        texto = _texto(_ler_pdf(r))
        for codigo in ("0009", "0010", "0011"):
            assert codigo in texto

    @pytest.mark.parametrize(
        "dados, mensagem",
        [
            ({}, "Informe o número inicial e o número final."),
            ({"inicio": "10"}, "Informe o número inicial e o número final."),
            ({"inicio": "abc", "fim": "10"}, "O intervalo deve conter apenas números."),
            ({"inicio": "-1", "fim": "10"}, "O intervalo deve conter apenas números."),
            ({"inicio": "²", "fim": "5"}, "O intervalo deve conter apenas números."),
            ({"inicio": "20", "fim": "10"}, "O número final deve ser maior ou igual ao inicial."),
            (
                {"inicio": "1", "fim": str(MAX_CODIGOS + 1)},
                f"O intervalo não pode ter mais de {MAX_CODIGOS} códigos.",
            ),
        ],
    )
    def test_erros_de_validacao(self, client, dados, mensagem):
        r = client.post("/gerar", data=dados)
        assert r.status_code == 400
        assert r.mimetype == "text/html"
        html = r.get_data(as_text=True)
        assert 'role="alert"' in html
        assert mensagem in html

    def test_erro_preserva_valores_digitados(self, client):
        r = client.post("/gerar", data={"inicio": "20", "fim": "10", "orgao": "MEU ÓRGÃO"})
        html = r.get_data(as_text=True)
        assert 'value="20"' in html
        assert 'value="10"' in html
        assert 'value="MEU ÓRGÃO"' in html

    def test_html_no_formulario_e_escapado(self, client):
        r = client.post(
            "/gerar",
            data={"inicio": "<script>x</script>", "fim": "1", "orgao": '"><b>'},
        )
        assert r.status_code == 400
        html = r.get_data(as_text=True)
        assert "<script>x</script>" not in html
        assert '"><b>' not in html

    def test_orgao_muito_longo_rejeitado(self, client):
        r = client.post("/gerar", data={"inicio": "1", "fim": "1", "orgao": "X" * 41})
        assert r.status_code == 400
        assert "40 caracteres" in r.get_data(as_text=True)

    def test_orgao_com_40_caracteres_aceito(self, client):
        r = client.post("/gerar", data={"inicio": "1", "fim": "1", "orgao": "X" * 40})
        assert r.status_code == 200


class TestTokenDeDownload:
    """O cookie com o token avisa a página que o PDF ficou pronto (reabilita o botão)."""

    def _cookie(self, resposta):
        return next(
            (h for h in resposta.headers.getlist("Set-Cookie") if h.startswith("download_pronto=")),
            None,
        )

    def test_devolve_token_no_cookie(self, client):
        r = client.post("/gerar", data={"inicio": "1", "fim": "2", "download_token": "abc123_XY-z"})
        assert r.status_code == 200
        cookie = self._cookie(r)
        assert cookie.startswith("download_pronto=abc123_XY-z;")
        assert "HttpOnly" not in cookie  # o JS precisa ler
        assert "SameSite=Lax" in cookie

    @pytest.mark.parametrize("token", ["", "a;b", "<script>", "x" * 65])
    def test_token_ausente_ou_invalido_nao_gera_cookie(self, client, token):
        r = client.post("/gerar", data={"inicio": "1", "fim": "2", "download_token": token})
        assert r.status_code == 200
        assert self._cookie(r) is None

    def test_erro_nao_gera_cookie(self, client):
        r = client.post("/gerar", data={"inicio": "9", "fim": "1", "download_token": "abc"})
        assert r.status_code == 400
        assert self._cookie(r) is None

    def test_pagina_tem_campo_do_token(self, client):
        html = client.get("/").get_data(as_text=True)
        assert 'name="download_token"' in html


class TestPreview:
    def test_retorna_so_a_primeira_pagina_inline(self, client):
        quantidade = ETIQUETAS_POR_PAGINA * 2 + 1
        r = client.post("/preview", data={"inicio": "1", "fim": str(quantidade), "orgao": "TESTE"})
        assert r.status_code == 200
        assert r.mimetype == "application/pdf"
        assert "attachment" not in r.headers.get("Content-Disposition", "")
        assert r.headers["Cache-Control"] == "no-store"
        reader = _ler_pdf(r)
        assert len(reader.pages) == 1
        assert contar_codigos_de_barras(reader.pages[0]) == ETIQUETAS_POR_PAGINA
        texto = _texto(reader)
        assert str(ETIQUETAS_POR_PAGINA) in texto
        assert str(ETIQUETAS_POR_PAGINA + 1) not in texto

    def test_info_continua_com_o_total(self, client):
        # O resumo (e o aviso na tela) usa o total, não só a 1ª página.
        quantidade = ETIQUETAS_POR_PAGINA * 2 + 1
        r = client.post("/preview/info", data={"inicio": "1", "fim": str(quantidade)})
        assert r.get_json() == {"codigos": quantidade, "paginas": 3}

    def test_menos_que_uma_pagina(self, client):
        r = client.post("/preview", data={"inicio": "1", "fim": "3"})
        assert contar_codigos_de_barras(_ler_pdf(r).pages[0]) == 3

    def test_primeira_pagina_igual_a_do_pdf_final(self, client):
        dados = {"inicio": "500", "fim": "620", "orgao": "TESTE"}
        prev = _ler_pdf(client.post("/preview", data=dados))
        final = _ler_pdf(client.post("/gerar", data=dados))
        assert len(final.pages) == 3
        assert prev.pages[0].extract_text() == final.pages[0].extract_text()

    def test_pagina_deixa_claro_que_e_so_a_primeira(self, client):
        html = client.get("/").get_data(as_text=True)
        assert "Prévia da 1ª página" in html
        assert 'id="preview-aviso"' in html
        js = client.get("/static/preview.js").get_data(as_text=True)
        assert "A prévia mostra apenas a 1ª página" in js

    def test_orgao_vazio_sem_texto(self, client):
        r = client.post("/preview", data={"inicio": "1", "fim": "2", "orgao": ""})
        assert r.status_code == 200
        texto = _texto(_ler_pdf(r))
        assert ORGAO_PADRAO not in texto
        assert "1" in texto and "2" in texto

    def test_info_resumo(self, client):
        r = client.post("/preview/info", data={"inicio": "1000", "fim": "1120"})
        assert r.status_code == 200
        assert r.get_json() == {"codigos": 121, "paginas": 3}

    @pytest.mark.parametrize("rota", ["/preview", "/preview/info"])
    def test_aceitam_apenas_post(self, client, rota):
        assert client.get(rota).status_code == 405

    @pytest.mark.parametrize("rota", ["/preview", "/preview/info"])
    @pytest.mark.parametrize(
        "dados",
        [
            {"inicio": "", "fim": "5"},
            {"inicio": "10", "fim": "1"},
            {"inicio": "a", "fim": "5"},
            {"inicio": "1", "fim": "2", "orgao": "X" * 41},
        ],
    )
    def test_erro_retorna_json(self, client, rota, dados):
        r = client.post(rota, data=dados)
        assert r.status_code == 400
        assert r.is_json
        assert r.get_json()["erro"]

    def test_pagina_inclui_iframe_e_script(self, client):
        html = client.get("/").get_data(as_text=True)
        assert 'name="preview-frame"' in html
        assert 'formaction="/preview#view=FitH"' in html
        assert 'formtarget="preview-frame"' in html
        assert 'data-preview-info-url="/preview/info"' in html
        assert client.get("/static/preview.js").status_code == 200


def _arquivo(conteudo, nome):
    return (BytesIO(conteudo), nome)


class TestPlanilha:
    def test_pagina_tem_campo_habilitado(self, client):
        html = client.get("/").get_data(as_text=True)
        assert 'enctype="multipart/form-data"' in html
        assert 'name="planilha"' in html
        assert 'accept=".csv,.txt,.xlsx,.ods"' in html
        assert "<fieldset class=\"planilha\">" in html  # sem "disabled"

    def test_gerar_com_csv(self, client):
        r = client.post(
            "/gerar",
            data={"orgao": "TESTE", "planilha": _arquivo(b"111\n222\n333\n", "lote-maio.csv")},
        )
        assert r.status_code == 200
        assert "codigos_lote-maio.pdf" in r.headers["Content-Disposition"]
        reader = _ler_pdf(r)
        texto = _texto(reader)
        assert all(c in texto for c in ("111", "222", "333"))
        assert contar_codigos_de_barras(reader.pages[0]) == 3

    def test_planilha_ignora_intervalo(self, client):
        r = client.post(
            "/gerar",
            data={"inicio": "1", "fim": "50", "planilha": _arquivo(b"777\n", "a.csv")},
        )
        reader = _ler_pdf(r)
        assert contar_codigos_de_barras(reader.pages[0]) == 1
        assert "777" in _texto(reader)

    def test_gerar_com_xlsx(self, client):
        conteudo = xlsx(["Código", 12385319, 12385320.0, "000123"])
        r = client.post("/gerar", data={"planilha": _arquivo(conteudo, "x.xlsx")})
        assert r.status_code == 200
        texto = _texto(_ler_pdf(r))
        assert all(c in texto for c in ("12385319", "12385320", "000123"))
        assert "Código" not in texto

    def test_gerar_com_ods(self, client):
        conteudo = ods([12385319, "0007"], linhas_vazias_no_fim=1_000_000)
        r = client.post("/gerar", data={"planilha": _arquivo(conteudo, "x.ods")})
        assert r.status_code == 200
        assert contar_codigos_de_barras(_ler_pdf(r).pages[0]) == 2

    def test_nome_do_pdf_sanitizado(self, client):
        r = client.post("/gerar", data={"planilha": _arquivo(b"1\n", "Lote de março (final).csv")})
        assert "codigos_Lote_de_mar_o_final.pdf" in r.headers["Content-Disposition"]

    def test_preview_e_info_com_planilha(self, client):
        dados = lambda: {"planilha": _arquivo(b"10\n20\n30\n", "a.csv")}  # noqa: E731
        info = client.post("/preview/info", data=dados())
        assert info.get_json() == {"codigos": 3, "paginas": 1}
        prev = client.post("/preview", data=dados())
        assert prev.mimetype == "application/pdf"
        assert contar_codigos_de_barras(_ler_pdf(prev).pages[0]) == 3

    @pytest.mark.parametrize(
        "conteudo, nome, mensagem",
        [
            (b"x", "a.pdf", "Formato não suportado"),
            (b"nao e zip", "a.xlsx", "Não foi possível ler"),
            (b"\n\n", "a.csv", "Nenhum código"),
            ("ação\n".encode(), "a.csv", "Linha 1"),
        ],
    )
    def test_erros_da_planilha(self, client, conteudo, nome, mensagem):
        r = client.post("/preview/info", data={"planilha": _arquivo(conteudo, nome)})
        assert r.status_code == 400
        assert mensagem in r.get_json()["erro"]

        r = client.post("/gerar", data={"planilha": _arquivo(conteudo, nome)})
        assert r.status_code == 400
        assert mensagem in r.get_data(as_text=True)

    def test_arquivo_grande_demais(self, client):
        grande = b"1\n" * (3 * 1024 * 1024)  # ~6 MB
        r = client.post("/preview/info", data={"planilha": _arquivo(grande, "a.csv")})
        assert r.status_code == 413
        assert "muito grande" in r.get_json()["erro"]

        r = client.post("/gerar", data={"planilha": _arquivo(grande, "a.csv")})
        assert r.status_code == 413
        assert "muito grande" in r.get_data(as_text=True)


def test_paginas_calculadas_batem_com_o_pdf():
    from labels.gerador import contar_paginas, gerar_pdf

    for n in (1, ETIQUETAS_POR_PAGINA, ETIQUETAS_POR_PAGINA + 1):
        destino = BytesIO()
        gerar_pdf([str(i) for i in range(n)], destino=destino)
        assert len(PdfReader(BytesIO(destino.getvalue())).pages) == contar_paginas(n)
