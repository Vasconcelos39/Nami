// Leitor de páginas da Nami.
//
// Dois modos: "paginado" (uma página por vez) e "scroll" (todas em coluna).
// As preferências ficam no localStorage do navegador; o modo é guardado
// separado pra obras em tira (manhwa, que abrem em rolagem) e em páginas
// (mangá, que abrem paginadas). A cada troca de página o leitor dispara o
// evento "nami:pagina"; com login, o progresso é salvo no servidor a partir
// dele (ver "progresso de leitura" lá embaixo).
(function () {
  "use strict";

  const dados = JSON.parse(document.getElementById("dados-leitor").textContent);
  const total = dados.paginas.length;
  const formato = dados.formato === "tira" ? "tira" : "paginas";
  const CHAVE_PREFS = "nami.leitor";
  const PADRAO = {
    modo: formato === "tira" ? "scroll" : "paginado",
    direcao: "ltr",
    ajuste: "altura",
    qualidade: dados.qualidadePadrao,
  };

  const $ = (id) => document.getElementById(id);
  const leitor = $("leitor");
  const imgAtual = $("pagina-atual");
  const areaScroll = $("area-scroll");
  const fim = $("fim-capitulo");
  const erro = $("erro-pagina");
  const barra = $("barra-pagina");
  const indicador = $("indicador-pagina");
  const aviso = $("aviso");
  const painel = $("painel-config");
  const botaoConfig = $("botao-config");

  let prefs = carregarPrefs();
  let pagina = paginaInicial(); // de 1 a total
  let noFim = false; // modo paginado: passou da última página e o cartaz de fim está aberto
  let observador = null;
  let timerAviso = null;

  // ---------------------------------------------------------- preferências

  function carregarPrefs() {
    let salvas = {};
    try {
      salvas = JSON.parse(localStorage.getItem(CHAVE_PREFS) || "{}") || {};
    } catch (e) {
      /* navegador sem localStorage (ex.: janela privada): fica no padrão */
    }
    const modos = salvas.modos || {};
    return Object.assign({}, PADRAO, salvas, { modos: modos, modo: modos[formato] || PADRAO.modo });
  }

  function salvarPrefs() {
    prefs.modos = Object.assign({}, prefs.modos, { [formato]: prefs.modo });
    try {
      localStorage.setItem(CHAVE_PREFS, JSON.stringify(prefs));
    } catch (e) {
      /* sem localStorage: as preferências valem só nesta aba */
    }
  }

  // A página do endereço (#p=N) tem prioridade; senão, onde a pessoa parou da última vez.
  function paginaInicial() {
    const m = location.hash.match(/p=(\d+)/);
    const n = m ? parseInt(m[1], 10) : dados.paginaSalva || 1;
    return Math.min(Math.max(n, 1), total);
  }

  function urlDaPagina(n, extra) {
    const params = [];
    if (prefs.qualidade !== dados.qualidadePadrao) params.push("q=" + encodeURIComponent(prefs.qualidade));
    if (extra) params.push(extra);
    return dados.paginas[n - 1] + (params.length ? "?" + params.join("&") : "");
  }

  // --------------------------------------------------------- estado comum

  function mudouPagina() {
    barra.value = pagina;
    indicador.textContent = pagina + " / " + total;
    history.replaceState(null, "", "#p=" + pagina);
    document.dispatchEvent(
      new CustomEvent("nami:pagina", { detail: { capitulo: dados.capitulo, pagina: pagina, total: total } })
    );
  }

  function mostrarAviso(texto) {
    aviso.textContent = texto;
    aviso.hidden = false;
    clearTimeout(timerAviso);
    timerAviso = setTimeout(() => { aviso.hidden = true; }, 1800);
  }

  // -------------------------------------------------------- modo paginado

  function exibirPagina(n) {
    noFim = false;
    fim.hidden = true;
    erro.hidden = true;
    pagina = n;
    imgAtual.src = urlDaPagina(n);
    imgAtual.alt = "Página " + n;
    window.scrollTo(0, 0);
    preCarregar(n);
    mudouPagina();
  }

  // Baixa as próximas páginas antes de a pessoa chegar nelas.
  function preCarregar(n) {
    for (let i = n + 1; i <= Math.min(n + 3, total); i++) {
      new Image().src = urlDaPagina(i);
    }
  }

  function avancarPaginado() {
    if (noFim) {
      if (dados.proximo) location.href = dados.proximo;
      else mostrarAviso("Este é o último capítulo disponível");
      return;
    }
    if (pagina < total) {
      exibirPagina(pagina + 1);
    } else {
      noFim = true;
      fim.hidden = false;
    }
  }

  function voltarPaginado() {
    if (noFim) {
      noFim = false;
      fim.hidden = true;
      return;
    }
    if (pagina > 1) exibirPagina(pagina - 1);
    else mostrarAviso("Esta é a primeira página");
  }

  // Com a página mais alta que a tela, o espaço rola antes de virar a página.
  function rolar(sentido) {
    const passo = window.innerHeight * 0.85;
    const maximo = document.documentElement.scrollHeight - window.innerHeight;
    if (sentido > 0 && window.scrollY < maximo - 2) {
      window.scrollBy({ top: passo, behavior: "smooth" });
      return true;
    }
    if (sentido < 0 && window.scrollY > 2) {
      window.scrollBy({ top: -passo, behavior: "smooth" });
      return true;
    }
    return false;
  }

  imgAtual.addEventListener("load", () => { erro.hidden = true; });
  imgAtual.addEventListener("error", () => {
    if (imgAtual.getAttribute("src")) erro.hidden = false;
  });
  $("tentar-de-novo").addEventListener("click", () => {
    erro.hidden = true;
    imgAtual.src = urlDaPagina(pagina, "r=" + Date.now());
  });

  // -------------------------------------------------- modo rolagem contínua

  function montarScroll() {
    if (areaScroll.childElementCount) return;
    for (let n = 1; n <= total; n++) {
      const caixa = document.createElement("div");
      caixa.className = "pagina-scroll";
      caixa.dataset.pagina = n;

      const img = document.createElement("img");
      img.loading = "lazy"; // só baixa quando estiver chegando perto da tela
      img.decoding = "async";
      img.alt = "Página " + n;
      img.addEventListener("load", () => caixa.classList.add("carregada"));
      img.addEventListener("error", () => caixa.classList.add("falhou"));
      img.src = urlDaPagina(n);

      const botao = document.createElement("button");
      botao.type = "button";
      botao.className = "botao";
      botao.textContent = "Página " + n + " falhou — tentar de novo";
      botao.addEventListener("click", () => {
        caixa.classList.remove("falhou");
        img.src = urlDaPagina(n, "r=" + Date.now());
      });

      caixa.append(img, botao);
      areaScroll.append(caixa);
    }

    // A página "atual" é a que está cruzando o meio da tela.
    observador = new IntersectionObserver((entradas) => {
      for (const entrada of entradas) {
        if (entrada.isIntersecting) {
          pagina = Number(entrada.target.dataset.pagina);
          mudouPagina();
        }
      }
    }, { rootMargin: "-50% 0px -50% 0px" });
    areaScroll.querySelectorAll(".pagina-scroll").forEach((caixa) => observador.observe(caixa));
  }

  function desmontarScroll() {
    if (observador) observador.disconnect();
    observador = null;
    areaScroll.replaceChildren();
  }

  function irNoScroll(n) {
    const alvo = areaScroll.children[n - 1];
    if (alvo) alvo.scrollIntoView({ block: "start" });
  }

  // ------------------------------------------------------ comandos gerais

  function proxima() {
    if (prefs.modo === "paginado") avancarPaginado();
    else if (pagina < total) irNoScroll(pagina + 1);
    else fim.scrollIntoView({ behavior: "smooth" });
  }

  function anterior() {
    if (prefs.modo === "paginado") voltarPaginado();
    else if (pagina > 1) irNoScroll(pagina - 1);
  }

  function irPara(n) {
    if (prefs.modo === "paginado") exibirPagina(n);
    else irNoScroll(n);
  }

  // No modo direita→esquerda (mangá tradicional), a seta da esquerda avança.
  function paraDireita() {
    if (prefs.modo === "paginado" && prefs.direcao === "rtl") anterior();
    else proxima();
  }

  function paraEsquerda() {
    if (prefs.modo === "paginado" && prefs.direcao === "rtl") proxima();
    else anterior();
  }

  function irCapitulo(url, mensagem) {
    if (url) location.href = url;
    else mostrarAviso(mensagem);
  }

  function telaCheia() {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => {});
  }

  function alternarPainel(abrir) {
    const aberto = abrir === undefined ? painel.hidden : abrir;
    painel.hidden = !aberto;
    botaoConfig.setAttribute("aria-expanded", String(aberto));
  }

  function aplicarPrefs() {
    leitor.dataset.modo = prefs.modo;
    document.body.dataset.modo = prefs.modo;
    alternarBarras(false);
    leitor.dataset.ajuste = prefs.ajuste;
    for (const nome of ["modo", "direcao", "ajuste", "qualidade"]) {
      const radio = painel.querySelector('input[name="' + nome + '"][value="' + prefs[nome] + '"]');
      if (radio) radio.checked = true;
    }
    if (prefs.modo === "scroll") {
      noFim = false;
      erro.hidden = true;
      fim.hidden = false; // no scroll, o bloco de fim fica sempre lá embaixo
      montarScroll();
      irNoScroll(pagina);
      mudouPagina();
    } else {
      exibirPagina(pagina);
    }
  }

  function trocarModo() {
    prefs.modo = prefs.modo === "paginado" ? "scroll" : "paginado";
    salvarPrefs();
    aplicarPrefs();
    mostrarAviso(prefs.modo === "paginado" ? "Modo paginado" : "Rolagem contínua");
  }

  // ---------------------------------------------------------------- eventos

  function alternarBarras(esconder) {
    document.body.classList.toggle("ui-oculta", esconder);
  }

  $("zona-esquerda").addEventListener("click", paraEsquerda);
  $("zona-direita").addEventListener("click", paraDireita);
  imgAtual.addEventListener("click", () => alternarBarras());
  // Na rolagem, tocar numa página mostra/esconde as barras.
  areaScroll.addEventListener("click", (ev) => {
    if (!(ev.target instanceof Element) || !ev.target.closest("button")) alternarBarras();
  });
  botaoConfig.addEventListener("click", () => alternarPainel());

  // Com as configurações abertas, tocar fora fecha o painel (e não vira a página).
  document.addEventListener("click", (ev) => {
    if (painel.hidden || !(ev.target instanceof Node)) return;
    if (painel.contains(ev.target) || botaoConfig.contains(ev.target)) return;
    alternarPainel(false);
    ev.preventDefault();
    ev.stopPropagation();
  }, true);

  // Deslizar o dedo vira a página no modo paginado: o dedo indo pra esquerda
  // puxa a página da direita. Com zoom de pinça, o gesto é só pra mover a imagem.
  let toque = null;
  const comZoom = () => window.visualViewport && window.visualViewport.scale > 1.05;
  leitor.addEventListener("touchstart", (ev) => {
    toque = null;
    if (prefs.modo !== "paginado" || ev.touches.length !== 1 || comZoom()) return;
    toque = { x: ev.touches[0].clientX, y: ev.touches[0].clientY, quando: Date.now() };
  }, { passive: true });
  leitor.addEventListener("touchend", (ev) => {
    if (!toque || ev.changedTouches.length !== 1) return;
    const dx = ev.changedTouches[0].clientX - toque.x;
    const dy = ev.changedTouches[0].clientY - toque.y;
    const rapido = Date.now() - toque.quando < 800;
    toque = null;
    if (!rapido || Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    ev.preventDefault(); // não deixa o fim do gesto virar também um toque na zona
    if (dx < 0) paraDireita();
    else paraEsquerda();
  }, { passive: false });

  // Na rolagem, as barras somem quando a pessoa desce e voltam quando sobe.
  let ultimoY = window.scrollY;
  window.addEventListener("scroll", () => {
    const y = window.scrollY;
    if (prefs.modo !== "scroll" || !painel.hidden || Math.abs(y - ultimoY) < 12) return;
    alternarBarras(y > ultimoY && y > 80);
    ultimoY = y;
  }, { passive: true });
  $("seletor-capitulo").addEventListener("change", (ev) => { location.href = ev.target.value; });

  barra.addEventListener("input", () => { indicador.textContent = barra.value + " / " + total; });
  barra.addEventListener("change", () => irPara(Number(barra.value)));

  painel.addEventListener("change", (ev) => {
    const campo = ev.target;
    if (!campo.name || !(campo.name in prefs)) return;
    prefs[campo.name] = campo.value;
    salvarPrefs();
    if (campo.name === "qualidade") desmontarScroll(); // remonta com as URLs novas
    aplicarPrefs();
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.target instanceof Element && ev.target.closest("input, select, textarea")) return;
    switch (ev.key) {
      case "ArrowRight": case "d": case "D": paraDireita(); break;
      case "ArrowLeft": case "a": case "A": paraEsquerda(); break;
      case " ": case "PageDown": case "PageUp": {
        if (prefs.modo !== "paginado") return; // no scroll, deixa o navegador rolar
        const voltar = ev.key === "PageUp" || (ev.key === " " && ev.shiftKey);
        if (!rolar(voltar ? -1 : 1)) (voltar ? anterior : proxima)();
        break;
      }
      case "Home": irPara(1); break;
      case "End": irPara(total); break;
      case "]": irCapitulo(dados.proximo, "Não há próximo capítulo"); break;
      case "[": irCapitulo(dados.anterior, "Não há capítulo anterior"); break;
      case "m": case "M": trocarModo(); break;
      case "f": case "F": telaCheia(); break;
      case "h": case "H": alternarBarras(); break;
      case "c": case "C": alternarPainel(); break;
      case "Escape": alternarPainel(false); break;
      default: return;
    }
    ev.preventDefault();
  });

  // --------------------------------------------------- progresso de leitura

  // Só com login (o servidor manda o endereço). Espera a pessoa parar numa
  // página por um instante antes de salvar, pra não mandar uma requisição a
  // cada página folheada; ao sair da página, salva na hora.
  if (dados.salvarProgresso) {
    let timerProgresso = null;
    let ultimaSalva = null;

    const salvarProgresso = (saindo) => {
      clearTimeout(timerProgresso);
      if (pagina === ultimaSalva) return;
      ultimaSalva = pagina;
      fetch(dados.salvarProgresso, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pagina: pagina, total: total }),
        keepalive: saindo, // deixa o envio terminar mesmo com a aba fechando
      }).catch(() => { ultimaSalva = null; }); // sem rede: tenta de novo na próxima página
    };

    document.addEventListener("nami:pagina", () => {
      clearTimeout(timerProgresso);
      timerProgresso = setTimeout(() => salvarProgresso(false), 1500);
    });
    window.addEventListener("pagehide", () => salvarProgresso(true));
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") salvarProgresso(true);
    });
  }

  aplicarPrefs();
})();
