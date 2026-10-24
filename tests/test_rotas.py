from tests.fabrica import (
    API,
    CAP1,
    CAP2,
    CAP3,
    CAPAS,
    NO,
    OBRA,
    REPORT,
    capitulo,
    capitulo_detalhe,
    feed,
    lista,
    manga,
    servidor,
)


def test_inicio_pede_so_conteudo_livre(cliente, api):
    api.responder("GET", f"{API}/manga", json=lista(manga()))
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert "Obra Teste" in resposta.text
    assert "+18" not in resposta.text
    for chamada in api.chamadas:
        assert chamada.url.params.get_list("contentRating[]") == ["safe"]


def test_secao_18_nao_existe_para_visitante(cliente, api):
    assert cliente.get("/secao/adulto").status_code == 404
    assert api.chamadas == []


def test_secao_inexistente(cliente):
    assert cliente.get("/secao/qualquer").status_code == 404


def test_busca_vazia_nao_chama_a_api(cliente, api):
    assert cliente.get("/busca").status_code == 200
    assert api.chamadas == []


def test_busca(cliente, api):
    api.responder("GET", f"{API}/manga", json=lista(manga(titulo="Achado")))
    resposta = cliente.get("/busca", params={"q": "achado"})
    assert "Achado" in resposta.text
    assert api.chamadas[0].url.params["title"] == "achado"


def test_obra_adulta_e_404_para_visitante(cliente, api):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga(classificacao="erotica")})
    assert cliente.get(f"/obra/mangadex/{OBRA}").status_code == 404
    assert api.chamadas_para(f"/manga/{OBRA}/feed") == []


def test_obra_lista_capitulos_com_credito(cliente, api):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga()})
    api.responder(
        "GET",
        f"{API}/manga/{OBRA}/feed",
        json=feed(
            capitulo(CAP1, numero="1"),
            capitulo(CAP2, numero="2", grupo="Outro Grupo"),
            capitulo(CAP3, numero="1", idioma="en", externo="https://oficial.example"),
        ),
    )
    resposta = cliente.get(f"/obra/mangadex/{OBRA}")
    assert resposta.status_code == 200
    assert "Outro Grupo" in resposta.text
    assert f'href="/ler/mangadex/{CAP1}">Começar a ler' in resposta.text
    assert "Inglês (1)" in resposta.text

    em_ingles = cliente.get(f"/obra/mangadex/{OBRA}", params={"idioma": "en"})
    assert "https://oficial.example" in em_ingles.text


def test_obra_sem_capitulos_explica_o_motivo(cliente, api):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga()})
    api.responder("GET", f"{API}/manga/{OBRA}/feed", json=feed())
    assert "removidos" in cliente.get(f"/obra/mangadex/{OBRA}").text


def test_leitor_mostra_paginas_e_proximo_capitulo(cliente, api):
    api.responder("GET", f"{API}/chapter/{CAP1}", json=capitulo_detalhe(CAP1))
    api.responder("GET", f"{API}/at-home/server/{CAP1}", json=servidor(paginas=3))
    api.responder("GET", f"{API}/manga/{OBRA}/feed", json=feed(capitulo(CAP1, numero="1"), capitulo(CAP2, numero="2")))
    resposta = cliente.get(f"/ler/mangadex/{CAP1}")
    assert resposta.status_code == 200
    assert f"/img/mangadex/{CAP1}/3" in resposta.text
    assert f"/ler/mangadex/{CAP2}" in resposta.text
    assert "Grupo Teste" in resposta.text


def test_leitor_de_capitulo_externo_manda_pro_site_oficial(cliente, api):
    api.responder("GET", f"{API}/chapter/{CAP1}", json=capitulo_detalhe(CAP1, externo="https://oficial.example", paginas=0))
    resposta = cliente.get(f"/ler/mangadex/{CAP1}")
    assert "https://oficial.example" in resposta.text
    assert api.chamadas_para(f"/at-home/server/{CAP1}") == []


def test_proxy_entrega_a_pagina(cliente, api):
    api.responder("GET", f"{API}/chapter/{CAP1}", json=capitulo_detalhe(CAP1))
    api.responder("GET", f"{API}/at-home/server/{CAP1}", json=servidor())
    api.imagem(f"{NO}/data-saver/abc123/1-leve.jpg", conteudo=b"pagina")
    api.responder("POST", REPORT, json={})

    resposta = cliente.get(f"/img/mangadex/{CAP1}/1")
    assert resposta.status_code == 200
    assert resposta.content == b"pagina"
    assert resposta.headers["content-type"] == "image/jpeg"
    assert resposta.headers["cache-control"].startswith("private")


def test_proxy_bloqueia_pagina_de_obra_adulta(cliente, api):
    api.responder("GET", f"{API}/chapter/{CAP1}", json=capitulo_detalhe(CAP1, classificacao="pornographic"))
    assert cliente.get(f"/img/mangadex/{CAP1}/1").status_code == 404
    assert api.chamadas_para(f"/at-home/server/{CAP1}") == []


def test_capa_fica_em_cache_no_disco(cliente, api, config):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga()})
    api.imagem(f"{CAPAS}/{OBRA}/capa.jpg.256.jpg", conteudo=b"capa")

    primeira = cliente.get(f"/capa/mangadex/{OBRA}")
    segunda = cliente.get(f"/capa/mangadex/{OBRA}")

    assert primeira.content == segunda.content == b"capa"
    assert len(api.chamadas_para(f"/covers/{OBRA}/capa.jpg.256.jpg")) == 1
    assert len(list((config.dir_cache_capas / "mangadex").glob(f"{OBRA}.*.jpg"))) == 1


def test_capa_de_obra_adulta_nao_aparece(cliente, api):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga(classificacao="erotica")})
    assert cliente.get(f"/capa/mangadex/{OBRA}").status_code == 404


def test_api_fora_do_ar_mostra_pagina_de_erro(cliente, api):
    api.responder("GET", f"{API}/manga", json={}, status=500)
    resposta = cliente.get("/busca", params={"q": "x"})
    assert resposta.status_code == 503
    assert "Fonte indisponível" in resposta.text


def test_healthz(cliente):
    assert cliente.get("/healthz").json() == {"ok": True}
