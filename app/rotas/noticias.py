"""Novidades: o que mudou no site, contado pelos admins (escrito em /admin/novidades)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.dependencias import exigir_login, obter_db
from app.models import Usuario
from app.renderizar import render
from app.servicos import noticias

router = APIRouter()


@router.get("/novidades")
def pagina(request: Request, usuario: Usuario = Depends(exigir_login), db: Session = Depends(obter_db)):
    # Marca "nova" nos posts que saíram desde a última visita e apaga a bolinha do menu.
    vistas_antes = usuario.noticias_vistas_em
    lista = noticias.publicadas(db)
    noticias.marcar_vistas(db, usuario)
    return render(request, "noticias.html", lista=lista, vistas_antes=vistas_antes)
