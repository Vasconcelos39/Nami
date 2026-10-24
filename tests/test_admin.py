import re

import pytest
from sqlalchemy import select

from app.models import Capitulo, Favorito, Obra, Progresso, Sessao, Usuario
from tests.ajudantes import cadastrar, cbz, cbz_simples, consultar, contar, entrar, imagem, sair, tornar_admin
from tests.fabrica import ANILIST, ANILIST_ID, API, lista, manga, media_anilist, resposta_anilist


@pytest.fixture
def admin(cliente):
    cadastrar(cliente, "chefe", "senha-do-chefe-123")
    tornar_admin(cliente, "chefe")
    return cliente


def enviar_obra(cliente, arquivos=None, **campos):
    dados = {"titulo": "Minha HQ", "tipo": "hq", "classificacao": "safe", "idioma": "pt-br", **campos}
    arquivos = arquivos or [("Minha HQ v01 c001.cbz", cbz_simples(3)), ("Minha HQ v01 c002.cbz", cbz_simples(2))]
    return cliente.post(
        "/admin/obras/nova",
        data=dados,
        files=[("arquivos", (nome, conteudo, "application/zip")) for nome, conteudo in arquivos],
        follow_redirects=False,
    )


def id_da_obra(resposta) -> str:
    return re.search(r"/admin/obras/([0-9a-f]{32})", resposta.headers["location"]).group(1)


# ----------------------------------------------------------------- acesso


def test_visitante_vai_pro_login(cliente):
    resposta = cliente.get("/admin", follow_redirects=False)
    assert resposta.status_code == 303
    assert resposta.headers["location"].startswith("/entrar")


def test_conta_comum_nao_ve_o_painel(cliente):
    cadastrar(cliente)
    assert cliente.get("/admin").status_code == 404
    assert cliente.post("/admin/obras/nova", data={}, files=[("arquivos", ("a.cbz", b"x"))]).status_code == 404


def test_menu_mostra_admin_so_pra_admin(admin):
    assert 'href="/admin"' in admin.get("/admin/usuarios").text


# ------------------------------------------------------------ biblioteca


def test_enviar_obra_cria_capitulos_paginas_e_capa(admin, config):
    resposta = enviar_obra(admin, tags="Ação, aventura")
    assert resposta.status_code == 303
    obra_id = id_da_obra(resposta)

    (obra,) = consultar(admin, select(Obra))
    assert (obra.fonte_id, obra.titulo, obra.tipo) == ("local", "Minha HQ", "hq")
    capitulos = sorted(consultar(admin, select(Capitulo)), key=lambda c: c.ordem)
    assert [(c.numero, c.volume, c.total_paginas) for c in capitulos] == [("1", "1", 3), ("2", "1", 2)]
    assert (config.dir_biblioteca / obra_id / "capa.jpg").exists()
    assert len(list((config.dir_biblioteca / capitulos[0].pasta).iterdir())) == 3
    assert list(config.dir_temporario.iterdir()) == []  # os envios temporários foram apagados

    pagina = admin.get(resposta.headers["location"])
    assert "Obra criada." in pagina.text
    assert "Ação" in pagina.text


def test_obra_local_aparece_no_site_e_e_lida(admin):
    obra_id = id_da_obra(enviar_obra(admin))
    (capitulo, _) = sorted(consultar(admin, select(Capitulo)), key=lambda c: c.ordem)

    obra = admin.get(f"/obra/local/{obra_id}")
    assert obra.status_code == 200
    assert "Minha HQ" in obra.text
    assert f'/ler/local/{capitulo.id_externo}">Começar a ler' in obra.text

    leitor = admin.get(f"/ler/local/{capitulo.id_externo}")
    assert f"/img/local/{capitulo.id_externo}/3" in leitor.text

    pagina = admin.get(f"/img/local/{capitulo.id_externo}/1")
    assert pagina.headers["content-type"] == "image/png"
    assert admin.get(f"/img/local/{capitulo.id_externo}/4").status_code == 404

    capa = admin.get(f"/capa/local/{obra_id}")
    assert capa.headers["content-type"] == "image/jpeg"


def test_secao_de_hqs_abre_na_biblioteca(admin, api):
    enviar_obra(admin)
    secao = admin.get("/secao/hqs")
    assert "Minha HQ" in secao.text
    assert api.chamadas == []  # nem precisou do MangaDex


def test_busca_procura_nas_duas_fontes(admin, api):
    enviar_obra(admin)
    api.responder("GET", f"{API}/manga", json=lista(manga(titulo="Minha HQ do MangaDex")))
    resposta = admin.get("/busca", params={"q": "minha hq"})
    assert "Na sua biblioteca" in resposta.text
    assert resposta.text.index("Na sua biblioteca") < resposta.text.index("No MangaDex")


