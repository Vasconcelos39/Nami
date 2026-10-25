"""Área madura (/madura): o único lugar com conteúdo adulto, com senha pra entrar."""

from datetime import timedelta

from sqlalchemy import select, update

from app.models import Sessao, agora
from tests.ajudantes import SENHA, cadastrar, consultar, ligar_adulto, sair
from tests.fabrica import API, CAP1, CAP2, CAPAS, OBRA, capitulo, capitulo_detalhe, feed, lista, manga, servidor


def _entrar(cliente, senha=SENHA, proximo=None):
    dados = {"senha": senha, **({"proximo": proximo} if proximo else {})}
    return cliente.post("/madura/entrar", data=dados, follow_redirects=False)


def _sair(cliente):
    assert cliente.post("/madura/sair", follow_redirects=False).status_code == 303


def _obra_adulta(api, classificacao="erotica"):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga(classificacao=classificacao)})
    api.responder("GET", f"{API}/chapter/{CAP1}", json=capitulo_detalhe(CAP1, classificacao=classificacao))
    api.responder("GET", f"{API}/at-home/server/{CAP1}", json=servidor())
    api.responder("GET", f"{API}/manga/{OBRA}/feed", json=feed(capitulo(CAP1, numero="1"), capitulo(CAP2, numero="2")))


# ------------------------------------------------------------------ entrada


def test_sem_acesso_a_area_nem_existe(cliente):
    assert cliente.get("/madura", follow_redirects=False).status_code == 404  # visitante
    cadastrar(cliente)
    for caminho in ("/madura", "/madura/entrar", "/madura/historico"):
        assert cliente.get(caminho, follow_redirects=False).status_code == 404, caminho
    assert 'href="/madura/entrar"' not in cliente.get("/conta").text


def test_entrar_pede_a_senha_toda_vez(cliente, api):
    cadastrar(cliente)
    ligar_adulto(cliente)
    _sair(cliente)
    fechada = cliente.get("/madura/historico", follow_redirects=False)
    assert fechada.headers["location"] == "/madura/entrar?proximo=/madura/historico"

    errada = _entrar(cliente, senha="outra-senha-qualquer")
    assert errada.status_code == 400 and "Senha incorreta" in errada.text
    certa = _entrar(cliente, proximo="/madura/historico")
    assert certa.headers["location"] == "/madura/historico"
    assert cliente.get("/madura/historico").status_code == 200
    # O link de entrar sempre mostra o formulário, mesmo com a área aberta.
    assert 'name="senha"' in cliente.get("/madura/entrar").text


def test_proximo_nunca_sai_da_area(cliente):
    cadastrar(cliente)
    ligar_adulto(cliente)
    assert _entrar(cliente, proximo="https://site-falso.example").headers["location"] == "/madura"
    assert _entrar(cliente, proximo="/conta").headers["location"] == "/madura"


def test_area_fecha_sozinha_sem_uso(cliente):
    cadastrar(cliente)
    ligar_adulto(cliente)
    with cliente.app.state.sessoes() as db:
        db.execute(update(Sessao).values(madura_ate=agora() - timedelta(minutes=1)))
        db.commit()
    assert cliente.get("/madura/historico", follow_redirects=False).status_code == 303


def test_cada_pagina_empurra_o_prazo(cliente):
    cadastrar(cliente)
    ligar_adulto(cliente)
    with cliente.app.state.sessoes() as db:
        db.execute(update(Sessao).values(madura_ate=agora() + timedelta(minutes=2)))
        db.commit()
    cliente.get("/madura/historico")
    (prazo,) = consultar(cliente, select(Sessao.madura_ate))
    assert prazo > agora() + timedelta(minutes=25)


def test_sair_da_conta_fecha_a_area(cliente):
    cadastrar(cliente)
    ligar_adulto(cliente)
    sair(cliente)
    from tests.ajudantes import entrar

    entrar(cliente)
    assert cliente.get("/madura/historico", follow_redirects=False).status_code == 303


