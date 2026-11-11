// Prévia do PDF completo num iframe, atualizada enquanto o usuário preenche o formulário.
// A navegação entre páginas e o zoom ficam com o leitor de PDF do navegador.
(function () {
  const form = document.getElementById("form-etiquetas");
  const frame = document.getElementById("preview-frame");
  const folha = frame.parentElement;
  const mensagem = document.getElementById("preview-mensagem");
  const resumo = document.getElementById("preview-resumo");
  const ESPERA_MS = 600;

  let temporizador = null;
  let controlador = null;

  function mostrarMensagem(estado, texto) {
    folha.dataset.estado = estado;
    delete folha.dataset.carregando;
    mensagem.textContent = texto;
    mensagem.hidden = false;
    frame.hidden = true;
    frame.removeAttribute("src");
  }

  function plural(n, singular, pluralTxt) {
    return n === 1 ? singular : pluralTxt;
  }

  async function atualizar() {
    const params = new URLSearchParams(new FormData(form));
    const inicio = (params.get("inicio") || "").trim();
    const fim = (params.get("fim") || "").trim();

    if (controlador) controlador.abort();

    if (!inicio || !fim) {
      resumo.textContent = "Preencha o intervalo para ver as páginas.";
      mostrarMensagem("vazio", "As páginas aparecem aqui.");
      return;
    }

    controlador = new AbortController();
    folha.dataset.carregando = "sim";

    // 1) Valida e busca o resumo (rápido). 2) Se estiver tudo certo, o iframe carrega o PDF.
    let info;
    try {
      const r = await fetch(`${form.dataset.previewInfoUrl}?${params}`, {
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
    frame.src = `${form.dataset.previewUrl}?${params}#view=FitH`;
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

  form.addEventListener("input", function () {
    clearTimeout(temporizador);
    temporizador = setTimeout(atualizar, ESPERA_MS);
  });

  // Ao gerar o PDF, desabilita o botão por alguns segundos para evitar cliques
  // repetidos. O formulário segue sendo enviado normalmente (não há preventDefault).
  const botaoGerar = form.querySelector('button[type="submit"]');
  const BOTAO_DESABILITADO_MS = 500;

  form.addEventListener("submit", function () {
    const textoOriginal = botaoGerar.textContent;
    botaoGerar.disabled = true;
    botaoGerar.textContent = "Baixando PDF…";
    setTimeout(function () {
      botaoGerar.disabled = false;
      botaoGerar.textContent = textoOriginal;
    }, BOTAO_DESABILITADO_MS);
  });

  // Se a página voltou com valores preenchidos (ex.: após um erro), já mostra a prévia.
  atualizar();
})();