def test_comicinfo_preenche_o_que_ficou_em_branco(admin):
    xml = "<ComicInfo><Series>Série do Arquivo</Series><Writer>Autora X</Writer><Summary>Resumo.</Summary></ComicInfo>"
    enviar_obra(admin, arquivos=[("qualquer.cbz", cbz({"1.png": imagem()}, xml))], titulo="")
    (obra,) = consultar(admin, select(Obra))
    assert (obra.titulo, obra.autor, obra.descricao) == ("Série do Arquivo", "Autora X", "Resumo.")


def test_arquivo_invalido_nao_cria_nada(admin, config):
    resposta = enviar_obra(admin, arquivos=[("texto.cbz", b"nao sou um zip")])
    assert resposta.status_code == 400
    assert "não parece" in resposta.text
    assert contar(admin, Obra) == 0
    assert list(config.dir_biblioteca.iterdir()) == []


def test_obra_adulta_local_segue_as_regras_do_18(admin):
    obra_id = id_da_obra(enviar_obra(admin, classificacao="erotica"))
    (capitulo, _) = sorted(consultar(admin, select(Capitulo)), key=lambda c: c.ordem)
    sair(admin)
    assert admin.get(f"/obra/local/{obra_id}").status_code == 404
    assert admin.get(f"/capa/local/{obra_id}").status_code == 404
    assert admin.get(f"/img/local/{capitulo.id_externo}/1").status_code == 404


def test_editar_obra_e_capitulo(admin):
    obra_id = id_da_obra(enviar_obra(admin))
    resposta = admin.post(
        f"/admin/obras/{obra_id}",
        data={"titulo": "Nome Novo", "tipo": "manga", "classificacao": "suggestive", "tags": "Drama", "ano": "2020"},
        follow_redirects=False,
    )
    assert resposta.status_code == 303
    (obra,) = consultar(admin, select(Obra))
    assert (obra.titulo, obra.tipo, obra.classificacao, obra.ano) == ("Nome Novo", "manga", "suggestive", 2020)

    capitulo = sorted(consultar(admin, select(Capitulo)), key=lambda c: c.ordem)[0]
    admin.post(f"/admin/obras/{obra_id}/capitulos/{capitulo.id_externo}", data={"numero": "0.5", "volume": "", "titulo": "Prólogo"})
    (editado,) = consultar(admin, select(Capitulo).where(Capitulo.id == capitulo.id))
    assert (editado.numero, editado.volume, editado.titulo, editado.ordem) == ("0.5", None, "Prólogo", 0.5)


def test_titulo_nao_pode_ficar_vazio(admin):
    obra_id = id_da_obra(enviar_obra(admin))
    resposta = admin.post(f"/admin/obras/{obra_id}", data={"titulo": "  ", "tipo": "hq", "classificacao": "safe"})
    assert resposta.status_code == 400
    assert consultar(admin, select(Obra.titulo)) == ["Minha HQ"]


def test_adicionar_e_remover_capitulo(admin, config):
    obra_id = id_da_obra(enviar_obra(admin))
    admin.post(
        f"/admin/obras/{obra_id}/capitulos",
        data={"idioma": "en"},
        files=[("arquivos", ("Minha HQ c003.cbz", cbz_simples(1), "application/zip"))],
    )
    novo = next(c for c in consultar(admin, select(Capitulo)) if c.numero == "3")
    assert novo.idioma == "en"

    admin.post(f"/admin/obras/{obra_id}/capitulos/{novo.id_externo}/remover")
    assert contar(admin, Capitulo) == 2
    assert not (config.dir_biblioteca / novo.pasta).exists()


def test_remover_obra_exige_confirmacao_e_apaga_tudo(admin, config):
    obra_id = id_da_obra(enviar_obra(admin))
    capitulo = consultar(admin, select(Capitulo))[0]
    admin.post(f"/progresso/local/{capitulo.id_externo}", json={"pagina": 1, "total": 3})
    admin.post(f"/favoritos/local/{obra_id}")

    assert admin.post(f"/admin/obras/{obra_id}/remover", data={}).status_code == 400
    assert contar(admin, Obra) == 1

    admin.post(f"/admin/obras/{obra_id}/remover", data={"confirmar": "on"})
    assert (contar(admin, Obra), contar(admin, Capitulo), contar(admin, Progresso), contar(admin, Favorito)) == (0, 0, 0, 0)
    assert not (config.dir_biblioteca / obra_id).exists()


