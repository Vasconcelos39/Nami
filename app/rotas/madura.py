"""Área madura (/madura): o único lugar com conteúdo adulto (erótico e pornográfico).

As páginas são as mesmas do site normal (busca, obra, leitor, histórico e
favoritos), chamadas com madura=True: aqui só aparece o que é adulto, e no site
normal nunca aparece. Regras de entrada em servicos/area_madura.py.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.catalogos.anilist import AniList
from app.config import Config
from app.dependencias import (
    exigir_area_madura,
    obter_anilist,
    obter_config,
    obter_db,
    obter_fontes,
    usuario_atual,
)
from app.dominio import Filtro, Ordem
from app.fontes.base import NaoEncontrado
from app.fontes.registro import Registro
from app.models import Usuario
from app.renderizar import render
from app.rotas import catalogo, estante, leitor
from app.rotas.conta import destino_seguro
from app.servicos import area_madura
from app.servicos import estante as servico_estante
from app.servicos.auth import COOKIE_SESSAO
from app.servicos.maioridade import SenhaErrada
from app.servicos.visibilidade import ADULTAS, pode_entrar_na_area_madura

router = APIRouter(prefix="/madura")

RAIZ = "/madura"


# ------------------------------------------------------------------- entrar


@router.get("/entrar")
def pagina_entrar(request: Request, proximo: str | None = None, usuario: Usuario | None = Depends(usuario_atual)):
    """Pede a senha sempre que alguém entra pelo link (mesmo com a área aberta)."""
    if not pode_entrar_na_area_madura(usuario):
        raise NaoEncontrado("madura")  # sem acesso: nem confirma que a área existe
    return _pagina_entrar(request, 200, proximo)


def _pagina_entrar(request: Request, status: int, proximo: str | None, **contexto):
    return render(
        request, "madura/entrar.html", status, proximo=_destino(proximo), madura=True, entrando=True,
        tempo_sem_uso=_minutos(), **contexto,
    )


def _minutos() -> int:
    return int(area_madura.TEMPO_SEM_USO.total_seconds() // 60)


def _destino(proximo: str | None) -> str:
    destino = destino_seguro(proximo)
    return destino if destino.startswith(RAIZ) else RAIZ


@router.post("/entrar")
def entrar(
    request: Request,
    senha: Annotated[str | None, Form(max_length=200)] = None,
    proximo: Annotated[str | None, Form(max_length=500)] = None,
    usuario: Usuario | None = Depends(usuario_atual),
    db: Session = Depends(obter_db),
):
    if not pode_entrar_na_area_madura(usuario):
        raise NaoEncontrado("madura")
    # Senha errada aqui conta no mesmo limite do login.
    limite, chave = request.app.state.limite_login_conta, usuario.username.lower()
    if limite.bloqueado(chave):
        return _pagina_entrar(
            request, 429, proximo, erro="Muitas tentativas com a senha errada. Espere 15 minutos e tente de novo."
        )
    try:
        area_madura.entrar(db, usuario, request.cookies.get(COOKIE_SESSAO), senha)
    except SenhaErrada as erro:
        limite.registrar(chave)
        return _pagina_entrar(request, 400, proximo, erro=str(erro))
    except area_madura.SemAcesso:
        raise NaoEncontrado("madura") from None
    return RedirectResponse(_destino(proximo), status_code=303)


@router.post("/sair")
def sair(request: Request, db: Session = Depends(obter_db)):
    area_madura.sair(db, request.cookies.get(COOKIE_SESSAO))
    return RedirectResponse("/", status_code=303)


# ------------------------------------------------------------------ páginas


@router.get("")
def inicio(
    request: Request,
    ordem: Ordem = Ordem.POPULARES,
    pagina: catalogo.NumeroPagina = 1,
    fonte: str | None = None,
    por: str | None = None,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario = Depends(exigir_area_madura),
    db: Session = Depends(obter_db),
):
    por_pagina, nova = catalogo._por_pagina(request, por)
    fonte = fonte or catalogo.MANGADEX
    if fonte not in catalogo.FONTES_DAS_LISTAGENS:
        raise NaoEncontrado(fonte)
    filtro = Filtro(ADULTAS, ordem=ordem, idiomas=tuple(config.idiomas))
    resultado = fontes.obter(fonte).buscar(filtro, pagina, por_pagina)
    lendo = servico_estante.historico(db, usuario, ADULTAS, limite=12) if pagina == 1 else []
    resposta = render(
        request,
        "madura/inicio.html",
        resultado=resultado,
        lendo=lendo,
        ordem=ordem,
        ordens=list(Ordem),
        fonte=fonte,
        abas_fonte=[(f, fontes.obter(f).nome) for f in catalogo.FONTES_DAS_LISTAGENS],
        tempo_sem_uso=_minutos(),
        madura=True,
    )
    return catalogo._lembrar_por_pagina(resposta, config, por_pagina, nova)


@router.get("/busca")
def busca(
    request: Request,
    q: Annotated[str, Query(max_length=200)] = "",
    pagina: catalogo.NumeroPagina = 1,
    fonte: str | None = None,
    por: str | None = None,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario = Depends(exigir_area_madura),
):
    return catalogo.pagina_busca(request, q, pagina, fonte, por, config, fontes, usuario, madura=True)


@router.get("/busca/sugestoes")
def sugestoes(
    q: Annotated[str, Query(max_length=200)] = "",
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario = Depends(exigir_area_madura),
):
    return catalogo.sugerir(q, config, fontes, usuario, madura=True)


@router.get("/obra/{fonte_id}/{obra_id}")
def obra(
    fonte_id: str,
    obra_id: str,
    request: Request,
    idioma: str | None = None,
    reportado: bool = False,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    anilist: AniList = Depends(obter_anilist),
    usuario: Usuario = Depends(exigir_area_madura),
    db: Session = Depends(obter_db),
):
    return catalogo.pagina_da_obra(
        request, fonte_id, obra_id, idioma, reportado, config, fontes, anilist, usuario, db, madura=True
    )


@router.get("/ler/{fonte_id}/{capitulo_id}")
def ler(
    fonte_id: str,
    capitulo_id: str,
    request: Request,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario = Depends(exigir_area_madura),
    db: Session = Depends(obter_db),
):
    return leitor.pagina_do_leitor(request, fonte_id, capitulo_id, config, fontes, usuario, db, madura=True)


@router.get("/historico")
def historico(request: Request, usuario: Usuario = Depends(exigir_area_madura), db: Session = Depends(obter_db)):
    return estante.pagina_historico(request, usuario, db, madura=True)


@router.get("/favoritos")
def favoritos(request: Request, usuario: Usuario = Depends(exigir_area_madura), db: Session = Depends(obter_db)):
    return estante.pagina_favoritos(request, usuario, db, madura=True)
