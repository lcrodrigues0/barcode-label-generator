"""Funções auxiliares para inspecionar os PDFs gerados nos testes."""


def contar_codigos_de_barras(pagina):
    """Quantos códigos de barras há na página.

    Cada código é desenhado num Form XObject próprio (ver _desenhar_codigo_de_barras).
    """
    recursos = pagina.get("/Resources")
    if recursos is None:
        return 0
    xobjetos = recursos.get_object().get("/XObject")
    if xobjetos is None:
        return 0
    return sum(
        1 for objeto in xobjetos.get_object().values() if objeto.get_object().get("/Subtype") == "/Form"
    )
