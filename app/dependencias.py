"""Coisas que as rotas recebem prontas (via Depends do FastAPI)."""

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.catalogos.anilist import AniList
from app.config import Config
from app.fontes.base import NaoEncontrado
from app.fontes.registro import Registro
from app.models import Usuario
from app.servicos import area_madura
from app.servicos.auth import COOKIE_SESSAO, LoginNecessario, usuario_da_sessao
from app.servicos.visibilidade import pode_entrar_na_area_madura


class AreaMaduraFechada(Exception):
    """A conta tem acesso, mas a área madura não está aberta neste aparelho:
    vai pra página que pede a senha."""


def obter_config(request: Request) -> Config:
    return request.app.state.config


def obter_fontes(request: Request) -> Registro:
    return request.app.state.fontes


def obter_anilist(request: Request) -> AniList:
    return request.app.state.anilist


def obter_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessoes() as sessao:
        yield sessao


def usuario_atual(request: Request, db: Session = Depends(obter_db)) -> Usuario | None:
    """Quem está usando o site, pelo cookie de sessão. None = visitante."""
    usuario = usuario_da_sessao(db, request.cookies.get(COOKIE_SESSAO))
    request.state.usuario = usuario  # os templates mostram o menu da conta a partir daqui
    return usuario


def exigir_login(usuario: Usuario | None = Depends(usuario_atual)) -> Usuario:
    if usuario is None:
        raise LoginNecessario()
    return usuario


def madura_ativa(request: Request, db: Session, usuario: Usuario | None, renovar: bool = False) -> bool:
    """A área madura está aberta neste aparelho? (pras rotas que servem as duas áreas)"""
    return area_madura.ativa(db, usuario, request.cookies.get(COOKIE_SESSAO), renovar=renovar)


def exigir_area_madura(
    request: Request, db: Session = Depends(obter_db), usuario: Usuario | None = Depends(usuario_atual)
) -> Usuario:
    """Toda página de /madura. Sem acesso: 404 (nem confirma que a área existe).
    Com acesso, mas com a área fechada: pede a senha."""
    if not pode_entrar_na_area_madura(usuario):
        raise NaoEncontrado("madura")
    if not madura_ativa(request, db, usuario, renovar=True):
        raise AreaMaduraFechada()
    return usuario
