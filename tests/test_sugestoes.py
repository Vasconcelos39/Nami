"""Autocompletar da busca (/busca/sugestoes)."""

from tests.ajudantes import cadastrar, ligar_adulto
from tests.fabrica import API, OBRA, lista, manga


def test_sugere_obras_enquanto_digita(cliente, api):
    api.responder("GET", f"{API}/manga", json=lista(manga(titulo="One Piece")))
    resposta = cliente.get("/busca/sugestoes", params={"q": " one "})
    assert resposta.status_code == 200
    [item] = resposta.json()["itens"]
    assert item["titulo"] == "One Piece"
    assert item["url"] == f"/obra/mangadex/{OBRA}"
    assert item["info"] == "Mangá · 2020"
    assert item["adulta"] is False

    [pedido] = api.chamadas_para("/manga")
    assert pedido.url.params["title"] == "one"
    assert pedido.url.params["limit"] == "12"
    assert pedido.url.params["order[followedCount]"] == "desc"  # as mais populares
    assert "order[relevance]" not in pedido.url.params
    # Visitante: só o conteúdo livre, como no resto do site.
    assert pedido.url.params.get_list("contentRating[]") == ["safe"]


def test_texto_curto_nao_pergunta_nada(cliente, api):
    assert cliente.get("/busca/sugestoes", params={"q": "on"}).json() == {"itens": []}
    assert api.chamadas == []


def test_mangadex_fora_do_ar_nao_quebra(cliente, api):
    api.responder("GET", f"{API}/manga", json={}, status=500)
    resposta = cliente.get("/busca/sugestoes", params={"q": "one piece"})
    assert resposta.status_code == 200
    assert resposta.json() == {"itens": []}


def test_titulo_vai_como_texto_no_json(cliente, api):
    # O JavaScript monta a lista com textContent; aqui só conferimos que nada é "pré-montado".
    api.responder("GET", f"{API}/manga", json=lista(manga(titulo="<img src=x onerror=alert(1)>")))
    [item] = cliente.get("/busca/sugestoes", params={"q": "img"}).json()["itens"]
    assert item["titulo"] == "<img src=x onerror=alert(1)>"


def test_quem_ligou_o_18_recebe_sugestoes_adultas(cliente, api):
    cadastrar(cliente)
    ligar_adulto(cliente)
    api.responder("GET", f"{API}/manga", json=lista(manga(classificacao="erotica")))
    [item] = cliente.get("/busca/sugestoes", params={"q": "qualquer"}).json()["itens"]
    assert item["adulta"] is True  # a capa vai desfocada, como nos cartões
    [pedido] = api.chamadas_para("/manga")
    assert set(pedido.url.params.get_list("contentRating[]")) == {"safe", "suggestive", "erotica", "pornographic"}


def test_quem_tem_o_texto_no_titulo_vem_primeiro(cliente, api):
    outra = "33333333-3333-4333-8333-333333333333"
    api.responder(
        "GET",
        f"{API}/manga",
        json=lista(
            manga(id=outra, titulo="Yuusha Party"),  # mais popular, mas não tem "one pi" no título
            manga(titulo="Wan Pīsu", alternativos=[{"en": "One Piece"}]),
        ),
    )
    itens = cliente.get("/busca/sugestoes", params={"q": "ONE PI"}).json()["itens"]
    assert [i["titulo"] for i in itens] == ["Wan Pīsu", "Yuusha Party"]
