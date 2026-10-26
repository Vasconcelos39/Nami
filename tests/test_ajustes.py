"""Ajustes do admin em obras do MangaDex: bloquear, classificação, título,
descrição, capa, esconder capítulos e capítulos extras."""

import pytest
from sqlalchemy import select

from app.models import AjusteObra, CapituloExtra
from tests.ajudantes import cadastrar, cbz_simples, consultar, entrar, imagem, ligar_adulto, sair, tornar_admin
from tests.fabrica import API, CAP1, CAP2, CAPAS, OBRA, capitulo, capitulo_detalhe, feed, lista, manga, servidor

AJUSTES = f"/admin/ajustes/mangadex/{OBRA}"
SENHA_CHEFE = "senha-do-chefe-123"


@pytest.fixture
def admin(cliente, api):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga()})
    api.responder("GET", f"{API}/manga/{OBRA}/feed", json=feed(capitulo(CAP1, numero="1"), capitulo(CAP2, numero="2")))
    api.responder("GET", f"{API}/chapter/{CAP1}", json=capitulo_detalhe(CAP1))
    api.responder("GET", f"{API}/chapter/{CAP2}", json=capitulo_detalhe(CAP2, numero="2"))
    api.responder("GET", f"{API}/at-home/server/{CAP1}", json=servidor())
    api.imagem(f"{CAPAS}/{OBRA}/capa.jpg.256.jpg", conteudo=b"capa-do-mangadex")
    cadastrar(cliente, "chefe", SENHA_CHEFE)
    tornar_admin(cliente, "chefe")
    return cliente


def _salvar(cliente, **campos):
    return cliente.post(AJUSTES, data=campos, follow_redirects=False)


def test_pagina_de_ajustes_e_botao_na_obra(admin):
    assert 'href="/admin/ajustes/mangadex/' in admin.get(f"/obra/mangadex/{OBRA}").text
    pagina = admin.get(AJUSTES)
    assert pagina.status_code == 200
    assert "Obra Teste" in pagina.text and "Cap. 2" in pagina.text


def test_abrir_pelo_link_do_mangadex(admin):
    resposta = admin.get("/admin/ajustes/abrir", params={"endereco": f"https://mangadex.org/title/{OBRA}/obra-teste"}, follow_redirects=False)
    assert resposta.headers["location"] == AJUSTES
    ruim = admin.get("/admin/ajustes/abrir", params={"endereco": "qualquer coisa"})
    assert "Não achei um id" in ruim.text


def test_bloquear_some_do_site_inteiro(admin, api):
    api.responder("GET", f"{API}/manga", json=lista(manga()))
    assert admin.post(f"/progresso/mangadex/{CAP1}", json={"pagina": 1, "total": 3}).status_code == 204
    assert "Obra Teste" in admin.get("/historico").text

    assert _salvar(admin, bloqueada="on", motivo="capa explícita").headers["location"] == AJUSTES + "?ok=salvo"
    assert admin.get(f"/obra/mangadex/{OBRA}").status_code == 404
    assert admin.get(f"/ler/mangadex/{CAP1}").status_code == 404
    assert admin.get(f"/capa/mangadex/{OBRA}").status_code == 404
    assert "Obra Teste" not in admin.get("/secao/mangas").text
    assert "Obra Teste" not in admin.get("/historico").text
    assert admin.get(AJUSTES).status_code == 200  # o painel continua abrindo
    assert "bloqueada" in admin.get("/admin/ajustes").text

    _salvar(admin)  # desmarcou: volta tudo
    assert admin.get(f"/obra/mangadex/{OBRA}").status_code == 200
    assert consultar(admin, select(AjusteObra)) == []  # sem nada mudado, sai da lista


def test_trocar_titulo_descricao_e_classificacao(admin, api):
    _salvar(admin, titulo="Nome Melhor", descricao="Sinopse nova.")
    pagina = admin.get(f"/obra/mangadex/{OBRA}").text
    assert "Nome Melhor" in pagina and "Sinopse nova." in pagina
    api.responder("GET", f"{API}/manga", json=lista(manga()))
    assert "Nome Melhor" in admin.get("/secao/mangas").text

    # Reclassificada como adulta: sai do site normal e passa a morar na área madura.
    _salvar(admin, classificacao="erotica")
    assert admin.get(f"/obra/mangadex/{OBRA}").status_code == 404
    assert "Obra Teste" not in admin.get("/secao/mangas").text
    ligar_adulto(admin, senha=SENHA_CHEFE)
    assert admin.get(f"/madura/obra/mangadex/{OBRA}").status_code == 200

    ruim = _salvar(admin, classificacao="qualquer")
    assert ruim.status_code == 400 and "Classificação inválida" in ruim.text


