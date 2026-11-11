"""Testes da interface web (labels/web.py)."""

from io import BytesIO

import pytest
from pypdf import PdfReader

from labels.gerador import ETIQUETAS_POR_PAGINA, MAX_CODIGOS, ORGAO_PADRAO


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
        assert len(reader.pages[0].images) == 5

    def test_orgao_vazio_sem_texto(self, client):
        r = client.post("/gerar", data={"inicio": "1", "fim": "1", "orgao": "   "})
        assert r.status_code == 200
        reader = _ler_pdf(r)
        assert _texto(reader).strip() == "1"
        assert len(reader.pages[0].images) == 1

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


class TestPreview:
    def test_retorna_pdf_completo_inline(self, client):
        quantidade = ETIQUETAS_POR_PAGINA * 2 + 1
        r = client.get(f"/preview?inicio=1&fim={quantidade}&orgao=TESTE")
        assert r.status_code == 200
        assert r.mimetype == "application/pdf"
        assert "attachment" not in r.headers.get("Content-Disposition", "")
        assert r.headers["Cache-Control"] == "no-store"
        reader = _ler_pdf(r)
        assert len(reader.pages) == 3
        assert len(reader.pages[2].images) == 1

    def test_igual_ao_pdf_final(self, client):
        dados = {"inicio": "500", "fim": "620", "orgao": "TESTE"}
        prev = _ler_pdf(client.get("/preview", query_string=dados))
        final = _ler_pdf(client.post("/gerar", data=dados))
        assert [p.extract_text() for p in prev.pages] == [p.extract_text() for p in final.pages]

    def test_orgao_vazio_sem_texto(self, client):
        r = client.get("/preview?inicio=1&fim=2&orgao=")
        assert r.status_code == 200
        texto = _texto(_ler_pdf(r))
        assert ORGAO_PADRAO not in texto
        assert "1" in texto and "2" in texto

    def test_info_resumo(self, client):
        r = client.get("/preview/info?inicio=1000&fim=1120")
        assert r.status_code == 200
        assert r.get_json() == {"codigos": 121, "paginas": 3}

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
        r = client.get(rota, query_string=dados)
        assert r.status_code == 400
        assert r.is_json
        assert r.get_json()["erro"]

    def test_pagina_inclui_iframe_e_script(self, client):
        html = client.get("/").get_data(as_text=True)
        assert 'id="preview-frame"' in html
        assert 'data-preview-url="/preview"' in html
        assert 'data-preview-info-url="/preview/info"' in html
        assert "preview-nav" not in html
        assert client.get("/static/preview.js").status_code == 200


def test_paginas_calculadas_batem_com_o_pdf():
    from labels.gerador import contar_paginas, gerar_pdf

    for n in (1, ETIQUETAS_POR_PAGINA, ETIQUETAS_POR_PAGINA + 1):
        destino = BytesIO()
        gerar_pdf([str(i) for i in range(n)], destino=destino)
        assert len(PdfReader(BytesIO(destino.getvalue())).pages) == contar_paginas(n)
