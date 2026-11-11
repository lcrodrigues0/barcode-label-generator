"""Os códigos de barras impressos precisam ser LIDOS por um leitor de verdade.

Renderiza o PDF como imagem (pdftoppm, do poppler-utils) e decodifica com o
zxing-cpp. Se alguma dessas ferramentas não estiver instalada, os testes são pulados.
"""

import shutil
import subprocess
from io import BytesIO

import pytest

from labels.gerador import ETIQUETAS_POR_PAGINA, gerar_pdf

zxingcpp = pytest.importorskip("zxingcpp")
Image = pytest.importorskip("PIL.Image")

pytestmark = pytest.mark.skipif(
    shutil.which("pdftoppm") is None, reason="pdftoppm (poppler-utils) não instalado"
)


def _ler_codigos(pdf_bytes, tmp_path, dpi):
    pdf = tmp_path / "etiquetas.pdf"
    pdf.write_bytes(pdf_bytes)
    subprocess.run(
        ["pdftoppm", "-r", str(dpi), "-png", "-f", "1", "-l", "1", str(pdf), str(tmp_path / "pagina")],
        check=True,
    )
    imagem = Image.open(next(tmp_path.glob("pagina*.png")))
    resultados = zxingcpp.read_barcodes(imagem, formats=zxingcpp.BarcodeFormat.Code128)
    return sorted(r.text for r in resultados)


def _pdf(codigos, **kwargs):
    destino = BytesIO()
    gerar_pdf(codigos, destino=destino, **kwargs)
    return destino.getvalue()


CODIGOS_VARIADOS = [
    "12385319",
    "0007",
    "000123",
    "9",
    "A-1",
    "HELLO world",
    "12345678901234567890",
] + [str(12_385_000 + n) for n in range(ETIQUETAS_POR_PAGINA - 7)]


@pytest.mark.parametrize("dpi", [300, 200])
def test_pagina_inteira_e_lida(tmp_path, dpi):
    # 300 dpi é a resolução comum de impressoras de etiqueta; 200 dpi é o mínimo usual.
    assert _ler_codigos(_pdf(CODIGOS_VARIADOS), tmp_path, dpi) == sorted(CODIGOS_VARIADOS)


def test_sem_texto_acima_continua_legivel(tmp_path):
    codigos = CODIGOS_VARIADOS[:10]
    assert _ler_codigos(_pdf(codigos, nome_do_orgao=""), tmp_path, 300) == sorted(codigos)


def test_zeros_a_esquerda_sao_preservados_na_leitura(tmp_path):
    codigos = ["0000001", "0000002", "0100000"]
    assert _ler_codigos(_pdf(codigos), tmp_path, 300) == codigos
