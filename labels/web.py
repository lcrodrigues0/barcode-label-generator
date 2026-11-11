from io import BytesIO

from flask import Flask, jsonify, render_template, request, send_file

from labels.gerador import (
    MAX_ORGAO,
    ORGAO_PADRAO,
    contar_paginas,
    gerar_codigos_intervalo,
    gerar_pdf,
)

app = Flask(__name__)


def _ler_formulario():
    """Lê e valida o formulário. Lança ValueError com a mensagem para o usuário."""
    # request.values cobre o POST do formulário e o GET (query string) do iframe.
    inicio = request.values.get("inicio", "").strip()
    fim = request.values.get("fim", "").strip()
    # Campo ausente usa o padrão; campo vazio gera etiquetas sem texto acima do código.
    orgao = request.values.get("orgao", ORGAO_PADRAO).strip()

    if len(orgao) > MAX_ORGAO:
        raise ValueError(f"O texto do órgão deve ter no máximo {MAX_ORGAO} caracteres.")
    codigos = gerar_codigos_intervalo(inicio, fim)
    return inicio, fim, orgao, codigos


def _pdf_em_memoria(codigos, orgao):
    destino = BytesIO()
    gerar_pdf(codigos, destino=destino, nome_do_orgao=orgao)
    destino.seek(0)
    return destino


@app.route("/")
def index():
    return render_template("index.html", orgao_padrao=ORGAO_PADRAO, max_orgao=MAX_ORGAO)


@app.route("/gerar", methods=["POST"])
def gerar():
    try:
        inicio, fim, orgao, codigos = _ler_formulario()
        destino = _pdf_em_memoria(codigos, orgao)
    except ValueError as erro:
        return render_template(
            "index.html",
            orgao_padrao=request.form.get("orgao", ORGAO_PADRAO).strip(),
            max_orgao=MAX_ORGAO,
            inicio=request.form.get("inicio", "").strip(),
            fim=request.form.get("fim", "").strip(),
            erro=str(erro),
        ), 400

    return send_file(
        destino,
        as_attachment=True,
        download_name=f"codigos_{inicio}_{fim}.pdf",
        mimetype="application/pdf",
    )


@app.route("/preview/info")
def preview_info():
    """Valida os parâmetros e devolve o resumo, antes de o iframe carregar o PDF."""
    try:
        _, _, _, codigos = _ler_formulario()
    except ValueError as erro:
        return jsonify(erro=str(erro)), 400
    return jsonify(codigos=len(codigos), paginas=contar_paginas(len(codigos)))


@app.route("/preview")
def preview():
    """PDF completo, exibido inline no iframe da página."""
    try:
        _, _, orgao, codigos = _ler_formulario()
    except ValueError as erro:
        return jsonify(erro=str(erro)), 400

    resposta = send_file(_pdf_em_memoria(codigos, orgao), mimetype="application/pdf")
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


if __name__ == "__main__":
    app.run(debug=True)
