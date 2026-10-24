"""O leitor de capítulos."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import Config
from app.dependencias import obter_config, obter_db, obter_fontes, usuario_atual
from app.dominio import Capitulo, navegacao
from app.fontes.base import NaoEncontrado
from app.fontes.registro import Registro
from app.models import Usuario
from app.renderizar import render
from app.servicos import estante
from app.servicos.visibilidade import pode_ver

router = APIRouter()


def _url(capitulo: Capitulo | None) -> str | None:
    return f"/ler/{capitulo.fonte}/{capitulo.id}" if capitulo else None


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
    fonte = fontes.obter(fonte_id)
    obra, capitulo = fonte.capitulo(capitulo_id)
    if not pode_ver(obra.classificacao, usuario):
        raise NaoEncontrado(capitulo_id)

    url_obra = f"/obra/{fonte.id}/{obra.id}"
    paginas = fonte.paginas(capitulo_id) if capitulo.legivel else []
    if not paginas:
        return render(
            request, "capitulo_indisponivel.html", obra=obra, capitulo=capitulo, url_obra=url_obra
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
        "anterior": _url(anterior),
        "proximo": _url(proximo),
        "obra": url_obra,
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
    )