def test_buscar_metadados_no_mangadex(admin, api):
    api.responder("GET", f"{API}/manga", json=lista(manga(titulo="Achada", idioma="ko", classificacao="suggestive")))
    dados = admin.get("/admin/metadados", params={"q": "achada"}).json()
    assert dados[0]["titulo"] == "Achada"
    assert (dados[0]["tipo"], dados[0]["classificacao"], dados[0]["autor"]) == ("manhwa", "suggestive", "Autora Teste")
    # o admin busca em todas as classificações
    assert api.chamadas[0].url.params.get_list("contentRating[]") == ["erotica", "pornographic", "safe", "suggestive"]


def test_buscar_metadados_no_anilist(admin, api):
    api.responder("POST", ANILIST, json={"data": {"Page": {"media": [media_anilist(generos=("Comedy", "Ecchi"))]}}})
    [dados] = admin.get("/admin/metadados", params={"q": "obra", "fonte": "anilist"}).json()
    assert (dados["titulo"], dados["anilist_id"], dados["tipo"]) == ("Obra Teste", ANILIST_ID, "manga")
    assert (dados["autor"], dados["tags"], dados["classificacao"]) == ("Autora Teste", "Comedy, Ecchi", "suggestive")
    assert dados["descricao"].startswith("Primeira linha.")


def test_anilist_fora_do_ar_na_busca_do_admin(admin, api):
    api.responder("POST", ANILIST, json={}, status=500)
    resposta = admin.get("/admin/metadados", params={"q": "obra", "fonte": "anilist"})
    assert resposta.status_code == 503
    assert "AniList" in resposta.json()["erro"]


def test_obra_local_ligada_ao_anilist_avisa_capitulos_faltando(admin, api):
    obra_id = id_da_obra(enviar_obra(admin, anilist_id=f"https://anilist.co/manga/{ANILIST_ID}/obra-teste"))
    assert consultar(admin, select(Obra.anilist_id)) == [ANILIST_ID]  # aceita o link e guarda só o número

    api.responder("POST", ANILIST, json=resposta_anilist(media_anilist(capitulos=40, status="FINISHED")))
    pagina = admin.get(f"/obra/local/{obra_id}").text
    assert "A obra original tem 40 capítulos" in pagina
    assert "https://mangaplus.shueisha.co.jp/titles/1" in pagina


# ---------------------------------------------------------------- usuários


def _id(cliente, username):
    return consultar(cliente, select(Usuario.id).where(Usuario.username == username))[0]


def test_promover_e_rebaixar(admin):
    sair(admin)
    cadastrar(admin, "ana")
    sair(admin)
    entrar(admin, "chefe", "senha-do-chefe-123")
    ana = _id(admin, "ana")
    admin.post(f"/admin/usuarios/{ana}/admin", data={"acao": "promover"})
    assert consultar(admin, select(Usuario.is_admin).where(Usuario.id == ana)) == [True]
    admin.post(f"/admin/usuarios/{ana}/admin", data={"acao": "rebaixar"})
    assert consultar(admin, select(Usuario.is_admin).where(Usuario.id == ana)) == [False]


def test_desativar_derruba_a_sessao(admin):
    sair(admin)
    cadastrar(admin, "ana")  # deixa uma sessão aberta da ana
    sair(admin)
    cadastrar(admin, "beto")
    sair(admin)
    entrar(admin, "chefe", "senha-do-chefe-123")
    beto = _id(admin, "beto")
    sessoes_antes = contar(admin, Sessao)
    admin.post(f"/admin/usuarios/{beto}/ativo", data={"acao": "desativar"})
    assert consultar(admin, select(Usuario.ativo).where(Usuario.id == beto)) == [False]
    assert contar(admin, Sessao) <= sessoes_antes
    assert entrar(admin, "beto").status_code == 403  # "conta desativada"


def test_admin_nao_tira_o_proprio_acesso(admin):
    eu = _id(admin, "chefe")
    assert admin.post(f"/admin/usuarios/{eu}/admin", data={"acao": "rebaixar"}).status_code == 400
    assert admin.post(f"/admin/usuarios/{eu}/ativo", data={"acao": "desativar"}).status_code == 400
    assert consultar(admin, select(Usuario.is_admin).where(Usuario.id == eu)) == [True]


def test_redefinir_senha_mostra_a_temporaria_uma_vez(admin):
    sair(admin)
    cadastrar(admin, "ana")
    sair(admin)
    entrar(admin, "chefe", "senha-do-chefe-123")
    resposta = admin.post(f"/admin/usuarios/{_id(admin, 'ana')}/senha")
    temporaria = re.search(r'<code class="senha">([^<]+)</code>', resposta.text).group(1)
    sair(admin)
    assert entrar(admin, "ana").status_code == 400  # a senha antiga não vale mais
    assert entrar(admin, "ana", temporaria).status_code == 303
