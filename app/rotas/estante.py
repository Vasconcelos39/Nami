"""Progresso de leitura, histórico e favoritos (só pra quem tem conta)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencias import exigir_login, madura_ativa, obter_db, obter_fontes
from app.fontes.base import NaoEncontrado
from app.fontes.registro import Registro
from app.models import Usuario
from app.renderizar import render
from app.rotas.conta import destino_seguro
from app.servicos import estante
from app.servicos.visibilidade import classificacoes_permitidas, pode_ver_em_alguma_area

router = APIRouter()


class CorpoProgresso(BaseModel):
    pagina: int = Field(ge=1, le=5000)
    total: int = Field(ge=1, le=5000)


@router.post("/progresso/{fonte_id}/{capitulo_id}", status_code=204)
def salvar_progresso(
    fonte_id: str,
    capitulo_id: str,
    corpo: CorpoProgresso,
    request: Request,
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    """Chamado pelo leitor (static/js/leitor.js) quando a pessoa troca de página.

    Serve as duas áreas. Lendo na área madura, cada página virada também
    mantém a área aberta (senão ela fecharia no meio de um capítulo longo)."""
    fonte = fontes.obter(fonte_id)
    obra, capitulo = fonte.capitulo(capitulo_id)  # vem do cache: o leitor acabou de abrir
    aberta = obra.classificacao.adulta and madura_ativa(request, db, usuario, renovar=True)
    if not pode_ver_em_alguma_area(obra.classificacao, usuario, aberta):
        raise NaoEncontrado(capitulo_id)
    estante.salvar_progresso(db, usuario, obra, capitulo, corpo.pagina, corpo.total)
    return Response(status_code=204)


@router.get("/historico")
def historico(request: Request, usuario: Usuario = Depends(exigir_login), db: Session = Depends(obter_db)):
    return pagina_historico(request, usuario, db, madura=False)


def pagina_historico(request: Request, usuario: Usuario, db: Session, madura: bool):
    """Cada área tem o seu: o do site normal nunca mostra obra adulta, e o da
    área madura só mostra obra adulta."""
    itens = estante.historico(db, usuario, classificacoes_permitidas(usuario, madura))
    return render(request, "historico.html", itens=itens, madura=madura)


@router.post("/historico/remover/{fonte_id}/{obra_id}")
def remover_do_historico(
    fonte_id: str,
    obra_id: str,
    voltar: Annotated[str | None, Form(max_length=500)] = None,
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    estante.remover_do_historico(db, usuario, fonte_id, obra_id)
    return RedirectResponse(destino_seguro(voltar or "/historico"), status_code=303)


@router.get("/favoritos")
def favoritos(request: Request, usuario: Usuario = Depends(exigir_login), db: Session = Depends(obter_db)):
    return pagina_favoritos(request, usuario, db, madura=False)


def pagina_favoritos(request: Request, usuario: Usuario, db: Session, madura: bool):
    obras = estante.favoritos(db, usuario, classificacoes_permitidas(usuario, madura))
    return render(request, "favoritos.html", obras=obras, madura=madura)


@router.post("/favoritos/{fonte_id}/{obra_id}")
def favoritar(
    fonte_id: str,
    obra_id: str,
    request: Request,
    voltar: Annotated[str | None, Form(max_length=500)] = None,
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    obra = fontes.obter(fonte_id).obra(obra_id)
    aberta = obra.classificacao.adulta and madura_ativa(request, db, usuario)
    if not pode_ver_em_alguma_area(obra.classificacao, usuario, aberta):
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
