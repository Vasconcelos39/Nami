// Autocompletar da busca: enquanto a pessoa digita, aparecem até 6 obras que
// combinam com o texto. Cada formulário diz de onde vêm as sugestões
// (data-sugestoes): /busca/sugestoes no site normal, /madura/busca/sugestoes
// na área madura. Setas escolhem, Enter abre a
// obra escolhida, Esc fecha; Enter sem escolher nada faz a busca normal.
// Segue o padrão "combobox" de acessibilidade (leitores de tela anunciam a lista).
(function () {
  "use strict";

  const ESPERA = 300; // ms sem digitar antes de perguntar ao servidor
  const MINIMO = 3; // letras (o mesmo MINIMO_SUGESTAO do servidor)

  document.querySelectorAll('form.busca input[name="q"]').forEach(prepararCampo);

  function prepararCampo(campo, indice) {
    const form = campo.form;
    const endereco = form.dataset.sugestoes || "/busca/sugestoes";
    const lista = document.createElement("ul");
    lista.className = "sugestoes";
    lista.id = "sugestoes-" + indice;
    lista.setAttribute("role", "listbox");
    lista.setAttribute("aria-label", "Sugestões");
    lista.hidden = true;
    form.appendChild(lista);

    campo.setAttribute("role", "combobox");
    campo.setAttribute("aria-autocomplete", "list");
    campo.setAttribute("aria-expanded", "false");
    campo.setAttribute("aria-controls", lista.id);
    campo.setAttribute("autocomplete", "off");

    let temporizador = null;
    let pedido = null;
    let termoMostrado = "";
    let opcoes = []; // os <li> que dá pra escolher, na ordem
    let ativa = -1;

    campo.addEventListener("input", () => {
      clearTimeout(temporizador);
      const termo = campo.value.trim();
      if (termo.length < MINIMO) {
        fechar();
        return;
      }
      temporizador = setTimeout(() => buscar(termo), ESPERA);
    });

    campo.addEventListener("focus", () => {
      if (opcoes.length && campo.value.trim() === termoMostrado) abrir();
    });

    campo.addEventListener("keydown", (evento) => {
      if (lista.hidden) {
        if (evento.key === "ArrowDown" && opcoes.length) {
          abrir();
          evento.preventDefault();
        }
        return;
      }
      if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
        // -1 = de volta no campo; dá a volta nas duas pontas.
        let proxima = ativa + (evento.key === "ArrowDown" ? 1 : -1);
        if (proxima >= opcoes.length) proxima = -1;
        if (proxima < -1) proxima = opcoes.length - 1;
        marcar(proxima);
        evento.preventDefault();
      } else if (evento.key === "Enter" && ativa >= 0) {
        evento.preventDefault();
        window.location.href = opcoes[ativa].querySelector("a").href;
      } else if (evento.key === "Escape") {
        fechar();
        evento.preventDefault();
      }
    });

    // Clicar numa sugestão não pode tirar o foco do campo antes do clique valer.
    lista.addEventListener("mousedown", (evento) => evento.preventDefault());
    form.addEventListener("focusout", (evento) => {
      if (!form.contains(evento.relatedTarget)) fechar();
    });

    async function buscar(termo) {
      if (pedido) pedido.abort();
      pedido = new AbortController();
      try {
        const resposta = await fetch(endereco + "?q=" + encodeURIComponent(termo), {
          headers: { Accept: "application/json" },
          signal: pedido.signal,
        });
        if (!resposta.ok) return; // ex.: limite de requisições; a busca normal continua
        const dados = await resposta.json();
        if (campo.value.trim() !== termo) return; // a pessoa já digitou outra coisa
        mostrar(dados.itens || [], termo);
      } catch (erro) {
        // pedido cancelado (chegou letra nova) ou sem internet: fica sem sugestões
      }
    }

    function mostrar(itens, termo) {
      termoMostrado = termo;
      lista.replaceChildren();
      opcoes = itens.map((item, i) => opcao(i, item.url, conteudoDaObra(item)));
      const todos = form.getAttribute("action") + "?" + new URLSearchParams({ q: termo });
      const verTodos = opcao(itens.length, todos, document.createTextNode("Ver todos os resultados"));
      verTodos.classList.add("ver-todos");
      opcoes.push(verTodos);
      lista.append(...opcoes);
      marcar(-1);
      if (document.activeElement === campo) abrir();
    }

    function opcao(indice, url, conteudo) {
      const li = document.createElement("li");
      li.id = lista.id + "-" + indice;
      li.setAttribute("role", "option");
      const link = document.createElement("a");
      link.href = url;
      link.tabIndex = -1;
      link.append(conteudo);
      li.append(link);
      return li;
    }

    // Tudo com textContent: título vindo do MangaDex nunca vira HTML.
    function conteudoDaObra(item) {
      const pedaco = document.createDocumentFragment();
      const capa = document.createElement("span");
      capa.className = "sugestao-capa";
      const img = document.createElement("img");
      img.src = item.capa;
      img.alt = "";
      img.loading = "lazy";
      capa.append(img);

      const texto = document.createElement("span");
      texto.className = "sugestao-texto";
      const titulo = document.createElement("span");
      titulo.className = "sugestao-titulo";
      titulo.textContent = item.titulo;
      const info = document.createElement("span");
      info.className = "sugestao-info";
      info.textContent = item.info + (item.so_fora ? " · só no site oficial" : "");
      texto.append(titulo, info);

      pedaco.append(capa, texto);
      return pedaco;
    }

    function marcar(indice) {
      ativa = indice;
      opcoes.forEach((li, i) => li.setAttribute("aria-selected", String(i === indice)));
      if (indice >= 0) {
        campo.setAttribute("aria-activedescendant", opcoes[indice].id);
        opcoes[indice].scrollIntoView({ block: "nearest" });
      } else {
        campo.removeAttribute("aria-activedescendant");
      }
    }

    function abrir() {
      lista.hidden = false;
      campo.setAttribute("aria-expanded", "true");
    }

    function fechar() {
      lista.hidden = true;
      campo.setAttribute("aria-expanded", "false");
      marcar(-1);
    }
  }
})();
