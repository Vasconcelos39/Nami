"""Formulário "Reportar problema" da página da obra (só com login)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.dependencias import exigir_login, madura_ativa, obter_db, obter_fontes
from app.dominio import Obra
from app.fontes.base import NaoEncontrado
from app.fontes.registro import Registro
from app.models import Usuario
from app.renderizar import render
from app.servicos import reportes
from app.servicos.visibilidade import pode_ver_em_alguma_area

router = APIRouter()


def _obra_visivel(
    request: Request, db: Session, fontes: Registro, fonte_id: str, obra_id: str, usuario: Usuario
) -> Obra:
    obra = fontes.obter(fonte_id).obra(obra_id)
    aberta = obra.classificacao.adulta and madura_ativa(request, db, usuario)
    if not pode_ver_em_alguma_area(obra.classificacao, usuario, aberta):
        raise NaoEncontrado(obra_id)  # obra escondida: nem confirma que existe
    return obra


@router.get("/obra/{fonte_id}/{obra_id}/reportar")
def formulario(
    fonte_id: str,
    obra_id: str,
    request: Request,
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    obra = _obra_visivel(request, db, fontes, fonte_id, obra_id, usuario)
    return render(
        request, "reportar.html", obra=obra, motivos=reportes.MOTIVOS, motivo="", detalhe="",
        madura=obra.classificacao.adulta,
    )


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
    obra = _obra_visivel(request, db, fontes, fonte_id, obra_id, usuario)
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
            madura=obra.classificacao.adulta,
        )
    raiz = "/madura" if obra.classificacao.adulta else ""
    return RedirectResponse(f"{raiz}/obra/{obra.fonte}/{obra.id}?reportado=1", status_code=303)
