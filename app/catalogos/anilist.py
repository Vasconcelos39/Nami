"""AniList (https://docs.anilist.co): catálogo de metadados de mangás.

A Nami usa o AniList pra três coisas:
- saber quantos capítulos a obra original tem (o AniList só informa depois
  que a obra termina);
- listar onde ler oficialmente (os "links externos" de cada obra);
- preencher os dados das obras da biblioteca local, no painel de admin.

Regras deles que este arquivo cumpre:
- Uso não comercial e sem guardar cópia do catálogo: só consultamos a obra
  que alguém abriu, e a resposta fica algumas horas na memória.
- No máximo 30 chamadas por minuto (a API está em modo "degradado"; o normal
  é 90). Usamos 25, e depois de um 429 esperamos o tempo do Retry-After.

Se o AniList estiver fora do ar, a página da obra abre normalmente, só sem
essas informações: `ficha()` nunca levanta erro.
"""

from __future__ import annotations

import html
import logging
import re
import threading
import time
from dataclasses import dataclass

import httpx

from app.cache import CacheTTL
from app.config import Config
from app.dominio import LinkOficial, Tipo, nome_do_site
from app.fontes.base import FonteIndisponivel, NaoEncontrado
from app.fontes.limitador import JanelaLimite

log = logging.getLogger("nami.anilist")

TTL_FICHA = 6 * 60 * 60
TTL_FALHA = 10 * 60  # sem resposta: não tenta de novo a cada visita
TTL_BUSCA = 60 * 60

TIPO_POR_PAIS = {"JP": Tipo.MANGA, "KR": Tipo.MANHWA, "CN": Tipo.MANHUA, "TW": Tipo.MANHUA}
STATUS = {
    "FINISHED": "completed",
    "RELEASING": "ongoing",
    "HIATUS": "hiatus",
    "CANCELLED": "cancelled",
}
# O AniList escreve o idioma por extenso; a Nami usa códigos.
IDIOMAS = {
    "Portuguese": "pt-br",
    "English": "en",
    "Japanese": "ja",
    "Korean": "ko",
    "Chinese": "zh",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Thai": "th",
    "Indonesian": "id",
    "Vietnamese": "vi",
    "Russian": "ru",
    "Turkish": "tr",
    "Polish": "pl",
    "Arabic": "ar",
}
FORMATOS = {"MANGA": "Mangá", "ONE_SHOT": "One-shot", "NOVEL": "Light novel"}

_CAMPOS = """
fragment campos on Media {
  id siteUrl format status chapters volumes countryOfOrigin isAdult
  title { romaji english native }
  synonyms
  startDate { year }
  description(asHtml: false)
  genres
  externalLinks { url site type language isDisabled }
  staff(sort: RELEVANCE, perPage: 8) { edges { role node { name { full } } } }
}
"""
_CONSULTA_FICHA = "query ($id: Int) { Media(id: $id, type: MANGA) { ...campos } }" + _CAMPOS
_CONSULTA_BUSCA = (
    "query ($termo: String, $limite: Int) { Page(perPage: $limite) {"
    " media(search: $termo, type: MANGA, sort: SEARCH_MATCH) { ...campos } } }" + _CAMPOS
)


@dataclass(frozen=True)
class FichaAniList:
    """O que a Nami usa de uma obra do AniList."""

    id: int
    url: str  # página da obra no AniList (crédito)
    titulo: str
    tipo: Tipo
    formato: str  # "Mangá", "One-shot", "Light novel"...
    status: str | None  # mesmos valores do MangaDex: ongoing, completed...
    capitulos: int | None  # só vem preenchido depois que a obra termina
    volumes: int | None
    ano: int | None
    descricao: str
    autores: tuple[str, ...]
    generos: tuple[str, ...]
    adulto: bool
    links: tuple[LinkOficial, ...]


