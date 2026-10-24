"""Página inicial, seções, busca e página da obra."""

from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.config import Config
from app.dependencias import obter_config, obter_db, obter_fontes, usuario_atual
from app.dominio import Filtro, Ordem, navegacao
from app.fontes.base import NaoEncontrado
from app.fontes.registro import Registro
from app.models import Usuario
from app.renderizar import render
from app.servicos import estante
from app.servicos.visibilidade import (
    SECOES,
    classificacoes_da_secao,
    classificacoes_gerais,
    classificacoes_permitidas,
    pode_ver,
    secoes_visiveis,
)

router = APIRouter()

MANGADEX, LOCAL = "mangadex", "local"
FONTES_DAS_LISTAGENS = (MANGADEX, LOCAL)  # ordem das abas nas seções
POR_PAGINA = 24
NumeroPagina = Annotated[int, Query(ge=1, le=1000)]


def _idiomas_do_usuario(config: Config, usuario: Usuario | None) -> list[str]:
    """Os idiomas configurados, com o preferido da pessoa primeiro."""
    preferido = usuario.idioma_preferido if usuario else None
    return sorted(config.idiomas, key=lambda idioma: idioma != preferido)


@router.get("/")
def inicio(
    request: Request,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario | None = Depends(usuario_atual),
    db: Session = Depends(obter_db),
):
    lendo = []
    if usuario is not None:
        lendo = [
            item for item in estante.historico(db, usuario, limite=12)
            if pode_ver(item.obra.classificacao, usuario)
        ]

    fonte = fontes.obter(MANGADEX)
    idiomas = tuple(config.idiomas)
    vitrines = []
    biblioteca = fontes.obter(LOCAL).buscar(
        Filtro(classificacoes_gerais(usuario), ordem=Ordem.RECENTES, idiomas=idiomas), por_pagina=12
    )
    if biblioteca.obras:
        vitrines.append(("Na sua biblioteca", f"/busca?fonte={LOCAL}", biblioteca.obras))
    recentes = fonte.buscar(
        Filtro(classificacoes_gerais(usuario), ordem=Ordem.RECENTES, idiomas=idiomas), por_pagina=12
    )
    vitrines.append(("Atualizados recentemente no MangaDex", None, recentes.obras))
    for secao in secoes_visiveis(usuario):
        if secao.adulta:
            continue
        filtro = Filtro(classificacoes_da_secao(secao, usuario), secao.tipos, idiomas=idiomas)
        obras = fonte.buscar(filtro, por_pagina=12).obras
        vitrines.append((f"{secao.nome} populares", f"/secao/{secao.slug}", obras))
    return render(request, "inicio.html", lendo=lendo, vitrines=vitrines)


@router.get("/secao/{slug}")
def secao(
    slug: str,
    request: Request,
    ordem: Ordem = Ordem.POPULARES,
    pagina: NumeroPagina = 1,
    fonte: str | None = None,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario | None = Depends(usuario_atual),
):
    secao = SECOES.get(slug)
    classificacoes = classificacoes_da_secao(secao, usuario) if secao else frozenset()
    if not classificacoes:
        # 404 (e não 403) também pra seção +18 escondida: não revela que ela existe.
        raise NaoEncontrado(slug)
    filtro = Filtro(classificacoes, secao.tipos, ordem=ordem, idiomas=tuple(config.idiomas))
    if fonte is None:
        # HQs quase não existem no MangaDex: a seção abre na biblioteca local se ela tiver alguma.
        tem_local = slug == "hqs" and fontes.obter(LOCAL).buscar(filtro, 1, 1).total > 0
        fonte = LOCAL if tem_local else MANGADEX
    if fonte not in FONTES_DAS_LISTAGENS:
        raise NaoEncontrado(fonte)
    resultado = fontes.obter(fonte).buscar(filtro, pagina, POR_PAGINA)
    return render(
        request,
        "secao.html",
        secao=secao,
        secao_atual=secao.slug,
        resultado=resultado,
        ordem=ordem,
        ordens=list(Ordem),
        fonte=fonte,
        abas_fonte=[(f, fontes.obter(f).nome) for f in FONTES_DAS_LISTAGENS],
    )


@router.get("/busca")
def busca(
    request: Request,
    q: Annotated[str, Query(max_length=200)] = "",
    pagina: NumeroPagina = 1,
    fonte: str | None = None,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario | None = Depends(usuario_atual),
):
    """Busca nas duas fontes. Com ?fonte=local sem termo, lista a biblioteca inteira."""
    termo = q.strip()
    filtro = Filtro(classificacoes_permitidas(usuario), termo=termo, idiomas=tuple(config.idiomas))
    locais = resultado = None
    if fonte == LOCAL:
        locais = fontes.obter(LOCAL).buscar(replace(filtro, ordem=Ordem.NOVOS), pagina, POR_PAGINA)
    elif termo:
        if pagina == 1:  # a biblioteca aparece só na primeira página, em cima
            locais = fontes.obter(LOCAL).buscar(filtro, 1, POR_PAGINA)
        resultado = fontes.obter(MANGADEX).buscar(filtro, pagina, POR_PAGINA)
    return render(request, "busca.html", q=termo, fonte=fonte, resultado=resultado, locais=locais)


@router.get("/obra/{fonte_id}/{obra_id}")
def obra(
    fonte_id: str,
    obra_id: str,
    request: Request,
    idioma: str | None = None,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario | None = Depends(usuario_atual),
    db: Session = Depends(obter_db),
):
    fonte = fontes.obter(fonte_id)
    obra = fonte.obra(obra_id)
    if not pode_ver(obra.classificacao, usuario):
        raise NaoEncontrado(obra_id)

    capitulos = fonte.capitulos(obra_id, config.idiomas)
    por_idioma = {
        i: lista
        for i in _idiomas_do_usuario(config, usuario)
        if (lista := [c for c in capitulos if c.idioma == i])
    }
    if idioma not in por_idioma:
        idioma = next(iter(por_idioma), None)
    lista = por_idioma.get(idioma, [])
    primeiro = next((c for c in lista if c.legivel), None)

    # Progresso de quem está logado: marca os capítulos lidos e monta o "Continuar".
    leituras, favorito, continuar, em_dia = {}, False, None, False
    if usuario is not None:
        leituras = estante.leituras_da_obra(db, usuario, fonte.id, obra.id)
        favorito = estante.eh_favorito(db, usuario, fonte.id, obra.id)
        if leituras:
            ultimo_id, ultima = max(leituras.items(), key=lambda item: item[1].quando)
            ultimo = next((c for c in capitulos if c.id == ultimo_id), None)
            if ultimo is not None and not ultima.concluido:
                continuar = (ultimo, ultima.pagina)
            elif ultimo is not None:
                _, _, proximo = navegacao(capitulos, ultimo)
                if proximo is not None:
                    continuar = (proximo, 1)
                else:
                    em_dia = True

    return render(
        request,
        "obra.html",
        obra=obra,
        fonte_nome=fonte.nome,
        por_idioma=por_idioma,
        idioma=idioma,
        capitulos=list(reversed(lista)),  # mais novos primeiro
        primeiro=primeiro,
        leituras=leituras,
        favorito=favorito,
        continuar=continuar,
        em_dia=em_dia,
    )
