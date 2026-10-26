"""Peças compartilhadas pelos testes.

Nenhum teste fala com o MangaDex ou o AniList de verdade: `ApiFalsa` responde
no lugar deles e registra cada chamada, pra os testes conferirem o que foi pedido.
"""

import time
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from app.catalogos.anilist import AniList
from app.config import Config
from app.fontes.mangadex import MangaDex
from app.main import criar_app


class ExecutorImediato:
    """Roda a tarefa na hora: nos testes não queremos threads em segundo plano."""

    def submit(self, funcao, *args, **kwargs):
        funcao(*args, **kwargs)


class ExecutorParado:
    """Não roda nada: pra tarefas de segundo plano que os testes comuns não esperam."""

    def submit(self, funcao, *args, **kwargs):
        pass


class ApiFalsa:
    def __init__(self):
        self._respostas: dict[tuple[str, str], list[Callable[[], httpx.Response]]] = {}
        self.chamadas: list[httpx.Request] = []

    def responder(self, metodo, url, *, json=None, conteudo=b"", status=200, headers=None, demora=0.0):
        """Define a resposta de uma URL. Chamar de novo pra mesma URL enfileira
        outra resposta: a primeira chamada recebe a primeira, e assim por diante
        (a última se repete). `demora`: segundos até responder (MangaDex lento)."""

        def gerar():
            time.sleep(demora)
            if json is not None:
                return httpx.Response(status, json=json, headers=headers)
            return httpx.Response(status, content=conteudo, headers=headers)

        self._respostas.setdefault((metodo, url), []).append(gerar)

    def imagem(self, url, conteudo=b"img", tipo="image/jpeg", status=200, headers=None, demora=0.0):
        headers = {"content-type": tipo, **(headers or {})}
        self.responder("GET", url, conteudo=conteudo, status=status, headers=headers, demora=demora)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.chamadas.append(request)
        chave = (request.method, str(request.url).split("?")[0])
        fila = self._respostas.get(chave)
        if not fila:
            raise AssertionError(f"Chamada inesperada: {chave}")
        gerar = fila.pop(0) if len(fila) > 1 else fila[0]
        return gerar()

    def chamadas_para(self, caminho: str) -> list[httpx.Request]:
        return [r for r in self.chamadas if r.url.path == caminho]


@pytest.fixture
def config(tmp_path):
    return Config(_env_file=None, data_dir=tmp_path)


@pytest.fixture
def api():
    return ApiFalsa()


@pytest.fixture
def mangadex(config, api):
    return MangaDex(
        config,
        http=httpx.Client(transport=httpx.MockTransport(api)),
        chamadas_por_segundo=1000,  # sem esperas nos testes
        executor=ExecutorImediato(),
        verificador=ExecutorParado(),  # tem capítulo pra ler? (test_so_fora.py liga isso)
    )


@pytest.fixture
def anilist(config, api):
    return AniList(config, http=httpx.Client(transport=httpx.MockTransport(api)))


@pytest.fixture
def cliente(config, mangadex, anilist):
    app = criar_app(config, mangadex=mangadex, anilist=anilist)
    with TestClient(app) as cliente:  # o "with" roda o início do app (migrations)
        yield cliente
