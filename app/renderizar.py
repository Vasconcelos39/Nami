"""Renderização das páginas HTML (templates Jinja em app/templates)."""

from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import __version__
from app.servicos.visibilidade import secoes_visiveis

PASTA_APP = Path(__file__).resolve().parent

NOMES_IDIOMA = {"pt-br": "Português", "en": "Inglês"}
NOMES_STATUS = {
    "ongoing": "Em andamento",
    "completed": "Completo",
    "hiatus": "Em hiato",
    "cancelled": "Cancelado",
}

templates = Jinja2Templates(directory=PASTA_APP / "templates")
templates.env.globals["versao"] = __version__
templates.env.filters["idioma"] = lambda codigo: NOMES_IDIOMA.get(codigo, codigo)
templates.env.filters["status"] = lambda status: NOMES_STATUS.get(status, status)
templates.env.filters["data"] = lambda d: d.strftime("%d/%m/%Y") if isinstance(d, datetime) else ""


def render(request: Request, nome: str, status: int = 200, **contexto):
    usuario = getattr(request.state, "usuario", None)
    contexto = {
        "usuario": usuario,
        "secoes": secoes_visiveis(usuario),
        "cadastro_aberto": request.app.state.config.cadastro_aberto,
        **contexto,
    }
    return templates.TemplateResponse(request, nome, contexto, status_code=status)
