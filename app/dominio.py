"""O formato interno da Nami.

Toda fonte (MangaDex, biblioteca local, ...) converte os dados dela para as
classes deste arquivo. Rotas, templates e leitor só conhecem este formato,
então adicionar uma fonte nova não exige mexer no resto do site.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit


class Classificacao(StrEnum):
    """Classificação etária, com os mesmos valores do MangaDex."""

    SAFE = "safe"
    SUGGESTIVE = "suggestive"
    EROTICA = "erotica"
    PORNOGRAPHIC = "pornographic"

    @property
    def adulta(self) -> bool:
        return self in (Classificacao.EROTICA, Classificacao.PORNOGRAPHIC)

    @property
    def rotulo(self) -> str:
        return _ROTULOS_CLASSIFICACAO[self]


_ROTULOS_CLASSIFICACAO = {
    Classificacao.SAFE: "Livre",
    Classificacao.SUGGESTIVE: "Sugestivo",
    Classificacao.EROTICA: "Erótico",
    Classificacao.PORNOGRAPHIC: "Pornográfico",
}


class Tipo(StrEnum):
    MANGA = "manga"
    MANHWA = "manhwa"
    MANHUA = "manhua"
    HQ = "hq"

    @property
    def rotulo(self) -> str:
        return _ROTULOS_TIPO[self]


_ROTULOS_TIPO = {Tipo.MANGA: "Mangá", Tipo.MANHWA: "Manhwa", Tipo.MANHUA: "Manhua", Tipo.HQ: "HQ"}


class Ordem(StrEnum):
    POPULARES = "populares"
    RECENTES = "recentes"
    NOVOS = "novos"

    @property
    def rotulo(self) -> str:
        return {"populares": "Populares", "recentes": "Atualizados", "novos": "Novos"}[self.value]


@dataclass(frozen=True)
class Filtro:
    """O que pedir para uma fonte numa busca ou listagem."""

    classificacoes: frozenset[Classificacao]
    tipos: frozenset[Tipo] | None = None  # None = todos os tipos
    termo: str = ""
    ordem: Ordem = Ordem.POPULARES
    idiomas: tuple[str, ...] = ("pt-br", "en")


@dataclass(frozen=True)
class LinkOficial:
    """Onde ler ou comprar a obra de forma legítima (app, site da revista, editora, loja)."""

    site: str
    url: str
    idioma: str | None = None  # código como "pt-br", "en", "ja"; None quando não informado
    leitura: bool = True  # True: dá pra ler lá; False: página de editora ou loja


@dataclass(frozen=True)
class Obra:
    fonte: str
    id: str  # id dentro da fonte (no MangaDex, o UUID)
    titulo: str
    tipo: Tipo
    classificacao: Classificacao
    capa_url: str | None = None  # sempre uma URL da própria Nami
    titulos_alternativos: tuple[str, ...] = ()
    descricao: str = ""
    autores: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    status: str | None = None
    ano: int | None = None
    link_original: str | None = None  # página da obra na fonte (crédito)
    anilist_id: int | None = None  # a mesma obra no AniList (catálogo de metadados)
    links_oficiais: tuple[LinkOficial, ...] = ()
    ultimo_capitulo: str | None = None  # número do capítulo final, quando a obra já terminou


@dataclass(frozen=True)
class Capitulo:
    fonte: str
    id: str
    obra_id: str
    idioma: str
    numero: str | None = None  # texto: "10.5" existe; None em oneshots
    volume: str | None = None
    titulo: str | None = None
    grupos: tuple[str, ...] = ()  # quem traduziu (crédito obrigatório)
    total_paginas: int = 0
    publicado_em: datetime | None = None
    link_externo: str | None = None  # capítulo hospedado fora (ex.: site oficial)
    disponivel: bool = True
    link_original: str | None = None  # página do capítulo na fonte (crédito)

    @property
    def ordem(self) -> float:
        """Número do capítulo como decimal, pra ordenar ("10.5" fica entre 10 e 11).

        Sem número de capítulo vale o do volume (biblioteca organizada por volumes).
        """
        for valor in (self.numero, self.volume):
            try:
                if valor:
                    return float(valor)
            except ValueError:
                pass
        return -1.0

    @property
    def chave(self) -> tuple:
        """Identifica "o mesmo capítulo" traduzido por grupos diferentes.

        Capítulo 3 e volume 3 são coisas diferentes; oneshots sem número nenhum
        nunca são confundidos entre si.
        """
        if self.numero:
            return ("cap", self.ordem)
        if self.volume:
            return ("vol", self.ordem)
        return ("id", self.id)

    @property
    def rotulo(self) -> str:
        if self.numero:
            return f"Cap. {self.numero}"
        return f"Vol. {self.volume}" if self.volume else "Oneshot"

    @property
    def legivel(self) -> bool:
        """Dá pra abrir no leitor da Nami?"""
        return self.disponivel and self.link_externo is None


@dataclass(frozen=True)
class Pagina:
    numero: int  # começa em 1
    url: str  # sempre uma URL da própria Nami


@dataclass(frozen=True)
class Imagem:
    conteudo: bytes
    tipo_mime: str


@dataclass(frozen=True)
class PaginaDeResultados:
    obras: list[Obra]
    total: int
    pagina: int
    por_pagina: int

    @property
    def total_paginas(self) -> int:
        return math.ceil(self.total / self.por_pagina) if self.total else 0


# Nomes bonitos pros sites oficiais mais comuns; os outros aparecem pelo domínio.
_NOMES_DE_SITES = {
    "mangaplus.shueisha.co.jp": "MANGA Plus",
    "webtoons.com": "WEBTOON",
    "viz.com": "VIZ",
    "yenpress.com": "Yen Press",
    "kodansha.us": "Kodansha",
    "comic-fuz.com": "COMIC FUZ",
    "bookwalker.jp": "BookWalker",
    "amazon.co.jp": "Amazon Japão",
    "amazon.com": "Amazon",
    "ebookjapan.yahoo.co.jp": "ebookjapan",
    "cdjapan.co.jp": "CDJapan",
    "tapas.io": "Tapas",
    "tappytoon.com": "Tappytoon",
    "pocketcomics.com": "Pocket Comics",
}


def _dominio(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def nome_do_site(url: str) -> str:
    dominio = _dominio(url)
    for conhecido, nome in _NOMES_DE_SITES.items():
        if dominio == conhecido or dominio.endswith("." + conhecido):
            return nome
    return dominio or url


def juntar_links(
    *listas: Iterable[LinkOficial], idiomas_primeiro: Sequence[str] = ()
) -> list[LinkOficial]:
    """Junta links de várias origens sem repetir, na ordem em que vão aparecer.

    Primeiro os que dá pra ler (antes das lojas), e dentro disso os idiomas
    que a pessoa lê, na ordem de `idiomas_primeiro`.
    """
    vistos: dict[str, LinkOficial] = {}
    for lista in listas:
        for link in lista:
            chave = _dominio(link.url) + urlsplit(link.url).path.rstrip("/").lower()
            vistos.setdefault(chave, link)

    def prioridade(link: LinkOficial) -> tuple[bool, int]:
        idioma = link.idioma or ""
        posicao = idiomas_primeiro.index(idioma) if idioma in idiomas_primeiro else len(idiomas_primeiro)
        return (not link.leitura, posicao)

    return sorted(vistos.values(), key=prioridade)


def um_por_numero(capitulos: Iterable[Capitulo], atual: Capitulo) -> list[Capitulo]:
    """Deixa só uma versão de cada número de capítulo.

    Quando vários grupos traduziram o mesmo capítulo, prefere o capítulo atual
    e depois o mesmo grupo dele, pra leitura seguir com a mesma tradução.
    """

    def prioridade(c: Capitulo) -> tuple[bool, bool]:
        return (c.id == atual.id, c.grupos == atual.grupos)

    escolhidos: dict[tuple, Capitulo] = {}
    for c in capitulos:
        anterior = escolhidos.get(c.chave)
        if anterior is None or prioridade(c) > prioridade(anterior):
            escolhidos[c.chave] = c
    return sorted(escolhidos.values(), key=lambda c: (c.ordem, c.chave[0]))


def navegacao(
    capitulos: Sequence[Capitulo], atual: Capitulo
) -> tuple[list[Capitulo], Capitulo | None, Capitulo | None]:
    """Lista de capítulos do mesmo idioma, mais o anterior e o próximo do atual."""
    mesmos = [c for c in capitulos if c.idioma == atual.idioma and c.legivel and c.id != atual.id]
    lista = um_por_numero([*mesmos, atual], atual)
    i = next(i for i, c in enumerate(lista) if c.id == atual.id)
    anterior = lista[i - 1] if i > 0 else None
    proximo = lista[i + 1] if i + 1 < len(lista) else None
    return lista, anterior, proximo
