"""O leitor de capítulos."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import Config
from app.dependencias import obter_config, obter_db, obter_fontes, usuario_atual
from app.dominio import Capitulo, Obra, Tipo, navegacao
from app.fontes.base import NaoEncontrado
from app.fontes.registro import Registro
from app.models import Usuario
from app.renderizar import render
from app.servicos import estante
from app.servicos.visibilidade import pode_ver

router = APIRouter()


def _url(capitulo: Capitulo | None, raiz: str) -> str | None:
    return f"{raiz}/ler/{capitulo.fonte}/{capitulo.id}" if capitulo else None


def formato(obra: Obra) -> str:
    """"tira" (rolagem vertical, como manhwa/webtoon) ou "paginas" (como mangá).

    O leitor abre as tiras em rolagem contínua e as páginas no modo paginado.
    """
    if obra.tipo in (Tipo.MANHWA, Tipo.MANHUA) or "Long Strip" in obra.tags:
        return "tira"
    return "paginas"


@router.get("/ler/{fonte_id}/{capitulo_id}")
def ler(
    fonte_id: str,
    capitulo_id: str,
    request: Request,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario | None = Depends(usuario_atual),
    db: Session = Depends(obter_db),
):
    return pagina_do_leitor(request, fonte_id, capitulo_id, config, fontes, usuario, db, madura=False)


def pagina_do_leitor(request, fonte_id, capitulo_id, config, fontes, usuario, db, madura: bool):
    """O leitor do site normal ou o da área madura (rotas/madura.py)."""
    fonte = fontes.obter(fonte_id)
    obra, capitulo = fonte.capitulo(capitulo_id)
    if not pode_ver(obra.classificacao, usuario, madura):
        raise NaoEncontrado(capitulo_id)

    raiz = "/madura" if madura else ""
    url_obra = f"{raiz}/obra/{fonte.id}/{obra.id}"
    paginas = fonte.paginas(capitulo_id) if capitulo.legivel else []
    if not paginas:
        return render(
            request, "capitulo_indisponivel.html", obra=obra, capitulo=capitulo, url_obra=url_obra, madura=madura
        )

    lista, anterior, proximo = navegacao(fonte.capitulos(obra.id, config.idiomas), capitulo)

    # Com login, o leitor salva o progresso e reabre na página onde a pessoa parou.
    salvar, pagina_salva = None, None
    if usuario is not None:
        salvar = f"/progresso/{fonte.id}/{capitulo.id}"
        leitura = estante.leitura_do_capitulo(db, usuario, fonte.id, capitulo.id)
        if leitura is not None and not leitura.concluido:
            pagina_salva = leitura.pagina

    # Vai pro JavaScript do leitor (static/js/leitor.js).
    dados = {
        "capitulo": capitulo.id,
        "paginas": [p.url for p in paginas],
        "anterior": _url(anterior, raiz),
        "proximo": _url(proximo, raiz),
        "obra": url_obra,
        "formato": formato(obra),
        "qualidadePadrao": config.qualidade_padrao,
        "salvarProgresso": salvar,
        "paginaSalva": pagina_salva,
    }
    return render(
        request,
        "leitor.html",
        obra=obra,
        capitulo=capitulo,
        fonte_nome=fonte.nome,
        lista=lista,
        anterior=anterior,
        proximo=proximo,
        total=len(paginas),
        url_obra=url_obra,
        dados=dados,
        madura=madura,
    )
