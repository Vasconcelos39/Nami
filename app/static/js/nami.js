// Script de todas as páginas da Nami.
//
// - Registra o service worker (/sw.js), que permite instalar a Nami como app.
// - Mostra o convite "Instalar" quando o navegador deixa (Chrome/Edge/Samsung
//   no Android e no computador) e explica o caminho no iPhone, onde não há
//   botão automático.
// - Corta sinopses longas com um botão "Ler mais".
// - Fecha menus abertos (como "Ler no site oficial") ao tocar fora deles.
(function () {
  "use strict";

  const CHAVE_CONVITE = "nami.convite-instalar"; // quando a pessoa fechou o convite
  const DIAS_SEM_CONVITE = 30;

  // ------------------------------------------------------- service worker

  if ("serviceWorker" in navigator && window.isSecureContext) {
    const versao = document.documentElement.dataset.versao || "0";
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js?v=" + encodeURIComponent(versao)).catch(() => {
        /* sem service worker a Nami funciona igual, só não fica instalável em alguns navegadores */
      });
    });
  }

  // ----------------------------------------------------- instalar como app

  const instalada =
    window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const ehIphone =
    /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1); // iPad se passa por Mac
  let pedidoDeInstalacao = null; // evento do navegador guardado pra usar no clique

  function lerLocal(chave) {
    try {
      return localStorage.getItem(chave);
    } catch (e) {
      return null;
    }
  }

  function gravarLocal(chave, valor) {
    try {
      localStorage.setItem(chave, valor);
    } catch (e) {
      /* sem localStorage: o convite volta a aparecer na próxima visita */
    }
  }

  function conviteFechadoRecentemente() {
    const quando = Number(lerLocal(CHAVE_CONVITE));
    return quando > 0 && Date.now() - quando < DIAS_SEM_CONVITE * 24 * 60 * 60 * 1000;
  }

  // Cada bloco [data-instalar] tem um texto, um botão e (o convite) um "fechar".
  function atualizarBlocos() {
    document.querySelectorAll("[data-instalar]").forEach((bloco) => {
      const ehConvite = bloco.hasAttribute("data-convite");
      const texto = bloco.querySelector("[data-instalar-texto]");
      const botao = bloco.querySelector("[data-instalar-botao]");
      let mensagem = "";
      let mostrarBotao = false;

      if (instalada) {
        mensagem = "Você já está usando a Nami como app.";
      } else if (pedidoDeInstalacao) {
        mensagem = "Abre direto da tela inicial, em tela cheia, como um app.";
        mostrarBotao = true;
      } else if (ehIphone) {
        mensagem =
          "Toque em Compartilhar (o quadrado com a seta) e depois em " +
          "“Adicionar à Tela de Início”.";
      } else {
        mensagem =
          "Procure “Instalar app” ou “Adicionar à tela inicial” no menu do navegador. " +
          "A instalação só funciona com o site aberto em HTTPS.";
      }

      // O convite da página inicial só aparece quando há algo útil pra fazer.
      const visivel = ehConvite
        ? !instalada && (pedidoDeInstalacao || ehIphone) && !conviteFechadoRecentemente()
        : true;
      if (texto) texto.textContent = mensagem;
      if (botao) botao.hidden = !mostrarBotao;
      bloco.hidden = !visivel;
    });
  }

  window.addEventListener("beforeinstallprompt", (ev) => {
    ev.preventDefault(); // a Nami mostra o próprio botão em vez da barrinha do navegador
    pedidoDeInstalacao = ev;
    atualizarBlocos();
  });

  window.addEventListener("appinstalled", () => {
    pedidoDeInstalacao = null;
    gravarLocal(CHAVE_CONVITE, String(Date.now()));
    atualizarBlocos();
  });

  document.addEventListener("click", (ev) => {
    if (!(ev.target instanceof Element)) return;
    if (ev.target.closest("[data-instalar-botao]") && pedidoDeInstalacao) {
      const pedido = pedidoDeInstalacao;
      pedidoDeInstalacao = null; // o navegador só deixa usar uma vez
      pedido.prompt();
      pedido.userChoice.finally(atualizarBlocos);
    } else if (ev.target.closest("[data-instalar-fechar]")) {
      gravarLocal(CHAVE_CONVITE, String(Date.now()));
      atualizarBlocos();
    }
  });

  // ------------------------------------------ menus (<details data-menu>)

  // Tocar fora de um menu aberto (ex.: "Ler no site oficial") fecha o menu.
  document.addEventListener("click", (ev) => {
    document.querySelectorAll("details[data-menu][open]").forEach((menu) => {
      if (!(ev.target instanceof Node) || !menu.contains(ev.target)) menu.open = false;
    });
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    document.querySelectorAll("details[data-menu][open]").forEach((menu) => { menu.open = false; });
  });

  // ------------------------------------------------------- sinopse longa

  function recolherTextos() {
    document.querySelectorAll("[data-recolher]").forEach((texto) => {
      texto.classList.add("recolhida");
      if (texto.scrollHeight <= texto.clientHeight + 2) {
        texto.classList.remove("recolhida"); // é curta: não precisa de botão
        return;
      }
      const botao = document.createElement("button");
      botao.type = "button";
      botao.className = "botao-link ler-mais";
      botao.textContent = "Ler mais";
      botao.setAttribute("aria-expanded", "false");
      botao.addEventListener("click", () => {
        const recolhida = texto.classList.toggle("recolhida");
        botao.textContent = recolhida ? "Ler mais" : "Ler menos";
        botao.setAttribute("aria-expanded", String(!recolhida));
      });
      texto.after(botao);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      atualizarBlocos();
      recolherTextos();
    });
  } else {
    atualizarBlocos();
    recolherTextos();
  }
})();
