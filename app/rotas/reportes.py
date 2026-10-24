"""Formulário "Reportar problema" da página da obra (só com login)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.dependencias import exigir_login, obter_db, obter_fontes
from app.dominio import Obra
from app.fontes.base import NaoEncontrado
from app.fontes.registro import Registro
from app.models import Usuario
from app.renderizar import render
from app.servicos import reportes
from app.servicos.visibilidade import pode_ver

router = APIRouter()


def _obra_visivel(fontes: Registro, fonte_id: str, obra_id: str, usuario: Usuario) -> Obra:
    obra = fontes.obter(fonte_id).obra(obra_id)
    if not pode_ver(obra.classificacao, usuario):
        raise NaoEncontrado(obra_id)  # obra +18 escondida: nem confirma que existe
    return obra


@router.get("/obra/{fonte_id}/{obra_id}/reportar")
def formulario(
    fonte_id: str,
    obra_id: str,
    request: Request,
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario = Depends(exigir_login),
):
    obra = _obra_visivel(fontes, fonte_id, obra_id, usuario)
    return render(request, "reportar.html", obra=obra, motivos=reportes.MOTIVOS, motivo="", detalhe="")


@router.post("/obra/{fonte_id}/{obra_id}/reportar")
def enviar(
    fonte_id: str,
    obra_id: str,
    request: Request,
    motivo: Annotated[str, Form(max_length=20)] = "",
    detalhe: Annotated[str, Form(max_length=5000)] = "",
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    obra = _obra_visivel(fontes, fonte_id, obra_id, usuario)
    try:
        reportes.reportar(db, usuario, obra, motivo, detalhe)
    except reportes.ErroDeReporte as erro:
        return render(
            request,
            "reportar.html",
            400,
            obra=obra,
            motivos=reportes.MOTIVOS,
            motivo=motivo,
            detalhe=detalhe,
            erro=str(erro),
        )
    return RedirectResponse(f"/obra/{obra.fonte}/{obra.id}?reportado=1", status_code=303)
