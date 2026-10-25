"""Página inicial, seções, busca e página da obra."""

from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.catalogos.anilist import AniList
from app.config import Config
from app.dependencias import obter_anilist, obter_config, obter_db, obter_fontes, usuario_atual
from app.dominio import Filtro, Ordem, navegacao
from app.fontes.base import FonteIndisponivel, NaoEncontrado
from app.fontes.registro import Registro
from app.models import Usuario
from app.renderizar import OPCOES_POR_PAGINA, render
from app.servicos import cobertura, estante
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
POR_PAGINA = OPCOES_POR_PAGINA[0]
COOKIE_POR_PAGINA = "nami_por_pagina"  # a escolha fica lembrada no navegador
NumeroPagina = Annotated[int, Query(ge=1, le=1000)]
SUGESTOES = 6  # obras no autocompletar da busca
MINIMO_SUGESTAO = 3  # letras digitadas antes de sugerir algo


def _idiomas_do_usuario(config: Config, usuario: Usuario | None) -> list[str]:
    """Os idiomas configurados, com o preferido da pessoa primeiro."""
    preferido = usuario.idioma_preferido if usuario else None
    return sorted(config.idiomas, key=lambda idioma: idioma != preferido)


def _por_pagina(request: Request, por: str | None) -> tuple[int, bool]:
    """Quantas obras mostrar: a escolhida agora (?por=), a lembrada ou o padrão.

    O segundo valor diz se a escolha é nova (e precisa ir pro cookie).
    """
    for valor, nova in ((por, True), (request.cookies.get(COOKIE_POR_PAGINA), False)):
        if valor and valor.isdigit() and int(valor) in OPCOES_POR_PAGINA:
            return int(valor), nova
    return POR_PAGINA, False


def _lembrar_por_pagina(resposta, config: Config, por_pagina: int, nova: bool):
    if nova:
        resposta.set_cookie(
            COOKIE_POR_PAGINA,
            str(por_pagina),
            max_age=365 * 24 * 60 * 60,
            httponly=True,
            samesite="lax",
            secure=config.cookie_seguro,
        )
    return resposta


