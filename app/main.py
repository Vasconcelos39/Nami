"""Monta o aplicativo: configuração, banco, fontes, rotas e páginas de erro.

Rodar em desenvolvimento (na raiz do projeto):
    .venv\\Scripts\\python -m uvicorn app.main:app --reload
"""

import mimetypes
from contextlib import asynccontextmanager
from urllib.parse import quote, urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.catalogos.anilist import AniList
from app.config import Config, get_config
from app.db import aplicar_migracoes, criar_engine
from app.dependencias import obter_db
from app.fontes.base import FonteIndisponivel, NaoEncontrado
from app.fontes.mangadex import MangaDex
from app.fontes.registro import criar_registro
from app.renderizar import PASTA_APP, render
from app.rotas import admin, catalogo, conta, estante, leitor, midia, reportes
from app.servicos.auth import LimiteTentativas, LoginNecessario
from app.servicos.imagens import CacheCapas
from app.servicos.protecao import LimiteDeTaxa, cabecalhos_de_seguranca, ip_do_cliente, segundos_retry

METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}

# O manifest (instalar a Nami como app no celular) precisa do tipo certo.
mimetypes.add_type("application/manifest+json", ".webmanifest")


def criar_app(
    config: Config | None = None, mangadex: MangaDex | None = None, anilist: AniList | None = None
) -> FastAPI:
    """Monta o app. `mangadex` e `anilist` permitem aos testes usar versões simuladas."""
    config = config or get_config()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        config.data_dir.mkdir(parents=True, exist_ok=True)
        aplicar_migracoes(config.database_url)  # cria/atualiza as tabelas
        app.state.capas.limpar()  # apaga capas que ficaram sem uso enquanto o servidor estava parado
        yield
        app.state.engine.dispose()

    # Sem /docs: a Nami é um site, não uma API pública.
    app = FastAPI(
        title="Nami", lifespan=ciclo_de_vida, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.config = config
    app.state.engine = criar_engine(config.database_url)
    app.state.sessoes = sessionmaker(app.state.engine, expire_on_commit=False)
    app.state.fontes = criar_registro(config, app.state.sessoes, mangadex)
    app.state.anilist = anilist or AniList(config)
    app.state.capas = CacheCapas(
        config.dir_cache_capas, config.cache_capas_mb, config.capas_dias_sem_uso
    )
    # Contra quem tenta adivinhar senhas ou criar contas em massa (por IP).
    app.state.limite_login = LimiteTentativas(maximo=10, janela=15 * 60)
    app.state.limite_cadastro = LimiteTentativas(maximo=5, janela=60 * 60)

    app.mount("/static", StaticFiles(directory=PASTA_APP / "static"), name="static")
    for modulo in (catalogo, leitor, midia, conta, estante, reportes, admin):
        app.include_router(modulo.router)

    limite_paginas = LimiteDeTaxa(config.limite_por_minuto) if config.limite_por_minuto else None
    limite_imagens = (
        LimiteDeTaxa(config.limite_imagens_por_minuto) if config.limite_imagens_por_minuto else None
    )
    cabecalhos = cabecalhos_de_seguranca(config)

    @app.middleware("http")
    async def proteger(request: Request, call_next):
        """Limite de requisições por IP e cabeçalhos de segurança em toda resposta."""
        caminho = request.url.path
        if not caminho.startswith("/static/") and caminho != "/healthz":
            limite = limite_imagens if caminho.startswith(("/img/", "/capa/")) else limite_paginas
            espera = limite.esperar(ip_do_cliente(request)) if limite else 0
            if espera:
                return PlainTextResponse(
                    "Muitas requisições seguidas. Espere um pouco e tente de novo.",
                    status_code=429,
                    headers={"Retry-After": segundos_retry(espera), **cabecalhos},
                )
        resposta = await call_next(request)
        for nome, valor in cabecalhos.items():
            resposta.headers.setdefault(nome, valor)
        return resposta

    @app.middleware("http")
    async def conferir_origem(request: Request, call_next):
        """Recusa formulários e envios vindos de outros sites (proteção contra CSRF).

        O navegador avisa de onde veio o envio no cabeçalho Origin. Se veio de
        outro endereço, alguém está tentando agir em nome de quem está logado.
        """
        if request.method not in METODOS_SEGUROS:
            origem = request.headers.get("origin")
            if origem and urlsplit(origem).netloc != request.headers.get("host"):
                return PlainTextResponse("Envio de outro site recusado.", status_code=403)
        return await call_next(request)

    @app.get("/healthz", include_in_schema=False)
    def healthz(db: Session = Depends(obter_db)):
        db.execute(text("SELECT 1"))
        return {"ok": True}

    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        # Navegadores pedem /favicon.ico na raiz mesmo com o <link rel="icon"> na página.
        return FileResponse(PASTA_APP / "static" / "marca" / "favicon.ico", headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        # Na raiz, e não em /static: o service worker só controla as páginas abaixo
        # do endereço dele. no-cache faz o navegador conferir sempre se há versão nova.
        return FileResponse(
            PASTA_APP / "static" / "js" / "sw.js",
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.exception_handler(LoginNecessario)
    async def login_necessario(request: Request, _erro: LoginNecessario):
        if request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"erro": "login necessário"}, status_code=401)
        # Depois de entrar, volta pra página que a pessoa tentou abrir.
        voltar = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if request.method != "GET":
            voltar = "/"
        return RedirectResponse(f"/entrar?proximo={quote(voltar)}", status_code=303)

    @app.exception_handler(NaoEncontrado)
    async def nao_encontrado(request: Request, _erro: NaoEncontrado):
        return _pagina_404(request)

    @app.exception_handler(FonteIndisponivel)
    async def fonte_indisponivel(request: Request, erro: FonteIndisponivel):
        return render(request, "erro.html", 503, titulo="Fonte indisponível", mensagem=str(erro))

    @app.exception_handler(StarletteHTTPException)
    async def erro_http(request: Request, erro: StarletteHTTPException):
        if erro.status_code == 404:
            return _pagina_404(request)
        return await http_exception_handler(request, erro)

    return app


def _pagina_404(request: Request):
    return render(
        request,
        "erro.html",
        404,
        titulo="Não encontrado",
        mensagem="Esta página não existe ou não está disponível pra você.",
    )


app = criar_app()
