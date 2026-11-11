"""Orçamentos de tempo/tamanho. Os marcados com "lento" só rodam com: pytest -m lento

Os limites são folgados de propósito (máquinas de CI costumam ser mais lentas);
servem para pegar regressões grandes, não para medir com precisão.
"""

import time
from io import BytesIO

import pytest
from pypdf import PdfReader

from labels.gerador import ETIQUETAS_POR_PAGINA, MAX_CODIGOS, gerar_pdf

# Tempo máximo que o servidor de produção espera por uma requisição
# (gunicorn --timeout 120, sugerido para o deploy). Gerar o PDF tem de caber nele.
TIMEOUT_DO_SERVIDOR_S = 120


def _cronometrar(funcao):
    inicio = time.perf_counter()
    resultado = funcao()
    return resultado, time.perf_counter() - inicio


class TestRespostasRapidas:
    def test_pagina_inicial(self, client):
        _, segundos = _cronometrar(lambda: client.get("/"))
        assert segundos < 0.5

    def test_info_e_rapido_mesmo_no_limite(self, client):
        # O resumo não gera o PDF: precisa ser instantâneo até com o máximo de códigos.
        r, segundos = _cronometrar(
            lambda: client.post("/preview/info", data={"inicio": "1", "fim": str(MAX_CODIGOS)})
        )
        assert r.get_json()["codigos"] == MAX_CODIGOS
        assert segundos < 0.5

    def test_preview_de_uma_pagina(self, client):
        r, segundos = _cronometrar(
            lambda: client.post("/preview", data={"inicio": "1", "fim": str(ETIQUETAS_POR_PAGINA)})
        )
        assert r.status_code == 200
        assert segundos < 2


@pytest.mark.lento
class TestVolumeMaximo:
    def test_pdf_com_o_maximo_de_codigos(self):
        destino = BytesIO()
        codigos = [str(10_000_000 + n) for n in range(MAX_CODIGOS)]
        _, segundos = _cronometrar(lambda: gerar_pdf(codigos, destino=destino))
        tamanho_mb = len(destino.getvalue()) / 1e6
        print(f"\n{MAX_CODIGOS} códigos: {segundos:.1f}s, {tamanho_mb:.1f} MB")

        assert segundos < TIMEOUT_DO_SERVIDOR_S / 2
        assert len(PdfReader(BytesIO(destino.getvalue())).pages) == MAX_CODIGOS // ETIQUETAS_POR_PAGINA

    def test_download_com_o_maximo_de_codigos(self, client):
        r, segundos = _cronometrar(
            lambda: client.post("/gerar", data={"inicio": "1", "fim": str(MAX_CODIGOS)})
        )
        assert r.status_code == 200
        assert r.data.startswith(b"%PDF")
        assert segundos < TIMEOUT_DO_SERVIDOR_S / 2
