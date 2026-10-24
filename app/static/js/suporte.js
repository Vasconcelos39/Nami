// Chat do suporte: manda a mensagem sem recarregar a página e, a cada alguns
// segundos (só com a aba aberta na tela), busca as mensagens novas.
// Sem JavaScript, o formulário funciona do jeito normal.
//
// O texto das mensagens entra sempre como texto (textContent), nunca como
// HTML: alguém escrevendo "<script>" na mensagem não consegue rodar nada.
(function () {
  "use strict";

  const conversa = document.getElementById("conversa");
  if (!conversa) return;

  const ticket = conversa.dataset.ticket;
  const chat = document.getElementById("chat");
  const form = document.getElementById("compor");
  const campo = document.getElementById("texto");
  const status = document.getElementById("status-ticket");
  const erro = document.getElementById("erro-chat");
  const fim = form; // "ir pro fim" = deixar as últimas mensagens e o campo de escrever na tela
  const INTERVALO = 15000;
  // Última mensagem que a busca automática já trouxe. A mensagem que a própria
  // pessoa manda não mexe nisso: assim, uma resposta que chegou no mesmo
  // instante não fica de fora.
  let ultima = Number(conversa.dataset.ultima) || 0;
  let buscando = false;

  // Horário no fuso de quem está lendo (o servidor guarda em UTC).
  function formatarHora(elemento) {
    const data = new Date(elemento.getAttribute("datetime"));
    if (!isNaN(data)) elemento.textContent = data.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  }

  // Põe a mensagem na conversa, na ordem certa e sem repetir. Devolve true se era nova.
  function adicionar(m) {
    const id = Number(m.id);
    const existentes = Array.from(chat.children);
    if (existentes.some((li) => Number(li.dataset.id) === id)) return false;
    const item = document.createElement("li");
    item.className = "msg" + (m.minha ? " msg-minha" : "") + (m.suporte ? " msg-suporte" : "");
    item.dataset.id = m.id;
    const autor = document.createElement("span");
    autor.className = "msg-autor";
    autor.textContent = m.autor;
    const texto = document.createElement("p");
    texto.className = "msg-texto";
    texto.textContent = m.texto;
    const quando = document.createElement("time");
    quando.className = "msg-quando";
    quando.setAttribute("datetime", m.quando);
    formatarHora(quando);
    item.append(autor, texto, quando);
    const depois = existentes.find((li) => Number(li.dataset.id) > id);
    chat.insertBefore(item, depois || null);
    return true;
  }

  function atualizarStatus(dados) {
    if (!dados.status) return;
    status.textContent = dados.rotulo;
    status.className = "ticket-status status-" + dados.status;
  }

  function rolarProFim(suave = true) {
    fim.scrollIntoView({ block: "end", behavior: suave ? "smooth" : "auto" });
  }

  async function buscarNovas() {
    if (buscando || document.visibilityState !== "visible") return;
    buscando = true;
    try {
      const resposta = await fetch("/suporte/" + ticket + "/mensagens?depois=" + ultima, {
        headers: { Accept: "application/json" },
      });
      if (!resposta.ok) return;
      const dados = await resposta.json();
      let chegou = false;
      for (const m of dados.mensagens) {
        if (adicionar(m)) chegou = true;
        ultima = Math.max(ultima, Number(m.id));
      }
      atualizarStatus(dados);
      if (chegou) rolarProFim();
    } catch (e) {
      /* sem internet agora: tenta de novo na próxima volta */
    } finally {
      buscando = false;
    }
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!campo.value.trim()) return;
    const botao = form.querySelector("button");
    botao.disabled = true;
    erro.hidden = true;
    try {
      const resposta = await fetch(form.action, {
        method: "POST",
        headers: { Accept: "application/json" },
        body: new URLSearchParams(new FormData(form)),
      });
      const dados = await resposta.json();
      if (!resposta.ok) throw new Error(dados.erro || "Não foi possível enviar.");
      adicionar(dados.mensagem);
      atualizarStatus(dados);
      campo.value = "";
      rolarProFim();
    } catch (e) {
      erro.textContent = e.message || "Não foi possível enviar. Confira a internet e tente de novo.";
      erro.hidden = false;
    } finally {
      botao.disabled = false;
      campo.focus();
    }
  });

  // Ctrl+Enter (ou Cmd+Enter) envia.
  campo.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) form.requestSubmit();
  });

  chat.querySelectorAll("time.msg-quando").forEach(formatarHora);
  rolarProFim(false);
  setInterval(buscarNovas, INTERVALO);
  document.addEventListener("visibilitychange", buscarNovas); // voltou pra aba: busca na hora
})();
