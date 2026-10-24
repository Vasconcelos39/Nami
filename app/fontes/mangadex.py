"""Adaptador do MangaDex (https://api.mangadex.org/docs/).

Regras deles que este arquivo cumpre:
- User-Agent honesto, sem fingir ser navegador.
- Limite de ~5 chamadas/s por IP (usamos 4/s) e 40/min no /at-home/server.
- Depois de um 429, parar até o horário que eles indicarem (insistir dá ban).
- contentRating sempre explícito: o padrão da API não é só "safe".
- Imagens nunca são linkadas direto (hotlink recebe imagem errada): as URLs
  apontam pras rotas /img e /capa da Nami, que buscam a imagem por aqui.
- Toda imagem baixada de um nó MangaDex@Home é reportada em
  api.mangadex.network/report, com sucesso ou falha.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.cache import CacheTTL
from app.config import Config
from app.dominio import (
    Capitulo,
    Classificacao,
    Filtro,
    Imagem,
    LinkOficial,
    Obra,
    Ordem,
    Pagina,
    PaginaDeResultados,
    Tipo,
    nome_do_site,
)
from app.fontes.base import FonteIndisponivel, NaoEncontrado
from app.fontes.limitador import JanelaLimite, Limitador

log = logging.getLogger("nami.mangadex")

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# Idioma original -> tipo. O que não estiver aqui vira HQ.
TIPO_POR_IDIOMA = {"ja": Tipo.MANGA, "ko": Tipo.MANHWA, "zh": Tipo.MANHUA, "zh-hk": Tipo.MANHUA}

_ORDEM_API = {
    Ordem.POPULARES: "followedCount",
    Ordem.RECENTES: "latestUploadedChapter",
    Ordem.NOVOS: "createdAt",
}

# O feed de capítulos filtra pela classificação da obra, que já foi checada
# antes de chegar aqui. Mandamos todas pra API não esconder nada por conta própria.
_TODAS_CLASSIFICACOES = [("contentRating[]", c.value) for c in Classificacao]

# Só servimos imagens desses tipos. Um SVG vindo de um nó de terceiros poderia
# carregar JavaScript e rodar no domínio da Nami.
_TIPOS_IMAGEM = {"image/jpeg", "image/png", "image/gif", "image/webp"}

LIMITE_RESULTADOS = 10_000  # a API recusa offset + limit acima disso

# Quanto tempo (s) cada resposta fica no cache.
TTL_BUSCA = 5 * 60
TTL_OBRA = 30 * 60
TTL_FEED = 10 * 60
TTL_CAPITULO = 30 * 60
TTL_SERVIDOR = 10 * 60  # o MangaDex garante a URL das páginas por pelo menos 15 min
TTL_VISTAS = 24 * 60 * 60


@dataclass(frozen=True)
class ServidorPaginas:
    """Resposta do /at-home/server: de onde baixar as páginas de um capítulo."""

    base_url: str
    hash: str
    arquivos: dict[str, tuple[str, ...]]  # qualidade ("data" | "data-saver") -> nomes


class MangaDex:
    id = "mangadex"
    nome = "MangaDex"
    capa_em_cache = True  # capas vêm de longe: guardar cópia no disco do servidor

    def __init__(
        self,
        config: Config,
        http: httpx.Client | None = None,
        chamadas_por_segundo: float = 4.0,
        executor: Executor | None = None,
    ):
        self.config = config
        self.http = http or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
        self.http.headers["User-Agent"] = config.user_agent
        self.cache = CacheTTL(maximo=2000)
        # Classificação e capa de toda obra que já passou por aqui (numa busca,
        # por exemplo). Assim o proxy de capas não chama a API pra cada capa.
        self._classificacoes = CacheTTL(maximo=50_000)
        self._capas = CacheTTL(maximo=50_000)
        self._limitador_api = Limitador(chamadas_por_segundo)
        self._limitador_capas = Limitador(chamadas_por_segundo)
        self._janela_servidor = JanelaLimite(limite=35, janela=60)  # o limite deles é 40/min
        # Os reports ao MangaDex@Home rodam em segundo plano pra não atrasar a imagem.
        self._executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="md-report")

    # ------------------------------------------------------------------ busca

    def buscar(self, filtro: Filtro, pagina: int = 1, por_pagina: int = 24) -> PaginaDeResultados:
        vazio = PaginaDeResultados([], 0, pagina, por_pagina)
        offset = (pagina - 1) * por_pagina
        if not filtro.classificacoes or offset + por_pagina > LIMITE_RESULTADOS:
            return vazio

        params: list[tuple[str, str | int]] = [
            ("limit", por_pagina),
            ("offset", offset),
            ("includes[]", "cover_art"),
            ("includes[]", "author"),
        ]
        params += [("contentRating[]", c.value) for c in sorted(filtro.classificacoes)]
        params += [("availableTranslatedLanguage[]", idioma) for idioma in filtro.idiomas]
        params += _params_de_tipo(filtro.tipos)
        if filtro.termo:
            params += [("title", filtro.termo), ("order[relevance]", "desc")]
        else:
            params.append((f"order[{_ORDEM_API[filtro.ordem]}]", "desc"))

        dados = self.cache.obter_ou_calcular(
            ("busca", tuple(params)), TTL_BUSCA, lambda: self._get("/manga", params)
        )
        # O total é limitado a um múltiplo de por_pagina que a API ainda aceita paginar.
        maximo = LIMITE_RESULTADOS - LIMITE_RESULTADOS % por_pagina
        return PaginaDeResultados(
            obras=[self._converter_obra(m) for m in dados["data"]],
            total=min(dados["total"], maximo),
            pagina=pagina,
            por_pagina=por_pagina,
        )

    # ------------------------------------------------------------------ obras

    def obra(self, obra_id: str) -> Obra:
        _validar_id(obra_id)
        dados = self.cache.obter_ou_calcular(
            ("obra", obra_id),
            TTL_OBRA,
            lambda: self._get(
                f"/manga/{obra_id}",
                [("includes[]", "cover_art"), ("includes[]", "author"), ("includes[]", "artist")],
            ),
        )
        return self._converter_obra(dados["data"])

    def classificacao_da_obra(self, obra_id: str) -> Classificacao:
        _validar_id(obra_id)
        classificacao = self._classificacoes.obter(obra_id)
        return classificacao if classificacao is not None else self.obra(obra_id).classificacao

    # ------------------------------------------------------------- capítulos

    def capitulos(self, obra_id: str, idiomas: Sequence[str]) -> list[Capitulo]:
        _validar_id(obra_id)
        idiomas = tuple(idiomas)

        def baixar() -> list[dict]:
            itens: list[dict] = []
            offset = 0
            while True:
                dados = self._get(
                    f"/manga/{obra_id}/feed",
                    [
                        ("limit", 500),
                        ("offset", offset),
                        ("includes[]", "scanlation_group"),
                        ("order[volume]", "asc"),
                        ("order[chapter]", "asc"),
                        *[("translatedLanguage[]", idioma) for idioma in idiomas],
                        *_TODAS_CLASSIFICACOES,
                    ],
                )
                itens += dados["data"]
                offset += 500
                if offset >= dados["total"] or offset + 500 > LIMITE_RESULTADOS:
                    return itens

        brutos = self.cache.obter_ou_calcular(("feed", obra_id, idiomas), TTL_FEED, baixar)
        capitulos = [self._converter_capitulo(c, obra_id) for c in brutos]
        return sorted(capitulos, key=lambda c: (c.ordem, c.idioma))

    def capitulo(self, capitulo_id: str) -> tuple[Obra, Capitulo]:
        _validar_id(capitulo_id)
        dados = self.cache.obter_ou_calcular(
            ("capitulo", capitulo_id),
            TTL_CAPITULO,
            lambda: self._get(
                f"/chapter/{capitulo_id}",
                [("includes[]", "manga"), ("includes[]", "scanlation_group")],
            ),
        )["data"]
        manga = next(
            (r for r in dados["relationships"] if r["type"] == "manga" and r.get("attributes")),
            None,
        )
        if manga is None:
            raise NaoEncontrado(capitulo_id)
        return self._converter_obra(manga), self._converter_capitulo(dados, manga["id"])

    # --------------------------------------------------------------- imagens

    def paginas(self, capitulo_id: str) -> list[Pagina]:
        _validar_id(capitulo_id)
        servidor = self._servidor(capitulo_id)
        return [
            Pagina(n, f"/img/{self.id}/{capitulo_id}/{n}")
            for n in range(1, len(servidor.arquivos["data"]) + 1)
        ]

    def imagem_pagina(self, capitulo_id: str, numero: int, qualidade: str) -> Imagem:
        _validar_id(capitulo_id)
        if qualidade not in ("data", "data-saver"):
            raise NaoEncontrado(qualidade)
        # Se a imagem falhar, o MangaDex manda pedir outro servidor e tentar de novo.
        for tentativa in range(2):
            servidor = self._servidor(capitulo_id, renovar=tentativa > 0)
            arquivos = servidor.arquivos[qualidade]
            if not 1 <= numero <= len(arquivos):
                raise NaoEncontrado(f"página {numero}")
            url = f"{servidor.base_url}/{qualidade}/{servidor.hash}/{arquivos[numero - 1]}"
            imagem = self._baixar_imagem(url, reportar="mangadex.org" not in servidor.base_url)
            if imagem is not None:
                return imagem
        raise FonteIndisponivel("Não foi possível baixar esta página do MangaDex.")

    def imagem_capa(self, obra_id: str) -> Imagem | None:
        _validar_id(obra_id)
        arquivo = self._capas.obter(obra_id)
        if arquivo is None:
            self.obra(obra_id)  # a resposta registra a capa em self._capas
            arquivo = self._capas.obter(obra_id)
        if arquivo is None:
            return None
        self._limitador_capas.aguardar()
        # ".256.jpg" = miniatura de 256 px de largura que o próprio MangaDex gera.
        url = f"{self.config.mangadex_capas}/{obra_id}/{arquivo}.256.jpg"
        return self._baixar_imagem(url, reportar=False)

    def versao_capa(self, obra_id: str) -> str | None:
        _validar_id(obra_id)
        # O nome do arquivo da capa muda quando o MangaDex troca a capa. Só usamos
        # o que já está na memória (vindo de uma busca, por exemplo), sem chamar a API.
        return self._capas.obter(obra_id)

    # ------------------------------------------------------- HTTP e detalhes

    def _get(self, caminho: str, params: Sequence[tuple[str, str | int]] = ()) -> dict:
        self._limitador_api.aguardar()
        try:
            resposta = self.http.get(f"{self.config.mangadex_api}{caminho}", params=list(params))
        except httpx.HTTPError as erro:
            log.warning("MangaDex sem resposta em %s: %s", caminho, erro)
            raise FonteIndisponivel("Não foi possível falar com o MangaDex agora.") from erro

        if resposta.status_code == 429:
            espera = _segundos_ate(resposta.headers.get("X-RateLimit-Retry-After"))
            log.warning("MangaDex devolveu 429; pausando chamadas por %.0f s", espera)
            self._limitador_api.bloquear(espera)
            raise FonteIndisponivel(
                "O MangaDex pediu uma pausa (limite de requisições). Tente de novo em instantes."
            )
        if resposta.status_code == 403:
            # 403 genérico costuma ser ban temporário; cada nova chamada renova o ban.
            log.warning("MangaDex devolveu 403 em %s; pausando chamadas por 60 s", caminho)
            self._limitador_api.bloquear(60)
            raise FonteIndisponivel("O MangaDex recusou o acesso. Tente de novo mais tarde.")
        if resposta.status_code == 404:
            raise NaoEncontrado(caminho)
        if resposta.status_code >= 400:
            log.warning(
                "MangaDex respondeu %s em %s: %s", resposta.status_code, caminho, resposta.text[:300]
            )
            raise FonteIndisponivel(f"O MangaDex respondeu com erro {resposta.status_code}.")
        return resposta.json()

    def _servidor(self, capitulo_id: str, renovar: bool = False) -> ServidorPaginas:
        chave = ("servidor", capitulo_id)
        if renovar:
            self.cache.remover(chave)

        def baixar() -> ServidorPaginas:
            self._janela_servidor.registrar()
            dados = self._get(f"/at-home/server/{capitulo_id}")
            capitulo = dados["chapter"]
            return ServidorPaginas(
                base_url=dados["baseUrl"],
                hash=capitulo["hash"],
                arquivos={
                    "data": tuple(capitulo["data"]),
                    "data-saver": tuple(capitulo["dataSaver"]),
                },
            )

        return self.cache.obter_ou_calcular(chave, TTL_SERVIDOR, baixar)

    def _baixar_imagem(self, url: str, reportar: bool) -> Imagem | None:
        inicio = time.monotonic()
        resposta = None
        try:
            resposta = self.http.get(url)
        except httpx.HTTPError as erro:
            log.info("Falha ao baixar %s: %s", url, erro)

        tipo = ""
        if resposta is not None:
            tipo = resposta.headers.get("content-type", "").split(";")[0].strip().lower()
        ok = resposta is not None and resposta.status_code == 200 and tipo in _TIPOS_IMAGEM

        if reportar:
            self._executor.submit(
                self._reportar,
                {
                    "url": url,
                    "success": ok,
                    "cached": resposta is not None
                    and resposta.headers.get("X-Cache", "").startswith("HIT"),
                    "bytes": len(resposta.content) if resposta is not None else 0,
                    "duration": round((time.monotonic() - inicio) * 1000),
                },
            )
        return Imagem(resposta.content, tipo) if ok else None

    def _reportar(self, dados: dict) -> None:
        try:
            self.http.post(self.config.mangadex_report, json=dados, timeout=10)
        except httpx.HTTPError as erro:
            log.debug("Report ao MangaDex@Home falhou: %s", erro)

    def _converter_obra(self, dados: dict) -> Obra:
        atributos = dados["attributes"]
        relacoes = dados.get("relationships", [])
        obra_id = dados["id"]

        classificacao = Classificacao(atributos["contentRating"])
        self._classificacoes.guardar(obra_id, classificacao, TTL_VISTAS)
        capa = next(
            (
                r["attributes"]["fileName"]
                for r in relacoes
                if r["type"] == "cover_art" and r.get("attributes")
            ),
            None,
        )
        if capa:
            self._capas.guardar(obra_id, capa, TTL_VISTAS)

        titulo = _primeiro_valor(atributos.get("title")) or "Sem título"
        autores = dict.fromkeys(  # dict.fromkeys tira repetidos mantendo a ordem
            r["attributes"]["name"]
            for r in relacoes
            if r["type"] in ("author", "artist") and r.get("attributes")
        )
        tags = sorted(
            nome
            for tag in atributos.get("tags", [])
            if (nome := tag["attributes"]["name"].get("en"))
        )
        return Obra(
            fonte=self.id,
            id=obra_id,
            titulo=titulo,
            tipo=TIPO_POR_IDIOMA.get(atributos.get("originalLanguage"), Tipo.HQ),
            classificacao=classificacao,
            capa_url=f"/capa/{self.id}/{obra_id}",
            titulos_alternativos=_titulos_alternativos(
                atributos.get("altTitles") or [], titulo, self.config.idiomas
            ),
            descricao=_limpar_descricao(
                _no_idioma(atributos.get("description") or {}, self.config.idiomas)
            ),
            autores=tuple(autores),
            tags=tuple(tags),
            status=atributos.get("status"),
            ano=atributos.get("year"),
            link_original=f"https://mangadex.org/title/{obra_id}",
            anilist_id=_anilist_id(atributos.get("links")),
            links_oficiais=_links_oficiais(atributos.get("links"), atributos.get("originalLanguage")),
            ultimo_capitulo=atributos.get("lastChapter") or None,
        )

    def _converter_capitulo(self, dados: dict, obra_id: str) -> Capitulo:
        atributos = dados["attributes"]
        grupos = tuple(
            r["attributes"]["name"]
            for r in dados.get("relationships", [])
            if r["type"] == "scanlation_group" and r.get("attributes")
        )
        return Capitulo(
            fonte=self.id,
            id=dados["id"],
            obra_id=obra_id,
            idioma=atributos["translatedLanguage"],
            numero=atributos.get("chapter"),
            volume=atributos.get("volume"),
            titulo=atributos.get("title") or None,
            grupos=grupos,
            total_paginas=atributos.get("pages") or 0,
            publicado_em=_data(atributos.get("publishAt")),
            link_externo=_url_externa(atributos.get("externalUrl")),
            disponivel=not atributos.get("isUnavailable", False),
            link_original=f"https://mangadex.org/chapter/{dados['id']}",
        )


def _params_de_tipo(tipos: frozenset[Tipo] | None) -> list[tuple[str, str]]:
    """Traduz os tipos pedidos pro filtro de idioma original da API.

    Mangá = japonês, manhwa = coreano, manhua = chinês. HQ é "todo o resto",
    então quando HQ está no filtro excluímos os idiomas que ficaram de fora.
    """
    if not tipos or tipos >= set(Tipo):
        return []
    if Tipo.HQ in tipos:
        return [
            ("excludedOriginalLanguage[]", idioma)
            for idioma, tipo in TIPO_POR_IDIOMA.items()
            if tipo not in tipos
        ]
    return [
        ("originalLanguage[]", idioma) for idioma, tipo in TIPO_POR_IDIOMA.items() if tipo in tipos
    ]


def _url_externa(valor: str | None) -> str | None:
    # O link vai parar num href da página: só http(s), nunca "javascript:" e afins.
    if isinstance(valor, str) and valor.lower().startswith(("https://", "http://")):
        return valor
    return None


def _anilist_id(links: dict | None) -> int | None:
    valor = str((links or {}).get("al") or "")
    return int(valor) if valor.isdigit() else None


# Chaves de "links" do MangaDex que levam a lugares oficiais. engtl = tradução
# oficial em inglês, raw = publicação original; as outras são lojas.
_LINKS_LOJAS = {
    "bw": "https://bookwalker.jp/",  # o valor é um caminho, ex.: "series/191669/list"
    "amz": "",
    "ebj": "",
    "cdj": "",
}


def _links_oficiais(links: dict | None, idioma_original: str | None) -> tuple[LinkOficial, ...]:
    links = links or {}
    encontrados = []
    for chave, idioma in (("engtl", "en"), ("raw", idioma_original)):
        url = links.get(chave)
        if isinstance(url, str) and url.startswith("https://"):
            encontrados.append(LinkOficial(nome_do_site(url), url, idioma, leitura=True))
    for chave, prefixo in _LINKS_LOJAS.items():
        valor = links.get(chave)
        if not isinstance(valor, str) or not valor:
            continue
        url = prefixo + valor if prefixo else valor
        if url.startswith("https://"):
            encontrados.append(LinkOficial(nome_do_site(url), url, idioma_original, leitura=False))
    return tuple(encontrados)


def _validar_id(valor: str) -> None:
    # Ids do MangaDex são UUIDs. Validar antes evita mandar lixo pra API (e
    # garante que o valor nunca vira caminho de arquivo ou URL inesperada).
    if not _UUID.fullmatch(valor):
        raise NaoEncontrado(valor)


def _segundos_ate(retry_after: str | None) -> float:
    """O cabeçalho X-RateLimit-Retry-After é um horário UNIX; converte em segundos de espera."""
    try:
        return min(max(float(retry_after) - time.time(), 1.0), 600.0)
    except (TypeError, ValueError):
        return 30.0


def _primeiro_valor(textos: dict | None) -> str | None:
    return next(iter(textos.values()), None) if textos else None


def _no_idioma(textos: dict[str, str], idiomas: Sequence[str]) -> str:
    for idioma in idiomas:
        if textos.get(idioma):
            return textos[idioma]
    return _primeiro_valor(textos) or ""


def _titulos_alternativos(
    alternativos: list[dict[str, str]], titulo: str, idiomas: Sequence[str], maximo: int = 3
) -> tuple[str, ...]:
    encontrados: list[str] = []
    for idioma in idiomas:
        for item in alternativos:
            valor = item.get(idioma)
            if valor and valor != titulo and valor not in encontrados:
                encontrados.append(valor)
    return tuple(encontrados[:maximo])


_LINK_MARKDOWN = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def _limpar_descricao(texto: str) -> str:
    """Tira a marcação Markdown das sinopses (a Nami mostra como texto puro)."""
    texto = re.split(r"\n\s*---", texto, maxsplit=1)[0]  # depois do --- costumam vir só links
    texto = _LINK_MARKDOWN.sub(r"\1", texto)
    texto = re.sub(r"\*\*|__|^#+\s*", "", texto, flags=re.MULTILINE)
    return texto.strip()


def _data(valor: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(valor) if valor else None
    except ValueError:
        return None
