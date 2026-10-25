"""Monta o aplicativo: configuração, banco, fontes, rotas e páginas de erro.

Rodar em desenvolvimento (na raiz do projeto):
    .venv\\Scripts\\python -m uvicorn app.main:app --reload
"""

import logging
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
from app.dependencias import AreaMaduraFechada, obter_db
from app.fontes.base import FonteIndisponivel, NaoEncontrado
from app.fontes.mangadex import MangaDex
from app.fontes.registro import criar_registro
from app.renderizar import PASTA_APP, render
from app.rotas import admin, catalogo, conta, estante, leitor, madura, midia, noticias, reportes, suporte
from app.servicos.auth import LimiteTentativas, LoginNecessario
from app.servicos.imagens import CacheCapas
from app.servicos.protecao import (
    LimiteDeTaxa,
    cabecalhos_de_seguranca,
    chave_do_cliente,
    limite_do_corpo,
    segundos_retry,
)

log = logging.getLogger("nami")

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
        config.dir_temporario.mkdir(parents=True, exist_ok=True)  # envios grandes vão pro disco
        aplicar_migracoes(config.database_url)  # cria/atualiza as tabelas
        app.state.capas.limpar()  # apaga capas que ficaram sem uso enquanto o servidor estava parado
        if config.cookie_seguro and config.cadastro_aberto:
            log.warning(
                "O cadastro está aberto: qualquer pessoa na internet pode criar conta. "
                "Depois de criar as contas que você quer, use NAMI_CADASTRO_ABERTO=false."
            )
        yield
        app.state.fontes.obter("mangadex").encerrar()
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
    # Contra quem tenta adivinhar senhas ou criar contas em massa: por rede (IP)
    # e, no login, também por conta (muitas redes tentando a mesma conta).
    app.state.limite_login = LimiteTentativas(maximo=10, janela=15 * 60)
    app.state.limite_login_conta = LimiteTentativas(maximo=20, janela=15 * 60)
    app.state.limite_cadastro = LimiteTentativas(maximo=5, janela=60 * 60)

    app.mount("/static", StaticFiles(directory=PASTA_APP / "static"), name="static")
    for modulo in (catalogo, leitor, midia, conta, estante, reportes, suporte, noticias, madura, admin):
        app.include_router(modulo.router)

    limite_paginas = LimiteDeTaxa(config.limite_por_minuto) if config.limite_por_minuto else None
    limite_imagens = (
        LimiteDeTaxa(config.limite_imagens_por_minuto) if config.limite_imagens_por_minuto else None
    )
    # Abrir um capítulo do MangaDex gasta uma das ~35 consultas por minuto que o
    # servidor inteiro tem. Este limite impede que uma pessoa só gaste todas.
    limite_capitulos = LimiteDeTaxa(12) if config.limite_por_minuto else None
    # O autocompletar da busca também gasta consultas ao MangaDex a cada pausa na digitação.
    limite_sugestoes = LimiteDeTaxa(30) if config.limite_por_minuto else None
    cabecalhos = cabecalhos_de_seguranca(config)

    def _recusar(texto: str, status: int, **extra: str) -> PlainTextResponse:
        return PlainTextResponse(texto, status_code=status, headers={**extra, **cabecalhos})

    @app.middleware("http")
    async def proteger(request: Request, call_next):
        """Limites por IP, tamanho máximo do envio e cabeçalhos de segurança em toda resposta."""
        caminho = request.url.path
        tamanho = request.headers.get("content-length")
        if tamanho is not None and (not tamanho.isdigit() or int(tamanho) > limite_do_corpo(caminho, config)):
            return _recusar("Envio grande demais.", 413)
        if not caminho.startswith("/static/") and caminho != "/healthz":
            chave = chave_do_cliente(request)
            limites = [limite_imagens if caminho.startswith(("/img/", "/capa/")) else limite_paginas]
            if caminho.startswith("/ler/"):
                limites.append(limite_capitulos)
            elif caminho == "/busca/sugestoes":
                limites.append(limite_sugestoes)
            for limite in filter(None, limites):
                if espera := limite.esperar(chave):
                    return _recusar(
                        "Muitas requisições seguidas. Espere um pouco e tente de novo.",
                        429,
                        **{"Retry-After": segundos_retry(espera)},
                    )
        resposta = await call_next(request)
        for nome, valor in cabecalhos.items():
            resposta.headers.setdefault(nome, valor)
        if caminho.startswith("/static/"):
            # Com ?v=..., o endereço muda quando o arquivo muda: pode guardar por um ano.
            # Sem versão (logo, ícones, manifest), o navegador confere antes de usar.
            guardar = "public, max-age=31536000, immutable" if "v" in request.query_params else "no-cache"
            resposta.headers.setdefault("Cache-Control", guardar)
        return resposta

    @app.middleware("http")
    async def conferir_origem(request: Request, call_next):
        """Recusa formulários e envios vindos de outros sites (proteção contra CSRF).

        O navegador avisa de onde veio o envio (cabeçalhos Sec-Fetch-Site,
        Origin ou, nos mais antigos, Referer). Se veio de outro endereço, alguém
        está tentando agir em nome de quem está logado.
        """
        if request.method not in METODOS_SEGUROS:
            # Compara só o nome do site, sem a porta: proxies como o Nginx Proxy
            # Manager repassam o Host sem a porta (ex.: HTTPS numa porta que não é a 443).
            host = urlsplit("//" + request.headers.get("host", "")).hostname or ""
            origem = request.headers.get("origin") or request.headers.get("referer")
            de_fora = request.headers.get("sec-fetch-site") == "cross-site" or (
                origem is not None and (urlsplit(origem).hostname or "") != host
            )
            if de_fora:
                return _recusar("Envio de outro site recusado.", 403)
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
        # no-cache: o navegador confere antes de usar, então um ícone novo aparece logo.
        return FileResponse(PASTA_APP / "static" / "marca" / "favicon.ico", headers={"Cache-Control": "no-cache"})

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

    @app.exception_handler(AreaMaduraFechada)
    async def area_madura_fechada(request: Request, _erro: AreaMaduraFechada):
        voltar = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/madura/entrar?proximo={quote(voltar)}", status_code=303)

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

    @app.exception_handler(Exception)
    async def erro_inesperado(request: Request, erro: Exception):
        # Página genérica, sem detalhes do erro (que poderiam ajudar um atacante).
        # O erro completo continua indo pro log do servidor.
        log.error("Erro em %s %s", request.method, request.url.path, exc_info=erro)
        try:
            resposta = render(
                request, "erro.html", 500,
                titulo="Algo deu errado",
                mensagem="Tivemos um problema aqui. Tente de novo daqui a pouco.",
            )
        except Exception:
            resposta = PlainTextResponse("Erro interno.", status_code=500)
        # Esta resposta sai por fora do middleware "proteger": os cabeçalhos vão aqui.
        resposta.headers.update(cabecalhos)
        return resposta

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
