import json

import httpx

from app.catalogos.anilist import AniList
from app.dominio import Tipo
from tests.fabrica import ANILIST, ANILIST_ID, media_anilist, resposta_anilist


def test_ficha_converte_os_dados(anilist, api):
    api.responder("POST", ANILIST, json=resposta_anilist(media_anilist(capitulos=116, status="FINISHED")))
    ficha = anilist.ficha(ANILIST_ID)

    assert ficha.titulo == "Obra Teste"
    assert ficha.tipo == Tipo.MANGA
    assert ficha.status == "completed"
    assert ficha.capitulos == 116
    assert ficha.autores == ("Autora Teste",)  # o tradutor fica de fora
    assert ficha.descricao == "Primeira linha.\n\nSegunda linha & fim."
    # Redes sociais e links desativados ficam de fora; INFO vira página de editora.
    assert [(link.site, link.idioma, link.leitura) for link in ficha.links] == [
        ("MANGA Plus", "en", True),
        ("Editora BR", "pt-br", False),
    ]
    enviado = json.loads(api.chamadas[0].content)
    assert enviado["variables"] == {"id": ANILIST_ID}
    assert api.chamadas[0].headers["user-agent"].startswith("Nami/")


def test_ficha_fica_em_cache(anilist, api):
    api.responder("POST", ANILIST, json=resposta_anilist())
    anilist.ficha(ANILIST_ID)
    anilist.ficha(ANILIST_ID)
    assert len(api.chamadas) == 1


def test_ficha_com_anilist_fora_do_ar_volta_none_e_nao_insiste(anilist, api):
    api.responder("POST", ANILIST, json={}, status=500)
    assert anilist.ficha(ANILIST_ID) is None
    assert anilist.ficha(ANILIST_ID) is None
    assert len(api.chamadas) == 1  # a falha também fica guardada por alguns minutos


def test_ficha_inexistente(anilist, api):
    api.responder("POST", ANILIST, json={"data": {"Media": None}, "errors": [{"status": 404}]}, status=404)
    assert anilist.ficha(999) is None


def test_429_pausa_as_consultas(anilist, api):
    api.responder("POST", ANILIST, json={}, status=429, headers={"Retry-After": "30"})
    assert anilist.ficha(1) is None
    assert anilist.ficha(2) is None  # nem chega a chamar: está em pausa
    assert len(api.chamadas) == 1


def test_limite_por_minuto(config, api):
    anilist = AniList(config, http=httpx.Client(transport=httpx.MockTransport(api)), por_minuto=2)
    api.responder("POST", ANILIST, json=resposta_anilist())
    for anilist_id in (1, 2, 3):
        anilist.ficha(anilist_id)
    assert len(api.chamadas) == 2


def test_desligado_nao_chama(config, api, anilist):
    config.anilist_ativo = False
    assert anilist.ficha(ANILIST_ID) is None
    assert api.chamadas == []


def test_busca(anilist, api):
    api.responder("POST", ANILIST, json={"data": {"Page": {"media": [media_anilist(), media_anilist(id=2)]}}})
    resultados = anilist.buscar("obra")
    assert [f.id for f in resultados] == [ANILIST_ID, 2]
    assert json.loads(api.chamadas[0].content)["variables"]["termo"] == "obra"
