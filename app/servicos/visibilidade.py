"""Quem pode ver o quê.

Toda decisão sobre classificação etária passa por este arquivo. São dois
"sites" separados:

    site normal    visitante -> safe; logado -> safe + suggestive
                   (nunca erotica nem pornographic: nem na busca, nem no histórico)
    área madura    /madura: só erotica e pornographic

Pra entrar na área madura, a conta precisa ter a idade confirmada
(/conta/maioridade, servicos/maioridade.py), não estar bloqueada por um admin
e digitar a senha de novo (servicos/area_madura.py).
"""

from dataclasses import dataclass

from app.dominio import Classificacao, Tipo
from app.models import Usuario

ADULTAS = frozenset({Classificacao.EROTICA, Classificacao.PORNOGRAPHIC})


@dataclass(frozen=True)
class Secao:
    slug: str
    nome: str
    tipos: frozenset[Tipo] | None  # None = todos os tipos


SECOES = {
    secao.slug: secao
    for secao in (
        Secao("mangas", "Mangás", frozenset({Tipo.MANGA})),
        Secao("manhwas", "Manhwas", frozenset({Tipo.MANHWA, Tipo.MANHUA})),
        Secao("hqs", "HQs", frozenset({Tipo.HQ})),
    )
}


def pode_entrar_na_area_madura(usuario: Usuario | None) -> bool:
    """A conta tem acesso à área madura (ainda falta a senha pra entrar)?"""
    return (
        usuario is not None
        and usuario.ativo
        and usuario.maioridade_confirmada_em is not None
        and usuario.mostrar_adulto
        and not usuario.adulto_bloqueado
    )


def classificacoes_permitidas(usuario: Usuario | None, madura: bool = False) -> frozenset[Classificacao]:
    """`madura=True` só pra quem já está dentro da área madura (senha digitada)."""
    if madura:
        return ADULTAS if pode_entrar_na_area_madura(usuario) else frozenset()
    if usuario is None or not usuario.ativo:
        return frozenset({Classificacao.SAFE})
    return frozenset({Classificacao.SAFE, Classificacao.SUGGESTIVE})


def classificacoes_da_secao(secao: Secao, usuario: Usuario | None) -> frozenset[Classificacao]:
    return classificacoes_permitidas(usuario)


def classificacoes_gerais(usuario: Usuario | None) -> frozenset[Classificacao]:
    """O que pode aparecer nas listagens do site normal (ex.: a página inicial)."""
    return classificacoes_permitidas(usuario)


def pode_ver(classificacao: Classificacao, usuario: Usuario | None, madura: bool = False) -> bool:
    return classificacao in classificacoes_permitidas(usuario, madura)


def pode_ver_em_alguma_area(classificacao: Classificacao, usuario: Usuario | None, madura_ativa: bool) -> bool:
    """Pras rotas que servem as duas áreas (imagens, progresso, favoritar):
    obra adulta só com a área madura aberta; o resto, pelas regras do site normal."""
    return pode_ver(classificacao, usuario, madura=classificacao.adulta and madura_ativa)


def secoes_visiveis(usuario: Usuario | None) -> list[Secao]:
    return list(SECOES.values())
