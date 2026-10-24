// Painel de admin da Nami: busca de metadados, aviso de envio e confirmações.
(function () {
  "use strict";

  // ------------------------------------- "Buscar no AniList / no MangaDex"

  const NOMES = { anilist: "AniList", mangadex: "MangaDex" };
  const CAMPOS = ["titulo", "autor", "descricao", "tags", "tipo", "classificacao", "status", "ano", "anilist_id"];

  document.querySelectorAll("[data-busca-metadados]").forEach((bloco) => {
    const form = bloco.closest("form");
    const lista = bloco.querySelector("[data-resultados]");
    const titulo = form.elements.namedItem("titulo");

    const preencher = (dados) => {
      for (const campo of CAMPOS) {
        const elemento = form.elements.namedItem(campo);
        // anilist_id vazio (obra do MangaDex sem AniList) não apaga o que já estava preenchido
        if (elemento && dados[campo] !== undefined && (campo !== "anilist_id" || dados[campo] !== "")) {
          elemento.value = dados[campo];
        }
      }
      lista.hidden = true;
    };

    const mostrar = (resultados, nome) => {
      lista.replaceChildren();
      if (!resultados.length) {
        const vazio = document.createElement("li");
        vazio.textContent = "Nada encontrado no " + nome + ".";
        lista.append(vazio);
      }
      for (const dados of resultados) {
        const item = document.createElement("li");
        const texto = document.createElement("span");
        const partes = [dados.formato || dados.tipo, dados.classificacao].filter(Boolean);
        texto.textContent = dados.titulo + (dados.ano ? " (" + dados.ano + ")" : "") + " · " + partes.join(" · ");
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

    bloco.querySelectorAll("[data-buscar]").forEach((botao) => {
      const fonte = botao.dataset.buscar;
      const rotulo = botao.textContent;
      botao.addEventListener("click", async () => {
        const termo = titulo.value.trim();
        if (!termo) {
          titulo.focus();
          return;
        }
        botao.disabled = true;
        botao.textContent = "Buscando…";
        try {
          const resposta = await fetch(
            "/admin/metadados?fonte=" + fonte + "&q=" + encodeURIComponent(termo)
          );
          const dados = await resposta.json();
          if (!resposta.ok) throw new Error(dados.erro || "erro");
          mostrar(dados, NOMES[fonte]);
        } catch (e) {
          mostrar([], NOMES[fonte]);
          lista.firstChild.textContent =
            "Não consegui falar com o " + NOMES[fonte] + " agora. Tente de novo em instantes.";
        } finally {
          botao.disabled = false;
          botao.textContent = rotulo;
        }
      });
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
