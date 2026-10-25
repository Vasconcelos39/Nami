"""Quem pode ver o quê.

Toda decisão sobre classificação etária passa por este arquivo:

    visitante                                    -> safe
    logado                                       -> safe + suggestive
    logado + maioridade confirmada + opt-in +18  -> também erotica e pornographic
    (a não ser que um admin tenha bloqueado o +18 da conta)

A maioridade é confirmada em /conta/maioridade (servicos/maioridade.py).

Conteúdo adulto só aparece na seção +18 e na busca, nunca misturado em
Mangás/Manhwas/HQs.
"""

from dataclasses import dataclass

from app.dominio import Classificacao, Tipo
from app.models import Usuario


@dataclass(frozen=True)
class Secao:
    slug: str
    nome: str
    tipos: frozenset[Tipo] | None  # None = todos os tipos
    adulta: bool = False


SECOES = {
    secao.slug: secao
    for secao in (
        Secao("mangas", "Mangás", frozenset({Tipo.MANGA})),
        Secao("manhwas", "Manhwas", frozenset({Tipo.MANHWA, Tipo.MANHUA})),
        Secao("hqs", "HQs", frozenset({Tipo.HQ})),
        Secao("adulto", "+18", None, adulta=True),
    )
}


def classificacoes_permitidas(usuario: Usuario | None) -> frozenset[Classificacao]:
    if usuario is None or not usuario.ativo:
        return frozenset({Classificacao.SAFE})
    permitidas = {Classificacao.SAFE, Classificacao.SUGGESTIVE}
    if (
        usuario.maioridade_confirmada_em is not None
        and usuario.mostrar_adulto
        and not usuario.adulto_bloqueado
    ):
        permitidas |= {Classificacao.EROTICA, Classificacao.PORNOGRAPHIC}
    return frozenset(permitidas)


def classificacoes_da_secao(secao: Secao, usuario: Usuario | None) -> frozenset[Classificacao]:
    """Seções comuns mostram só o que não é adulto; a seção +18, só o adulto."""
    return frozenset(c for c in classificacoes_permitidas(usuario) if c.adulta == secao.adulta)


def classificacoes_gerais(usuario: Usuario | None) -> frozenset[Classificacao]:
    """O que pode aparecer em listagens fora da seção +18 (ex.: a página inicial)."""
    return frozenset(c for c in classificacoes_permitidas(usuario) if not c.adulta)


def pode_ver(classificacao: Classificacao, usuario: Usuario | None) -> bool:
    return classificacao in classificacoes_permitidas(usuario)


def secoes_visiveis(usuario: Usuario | None) -> list[Secao]:
    return [s for s in SECOES.values() if classificacoes_da_secao(s, usuario)]
