"""Reportes: alguém logado avisa os admins de um problema numa obra."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dominio import Obra
from app.models import MOTIVOS_REPORTE, Reporte, Usuario, agora

MOTIVOS = {
    "capitulos": "Faltam capítulos ou estão fora de ordem",
    "capa": "Capa errada",
    "informacoes": "Título, sinopse ou outras informações erradas",
    "classificacao": "Classificação errada (ex.: conteúdo adulto sem aviso)",
    "outro": "Outro problema",
}
assert set(MOTIVOS) == set(MOTIVOS_REPORTE)

MAX_DETALHE = 1000
MAX_POR_DIA = 10  # por conta: evita que alguém lote a lista dos admins


class ErroDeReporte(Exception):
    """Mensagem pra mostrar no formulário."""


def reportar(db: Session, usuario: Usuario, obra: Obra, motivo: str, detalhe: str) -> Reporte:
    if motivo not in MOTIVOS:
        raise ErroDeReporte("Escolha o tipo de problema.")
    detalhe = detalhe.strip()
    if len(detalhe) > MAX_DETALHE:
        raise ErroDeReporte(f"A descrição pode ter no máximo {MAX_DETALHE} caracteres.")

    # O mesmo aviso de novo (ainda aberto) só atualiza a descrição.
    existente = db.scalar(
        select(Reporte).where(
            Reporte.usuario_id == usuario.id,
            Reporte.fonte_id == obra.fonte,
            Reporte.obra_externa == obra.id,
            Reporte.motivo == motivo,
            Reporte.resolvido_em.is_(None),
        )
    )
    if existente is not None:
        existente.detalhe = detalhe or existente.detalhe
        db.commit()
        return existente

    ultimas_24h = db.scalar(
        select(func.count())
        .select_from(Reporte)
        .where(Reporte.usuario_id == usuario.id, Reporte.criado_em > agora() - timedelta(days=1))
    )
    if ultimas_24h >= MAX_POR_DIA:
        raise ErroDeReporte("Você já mandou muitos avisos hoje. Tente de novo amanhã.")

    reporte = Reporte(
        usuario_id=usuario.id,
        fonte_id=obra.fonte,
        obra_externa=obra.id,
        titulo=obra.titulo[:500],
        motivo=motivo,
        detalhe=detalhe or None,
    )
    db.add(reporte)
    db.commit()
    return reporte


def abertos(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Reporte).where(Reporte.resolvido_em.is_(None)))


def listar(db: Session, resolvidos: bool, limite: int = 200) -> list[Reporte]:
    filtro = Reporte.resolvido_em.is_not(None) if resolvidos else Reporte.resolvido_em.is_(None)
    ordem = Reporte.resolvido_em.desc() if resolvidos else Reporte.criado_em.asc()
    return list(db.scalars(select(Reporte).where(filtro).order_by(ordem).limit(limite)))


def marcar(db: Session, reporte: Reporte, resolvido: bool) -> None:
    reporte.resolvido_em = agora() if resolvido else None
    db.commit()
