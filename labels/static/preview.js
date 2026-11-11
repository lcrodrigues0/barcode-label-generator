// Prévia do PDF completo num iframe, atualizada enquanto o usuário preenche o formulário.
// A navegação entre páginas e o zoom ficam com o leitor de PDF do navegador.
// Os códigos vêm do intervalo numérico ou de uma planilha importada (que bloqueia o intervalo).
(function () {
  const form = document.getElementById("form-etiquetas");
  const frame = document.getElementById("preview-frame");
  const folha = frame.parentElement;
  const mensagem = document.getElementById("preview-mensagem");
  const resumo = document.getElementById("preview-resumo");
  const campoIntervalo = form.querySelector("fieldset.range");
  const campoPlanilha = document.getElementById("campo-planilha");
  const botaoRemover = document.getElementById("remover-planilha");
  const botaoGerar = document.getElementById("botao-gerar");
  const botaoPreview = document.getElementById("botao-preview");
  const ESPERA_MS = 600;
  const TEXTO_VAZIO = "Preencha o intervalo ou importe uma planilha.";

  let temporizador = null;
  let controlador = null;

  function mostrarMensagem(estado, texto) {
    folha.dataset.estado = estado;
    delete folha.dataset.carregando;
    mensagem.textContent = texto;
    mensagem.hidden = false;
    frame.hidden = true;
  }

  function plural(n, singular, pluralTxt) {
    return n === 1 ? singular : pluralTxt;
  }

  function temPlanilha() {
    return campoPlanilha.files.length > 0;
  }

  // Com planilha, o intervalo fica bloqueado: um fieldset desabilitado não envia
  // os campos nem exige o "required" deles.
  function sincronizarModo() {
    const usandoPlanilha = temPlanilha();
    campoIntervalo.disabled = usandoPlanilha;
    botaoRemover.hidden = !usandoPlanilha;
  }

  async function atualizar() {
    const dados = new FormData(form);

    if (controlador) controlador.abort();

    if (!temDadosParaPrevia()) {
      resumo.textContent = TEXTO_VAZIO;
      mostrarMensagem("vazio", "As páginas aparecem aqui.");
      return;
    }

    controlador = new AbortController();
    folha.dataset.carregando = "sim";

    // 1) Valida e busca o resumo (rápido). 2) Se estiver tudo certo, o formulário
    //    é enviado para o iframe, que mostra o PDF.
    let info;
    try {
      const r = await fetch(form.dataset.previewInfoUrl, {
        method: "POST",
        body: dados,
        signal: controlador.signal,
      });
      info = await r.json();
      if (!r.ok) {
        resumo.textContent = "Corrija o formulário para ver a prévia.";
        mostrarMensagem("erro", info.erro || "Não foi possível gerar a prévia.");
        return;
      }
    } catch (erro) {
      if (erro.name === "AbortError") return;
      resumo.textContent = "Sem conexão com o servidor.";
      mostrarMensagem("erro", "Não foi possível gerar a prévia.");
      return;
    }

    resumo.textContent =
      `${info.codigos} ${plural(info.codigos, "código", "códigos")} · ` +
      `${info.paginas} ${plural(info.paginas, "página", "páginas")}`;
    folha.dataset.estado = "ok";
    mensagem.hidden = true;
    frame.hidden = false;
    form.requestSubmit(botaoPreview);
  }

  function temDadosParaPrevia() {
    if (temPlanilha()) return true;
    const dados = new FormData(form);
    return Boolean((dados.get("inicio") || "").trim() && (dados.get("fim") || "").trim());
  }

  function atualizarComEspera() {
    clearTimeout(temporizador);
    // Mostra o "carregando" já durante a espera, e não só quando a requisição sai.
    if (temDadosParaPrevia()) folha.dataset.carregando = "sim";
    temporizador = setTimeout(atualizar, ESPERA_MS);
  }

  frame.addEventListener("load", function () {
    delete folha.dataset.carregando;
  });

  // Enter num campo não baixa o PDF: só atualiza a prévia na hora.
  // O download acontece apenas pelo botão "Gerar PDF".
  form.addEventListener("keydown", function (evento) {
    if (evento.key === "Enter" && evento.target.tagName === "INPUT") {
      evento.preventDefault();
      clearTimeout(temporizador);
      atualizar();
    }
  });

  form.addEventListener("input", atualizarComEspera);

  campoPlanilha.addEventListener("change", sincronizarModo);

  botaoRemover.addEventListener("click", function () {
    campoPlanilha.value = "";
    sincronizarModo();
    clearTimeout(temporizador);
    atualizar();
  });

  // Ao baixar o PDF, o botão fica desabilitado até o arquivo começar a ser entregue.
  // O formulário segue sendo enviado normalmente (sem preventDefault). Junto vai um
  // token único; o servidor o devolve no cookie "download_pronto" com o PDF, e a
  // página verifica o cookie para saber quando reabilitar o botão.
  // Se der erro, o servidor devolve a página com a mensagem e o botão volta sozinho.
  // Os envios da prévia (botão oculto) não passam por aqui.
  const campoToken = document.getElementById("download-token");
  const COOKIE_DOWNLOAD = "download_pronto";
  const VERIFICAR_MS = 250;
  const ESPERA_MAXIMA_MS = 3 * 60 * 1000; // segurança: reabilita mesmo sem resposta
  const textoBotaoGerar = botaoGerar.textContent;

  function lerCookie(nome) {
    const par = document.cookie.split("; ").find((c) => c.startsWith(nome + "="));
    return par ? decodeURIComponent(par.slice(nome.length + 1)) : null;
  }

  function apagarCookie(nome) {
    document.cookie = `${nome}=; Max-Age=0; path=/; SameSite=Lax`;
  }

  function reabilitarBotao() {
    botaoGerar.disabled = false;
    botaoGerar.removeAttribute("aria-busy");
    botaoGerar.textContent = textoBotaoGerar;
  }

  form.addEventListener("submit", function (evento) {
    if (evento.submitter !== botaoGerar) return;

    const token = Date.now().toString(36) + Math.random().toString(36).slice(2);
    campoToken.value = token;
    apagarCookie(COOKIE_DOWNLOAD);

    botaoGerar.disabled = true;
    botaoGerar.setAttribute("aria-busy", "true");
    botaoGerar.textContent = "Gerando PDF…";

    const inicio = Date.now();
    const verificador = setInterval(function () {
      const pronto = lerCookie(COOKIE_DOWNLOAD) === token;
      if (pronto || Date.now() - inicio > ESPERA_MAXIMA_MS) {
        clearInterval(verificador);
        apagarCookie(COOKIE_DOWNLOAD);
        reabilitarBotao();
      }
    }, VERIFICAR_MS);
  });

  // O navegador pode manter o arquivo escolhido ao recarregar a página.
  sincronizarModo();
  // Se a página voltou com valores preenchidos (ex.: após um erro), já mostra a prévia.
  atualizar();
})();
