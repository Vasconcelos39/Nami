"""Muitas imagens ao mesmo tempo não podem travar o banco.

Uma listagem pede dezenas de capas de uma vez, e o leitor dezenas de páginas.
Cada pedido segura a conexão dele com o banco enquanto espera o MangaDex; se
ainda precisasse de uma segunda, as conexões acabavam e todo mundo ficava
parado 30 s (o erro "QueuePool limit ... reached" no log).
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

from app.db import criar_engine
from tests.ajudantes import cadastrar
from tests.fabrica import API, CAPAS, OBRA, manga


def test_muitas_capas_ao_mesmo_tempo(cliente, api):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga()}, demora=0.2)
    api.imagem(f"{CAPAS}/{OBRA}/capa.jpg.256.jpg", conteudo=b"capa", demora=0.2)
    cadastrar(cliente)  # com conta: o pedido pega uma conexão logo no começo
    with ThreadPoolExecutor(40) as threads:  # o FastAPI atende até 40 de uma vez
        codigos = list(threads.map(lambda _: cliente.get(f"/capa/mangadex/{OBRA}").status_code, range(40)))
    assert codigos == [200] * 40


def test_conexoes_sem_teto(tmp_path):
    # As capas já não abrem uma segunda conexão (os ajustes ficam em memória),
    # mas o menu da conta e a biblioteca local abrem: 40 pedidos com duas cada.
    engine = criar_engine(f"sqlite:///{(tmp_path / 'nami.db').as_posix()}")
    with ExitStack() as pilha:
        conexoes = [pilha.enter_context(engine.connect()) for _ in range(80)]
        assert all(c.exec_driver_sql("select 1").scalar() == 1 for c in conexoes)
    engine.dispose()
