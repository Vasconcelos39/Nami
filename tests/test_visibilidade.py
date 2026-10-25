from datetime import datetime
from types import SimpleNamespace

from app.dominio import Classificacao as C
from app.servicos.visibilidade import (
    SECOES,
    classificacoes_da_secao,
    classificacoes_permitidas,
    pode_ver,
    secoes_visiveis,
)


def usuario(maioridade=False, adulto=False, ativo=True, bloqueado=False):
    return SimpleNamespace(
        ativo=ativo,
        maioridade_confirmada_em=datetime(2026, 1, 1) if maioridade else None,
        mostrar_adulto=adulto,
        adulto_bloqueado=bloqueado,
    )


def test_visitante_ve_so_safe():
    assert classificacoes_permitidas(None) == {C.SAFE}
    assert not pode_ver(C.SUGGESTIVE, None)


def test_logado_ve_safe_e_suggestive():
    assert classificacoes_permitidas(usuario()) == {C.SAFE, C.SUGGESTIVE}


def test_opt_in_sem_maioridade_nao_libera_adulto():
    assert classificacoes_permitidas(usuario(adulto=True)) == {C.SAFE, C.SUGGESTIVE}


def test_maioridade_sem_opt_in_nao_libera_adulto():
    assert classificacoes_permitidas(usuario(maioridade=True)) == {C.SAFE, C.SUGGESTIVE}


def test_maioridade_e_opt_in_liberam_tudo():
    assert classificacoes_permitidas(usuario(maioridade=True, adulto=True)) == set(C)


def test_bloqueio_do_admin_vence_o_opt_in():
    assert classificacoes_permitidas(usuario(maioridade=True, adulto=True, bloqueado=True)) == {C.SAFE, C.SUGGESTIVE}


def test_conta_desativada_volta_a_ser_visitante():
    assert classificacoes_permitidas(usuario(maioridade=True, adulto=True, ativo=False)) == {C.SAFE}


def test_adulto_fica_so_na_secao_18():
    u = usuario(maioridade=True, adulto=True)
    assert classificacoes_da_secao(SECOES["mangas"], u) == {C.SAFE, C.SUGGESTIVE}
    assert classificacoes_da_secao(SECOES["adulto"], u) == {C.EROTICA, C.PORNOGRAPHIC}


def test_secao_18_escondida_sem_opt_in():
    assert "adulto" not in [s.slug for s in secoes_visiveis(None)]
    assert "adulto" not in [s.slug for s in secoes_visiveis(usuario())]
    assert "adulto" in [s.slug for s in secoes_visiveis(usuario(maioridade=True, adulto=True))]
