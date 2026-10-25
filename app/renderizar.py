"""Renderização das páginas HTML (templates Jinja em app/templates)."""

import hashlib
from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import __version__
from app.dominio import nome_do_site
from app.servicos import noticias, suporte
from app.servicos.visibilidade import secoes_visiveis

PASTA_APP = Path(__file__).resolve().parent

NOMES_IDIOMA = {
    "pt-br": "Português",
    "en": "Inglês",
    "ja": "Japonês",
    "ko": "Coreano",
    "zh": "Chinês",
    "zh-hk": "Chinês",
    "es": "Espanhol",
    "fr": "Francês",
    "de": "Alemão",
    "it": "Italiano",
    "th": "Tailandês",
    "id": "Indonésio",
    "vi": "Vietnamita",
    "ru": "Russo",
    "tr": "Turco",
    "pl": "Polonês",
    "ar": "Árabe",
}
NOMES_STATUS = {
    "ongoing": "Em andamento",
    "completed": "Completo",
    "hiatus": "Em hiato",
    "cancelled": "Cancelado",
}

# Quantas obras por página as listagens oferecem (o MangaDex aceita no máximo 100).
OPCOES_POR_PAGINA = (30, 50, 80, 100)


def _versao_dos_estaticos() -> str:
    """Muda sempre que algum arquivo de app/static muda.

    Vai no endereço do CSS e dos scripts (?v=...). Assim o navegador pode
    guardar esses arquivos por muito tempo e, mesmo assim, baixa a versão nova
    assim que ela existe (o endereço muda junto).
    """
    resumo = hashlib.sha1()
    for arquivo in sorted((PASTA_APP / "static").rglob("*")):
        if arquivo.is_file():  # são poucos e pequenos: ler tudo leva milissegundos
            resumo.update(arquivo.relative_to(PASTA_APP).as_posix().encode())
            resumo.update(arquivo.read_bytes())
    return f"{__version__}-{resumo.hexdigest()[:8]}"


templates = Jinja2Templates(directory=PASTA_APP / "templates")
templates.env.globals["versao"] = _versao_dos_estaticos()
templates.env.globals["opcoes_por_pagina"] = OPCOES_POR_PAGINA
templates.env.filters["idioma"] = lambda codigo: NOMES_IDIOMA.get(codigo, codigo)
templates.env.filters["status"] = lambda status: NOMES_STATUS.get(status, status)
templates.env.filters["data"] = lambda d: d.strftime("%d/%m/%Y") if isinstance(d, datetime) else ""
# 27.0 -> "27"; 10.5 -> "10.5"
templates.env.filters["numero"] = lambda n: f"{n:g}" if isinstance(n, (int, float)) else ""
templates.env.filters["site"] = nome_do_site  # "https://mangaplus.shueisha.co.jp/..." -> "MANGA Plus"
templates.env.filters["texto_simples"] = noticias.formatar  # posts de Novidades (escapa tudo)


def _avisos(request: Request, usuario) -> tuple[suporte.Novidades, bool]:
    """Os avisos do menu: respostas novas do suporte (e, pros admins, tickets
    esperando) e se saiu post em Novidades que a pessoa ainda não viu."""
    if usuario is None:
        return suporte.Novidades(), False
    with request.app.state.sessoes() as db:
        return suporte.novidades(db, usuario), noticias.tem_nova(db, usuario)


def render(request: Request, nome: str, status: int = 200, /, **contexto):
    # O "/" deixa request, nome e status só por posição: assim um template pode
    # receber uma variável chamada "status" sem confundir com o código HTTP.
    usuario = getattr(request.state, "usuario", None)
    do_suporte, noticia_nova = _avisos(request, usuario)
    contexto = {
        "usuario": usuario,
        "secoes": secoes_visiveis(usuario),
        "cadastro_aberto": request.app.state.config.cadastro_aberto,
        "novidades": do_suporte,  # (o nome é antigo: são os avisos do suporte)
        "noticia_nova": noticia_nova,
        **contexto,
    }
    return templates.TemplateResponse(request, nome, contexto, status_code=status)