def test_trocar_capa_e_voltar_a_original(admin):
    assert admin.get(f"/capa/mangadex/{OBRA}").content == b"capa-do-mangadex"
    resposta = admin.post(f"{AJUSTES}/capa", files={"arquivo": ("capa.png", imagem(), "image/png")}, follow_redirects=False)
    assert resposta.headers["location"] == AJUSTES + "?ok=capa"
    nova = admin.get(f"/capa/mangadex/{OBRA}")
    assert nova.headers["content-type"] == "image/jpeg" and nova.content != b"capa-do-mangadex"
    assert f"/capa/mangadex/{OBRA}?v=a" in admin.get(f"/obra/mangadex/{OBRA}").text  # o navegador pega a nova

    admin.post(f"{AJUSTES}/capa", data={"acao": "original"})
    assert admin.get(f"/capa/mangadex/{OBRA}").content == b"capa-do-mangadex"

    ruim = admin.post(f"{AJUSTES}/capa", files={"arquivo": ("x.png", b"nao e imagem", "image/png")})
    assert ruim.status_code == 400


def test_esconder_e_mostrar_capitulo(admin):
    admin.post(f"{AJUSTES}/capitulos/{CAP2}", data={"acao": "esconder"})
    pagina = admin.get(f"/obra/mangadex/{OBRA}").text
    assert f"/ler/mangadex/{CAP2}" not in pagina and f"/ler/mangadex/{CAP1}" in pagina
    assert admin.get(f"/ler/mangadex/{CAP2}").status_code == 404

    admin.post(f"{AJUSTES}/capitulos/{CAP2}", data={"acao": "mostrar"})
    assert f"/ler/mangadex/{CAP2}" in admin.get(f"/obra/mangadex/{OBRA}").text
    # Capítulo que não é desta obra: nem guarda.
    assert admin.post(f"{AJUSTES}/capitulos/33333333-3333-4333-8333-333333333333").status_code == 404


def test_capitulo_extra_entra_na_ordem_certa(admin):
    assert "Adicionado pelo admin" not in admin.get(f"/obra/mangadex/{OBRA}").text  # o site já leu os ajustes
    resposta = admin.post(
        f"{AJUSTES}/extras",
        data={"numero": "1,5", "titulo": "O especial", "idioma": "pt-br"},
        files={"arquivo": ("especial.cbz", cbz_simples(4), "application/zip")},
        follow_redirects=False,
    )
    assert resposta.status_code == 303
    (extra,) = consultar(admin, select(CapituloExtra))
    assert extra.numero == "1.5" and extra.total_paginas == 4

    pagina = admin.get(f"/obra/mangadex/{OBRA}").text
    lista_html = pagina[pagina.index('class="lista-capitulos"'):]
    posicoes = [lista_html.index(f"/ler/mangadex/{cap}") for cap in (CAP2, f"extra-{extra.id}", CAP1)]
    assert posicoes == sorted(posicoes)  # mais novos primeiro: 2, 1.5, 1
    assert "Adicionado pelo admin" in pagina

    leitor = admin.get(f"/ler/mangadex/extra-{extra.id}")
    assert leitor.status_code == 200
    assert f'"anterior": "/ler/mangadex/{CAP1}"' in leitor.text and f'"proximo": "/ler/mangadex/{CAP2}"' in leitor.text
    img = admin.get(f"/img/mangadex/extra-{extra.id}/2")
    assert img.status_code == 200 and img.headers["content-type"].startswith("image/")
    assert admin.get(f"/img/mangadex/extra-{extra.id}/5").status_code == 404

    assert admin.post(f"/progresso/mangadex/extra-{extra.id}", json={"pagina": 2, "total": 4}).status_code == 204
    admin.post(f"{AJUSTES}/extras/{extra.id}/remover")
    assert admin.get(f"/ler/mangadex/extra-{extra.id}").status_code == 404
    assert "O especial" not in admin.get("/historico").text


def test_extra_precisa_de_numero(admin):
    sem = admin.post(f"{AJUSTES}/extras", data={"idioma": "pt-br"}, files={"arquivo": ("a.cbz", cbz_simples(), "application/zip")})
    assert sem.status_code == 400 and "Informe o número" in sem.text
    ruim = admin.post(
        f"{AJUSTES}/extras", data={"numero": "doze", "idioma": "pt-br"}, files={"arquivo": ("a.cbz", cbz_simples(), "application/zip")}
    )
    assert ruim.status_code == 400 and "precisa ser um número" in ruim.text
    assert consultar(admin, select(CapituloExtra)) == []


def test_conta_comum_nao_ajusta_nada(admin):
    sair(admin)
    cadastrar(admin, "ana")
    assert admin.get(AJUSTES).status_code == 404
    assert _salvar(admin, bloqueada="on").status_code == 404
    sair(admin)
    entrar(admin, "chefe", SENHA_CHEFE)
    assert consultar(admin, select(AjusteObra)) == []


def test_ajustes_ficam_em_memoria_e_atualizam_na_hora(admin):
    # Toda capa e toda página passam pelos ajustes: o banco é lido uma vez só,
    # e de novo quando um admin grava alguma coisa.
    fonte = admin.app.state.fontes.obter("mangadex")
    sessoes, leituras = fonte.sessoes, []
    fonte.sessoes = lambda: leituras.append(1) or sessoes()
    for _ in range(5):
        assert admin.get(f"/capa/mangadex/{OBRA}").status_code == 200
        assert admin.get(f"/obra/mangadex/{OBRA}").status_code == 200
    assert len(leituras) == 1

    _salvar(admin, titulo="Nome Novo")
    assert "Nome Novo" in admin.get(f"/obra/mangadex/{OBRA}").text
    assert len(leituras) == 2
