"""Progresso de leitura, histórico e favoritos (só pra quem tem conta)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencias import exigir_login, obter_db, obter_fontes
from app.fontes.base import NaoEncontrado
from app.fontes.registro import Registro
from app.models import Usuario
from app.renderizar import render
from app.rotas.conta import destino_seguro
from app.servicos import estante
from app.servicos.visibilidade import pode_ver

router = APIRouter()


class CorpoProgresso(BaseModel):
    pagina: int = Field(ge=1, le=5000)
    total: int = Field(ge=1, le=5000)


@router.post("/progresso/{fonte_id}/{capitulo_id}", status_code=204)
def salvar_progresso(
    fonte_id: str,
    capitulo_id: str,
    corpo: CorpoProgresso,
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    """Chamado pelo leitor (static/js/leitor.js) quando a pessoa troca de página."""
    fonte = fontes.obter(fonte_id)
    obra, capitulo = fonte.capitulo(capitulo_id)  # vem do cache: o leitor acabou de abrir
    if not pode_ver(obra.classificacao, usuario):
        raise NaoEncontrado(capitulo_id)
    estante.salvar_progresso(db, usuario, obra, capitulo, corpo.pagina, corpo.total)
    return Response(status_code=204)


@router.get("/historico")
def historico(request: Request, usuario: Usuario = Depends(exigir_login), db: Session = Depends(obter_db)):
    # Some do histórico o que a pessoa não pode mais ver (ex.: desligou o +18).
    itens = [i for i in estante.historico(db, usuario) if pode_ver(i.obra.classificacao, usuario)]
    return render(request, "historico.html", itens=itens)


@router.post("/historico/remover/{fonte_id}/{obra_id}")
def remover_do_historico(
    fonte_id: str, obra_id: str, usuario: Usuario = Depends(exigir_login), db: Session = Depends(obter_db)
):
    estante.remover_do_historico(db, usuario, fonte_id, obra_id)
    return RedirectResponse("/historico", status_code=303)


@router.get("/favoritos")
def favoritos(request: Request, usuario: Usuario = Depends(exigir_login), db: Session = Depends(obter_db)):
    obras = [o for o in estante.favoritos(db, usuario) if pode_ver(o.classificacao, usuario)]
    return render(request, "favoritos.html", obras=obras)


@router.post("/favoritos/{fonte_id}/{obra_id}")
def favoritar(
    fonte_id: str,
    obra_id: str,
    voltar: Annotated[str | None, Form(max_length=500)] = None,
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    obra = fontes.obter(fonte_id).obra(obra_id)
    if not pode_ver(obra.classificacao, usuario):
        raise NaoEncontrado(obra_id)
    estante.favoritar(db, usuario, obra)
    return RedirectResponse(destino_seguro(voltar or f"/obra/{fonte_id}/{obra_id}"), status_code=303)


@router.post("/favoritos/{fonte_id}/{obra_id}/remover")
def desfavoritar(
    fonte_id: str,
    obra_id: str,
    voltar: Annotated[str | None, Form(max_length=500)] = None,
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    estante.desfavoritar(db, usuario, fonte_id, obra_id)
    return RedirectResponse(destino_seguro(voltar or f"/obra/{fonte_id}/{obra_id}"), status_code=303)
