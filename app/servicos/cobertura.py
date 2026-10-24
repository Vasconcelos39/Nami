"""Quanto da obra dá pra ler aqui, comparado com a obra original.

O MangaDex às vezes tem menos capítulos que a obra: obras licenciadas perdem
capítulos, e grupos de tradução param no meio. Aqui a Nami compara o que tem
com outras referências pra avisar a pessoa e mostrar onde continuar oficialmente:

- o total de capítulos da obra original (AniList, ou o "último capítulo" do
  MangaDex), que só existe quando a obra já terminou;
- os outros idiomas, que às vezes vão bem mais longe;
- a data do último capítulo traduzido, quando a obra continua saindo.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.catalogos.anilist import FichaAniList
from app.dominio import Capitulo, LinkOficial, Obra, juntar_links

PARADA_APOS = timedelta(days=365)  # sem capítulo novo há mais que isso: tradução parada


@dataclass(frozen=True)
class Cobertura:
    unidade: str  # "cap" ou "vol" (biblioteca organizada só por volumes)
    ultimo_aqui: float | None  # maior capítulo (ou volume) que dá pra ler no idioma mostrado
    total_original: float | None  # capítulos (ou volumes) da obra original, se ela já terminou
    referencia: str | None  # de onde veio o total: "AniList" ou "MangaDex"
    mais_longe: tuple[str, float] | None  # outro idioma que vai além: (idioma, último)
    parada_desde: datetime | None  # último capítulo no idioma, quando a tradução parece parada
    links: tuple[LinkOficial, ...]  # onde continuar oficialmente
    ficha_url: str | None  # a obra no AniList (crédito)

    @property
    def faltando(self) -> bool:
        """A obra original tem mais capítulos do que dá pra ler aqui."""
        if self.total_original is None:
            return False
        return self.ultimo_aqui is None or self.ultimo_aqui < self.total_original

    @property
    def tem_aviso(self) -> bool:
        return self.faltando or self.mais_longe is not None or self.parada_desde is not None


def analisar(
    obra: Obra,
    por_idioma: Mapping[str, Sequence[Capitulo]],
    idioma: str | None,
    ficha: FichaAniList | None,
    idiomas_preferidos: Sequence[str] = (),
    agora: datetime | None = None,
) -> Cobertura:
    agora = agora or datetime.now(UTC)
    lista = por_idioma.get(idioma, []) if idioma else []
    todos = [c for caps in por_idioma.values() for c in caps]
    # Biblioteca só com volumes (sem número de capítulo): compara volumes.
    unidade = "cap" if any(c.numero for c in todos) or not any(c.volume for c in todos) else "vol"

    ultimo_aqui = _ultimo(lista, unidade)
    total, referencia = _total(obra, ficha, unidade)

    mais_longe = None
    for outro, capitulos in por_idioma.items():
        ultimo = _ultimo(capitulos, unidade)
        if outro == idioma or ultimo is None:
            continue
        if (ultimo_aqui is None or ultimo >= ultimo_aqui + 1) and (
            mais_longe is None or ultimo > mais_longe[1]
        ):
            mais_longe = (outro, ultimo)

    status = obra.status or (ficha.status if ficha else None)
    parada_desde = None
    if status == "ongoing":
        datas = [_com_fuso(c.publicado_em) for c in lista if c.publicado_em]
        recente = max(datas, default=None)
        if recente is not None and agora - recente > PARADA_APOS:
            parada_desde = recente

    links = juntar_links(
        obra.links_oficiais,
        ficha.links if ficha else (),
        idiomas_primeiro=[*idiomas_preferidos, *_idioma_original(obra)],
    )
    return Cobertura(
        unidade=unidade,
        ultimo_aqui=ultimo_aqui,
        total_original=total,
        referencia=referencia,
        mais_longe=mais_longe,
        parada_desde=parada_desde,
        links=tuple(links),
        ficha_url=ficha.url if ficha else None,
    )


def _ultimo(capitulos: Sequence[Capitulo], unidade: str) -> float | None:
    valores = [
        c.ordem for c in capitulos if c.legivel and (c.numero if unidade == "cap" else c.volume)
    ]
    return max(valores, default=None)


def _total(obra: Obra, ficha: FichaAniList | None, unidade: str) -> tuple[float | None, str | None]:
    if unidade == "vol":
        return (float(ficha.volumes), "AniList") if ficha and ficha.volumes else (None, None)
    if ficha and ficha.capitulos:
        return float(ficha.capitulos), "AniList"
    try:
        if obra.ultimo_capitulo:
            return float(obra.ultimo_capitulo), "MangaDex"
    except ValueError:
        pass
    return None, None


def _idioma_original(obra: Obra) -> list[str]:
    return {"manga": ["ja"], "manhwa": ["ko"], "manhua": ["zh"]}.get(obra.tipo.value, [])


def _com_fuso(data: datetime) -> datetime:
    # Datas da biblioteca local ficam no banco sem fuso (em UTC); as do MangaDex vêm com fuso.
    return data if data.tzinfo else data.replace(tzinfo=UTC)
