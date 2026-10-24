"""Cadastro, login, logout e configurações da conta."""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import Config
from app.dependencias import exigir_login, obter_config, obter_db, usuario_atual
from app.fontes.base import NaoEncontrado
from app.models import Usuario, agora
from app.renderizar import NOMES_IDIOMA, render
from app.servicos.auth import (
    COOKIE_SESSAO,
    ErroDeConta,
    autenticar,
    criar_conta,
    criar_sessao,
    encerrar_sessao,
    trocar_senha,
)
from app.servicos.protecao import ip_do_cliente

router = APIRouter()

Campo = Annotated[str, Form(max_length=200)]
CampoOpcional = Annotated[str | None, Form(max_length=200)]

MENSAGENS_OK = {"preferencias": "Preferências salvas.", "senha": "Senha trocada. Os outros aparelhos foram desconectados."}


def destino_seguro(proximo: str | None) -> str:
    """Só aceita voltar pra uma página deste site (evita redirecionar pra um site falso)."""
    if not proximo or not proximo.startswith("/") or proximo.startswith(("//", "/\\")):
        return "/"
    partes = urlsplit(proximo)
    return "/" if partes.scheme or partes.netloc else proximo


def _entrar(resposta: RedirectResponse, token: str, config: Config) -> RedirectResponse:
    resposta.set_cookie(
        COOKIE_SESSAO,
        token,
        max_age=config.sessao_dias * 24 * 3600,
        httponly=True,  # o JavaScript da página não enxerga o cookie
        samesite="lax",  # outros sites não conseguem enviar formulários "como você"
        secure=config.cookie_seguro,
        path="/",
    )
    return resposta


# -------------------------------------------------------------------- entrar


@router.get("/entrar")
def pagina_entrar(request: Request, proximo: str | None = None, usuario: Usuario | None = Depends(usuario_atual)):
    if usuario is not None:
        return RedirectResponse(destino_seguro(proximo), status_code=303)
    return render(request, "entrar.html", proximo=destino_seguro(proximo))


@router.post("/entrar")
def entrar(
    request: Request,
    username: Campo,
    senha: Campo,
    proximo: CampoOpcional = None,
    config: Config = Depends(obter_config),
    db: Session = Depends(obter_db),
):
    proximo = destino_seguro(proximo)
    limite = request.app.state.limite_login
    if limite.bloqueado(ip_do_cliente(request)):
        return render(
            request, "entrar.html", 429, proximo=proximo, username=username,
            erro="Muitas tentativas erradas. Espere 15 minutos e tente de novo.",
        )
    try:
        usuario = autenticar(db, username, senha)
    except ErroDeConta as erro:
        return render(request, "entrar.html", 403, proximo=proximo, username=username, erro=str(erro))
    if usuario is None:
        limite.registrar(ip_do_cliente(request))
        return render(
            request, "entrar.html", 400, proximo=proximo, username=username,
            erro="Usuário ou senha incorretos.",
        )
    token = criar_sessao(db, usuario, config.sessao_dias)
    return _entrar(RedirectResponse(proximo, status_code=303), token, config)


# ------------------------------------------------------------------ cadastro


@router.get("/cadastro")
def pagina_cadastro(
    request: Request, config: Config = Depends(obter_config), usuario: Usuario | None = Depends(usuario_atual)
):
    if not config.cadastro_aberto:
        raise NaoEncontrado("cadastro")
    if usuario is not None:
        return RedirectResponse("/", status_code=303)
    return render(request, "cadastro.html")


@router.post("/cadastro")
def cadastrar(
    request: Request,
    username: Campo,
    senha: Campo,
    senha2: Campo,
    config: Config = Depends(obter_config),
    db: Session = Depends(obter_db),
):
    if not config.cadastro_aberto:
        raise NaoEncontrado("cadastro")
    limite = request.app.state.limite_cadastro
    if limite.bloqueado(ip_do_cliente(request)):
        return render(
            request, "cadastro.html", 429, username=username,
            erro="Muitas contas criadas a partir desta rede. Tente de novo mais tarde.",
        )
    try:
        if senha != senha2:
            raise ErroDeConta("As duas senhas não são iguais.")
        usuario = criar_conta(db, username, senha)
    except ErroDeConta as erro:
        return render(request, "cadastro.html", 400, username=username, erro=str(erro))
    limite.registrar(ip_do_cliente(request))
    token = criar_sessao(db, usuario, config.sessao_dias)
    return _entrar(RedirectResponse("/", status_code=303), token, config)


# --------------------------------------------------------------------- sair


@router.post("/sair")
def sair(request: Request, db: Session = Depends(obter_db)):
    token = request.cookies.get(COOKIE_SESSAO)
    if token:
        encerrar_sessao(db, token)
    resposta = RedirectResponse("/", status_code=303)
    resposta.delete_cookie(COOKIE_SESSAO, path="/")
    return resposta


# --------------------------------------------------------------------- conta


def _pagina_conta(request: Request, config: Config, status: int = 200, **contexto):
    return render(
        request, "conta.html", status,
        idiomas=[(codigo, NOMES_IDIOMA.get(codigo, codigo)) for codigo in config.idiomas],
        **contexto,
    )


@router.get("/conta")
def conta(
    request: Request,
    ok: str | None = None,
    config: Config = Depends(obter_config),
    _usuario: Usuario = Depends(exigir_login),
):
    return _pagina_conta(request, config, mensagem=MENSAGENS_OK.get(ok))


@router.post("/conta/preferencias")
def salvar_preferencias(
    request: Request,
    idioma: CampoOpcional = None,
    mostrar_adulto: CampoOpcional = None,
    confirmo_maioridade: CampoOpcional = None,
    config: Config = Depends(obter_config),
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    if idioma in config.idiomas:
        usuario.idioma_preferido = idioma
    quer_adulto = mostrar_adulto == "on"
    if quer_adulto and usuario.maioridade_confirmada_em is None:
        if confirmo_maioridade != "on":
            db.rollback()
            return _pagina_conta(
                request, config, 400, marcar_adulto=True,  # mantém a caixa marcada
                erro_preferencias="Pra ver conteúdo +18, confirme que você tem 18 anos ou mais.",
            )
        usuario.maioridade_confirmada_em = agora()
    usuario.mostrar_adulto = quer_adulto
    db.commit()
    return RedirectResponse("/conta?ok=preferencias", status_code=303)


@router.post("/conta/senha")
def salvar_senha(
    request: Request,
    atual: Campo,
    nova: Campo,
    nova2: Campo,
    config: Config = Depends(obter_config),
    usuario: Usuario = Depends(exigir_login),
    db: Session = Depends(obter_db),
):
    try:
        if nova != nova2:
            raise ErroDeConta("As duas senhas novas não são iguais.")
        trocar_senha(db, usuario, atual, nova, request.cookies.get(COOKIE_SESSAO, ""))
    except ErroDeConta as erro:
        return _pagina_conta(request, config, 400, erro_senha=str(erro))
    return RedirectResponse("/conta?ok=senha", status_code=303)
