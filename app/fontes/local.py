"""Fonte "Biblioteca local": obras que o admin enviou em .cbz/.cbr.

Cumpre o mesmo contrato do MangaDex (app/fontes/base.py), mas os dados vêm do
banco e as páginas, do disco. Os ids (obra e capítulo) são textos de 32
caracteres gerados no envio.
"""

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.config import Config
from app.dominio import (
    Capitulo,
    Classificacao,
    Filtro,
    Imagem,
    Obra,
    Ordem,
    Pagina,
    PaginaDeResultados,
    Tipo,
)
from app.fontes.base import NaoEncontrado
from app import models
from app.servicos.biblioteca import ID_LOCAL, TIPO_POR_EXTENSAO

FONTE_ID = "local"


class BibliotecaLocal:
    id = FONTE_ID
    nome = "Biblioteca local"
    capa_em_cache = False  # as capas já estão no disco: não precisa de cópia

    def __init__(self, config: Config, sessoes: sessionmaker[Session]):
        self.pasta = config.dir_biblioteca
        self.sessoes = sessoes

    # ------------------------------------------------------------------ busca

    def buscar(self, filtro: Filtro, pagina: int = 1, por_pagina: int = 24) -> PaginaDeResultados:
        if not filtro.classificacoes:
            return PaginaDeResultados([], 0, pagina, por_pagina)
        consulta = select(models.Obra).where(
            models.Obra.fonte_id == FONTE_ID,
            models.Obra.classificacao.in_([c.value for c in filtro.classificacoes]),
        )
        if filtro.tipos:
            consulta = consulta.where(models.Obra.tipo.in_([t.value for t in filtro.tipos]))
        if filtro.termo:
            parecido = "%" + filtro.termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            consulta = consulta.where(
                or_(models.Obra.titulo.ilike(parecido, escape="\\"), models.Obra.autor.ilike(parecido, escape="\\"))
            )

        with self.sessoes() as db:
            total = db.scalar(select(func.count()).select_from(consulta.subquery()))
            obras = db.scalars(
                self._ordenar(consulta, filtro)
                .options(selectinload(models.Obra.tags))
                .offset((pagina - 1) * por_pagina)
                .limit(por_pagina)
            ).all()
            return PaginaDeResultados([self._obra(o) for o in obras], total, pagina, por_pagina)

    def _ordenar(self, consulta, filtro: Filtro):
        if filtro.termo:
            return consulta.order_by(models.Obra.titulo)
        if filtro.ordem is Ordem.NOVOS:
            return consulta.order_by(models.Obra.criado_em.desc())
        if filtro.ordem is Ordem.RECENTES:  # capítulo enviado por último
            ultimo = (
                select(models.Capitulo.obra_id, func.max(models.Capitulo.publicado_em).label("quando"))
                .group_by(models.Capitulo.obra_id)
                .subquery()
            )
            return consulta.outerjoin(ultimo, ultimo.c.obra_id == models.Obra.id).order_by(
                ultimo.c.quando.desc().nulls_last(), models.Obra.titulo
            )
        favoritos = (  # "populares" na biblioteca = mais favoritada
            select(models.Favorito.obra_id, func.count().label("n")).group_by(models.Favorito.obra_id).subquery()
        )
        return consulta.outerjoin(favoritos, favoritos.c.obra_id == models.Obra.id).order_by(
            func.coalesce(favoritos.c.n, 0).desc(), models.Obra.titulo
        )

    # ------------------------------------------------------------------ obras

    def obra(self, obra_id: str) -> Obra:
        with self.sessoes() as db:
            return self._obra(self._obra_do_banco(db, obra_id))

    def classificacao_da_obra(self, obra_id: str) -> Classificacao:
        _validar_id(obra_id)
        with self.sessoes() as db:
            valor = db.scalar(
                select(models.Obra.classificacao).where(
                    models.Obra.fonte_id == FONTE_ID, models.Obra.id_externo == obra_id
                )
            )
        if valor is None:
            raise NaoEncontrado(obra_id)
        return Classificacao(valor)

    def capitulos(self, obra_id: str, idiomas: Sequence[str]) -> list[Capitulo]:
        with self.sessoes() as db:
            obra = self._obra_do_banco(db, obra_id)
            linhas = db.scalars(
                select(models.Capitulo).where(
                    models.Capitulo.obra_id == obra.id, models.Capitulo.idioma.in_(list(idiomas))
                )
            ).all()
            capitulos = [self._capitulo(c, obra) for c in linhas]
        return sorted(capitulos, key=lambda c: (c.ordem, c.idioma))

    def capitulo(self, capitulo_id: str) -> tuple[Obra, Capitulo]:
        with self.sessoes() as db:
            capitulo = self._capitulo_do_banco(db, capitulo_id)
            obra = db.scalar(
                select(models.Obra).options(selectinload(models.Obra.tags)).where(models.Obra.id == capitulo.obra_id)
            )
            return self._obra(obra), self._capitulo(capitulo, obra)

    # --------------------------------------------------------------- imagens

    def paginas(self, capitulo_id: str) -> list[Pagina]:
        with self.sessoes() as db:
            total = self._capitulo_do_banco(db, capitulo_id).total_paginas
        return [Pagina(n, f"/img/{self.id}/{capitulo_id}/{n}") for n in range(1, total + 1)]

    def imagem_pagina(self, capitulo_id: str, numero: int, qualidade: str) -> Imagem:
        # A qualidade não muda nada aqui: a imagem já está no disco do servidor.
        with self.sessoes() as db:
            capitulo = self._capitulo_do_banco(db, capitulo_id)
        if not 1 <= numero <= capitulo.total_paginas or not capitulo.pasta:
            raise NaoEncontrado(f"página {numero}")
        arquivo = next((self.pasta / capitulo.pasta).glob(f"{numero:04d}.*"), None)
        if arquivo is None or arquivo.suffix not in TIPO_POR_EXTENSAO:
            raise NaoEncontrado(f"página {numero}")
        return Imagem(arquivo.read_bytes(), TIPO_POR_EXTENSAO[arquivo.suffix])

    def imagem_capa(self, obra_id: str) -> Imagem | None:
        arquivo = self._arquivo_capa(obra_id)
        return Imagem(arquivo.read_bytes(), "image/jpeg") if arquivo.exists() else None

    def versao_capa(self, obra_id: str) -> str | None:
        arquivo = self._arquivo_capa(obra_id)
        return str(arquivo.stat().st_mtime_ns) if arquivo.exists() else None

    # ------------------------------------------------------------- detalhes

    def _arquivo_capa(self, obra_id: str) -> Path:
        _validar_id(obra_id)
        return self.pasta / obra_id / "capa.jpg"

    def _obra_do_banco(self, db: Session, obra_id: str) -> models.Obra:
        _validar_id(obra_id)
        obra = db.scalar(
            select(models.Obra)
            .options(selectinload(models.Obra.tags))
            .where(models.Obra.fonte_id == FONTE_ID, models.Obra.id_externo == obra_id)
        )
        if obra is None:
            raise NaoEncontrado(obra_id)
        return obra

    def _capitulo_do_banco(self, db: Session, capitulo_id: str) -> models.Capitulo:
        _validar_id(capitulo_id)
        capitulo = db.scalar(
            select(models.Capitulo)
            .join(models.Obra, models.Obra.id == models.Capitulo.obra_id)
            .where(models.Obra.fonte_id == FONTE_ID, models.Capitulo.id_externo == capitulo_id)
        )
        if capitulo is None:
            raise NaoEncontrado(capitulo_id)
        return capitulo

    def _obra(self, obra: models.Obra) -> Obra:
        capa = self.pasta / obra.id_externo / "capa.jpg"
        # O "?v=" muda quando a capa muda: o navegador não fica mostrando a antiga.
        capa_url = f"/capa/{self.id}/{obra.id_externo}?v={capa.stat().st_mtime_ns}" if capa.exists() else None
        return Obra(
            fonte=self.id,
            id=obra.id_externo,
            titulo=obra.titulo,
            tipo=Tipo(obra.tipo),
            classificacao=Classificacao(obra.classificacao),
            capa_url=capa_url,
            descricao=obra.descricao or "",
            autores=tuple(a.strip() for a in (obra.autor or "").split(",") if a.strip()),
            tags=tuple(sorted(t.nome for t in obra.tags)),
            status=obra.status,
            ano=obra.ano,
        )

    def _capitulo(self, capitulo: models.Capitulo, obra: models.Obra) -> Capitulo:
        return Capitulo(
            fonte=self.id,
            id=capitulo.id_externo,
            obra_id=obra.id_externo,
            idioma=capitulo.idioma,
            numero=capitulo.numero,
            volume=capitulo.volume,
            titulo=capitulo.titulo,
            grupos=(capitulo.grupo,) if capitulo.grupo else (),
            total_paginas=capitulo.total_paginas,
            publicado_em=capitulo.publicado_em,
        )


def _validar_id(valor: str) -> None:
    if not ID_LOCAL.fullmatch(valor):
        raise NaoEncontrado(valor)
