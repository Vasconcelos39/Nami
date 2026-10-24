// Painel de admin da Nami: busca de metadados, aviso de envio e confirmações.
(function () {
  "use strict";

  // ------------------------------------------------ "Buscar no MangaDex"

  document.querySelectorAll("[data-busca-metadados]").forEach((bloco) => {
    const form = bloco.closest("form");
    const botao = bloco.querySelector("[data-buscar]");
    const lista = bloco.querySelector("[data-resultados]");
    const titulo = form.elements.namedItem("titulo");

    const preencher = (dados) => {
      for (const campo of ["titulo", "autor", "descricao", "tags", "tipo", "classificacao", "status", "ano"]) {
        const elemento = form.elements.namedItem(campo);
        if (elemento && dados[campo] !== undefined) elemento.value = dados[campo];
      }
      lista.hidden = true;
    };

    const mostrar = (resultados) => {
      lista.replaceChildren();
      if (!resultados.length) {
        const vazio = document.createElement("li");
        vazio.textContent = "Nada encontrado no MangaDex.";
        lista.append(vazio);
      }
      for (const dados of resultados) {
        const item = document.createElement("li");
        const texto = document.createElement("span");
        texto.textContent = dados.titulo + (dados.ano ? " (" + dados.ano + ")" : "") + " · " + dados.tipo + " · " + dados.classificacao;
        const usar = document.createElement("button");
        usar.type = "button";
        usar.className = "botao botao-secundario botao-pequeno";
        usar.textContent = "Usar estes dados";
        usar.addEventListener("click", () => preencher(dados));
        item.append(texto, usar);
        lista.append(item);
      }
      lista.hidden = false;
    };

    botao.addEventListener("click", async () => {
      const termo = titulo.value.trim();
      if (!termo) {
        titulo.focus();
        return;
      }
      botao.disabled = true;
      botao.textContent = "Buscando…";
      try {
        const resposta = await fetch("/admin/metadados?q=" + encodeURIComponent(termo));
        const dados = await resposta.json();
        if (!resposta.ok) throw new Error(dados.erro || "erro");
        mostrar(dados);
      } catch (e) {
        mostrar([]);
        lista.firstChild.textContent = "Não consegui falar com o MangaDex agora. Tente de novo em instantes.";
      } finally {
        botao.disabled = false;
        botao.textContent = "Buscar no MangaDex";
      }
    });
  });

  // --------------------------------------------- envio de arquivos grandes

  document.querySelectorAll("form[data-envio]").forEach((form) => {
    form.addEventListener("submit", () => {
      const botao = form.querySelector("[data-enviar]");
      const aviso = form.querySelector("[data-aguarde]");
      if (botao) botao.disabled = true;
      if (aviso) aviso.hidden = false;
    });
  });

  // ---------------------------------------------- confirmação antes de apagar

  document.querySelectorAll("form[data-confirmar]").forEach((form) => {
    form.addEventListener("submit", (ev) => {
      if (!window.confirm(form.dataset.confirmar)) ev.preventDefault();
    });
  });
})();