class AniList:
    nome = "AniList"

    def __init__(self, config: Config, http: httpx.Client | None = None, por_minuto: int = 25):
        self.config = config
        self.http = http or httpx.Client(timeout=httpx.Timeout(6.0, connect=4.0))
        self.http.headers["User-Agent"] = config.user_agent
        self.cache = CacheTTL(maximo=2000)
        self._janela = JanelaLimite(
            limite=por_minuto,
            janela=60,
            mensagem="O AniList está recebendo muitas consultas agora. Tente de novo em um minuto.",
        )
        self._bloqueado_ate = 0.0
        self._lock = threading.Lock()

    def ficha(self, anilist_id: int) -> FichaAniList | None:
        """A obra no AniList, ou None (desligado, fora do ar, limite, id que não existe)."""
        if not self.config.anilist_ativo:
            return None
        chave = ("ficha", anilist_id)
        guardado = self.cache.obter(chave)
        if guardado is not None:
            return guardado[0]  # guardado como tupla pra também lembrar das falhas (None)
        try:
            dados = self._consultar(_CONSULTA_FICHA, {"id": anilist_id})["Media"]
            ficha, ttl = (_converter(dados) if dados else None), TTL_FICHA
        except NaoEncontrado:
            ficha, ttl = None, TTL_FICHA
        except FonteIndisponivel as erro:
            log.info("AniList sem resposta para a obra %s: %s", anilist_id, erro)
            ficha, ttl = None, TTL_FALHA
        self.cache.guardar(chave, (ficha,), ttl)
        return ficha

    def buscar(self, termo: str, limite: int = 8) -> list[FichaAniList]:
        """Busca por título (painel de admin). Levanta FonteIndisponivel se não der."""
        if not self.config.anilist_ativo:
            raise FonteIndisponivel("A consulta ao AniList está desligada nesta instalação.")
        termo = termo.strip()[:200]
        if not termo:
            return []

        def baixar() -> list[FichaAniList]:
            dados = self._consultar(_CONSULTA_BUSCA, {"termo": termo, "limite": limite})
            return [_converter(m) for m in dados["Page"]["media"]]

        return self.cache.obter_ou_calcular(("busca", termo.lower(), limite), TTL_BUSCA, baixar)

    # ---------------------------------------------------------------- HTTP

    def _consultar(self, consulta: str, variaveis: dict) -> dict:
        with self._lock:
            if time.monotonic() < self._bloqueado_ate:
                raise FonteIndisponivel("O AniList pediu uma pausa. Tente de novo em instantes.")
        self._janela.registrar()
        try:
            resposta = self.http.post(
                self.config.anilist_api,
                json={"query": consulta, "variables": variaveis},
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as erro:
            raise FonteIndisponivel("Não foi possível falar com o AniList agora.") from erro

        if resposta.status_code == 429:
            espera = _segundos(resposta.headers.get("Retry-After"))
            log.warning("AniList devolveu 429; pausando consultas por %.0f s", espera)
            with self._lock:
                self._bloqueado_ate = max(self._bloqueado_ate, time.monotonic() + espera)
            raise FonteIndisponivel("O AniList pediu uma pausa. Tente de novo em instantes.")
        if resposta.status_code == 404:
            raise NaoEncontrado("anilist")
        if resposta.status_code >= 400:
            log.warning("AniList respondeu %s: %s", resposta.status_code, resposta.text[:300])
            raise FonteIndisponivel(f"O AniList respondeu com erro {resposta.status_code}.")
        try:
            return resposta.json()["data"]
        except (ValueError, KeyError, TypeError) as erro:
            raise FonteIndisponivel("O AniList mandou uma resposta inesperada.") from erro


def _segundos(valor: str | None) -> float:
    try:
        return min(max(float(valor), 1.0), 600.0)
    except (TypeError, ValueError):
        return 60.0


def _converter(dados: dict) -> FichaAniList:
    titulos = dados.get("title") or {}
    titulo = titulos.get("romaji") or titulos.get("english") or titulos.get("native") or "Sem título"
    autores = dict.fromkeys(  # sem repetir, na ordem de relevância
        aresta["node"]["name"]["full"]
        for aresta in (dados.get("staff") or {}).get("edges", [])
        if _eh_autor(aresta.get("role") or "") and aresta.get("node")
    )
    links = tuple(
        LinkOficial(
            # "Official Site" não diz nada: nesse caso, o nome do site vem do endereço.
            site=nome_do_site(link["url"]) if link.get("site") == "Official Site" else link["site"],
            url=link["url"],
            idioma=IDIOMAS.get(link.get("language") or ""),
            leitura=link.get("type") == "STREAMING",
        )
        for link in dados.get("externalLinks") or []
        if link.get("type") in ("STREAMING", "INFO")
        and not link.get("isDisabled")
        and str(link.get("url", "")).startswith("https://")
    )
    return FichaAniList(
        id=dados["id"],
        url=dados.get("siteUrl") or f"https://anilist.co/manga/{dados['id']}",
        titulo=titulo,
        tipo=TIPO_POR_PAIS.get(dados.get("countryOfOrigin"), Tipo.HQ),
        formato=FORMATOS.get(dados.get("format"), dados.get("format") or ""),
        status=STATUS.get(dados.get("status")),
        capitulos=dados.get("chapters"),
        volumes=dados.get("volumes"),
        ano=(dados.get("startDate") or {}).get("year"),
        descricao=_limpar_descricao(dados.get("description") or ""),
        autores=tuple(autores),
        generos=tuple(dados.get("genres") or ()),
        adulto=bool(dados.get("isAdult")),
        links=links,
    )


def _eh_autor(papel: str) -> bool:
    # "Story & Art", "Story", "Art", "Original Creator"... Tradutores e letristas
    # vêm como "Translator (English)": o parêntese indica edição estrangeira.
    return "(" not in papel and bool(re.search(r"story|art|original|creator", papel, re.IGNORECASE))


def _limpar_descricao(texto: str) -> str:
    """O AniList manda a sinopse com <br>, <i> e afins; a Nami mostra texto puro."""
    texto = re.sub(r"<br\s*/?>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = html.unescape(texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()
