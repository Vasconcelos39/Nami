"""A estante de cada usuário: progresso de leitura, histórico e favoritos.

Obras e capítulos do MangaDex entram no banco aqui, numa cópia "leve", na
primeira vez que alguém lê ou favorita: progresso e favorito precisam apontar
pra uma linha do banco. O histórico sai da tabela de progresso.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app import dominio
from app.models import Capitulo, Favorito, Obra, Progresso, Usuario, agora


@dataclass(frozen=True)
class Leitura:
    """Até onde o usuário leu um capítulo."""

    pagina: int
    total: int
    concluido: bool
    quando: datetime


@dataclass(frozen=True)
class ItemHistorico:
    obra: dominio.Obra
    capitulo: dominio.Capitulo
    leitura: Leitura


# --------------------------------------------------- cópias leves no banco


def guardar_obra(db: Session, obra: dominio.Obra) -> int:
    """Cria ou atualiza a cópia da obra no banco e devolve o id dela."""
    valores = {
        "fonte_id": obra.fonte,
        "id_externo": obra.id,
        "titulo": obra.titulo[:500],
        "tipo": obra.tipo.value,
        "classificacao": obra.classificacao.value,
        "status": obra.status,
        "ano": obra.ano,
        "capa": obra.capa_url,
        "criado_em": agora(),
        "atualizado_em": agora(),
    }
    if obra.autores:  # a obra que vem junto de um capítulo não traz autores
        valores["autor"] = ", ".join(obra.autores)[:500]
    atualizar = {k: v for k, v in valores.items() if k not in ("fonte_id", "id_externo", "criado_em")}
    # "upsert": insere a obra ou, se ela já existe, atualiza (numa operação só).
    # Assim a classificação guardada acompanha a da fonte.
    db.execute(
        insert(Obra)
        .values(**valores)
        .on_conflict_do_update(index_elements=["fonte_id", "id_externo"], set_=atualizar)
    )
    return db.scalar(select(Obra.id).where(Obra.fonte_id == obra.fonte, Obra.id_externo == obra.id))


def guardar_capitulo(db: Session, obra_id: int, capitulo: dominio.Capitulo) -> int:
    publicado = capitulo.publicado_em
    if publicado is not None and publicado.tzinfo is not None:
        publicado = publicado.astimezone(UTC).replace(tzinfo=None)
    valores = {
        "obra_id": obra_id,
        "id_externo": capitulo.id,
        "numero": capitulo.numero,
        "volume": capitulo.volume,
        "ordem": capitulo.ordem,
        "titulo": (capitulo.titulo or "")[:500] or None,
        "idioma": capitulo.idioma,
        "grupo": ", ".join(capitulo.grupos)[:500] or None,
        "total_paginas": capitulo.total_paginas,
        "publicado_em": publicado,
    }
    atualizar = {k: v for k, v in valores.items() if k not in ("obra_id", "id_externo")}
    db.execute(
        insert(Capitulo)
        .values(**valores)
        .on_conflict_do_update(index_elements=["obra_id", "id_externo"], set_=atualizar)
    )
    return db.scalar(
        select(Capitulo.id).where(Capitulo.obra_id == obra_id, Capitulo.id_externo == capitulo.id)
    )


def _obra_do_banco(obra: Obra) -> dominio.Obra:
    return dominio.Obra(
        fonte=obra.fonte_id,
        id=obra.id_externo,
        titulo=obra.titulo,
        tipo=dominio.Tipo(obra.tipo),
        classificacao=dominio.Classificacao(obra.classificacao),
        capa_url=obra.capa,
    )


def _capitulo_do_banco(capitulo: Capitulo, obra: Obra) -> dominio.Capitulo:
    return dominio.Capitulo(
        fonte=obra.fonte_id,
        id=capitulo.id_externo,
        obra_id=obra.id_externo,
        idioma=capitulo.idioma,
        numero=capitulo.numero,
        volume=capitulo.volume,
        titulo=capitulo.titulo,
        grupos=tuple(capitulo.grupo.split(", ")) if capitulo.grupo else (),
        total_paginas=capitulo.total_paginas,
    )


# ----------------------------------------------------------------- progresso


def salvar_progresso(
    db: Session, usuario: Usuario, obra: dominio.Obra, capitulo: dominio.Capitulo, pagina: int, total: int
) -> None:
    obra_id = guardar_obra(db, obra)
    capitulo_id = guardar_capitulo(db, obra_id, capitulo)
    total = capitulo.total_paginas or total
    pagina = max(1, min(pagina, total))
    comando = insert(Progresso).values(
        usuario_id=usuario.id,
        capitulo_id=capitulo_id,
        pagina=pagina,
        concluido=pagina >= total,
        atualizado_em=agora(),
    )
    db.execute(
        comando.on_conflict_do_update(
            index_elements=["usuario_id", "capitulo_id"],
            set_={
                "pagina": comando.excluded.pagina,
                # Uma vez lido até o fim, continua "lido" mesmo se a pessoa voltar pro começo.
                "concluido": or_(Progresso.concluido, comando.excluded.concluido),
                "atualizado_em": comando.excluded.atualizado_em,
            },
        )
    )
    db.commit()


def _leituras(db: Session, usuario: Usuario, *filtros) -> dict[str, Leitura]:
    linhas = db.execute(
        select(
            Capitulo.id_externo,
            Progresso.pagina,
            Capitulo.total_paginas,
            Progresso.concluido,
            Progresso.atualizado_em,
        )
        .join(Progresso, Progresso.capitulo_id == Capitulo.id)
        .join(Obra, Obra.id == Capitulo.obra_id)
        .where(Progresso.usuario_id == usuario.id, *filtros)
    )
    return {
        linha.id_externo: Leitura(linha.pagina, linha.total_paginas, linha.concluido, linha.atualizado_em)
        for linha in linhas
    }


def leituras_da_obra(db: Session, usuario: Usuario, fonte_id: str, obra_id: str) -> dict[str, Leitura]:
    """Progresso em cada capítulo da obra, pelo id do capítulo na fonte."""
    return _leituras(db, usuario, Obra.fonte_id == fonte_id, Obra.id_externo == obra_id)


def leitura_do_capitulo(db: Session, usuario: Usuario, fonte_id: str, capitulo_id: str) -> Leitura | None:
    return _leituras(db, usuario, Obra.fonte_id == fonte_id, Capitulo.id_externo == capitulo_id).get(capitulo_id)


# ----------------------------------------------------------------- histórico


def historico(db: Session, usuario: Usuario, limite: int = 60) -> list[ItemHistorico]:
    """Obras lidas, da mais recente pra mais antiga, com o último capítulo aberto de cada uma."""
    ultima_leitura = (
        select(Capitulo.obra_id, func.max(Progresso.atualizado_em).label("quando"))
        .join(Progresso, Progresso.capitulo_id == Capitulo.id)
        .where(Progresso.usuario_id == usuario.id)
        .group_by(Capitulo.obra_id)
        .subquery()
    )
    linhas = db.execute(
        select(Obra, Capitulo, Progresso)
        .join(Capitulo, Capitulo.obra_id == Obra.id)
        .join(Progresso, Progresso.capitulo_id == Capitulo.id)
        .join(
            ultima_leitura,
            (ultima_leitura.c.obra_id == Obra.id) & (ultima_leitura.c.quando == Progresso.atualizado_em),
        )
        .where(Progresso.usuario_id == usuario.id)
        .order_by(Progresso.atualizado_em.desc())
        .limit(limite * 2)
    ).all()

    itens: list[ItemHistorico] = []
    vistas: set[int] = set()
    for obra, capitulo, progresso in linhas:
        if obra.id in vistas:  # dois capítulos salvos no mesmo instante: fica um só
            continue
        vistas.add(obra.id)
        leitura = Leitura(progresso.pagina, capitulo.total_paginas, progresso.concluido, progresso.atualizado_em)
        itens.append(ItemHistorico(_obra_do_banco(obra), _capitulo_do_banco(capitulo, obra), leitura))
    return itens[:limite]


def remover_do_historico(db: Session, usuario: Usuario, fonte_id: str, obra_id: str) -> None:
    capitulos = (
        select(Capitulo.id)
        .join(Obra, Obra.id == Capitulo.obra_id)
        .where(Obra.fonte_id == fonte_id, Obra.id_externo == obra_id)
    )
    db.execute(
        delete(Progresso).where(Progresso.usuario_id == usuario.id, Progresso.capitulo_id.in_(capitulos))
    )
    db.commit()


# ----------------------------------------------------------------- favoritos


def favoritar(db: Session, usuario: Usuario, obra: dominio.Obra) -> None:
    obra_id = guardar_obra(db, obra)
    db.execute(
        insert(Favorito)
        .values(usuario_id=usuario.id, obra_id=obra_id, criado_em=agora())
        .on_conflict_do_nothing()
    )
    db.commit()


def desfavoritar(db: Session, usuario: Usuario, fonte_id: str, obra_id: str) -> None:
    obra = select(Obra.id).where(Obra.fonte_id == fonte_id, Obra.id_externo == obra_id)
    db.execute(delete(Favorito).where(Favorito.usuario_id == usuario.id, Favorito.obra_id.in_(obra)))
    db.commit()


def eh_favorito(db: Session, usuario: Usuario, fonte_id: str, obra_id: str) -> bool:
    return (
        db.scalar(
            select(Favorito.obra_id)
            .join(Obra, Obra.id == Favorito.obra_id)
            .where(Favorito.usuario_id == usuario.id, Obra.fonte_id == fonte_id, Obra.id_externo == obra_id)
        )
        is not None
    )


def favoritos(db: Session, usuario: Usuario) -> list[dominio.Obra]:
    obras = db.scalars(
        select(Obra)
        .join(Favorito, Favorito.obra_id == Obra.id)
        .where(Favorito.usuario_id == usuario.id)
        .order_by(Favorito.criado_em.desc())
    )
    return [_obra_do_banco(obra) for obra in obras]
