import pytest

from app.cache import CacheTTL
from app.fontes.base import FonteIndisponivel
from app.fontes.limitador import JanelaLimite, Limitador


class Relogio:
    def __init__(self):
        self.agora = 100.0

    def __call__(self):
        return self.agora


def test_cache_expira():
    relogio = Relogio()
    cache = CacheTTL(relogio=relogio)
    cache.guardar("x", 1, ttl=10)
    assert cache.obter("x") == 1
    relogio.agora += 11
    assert cache.obter("x") is None


def test_cache_descarta_o_menos_usado():
    cache = CacheTTL(maximo=2)
    cache.guardar("a", 1, 60)
    cache.guardar("b", 2, 60)
    cache.obter("a")  # "a" passa a ser o mais recente
    cache.guardar("c", 3, 60)
    assert cache.obter("b") is None
    assert cache.obter("a") == 1


def test_limitador_espaca_as_chamadas():
    relogio, esperas = Relogio(), []
    limitador = Limitador(por_segundo=4, relogio=relogio, dormir=esperas.append)
    for _ in range(3):
        limitador.aguardar()
    assert esperas == [0.25, 0.5]


def test_limitador_bloqueado_recusa_ate_o_horario():
    relogio = Relogio()
    limitador = Limitador(por_segundo=4, relogio=relogio, dormir=lambda s: None)
    limitador.bloquear(30)
    with pytest.raises(FonteIndisponivel):
        limitador.aguardar()
    relogio.agora += 31
    limitador.aguardar()


def test_janela_limite():
    relogio = Relogio()
    janela = JanelaLimite(limite=2, janela=60, relogio=relogio)
    janela.registrar()
    janela.registrar()
    with pytest.raises(FonteIndisponivel):
        janela.registrar()
    relogio.agora += 61
    janela.registrar()
