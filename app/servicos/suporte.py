"""Suporte: a pessoa abre um ticket e os admins respondem, como num chat.

Quem vê um ticket: quem abriu e os admins. Pra qualquer outra conta, o
ticket "não existe" (404), nem confirma que o número está em uso.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import MensagemTicket, Ticket, Usuario, agora

ASSUNTO_MAXIMO = 120
TEXTO_MAXIMO = 4000
MAX_ABERTOS = 5  # tickets não fechados ao mesmo tempo, por conta
MAX_MENSAGENS_POR_HORA = 30  # por conta (os admins não têm limite)

ROTULOS_STATUS = {
    "aberto": "Esperando o suporte",
    "respondido": "Respondido",
    "fechado": "Fechado",
}


class ErroDeSuporte(Exception):
    """Mensagem pra mostrar no formulário."""


@dataclass(frozen=True)
class Novidades:
    respostas: int = 0  # tickets da pessoa com resposta nova do suporte
    aguardando: int = 0  # (admins) tickets esperando o suporte


def pode_ver(ticket: Ticket, usuario: Usuario) -> bool:
    return ticket.usuario_id == usuario.id or usuario.is_admin


def fala_como_suporte(ticket: Ticket, usuario: Usuario) -> bool:
    # Um admin no próprio ticket fala como qualquer pessoa.
    return usuario.is_admin and ticket.usuario_id != usuario.id


def obter(db: Session, ticket_id: int, usuario: Usuario) -> Ticket | None:
    ticket = db.scalar(
        select(Ticket)
        .options(selectinload(Ticket.mensagens).selectinload(MensagemTicket.autor), selectinload(Ticket.usuario))
        .where(Ticket.id == ticket_id)
    )
    return ticket if ticket is not None and pode_ver(ticket, usuario) else None


def _validar_texto(texto: str) -> str:
    texto = texto.strip()
    if not texto:
        raise ErroDeSuporte("Escreva a sua mensagem.")
    if len(texto) > TEXTO_MAXIMO:
        raise ErroDeSuporte(f"A mensagem pode ter no máximo {TEXTO_MAXIMO} caracteres.")
    return texto


def _conferir_ritmo(db: Session, usuario: Usuario) -> None:
    if usuario.is_admin:
        return
    na_ultima_hora = db.scalar(
        select(func.count())
        .select_from(MensagemTicket)
        .where(MensagemTicket.autor_id == usuario.id, MensagemTicket.criado_em > agora() - timedelta(hours=1))
    )
    if na_ultima_hora >= MAX_MENSAGENS_POR_HORA:
        raise ErroDeSuporte("Você mandou muitas mensagens na última hora. Espere um pouco.")


def abrir(db: Session, usuario: Usuario, assunto: str, texto: str) -> Ticket:
    assunto = " ".join(assunto.split())
    if len(assunto) < 3:
        raise ErroDeSuporte("Escreva um assunto (pelo menos 3 letras).")
    if len(assunto) > ASSUNTO_MAXIMO:
        raise ErroDeSuporte(f"O assunto pode ter no máximo {ASSUNTO_MAXIMO} caracteres.")
    texto = _validar_texto(texto)
    abertos = db.scalar(
        select(func.count())
        .select_from(Ticket)
        .where(Ticket.usuario_id == usuario.id, Ticket.status != "fechado")
    )
    if abertos >= MAX_ABERTOS:
        raise ErroDeSuporte(
            f"Você já tem {MAX_ABERTOS} conversas em aberto. Continue numa delas ou feche alguma."
        )
    _conferir_ritmo(db, usuario)
    ticket = Ticket(usuario_id=usuario.id, assunto=assunto, status="aberto")
    ticket.mensagens.append(MensagemTicket(autor_id=usuario.id, texto=texto))
    db.add(ticket)
    db.commit()
    return ticket


def responder(db: Session, ticket: Ticket, usuario: Usuario, texto: str) -> MensagemTicket:
    texto = _validar_texto(texto)
    _conferir_ritmo(db, usuario)
    do_suporte = fala_como_suporte(ticket, usuario)
    mensagem = MensagemTicket(autor_id=usuario.id, do_suporte=do_suporte, texto=texto)
    ticket.mensagens.append(mensagem)
    # Quem falou por último decide quem está "devendo" resposta. Ticket fechado reabre.
    ticket.status = "respondido" if do_suporte else "aberto"
    ticket.atualizado_em = agora()
    db.commit()
    return mensagem


def mudar_status(db: Session, ticket: Ticket, fechado: bool) -> None:
    if fechado:
        ticket.status = "fechado"
    else:
        ultima = ticket.mensagens[-1] if ticket.mensagens else None
        ticket.status = "respondido" if ultima is not None and ultima.do_suporte else "aberto"
    db.commit()


def da_pessoa(db: Session, usuario: Usuario) -> list[Ticket]:
    return list(
        db.scalars(
            select(Ticket).where(Ticket.usuario_id == usuario.id).order_by(Ticket.atualizado_em.desc())
        )
    )


def para_o_suporte(db: Session, status: str, limite: int = 200) -> list[Ticket]:
    # Os que esperam resposta: os mais antigos primeiro (quem espera há mais tempo).
    ordem = Ticket.atualizado_em.asc() if status == "aberto" else Ticket.atualizado_em.desc()
    return list(
        db.scalars(
            select(Ticket)
            .options(selectinload(Ticket.usuario))
            .where(Ticket.status == status)
            .order_by(ordem)
            .limit(limite)
        )
    )


def contar(db: Session, status: str) -> int:
    return db.scalar(select(func.count()).select_from(Ticket).where(Ticket.status == status))


def novidades(db: Session, usuario: Usuario) -> Novidades:
    respostas = db.scalar(
        select(func.count())
        .select_from(Ticket)
        .where(Ticket.usuario_id == usuario.id, Ticket.status == "respondido")
    )
    return Novidades(respostas=respostas, aguardando=contar(db, "aberto") if usuario.is_admin else 0)


def como_dict(mensagem: MensagemTicket, usuario: Usuario) -> dict:
    """Uma mensagem no formato que o chat (static/js/suporte.js) usa."""
    if mensagem.do_suporte:
        autor = "Suporte" + (f" ({mensagem.autor.username})" if usuario.is_admin and mensagem.autor else "")
    else:
        autor = mensagem.autor.username if mensagem.autor else "Conta apagada"
    return {
        "id": mensagem.id,
        "autor": autor,
        "minha": mensagem.autor_id == usuario.id,
        "suporte": mensagem.do_suporte,
        "texto": mensagem.texto,
        # Guardado em UTC. O JavaScript mostra no fuso do aparelho; sem ele, fica o texto em UTC.
        "quando": mensagem.criado_em.isoformat() + "Z",
        "quando_texto": mensagem.criado_em.strftime("%d/%m/%Y %H:%M") + " (UTC)",
    }
