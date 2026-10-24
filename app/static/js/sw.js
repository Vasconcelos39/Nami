// Service worker da Nami: o que faz o navegador oferecer "Instalar app".
//
// De propósito, ele NÃO guarda páginas nem imagens de capítulos: as páginas
// mudam (e mostram dados da conta), e as imagens já têm o cache normal do
// navegador. Ele só guarda o mínimo pra mostrar uma tela "sem conexão" quando
// a internet cai, em vez da página de erro do navegador.
//
// É servido em /sw.js (raiz) porque só controla páginas abaixo do endereço
// dele. A versão vem no endereço (?v=...): a cada versão nova da Nami o
// navegador instala um service worker novo, que apaga o cache antigo.
"use strict";

const VERSAO = new URL(self.location.href).searchParams.get("v") || "0";
const CACHE = "nami-" + VERSAO;
const OFFLINE = "/static/offline.html";
const ARQUIVOS = [OFFLINE, "/static/css/nami.css", "/static/marca/nami-logo.png"];

self.addEventListener("install", (ev) => {
  ev.waitUntil(
    caches
      .open(CACHE)
      // cache: "reload" pula o cache HTTP do navegador e baixa a versão atual
      .then((cache) => cache.addAll(ARQUIVOS.map((url) => new Request(url, { cache: "reload" }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil(
    caches
      .keys()
      .then((nomes) =>
        Promise.all(nomes.filter((n) => n.startsWith("nami-") && n !== CACHE).map((n) => caches.delete(n)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (ev) => {
  const pedido = ev.request;
  if (pedido.method !== "GET") return;

  // Abrir uma página: sempre pela internet; sem conexão, a tela "sem conexão".
  if (pedido.mode === "navigate") {
    ev.respondWith(fetch(pedido).catch(() => caches.match(OFFLINE)));
    return;
  }

  // Os arquivos da tela "sem conexão": internet primeiro, cópia guardada se cair.
  const url = new URL(pedido.url);
  if (url.origin === self.location.origin && ARQUIVOS.includes(url.pathname)) {
    ev.respondWith(fetch(pedido).catch(() => caches.match(url.pathname)));
  }
  // Todo o resto (imagens, capas, progresso...) segue direto, sem passar por aqui.
});
