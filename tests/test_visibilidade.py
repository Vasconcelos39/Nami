from datetime import datetime
from types import SimpleNamespace

from app.dominio import Classificacao as C
from app.servicos.visibilidade import (
    ADULTAS,
    SECOES,
    classificacoes_da_secao,
    classificacoes_permitidas,
    pode_ver,
    pode_ver_em_alguma_area,
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


def test_maioridade_e_opt_in_liberam_so_a_area_madura():
    u = usuario(maioridade=True, adulto=True)
    assert classificacoes_permitidas(u) == {C.SAFE, C.SUGGESTIVE}  # o site normal continua limpo
    assert classificacoes_permitidas(u, madura=True) == ADULTAS == {C.EROTICA, C.PORNOGRAPHIC}


def test_bloqueio_do_admin_vence_o_opt_in():
    assert classificacoes_permitidas(usuario(maioridade=True, adulto=True, bloqueado=True), madura=True) == set()


def test_conta_desativada_volta_a_ser_visitante():
    u = usuario(maioridade=True, adulto=True, ativo=False)
    assert classificacoes_permitidas(u) == {C.SAFE}
    assert classificacoes_permitidas(u, madura=True) == set()


def test_site_normal_nunca_tem_adulto():
    u = usuario(maioridade=True, adulto=True)
    for secao in SECOES.values():
        assert not any(c.adulta for c in classificacoes_da_secao(secao, u))
    assert not pode_ver(C.EROTICA, u)
    assert pode_ver(C.EROTICA, u, madura=True)
    assert not pode_ver(C.SAFE, u, madura=True)  # e a área madura só tem adulto


def test_nao_existe_mais_secao_18():
    assert "adulto" not in SECOES
    assert "adulto" not in [s.slug for s in secoes_visiveis(usuario(maioridade=True, adulto=True))]


def test_rotas_das_duas_areas():
    u = usuario(maioridade=True, adulto=True)
    assert pode_ver_em_alguma_area(C.EROTICA, u, madura_ativa=True)
    assert not pode_ver_em_alguma_area(C.EROTICA, u, madura_ativa=False)
    assert pode_ver_em_alguma_area(C.SAFE, u, madura_ativa=True)  # imagem de obra normal continua valendo