@router.get("/")
def inicio(
    request: Request,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario | None = Depends(usuario_atual),
    db: Session = Depends(obter_db),
):
    lendo = estante.historico(db, usuario, classificacoes_gerais(usuario), limite=12) if usuario else []

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
    por: str | None = None,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario | None = Depends(usuario_atual),
):
    por_pagina, nova = _por_pagina(request, por)
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
    resultado = fontes.obter(fonte).buscar(filtro, pagina, por_pagina)
    resposta = render(
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
    return _lembrar_por_pagina(resposta, config, por_pagina, nova)


@router.get("/busca")
def busca(
    request: Request,
    q: Annotated[str, Query(max_length=200)] = "",
    pagina: NumeroPagina = 1,
    fonte: str | None = None,
    por: str | None = None,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario | None = Depends(usuario_atual),
):
    """Busca nas duas fontes. Com ?fonte=local sem termo, lista a biblioteca inteira."""
    return pagina_busca(request, q, pagina, fonte, por, config, fontes, usuario, madura=False)


def pagina_busca(request, q, pagina, fonte, por, config, fontes, usuario, madura: bool):
    """A busca do site normal e a da área madura (rotas/madura.py): cada uma só
    acha a classificação da sua área."""
    por_pagina, nova = _por_pagina(request, por)
    termo = q.strip()
    filtro = Filtro(classificacoes_permitidas(usuario, madura), termo=termo, idiomas=tuple(config.idiomas))
    locais = resultado = None
    if fonte == LOCAL:
        locais = fontes.obter(LOCAL).buscar(replace(filtro, ordem=Ordem.NOVOS), pagina, por_pagina)
    elif termo:
        if pagina == 1:  # a biblioteca aparece só na primeira página, em cima
            locais = fontes.obter(LOCAL).buscar(filtro, 1, por_pagina)
        resultado = fontes.obter(MANGADEX).buscar(filtro, pagina, por_pagina)
    resposta = render(
        request, "busca.html", q=termo, fonte=fonte, resultado=resultado, locais=locais, madura=madura
    )
    return _lembrar_por_pagina(resposta, config, por_pagina, nova)


@router.get("/busca/sugestoes")
def sugestoes(
    q: Annotated[str, Query(max_length=200)] = "",
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    usuario: Usuario | None = Depends(usuario_atual),
):
    """Autocompletar da busca (static/js/sugestoes.js): obras que combinam com o
    que a pessoa já digitou. A biblioteca local vem primeiro."""
    return sugerir(q, config, fontes, usuario, madura=False)


def sugerir(q: str, config: Config, fontes: Registro, usuario: Usuario | None, madura: bool) -> dict:
    termo = q.strip()
    if len(termo) < MINIMO_SUGESTAO:
        return {"itens": []}
    filtro = Filtro(classificacoes_permitidas(usuario, madura), termo=termo, idiomas=tuple(config.idiomas))
    obras = list(fontes.obter(LOCAL).buscar(filtro, 1, SUGESTOES).obras)
    if len(obras) < SUGESTOES:
        # No MangaDex, a "relevância" põe os derivados na frente ("one pi" traz
        # One Piece Academy antes do One Piece). Pede as mais populares e passa na
        # frente as que têm o texto digitado em algum título.
        try:
            populares = fontes.obter(MANGADEX).buscar(replace(filtro, relevancia=False), 1, SUGESTOES * 2).obras
        except FonteIndisponivel:
            populares = []  # fica só com a biblioteca; a busca normal explica o erro, se ele continuar
        procurado = termo.casefold()
        obras += sorted(
            populares,
            key=lambda o: not any(procurado in t.casefold() for t in (o.titulo, *o.titulos_alternativos)),
        )
    return {
        "itens": [
            {
                "titulo": o.titulo,
                "url": f"{'/madura' if madura else ''}/obra/{o.fonte}/{o.id}",
                "capa": o.capa_url or "/static/sem-capa.svg",
                "info": " · ".join(
                    filter(None, [o.tipo.rotulo, str(o.ano) if o.ano else "", "biblioteca" if o.fonte == LOCAL else ""])
                ),
                "so_fora": o.so_fora,
            }
            for o in obras[:SUGESTOES]
        ]
    }


@router.get("/obra/{fonte_id}/{obra_id}")
def obra(
    fonte_id: str,
    obra_id: str,
    request: Request,
    idioma: str | None = None,
    reportado: bool = False,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    anilist: AniList = Depends(obter_anilist),
    usuario: Usuario | None = Depends(usuario_atual),
    db: Session = Depends(obter_db),
):
    return pagina_da_obra(
        request, fonte_id, obra_id, idioma, reportado, config, fontes, anilist, usuario, db, madura=False
    )


def pagina_da_obra(request, fonte_id, obra_id, idioma, reportado, config, fontes, anilist, usuario, db, madura: bool):
    """Página da obra no site normal ou na área madura. Obra da outra área: 404."""
    fonte = fontes.obter(fonte_id)
    obra = fonte.obra(obra_id)
    if not pode_ver(obra.classificacao, usuario, madura):
        raise NaoEncontrado(obra_id)

    capitulos = fonte.capitulos(obra_id, config.idiomas)
    idiomas = _idiomas_do_usuario(config, usuario)
    por_idioma = {i: lista for i in idiomas if (lista := [c for c in capitulos if c.idioma == i])}
    if idioma not in por_idioma:
        idioma = next(iter(por_idioma), None)
    lista = por_idioma.get(idioma, [])
    # "Começar a ler": no idioma escolhido ou, se nele nada dá pra ler aqui, no próximo.
    primeiro = next(
        (c for i in [idioma, *por_idioma] for c in por_idioma.get(i, []) if c.legivel), None
    )

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

    # Compara com a obra original (AniList) e junta os links oficiais. Se o
    # AniList não responder, `ficha` vem None e a página só fica sem essa parte.
    ficha = anilist.ficha(obra.anilist_id) if obra.anilist_id else None
    resumo = cobertura.analisar(obra, por_idioma, idioma, ficha, idiomas_preferidos=idiomas)

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
        cobertura=resumo,
        reportado=reportado,
        madura=madura,
    )
