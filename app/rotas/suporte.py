"""Área de suporte: tickets em forma de chat (só com login).

As páginas funcionam sem JavaScript (formulário normal). Com JavaScript, o
static/js/suporte.js manda as mensagens sem recarregar e busca as novas a
cada alguns segundos, pra conversa parecer um chat.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.dependencias import exigir_login, obter_db
from app.fontes.base import NaoEncontrado
from app.models import Usuario
from app.renderizar import render
from app.servicos import suporte

router = APIRouter(prefix="/suporte")

Assunto = Annotated[str, Form(max_length=500)]
Texto = Annotated[str, Form(max_length=10_000)]


def _quer_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _ticket_ou_404(db: Session, ticket_id: int, usuario: Usuario):
    ticket = suporte.obter(db, ticket_id, usuario)
    if ticket is None:
        raise NaoEncontrado(str(ticket_id))
    return ticket


@router.get("")
def lista(request: Request, usuario: Usuario = Depends(exigir_login), db: Session = Depends(obter_db)):
    return render(
        request, "suporte/lista.html", tickets=suporte.da_pessoa(db, usuario), rotulos=suporte.ROTULOS_STATUS
    )


@router.get("/novo")
def novo(request: Request, _usuario: Usuario = Depends(exigir_login)):
    return render(request, "suporte/novo.html", assunto="", texto="")


@router.post("/novo")
def criar(
    request: Request,
    assunto: Assunto = "",
    texto: Texto = "",
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    try:
        ticket = suporte.abrir(db, usuario, assunto, texto)
    except suporte.ErroDeSuporte as erro:
        return render(request, "suporte/novo.html", 400, assunto=assunto, texto=texto, erro=str(erro))
    return RedirectResponse(f"/suporte/{ticket.id}", status_code=303)


@router.get("/{ticket_id}")
def conversa(
    ticket_id: int, request: Request, usuario: Usuario = Depends(exigir_login), db: Session = Depends(obter_db)
):
    ticket = _ticket_ou_404(db, ticket_id, usuario)
    return _pagina(request, ticket, usuario)


def _pagina(request: Request, ticket, usuario: Usuario, status: int = 200, **extra):
    return render(
        request,
        "suporte/conversa.html",
        status,
        ticket=ticket,
        mensagens=[suporte.como_dict(m, usuario) for m in ticket.mensagens],
        rotulos=suporte.ROTULOS_STATUS,
        como_suporte=suporte.fala_como_suporte(ticket, usuario),
        **extra,
    )


@router.get("/{ticket_id}/mensagens")
def mensagens_novas(
    ticket_id: int,
    depois: Annotated[int, Query(ge=0)] = 0,
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    """O chat pergunta de tempos em tempos: "tem mensagem depois da N?"."""
    ticket = _ticket_ou_404(db, ticket_id, usuario)
    return {
        "status": ticket.status,
        "rotulo": suporte.ROTULOS_STATUS[ticket.status],
        "mensagens": [suporte.como_dict(m, usuario) for m in ticket.mensagens if m.id > depois],
    }


@router.post("/{ticket_id}/mensagens")
def enviar(
    ticket_id: int,
    request: Request,
    texto: Texto = "",
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    ticket = _ticket_ou_404(db, ticket_id, usuario)
    try:
        mensagem = suporte.responder(db, ticket, usuario, texto)
    except suporte.ErroDeSuporte as erro:
        if _quer_json(request):
            return JSONResponse({"erro": str(erro)}, status_code=400)
        return _pagina(request, ticket, usuario, 400, erro=str(erro), texto=texto)
    if _quer_json(request):
        return {
            "status": ticket.status,
            "rotulo": suporte.ROTULOS_STATUS[ticket.status],
            "mensagem": suporte.como_dict(mensagem, usuario),
        }
    return RedirectResponse(f"/suporte/{ticket.id}#fim", status_code=303)


@router.post("/{ticket_id}/status")
def mudar_status(
    ticket_id: int,
    acao: Annotated[str, Form(max_length=20)] = "",
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    ticket = _ticket_ou_404(db, ticket_id, usuario)
    suporte.mudar_status(db, ticket, fechado=acao == "fechar")
    return RedirectResponse(f"/suporte/{ticket.id}", status_code=303)
