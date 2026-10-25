"""Obras que só dá pra ler nos sites oficiais: no MangaDex, os capítulos delas
são só links ("externos"), como acontece com muitas obras licenciadas."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.fontes.mangadex import MangaDex
from app.main import criar_app
from tests.conftest import ExecutorImediato
from tests.fabrica import API, CAP1, CAP2, OBRA, capitulo, feed, lista, manga

OUTRA = "33333333-3333-4333-8333-333333333333"
MANGA_PLUS = "https://mangaplus.shueisha.co.jp/viewer/1"


@pytest.fixture
def cliente(config, api, anilist):
    """Como o cliente comum, mas a verificação em segundo plano roda na hora."""
    mangadex = MangaDex(
        config,
        http=httpx.Client(transport=httpx.MockTransport(api)),
        chamadas_por_segundo=1000,
        executor=ExecutorImediato(),
        verificador=ExecutorImediato(),
    )
    with TestClient(criar_app(config, mangadex=mangadex, anilist=anilist)) as cliente:
        yield cliente


def test_cartao_avisa_quando_so_da_pra_ler_fora(cliente, api):
    api.responder("GET", f"{API}/manga", json=lista(manga(), manga(id=OUTRA, titulo="Outra")))
    api.responder("GET", f"{API}/manga/{OBRA}/feed", json=feed())  # nenhum capítulo legível
    api.responder("GET", f"{API}/manga/{OUTRA}/feed", json=feed(capitulo(obra=OUTRA)))

    # Na primeira vez a Nami ainda não sabe: pergunta ao MangaDex em segundo plano.
    assert "Só no site oficial" not in cliente.get("/secao/mangas").text
    pedido = api.chamadas_para(f"/manga/{OBRA}/feed")[0]
    assert pedido.url.params["includeExternalUrl"] == "0"
    assert pedido.url.params.get_list("translatedLanguage[]") == ["pt-br", "en"]

    assert cliente.get("/secao/mangas").text.count("Só no site oficial") == 1
    assert len(api.chamadas_para(f"/manga/{OBRA}/feed")) == 1  # a resposta fica guardada


def test_verificacao_que_falha_tenta_de_novo_depois(cliente, api):
    api.responder("GET", f"{API}/manga", json=lista(manga()))
    api.responder("GET", f"{API}/manga/{OBRA}/feed", json={}, status=500)
    api.responder("GET", f"{API}/manga/{OBRA}/feed", json=feed())

    assert cliente.get("/secao/mangas").status_code == 200  # a falha não atrapalha a página
    cliente.get("/secao/mangas")
    assert "Só no site oficial" in cliente.get("/secao/mangas").text
    assert len(api.chamadas_para(f"/manga/{OBRA}/feed")) == 2


def test_abrir_a_obra_ja_ensina_e_explica(cliente, api):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga()})
    api.responder("GET", f"{API}/manga/{OBRA}/feed", json=feed(capitulo(externo=MANGA_PLUS)))

    obra = cliente.get(f"/obra/mangadex/{OBRA}").text
    assert "Nenhum capítulo em português dá pra ler aqui na Nami" in obra
    assert "MANGA Plus ↗" in obra
    assert "Começar a ler" not in obra

    api.responder("GET", f"{API}/manga", json=lista(manga()))
    assert "Só no site oficial" in cliente.get("/secao/mangas").text
    assert len(api.chamadas_para(f"/manga/{OBRA}/feed")) == 1  # só a da página da obra


def test_comecar_a_ler_vai_pro_idioma_que_tem(cliente, api):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga()})
    api.responder(
        "GET",
        f"{API}/manga/{OBRA}/feed",
        json=feed(capitulo(CAP1, externo=MANGA_PLUS), capitulo(CAP2, idioma="en")),
    )
    obra = cliente.get(f"/obra/mangadex/{OBRA}").text
    assert f'href="/ler/mangadex/{CAP2}">Começar a ler · inglês' in obra
