import re
from io import BytesIO
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from labels.gerador import (
    FORMATOS_PLANILHA,
    MAX_ORGAO,
    MAX_TAMANHO_CODIGO,
    ORGAO_PADRAO,
    contar_paginas,
    gerar_codigos_intervalo,
    gerar_pdf,
    ler_codigos_planilha,
)

MAX_PLANILHA_MB = 5
# Cookie que avisa a página que o PDF ficou pronto (para reabilitar o botão "Gerar PDF").
COOKIE_DOWNLOAD = "download_pronto"
_TOKEN_VALIDO = re.compile(r"[A-Za-z0-9_-]{1,64}")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_PLANILHA_MB * 1024 * 1024

# Política de conteúdo das páginas HTML: só recursos do próprio app, mais as fontes
# do Google Fonts usadas no template. Não vale para o PDF (o leitor de PDF do
# navegador poderia deixar de abri-lo no iframe da prévia).
_CSP_HTML = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self'",
        "frame-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ]
)


@app.after_request
def cabecalhos_de_seguranca(resposta):
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    # SAMEORIGIN (e não DENY): a prévia é um iframe do próprio app.
    resposta.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if resposta.mimetype == "text/html":
        resposta.headers.setdefault("Content-Security-Policy", _CSP_HTML)
    return resposta


def _nome_base_planilha(nome_arquivo):
    """Nome da planilha sem extensão, só com caracteres seguros para o nome do PDF."""
    nome = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(nome_arquivo).stem).strip("_")
    return nome or "planilha"


def _ler_formulario():
    """Lê e valida o formulário. Lança ValueError com a mensagem para o usuário.

    Devolve (nome_base, orgao, codigos). Com uma planilha enviada, o intervalo é ignorado.
    """
    # Campo ausente usa o padrão; campo vazio gera etiquetas sem texto acima do código.
    orgao = request.form.get("orgao", ORGAO_PADRAO).strip()
    if len(orgao) > MAX_ORGAO:
        raise ValueError(f"O texto acima do código deve ter no máximo {MAX_ORGAO} caracteres.")

    planilha = request.files.get("planilha")
    if planilha and planilha.filename:
        codigos = ler_codigos_planilha(planilha.read(), planilha.filename)
        return _nome_base_planilha(planilha.filename), orgao, codigos

    inicio = request.form.get("inicio", "").strip()
    fim = request.form.get("fim", "").strip()
    codigos = gerar_codigos_intervalo(inicio, fim)
    return f"{inicio}_{fim}", orgao, codigos


def _pdf_em_memoria(codigos, orgao):
    destino = BytesIO()
    gerar_pdf(codigos, destino=destino, nome_do_orgao=orgao)
    destino.seek(0)
    return destino


def _pagina(erro=None, status=200, ler_formulario=True):
    # Com ler_formulario=False usa os valores padrão (ex.: corpo grande demais para ser lido).
    form = request.form if ler_formulario else {}
    return render_template(
        "index.html",
        orgao_padrao=form.get("orgao", ORGAO_PADRAO).strip(),
        max_orgao=MAX_ORGAO,
        max_digitos=MAX_TAMANHO_CODIGO,
        formatos=",".join(FORMATOS_PLANILHA),
        inicio=form.get("inicio", "").strip(),
        fim=form.get("fim", "").strip(),
        erro=erro,
    ), status


@app.errorhandler(413)
def planilha_grande_demais(_erro):
    mensagem = f"Planilha muito grande (máximo de {MAX_PLANILHA_MB} MB)."
    if request.path.startswith("/preview"):
        return jsonify(erro=mensagem), 413
    # Não dá para ler o formulário: o próprio corpo da requisição é que é grande demais.
    return _pagina(erro=mensagem, status=413, ler_formulario=False)


@app.route("/")
def index():
    return _pagina()


@app.route("/gerar", methods=["POST"])
def gerar():
    try:
        nome_base, orgao, codigos = _ler_formulario()
        destino = _pdf_em_memoria(codigos, orgao)
    except ValueError as erro:
        return _pagina(erro=str(erro), status=400)

    resposta = send_file(
        destino,
        as_attachment=True,
        download_name=f"codigos_{nome_base}.pdf",
        mimetype="application/pdf",
    )
    # Devolve o token enviado pela página; ao ver o cookie, o JS reabilita o botão.
    token = request.form.get("download_token", "")
    if _TOKEN_VALIDO.fullmatch(token):
        resposta.set_cookie(COOKIE_DOWNLOAD, token, max_age=60, samesite="Lax")
    return resposta


@app.route("/preview/info", methods=["POST"])
def preview_info():
    """Valida o formulário e devolve o resumo, antes de o iframe carregar o PDF."""
    try:
        _, _, codigos = _ler_formulario()
    except ValueError as erro:
        return jsonify(erro=str(erro)), 400
    return jsonify(codigos=len(codigos), paginas=contar_paginas(len(codigos)))


@app.route("/preview", methods=["POST"])
def preview():
    """PDF completo, exibido inline no iframe da página (o formulário é enviado para ele)."""
    try:
        _, orgao, codigos = _ler_formulario()
    except ValueError as erro:
        return jsonify(erro=str(erro)), 400

    resposta = send_file(_pdf_em_memoria(codigos, orgao), mimetype="application/pdf")
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


if __name__ == "__main__":
    app.run(debug=True)
