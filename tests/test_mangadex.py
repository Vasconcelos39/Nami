import json
import time

import pytest

from app.dominio import Classificacao, Filtro, Tipo
from app.fontes.base import FonteIndisponivel, NaoEncontrado
from tests.fabrica import API, CAP1, NO, OBRA, REPORT, lista, manga, servidor

SO_SAFE = frozenset({Classificacao.SAFE})


def test_busca_manda_classificacao_explicita_e_filtro_de_mangas(mangadex, api):
    api.responder("GET", f"{API}/manga", json=lista(manga()))
    resultado = mangadex.buscar(Filtro(SO_SAFE, frozenset({Tipo.MANGA})))

    params = api.chamadas[0].url.params
    assert params.get_list("contentRating[]") == ["safe"]
    assert params.get_list("originalLanguage[]") == ["ja"]
    assert params.get_list("availableTranslatedLanguage[]") == ["pt-br", "en"]
    assert resultado.obras[0].titulo == "Obra Teste"


def test_manhwas_incluem_manhuas(mangadex, api):
    api.responder("GET", f"{API}/manga", json=lista())
    mangadex.buscar(Filtro(SO_SAFE, frozenset({Tipo.MANHWA, Tipo.MANHUA})))
    assert api.chamadas[0].url.params.get_list("originalLanguage[]") == ["ko", "zh", "zh-hk"]


def test_hqs_excluem_idiomas_asiaticos(mangadex, api):
    api.responder("GET", f"{API}/manga", json=lista())
    mangadex.buscar(Filtro(SO_SAFE, frozenset({Tipo.HQ})))
    params = api.chamadas[0].url.params
    assert params.get_list("excludedOriginalLanguage[]") == ["ja", "ko", "zh", "zh-hk"]
    assert "originalLanguage[]" not in params


def test_busca_sem_classificacao_nao_chama_a_api(mangadex, api):
    assert mangadex.buscar(Filtro(frozenset())).obras == []
    assert api.chamadas == []


def test_busca_repetida_usa_o_cache(mangadex, api):
    api.responder("GET", f"{API}/manga", json=lista(manga()))
    mangadex.buscar(Filtro(SO_SAFE, termo="x"))
    mangadex.buscar(Filtro(SO_SAFE, termo="x"))
    assert len(api.chamadas) == 1


def test_converte_obra(mangadex, api):
    descricao = {"en": "In English", "pt-br": "Sinopse com [link](https://x) e **negrito**.\n\n---\n**Links:** ..."}
    api.responder(
        "GET",
        f"{API}/manga/{OBRA}",
        json={"data": manga(idioma="ko", classificacao="suggestive", descricao=descricao, alternativos=[{"pt-br": "Título BR"}, {"ja": "日本"}])},
    )
    obra = mangadex.obra(OBRA)
    assert obra.tipo is Tipo.MANHWA
    assert obra.classificacao is Classificacao.SUGGESTIVE
    assert obra.titulos_alternativos == ("Título BR",)
    assert obra.descricao == "Sinopse com link e negrito."
    assert obra.capa_url == f"/capa/mangadex/{OBRA}"
    assert obra.autores == ("Autora Teste",)


def test_429_pausa_as_chamadas_seguintes(mangadex, api):
    volta_em = str(int(time.time()) + 60)
    api.responder("GET", f"{API}/manga", json={}, status=429, headers={"X-RateLimit-Retry-After": volta_em})
    with pytest.raises(FonteIndisponivel):
        mangadex.buscar(Filtro(SO_SAFE, termo="a"))
    with pytest.raises(FonteIndisponivel):
        mangadex.buscar(Filtro(SO_SAFE, termo="b"))
    assert len(api.chamadas) == 1  # a segunda nem saiu


def test_id_invalido_nao_chama_a_api(mangadex, api):
    with pytest.raises(NaoEncontrado):
        mangadex.obra("../../etc/passwd")
    assert api.chamadas == []


def test_imagem_de_no_md_home_e_reportada(mangadex, api):
    api.responder("GET", f"{API}/at-home/server/{CAP1}", json=servidor())
    api.imagem(f"{NO}/data-saver/abc123/2-leve.jpg", conteudo=b"pagina2", headers={"X-Cache": "HIT from x"})
    api.responder("POST", REPORT, json={})

    imagem = mangadex.imagem_pagina(CAP1, 2, "data-saver")

    assert imagem.conteudo == b"pagina2"
    report = json.loads(api.chamadas_para("/report")[0].content)
    assert report["url"] == f"{NO}/data-saver/abc123/2-leve.jpg"
    assert report["success"] is True
    assert report["cached"] is True
    assert report["bytes"] == 7


def test_imagem_do_proprio_mangadex_nao_e_reportada(mangadex, api):
    base = "https://uploads.mangadex.org"
    api.responder("GET", f"{API}/at-home/server/{CAP1}", json=servidor(base=base))
    api.imagem(f"{base}/data/abc123/1-original.jpg")
    mangadex.imagem_pagina(CAP1, 1, "data")
    assert api.chamadas_para("/report") == []


def test_falha_pede_outro_servidor_e_tenta_de_novo(mangadex, api):
    outro = "https://outro-no.mangadex.network"
    api.responder("GET", f"{API}/at-home/server/{CAP1}", json=servidor())
    api.responder("GET", f"{API}/at-home/server/{CAP1}", json=servidor(base=outro))
    api.imagem(f"{NO}/data-saver/abc123/1-leve.jpg", status=502)
    api.imagem(f"{outro}/data-saver/abc123/1-leve.jpg", conteudo=b"ok")
    api.responder("POST", REPORT, json={})

    assert mangadex.imagem_pagina(CAP1, 1, "data-saver").conteudo == b"ok"
    reports = [json.loads(r.content)["success"] for r in api.chamadas_para("/report")]
    assert reports == [False, True]  # a falha também é reportada


def test_svg_nunca_e_servido(mangadex, api):
    api.responder("GET", f"{API}/at-home/server/{CAP1}", json=servidor())
    api.imagem(f"{NO}/data-saver/abc123/1-leve.jpg", conteudo=b"<svg onload=alert(1)>", tipo="image/svg+xml")
    api.responder("POST", REPORT, json={})
    with pytest.raises(FonteIndisponivel):
        mangadex.imagem_pagina(CAP1, 1, "data-saver")


def test_pagina_fora_do_capitulo(mangadex, api):
    api.responder("GET", f"{API}/at-home/server/{CAP1}", json=servidor(paginas=3))
    with pytest.raises(NaoEncontrado):
        mangadex.imagem_pagina(CAP1, 4, "data")
