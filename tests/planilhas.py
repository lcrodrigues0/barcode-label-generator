"""Monta planilhas em memória para os testes (XLSX com openpyxl, ODS à mão)."""

import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

import openpyxl


def xlsx(valores):
    """XLSX com um valor por linha na coluna A (None = célula vazia)."""
    livro = openpyxl.Workbook()
    aba = livro.active
    for valor in valores:
        aba.append([valor])
    destino = BytesIO()
    livro.save(destino)
    return destino.getvalue()


def ods(valores, linhas_vazias_no_fim=0):
    """ODS mínimo com um valor por linha. Números viram células float, como no LibreOffice."""
    linhas = []
    for valor in valores:
        if valor is None:
            linhas.append("<table:table-row><table:table-cell/></table:table-row>")
        elif isinstance(valor, (int, float)):
            linhas.append(
                '<table:table-row><table:table-cell office:value-type="float" '
                f'office:value="{valor}"><text:p>{valor}</text:p></table:table-cell>'
                "<table:table-cell><text:p>outra coluna</text:p></table:table-cell>"
                "</table:table-row>"
            )
        else:
            linhas.append(
                '<table:table-row><table:table-cell office:value-type="string">'
                f"<text:p>{escape(valor)}</text:p></table:table-cell></table:table-row>"
            )
    if linhas_vazias_no_fim:
        linhas.append(
            f'<table:table-row table:number-rows-repeated="{linhas_vazias_no_fim}">'
            "<table:table-cell/></table:table-row>"
        )

    conteudo = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<office:document-content "
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        '<office:body><office:spreadsheet><table:table table:name="Planilha1">'
        + "".join(linhas)
        + "</table:table></office:spreadsheet></office:body></office:document-content>"
    )
    destino = BytesIO()
    with zipfile.ZipFile(destino, "w") as arquivo:
        arquivo.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        arquivo.writestr("content.xml", conteudo)
    return destino.getvalue()