def test_admin_bloqueia_e_a_pessoa_sai_na_hora(cliente):
    from app.models import Usuario

    cadastrar(cliente)
    ligar_adulto(cliente)
    with cliente.app.state.sessoes() as db:
        db.execute(update(Usuario).values(adulto_bloqueado=True))
        db.commit()
    assert cliente.get("/madura/historico", follow_redirects=False).status_code == 404


# ------------------------------------------------- duas áreas separadas


def test_obra_adulta_so_existe_na_area_madura(cliente, api):
    _obra_adulta(api)
    cadastrar(cliente)
    ligar_adulto(cliente)  # mesmo com a área aberta...
    assert cliente.get(f"/obra/mangadex/{OBRA}").status_code == 404  # ...o site normal não mostra
    assert cliente.get(f"/ler/mangadex/{CAP1}").status_code == 404
    pagina = cliente.get(f"/madura/obra/mangadex/{OBRA}")
    assert pagina.status_code == 200
    assert f'href="/madura/ler/mangadex/{CAP1}">Começar a ler' in pagina.text
    assert 'data-area="madura"' in pagina.text  # tema preto


def test_area_madura_nao_mostra_obra_normal(cliente, api):
    _obra_adulta(api, classificacao="safe")
    cadastrar(cliente)
    ligar_adulto(cliente)
    assert cliente.get(f"/madura/obra/mangadex/{OBRA}").status_code == 404
    assert cliente.get(f"/madura/ler/mangadex/{CAP1}").status_code == 404


def test_listagens_da_area_so_pedem_adulto(cliente, api):
    api.responder("GET", f"{API}/manga", json=lista(manga(classificacao="pornographic")))
    cadastrar(cliente)
    ligar_adulto(cliente)
    inicio = cliente.get("/madura")
    assert f'href="/madura/obra/mangadex/{OBRA}"' in inicio.text
    assert api.chamadas[-1].url.params.get_list("contentRating[]") == ["erotica", "pornographic"]
    cliente.get("/madura/busca", params={"q": "x"})
    assert api.chamadas[-1].url.params.get_list("contentRating[]") == ["erotica", "pornographic"]


def test_leitor_da_area_madura(cliente, api):
    _obra_adulta(api)
    cadastrar(cliente)
    ligar_adulto(cliente)
    pagina = cliente.get(f"/madura/ler/mangadex/{CAP1}")
    assert pagina.status_code == 200
    assert f'"proximo": "/madura/ler/mangadex/{CAP2}"' in pagina.text
    assert f'"obra": "/madura/obra/mangadex/{OBRA}"' in pagina.text  # o Esc volta pra cá


def test_imagens_adultas_so_com_a_area_aberta(cliente, api):
    _obra_adulta(api)
    api.imagem(f"{CAPAS}/{OBRA}/capa.jpg.256.jpg", conteudo=b"capa")
    cadastrar(cliente)
    ligar_adulto(cliente)
    assert cliente.get(f"/capa/mangadex/{OBRA}").content == b"capa"
    _sair(cliente)
    assert cliente.get(f"/capa/mangadex/{OBRA}").status_code == 404
    assert cliente.get(f"/img/mangadex/{CAP1}/1").status_code == 404


def test_favoritos_separados(cliente, api):
    _obra_adulta(api)
    cadastrar(cliente)
    ligar_adulto(cliente)
    voltar = f"/madura/obra/mangadex/{OBRA}"
    resposta = cliente.post(f"/favoritos/mangadex/{OBRA}", data={"voltar": voltar}, follow_redirects=False)
    assert resposta.headers["location"] == voltar
    assert "Obra Teste" in cliente.get("/madura/favoritos").text
    assert "Obra Teste" not in cliente.get("/favoritos").text
    _sair(cliente)
    assert cliente.post(f"/favoritos/mangadex/{OBRA}", follow_redirects=False).status_code == 404
