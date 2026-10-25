"""Proxy de imagens: páginas de capítulo e capas.

O navegador nunca recebe a URL do servidor de origem. Ele pede "capítulo X,
página N" e a Nami monta a URL a partir do que a fonte informou. Assim:
- o MangaDex fica satisfeito (eles exigem proxy e recusam hotlink);
- ninguém usa o seu servidor pra baixar coisas arbitrárias da internet;
- a classificação etária é checada de novo a cada imagem.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import RedirectResponse, Response

from app.config import Config
from sqlalchemy.orm import Session

from app.dependencias import madura_ativa, obter_config, obter_db, obter_fontes, usuario_atual
from app.dominio import Imagem
from app.fontes.base import FonteIndisponivel, NaoEncontrado
from app.fontes.registro import Registro
from app.models import Usuario
from app.servicos.visibilidade import pode_ver_em_alguma_area

router = APIRouter()

SEM_CAPA = "/static/sem-capa.svg"


def _pode(request: Request, db: Session, usuario: Usuario | None, classificacao) -> bool:
    # Imagem adulta só com a área madura aberta neste aparelho (sem renovar o
    # prazo: são dezenas de imagens por página).
    aberta = classificacao.adulta and madura_ativa(request, db, usuario)
    return pode_ver_em_alguma_area(classificacao, usuario, aberta)


def _resposta(imagem: Imagem) -> Response:
    return Response(
        imagem.conteudo,
        media_type=imagem.tipo_mime,
        headers={
            # "private": só o navegador de quem pediu guarda (pode ser conteúdo restrito).
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/img/{fonte_id}/{capitulo_id}/{numero}")
def pagina(
    fonte_id: str,
    capitulo_id: str,
    numero: Annotated[int, Path(ge=1, le=5000)],
    request: Request,
    q: str | None = None,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario | None = Depends(usuario_atual),
    db: Session = Depends(obter_db),
):
    fonte = fontes.obter(fonte_id)
    obra, _capitulo = fonte.capitulo(capitulo_id)
    if not _pode(request, db, usuario, obra.classificacao):
        raise NaoEncontrado(capitulo_id)
    qualidade = q if q in ("data", "data-saver") else config.qualidade_padrao
    return _resposta(fonte.imagem_pagina(capitulo_id, numero, qualidade))


@router.get("/capa/{fonte_id}/{obra_id}")
def capa(
    fonte_id: str,
    obra_id: str,
    request: Request,
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario | None = Depends(usuario_atual),
    db: Session = Depends(obter_db),
):
    fonte = fontes.obter(fonte_id)
    try:
        if not _pode(request, db, usuario, fonte.classificacao_da_obra(obra_id)):
            raise NaoEncontrado(obra_id)
        if fonte.capa_em_cache:
            imagem = request.app.state.capas.obter(fonte, obra_id)
        else:
            imagem = fonte.imagem_capa(obra_id)
    except FonteIndisponivel:
        imagem = None  # capa não é essencial: mostra o desenho padrão e tenta de novo depois
    if imagem is None:
        return RedirectResponse(SEM_CAPA, status_code=307)
    return _resposta(imagem)
