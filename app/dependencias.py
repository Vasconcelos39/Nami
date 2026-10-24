"""Coisas que as rotas recebem prontas (via Depends do FastAPI)."""

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Config
from app.fontes.registro import Registro
from app.models import Usuario
from app.servicos.auth import COOKIE_SESSAO, LoginNecessario, usuario_da_sessao


def obter_config(request: Request) -> Config:
    return request.app.state.config


def obter_fontes(request: Request) -> Registro:
    return request.app.state.fontes


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
