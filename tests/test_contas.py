import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import criar_app
from app.models import Sessao, Usuario
from app.rotas.conta import destino_seguro
from tests.ajudantes import SENHA, cadastrar, consultar, contar, entrar, ligar_adulto, sair
from tests.fabrica import API, lista, manga


def test_cadastro_cria_conta_e_ja_entra(cliente):
    resposta = cadastrar(cliente)
    assert resposta.status_code == 303
    assert "nami_sessao" in resposta.cookies
    conta = cliente.get("/conta")
    assert conta.status_code == 200
    assert "ana" in conta.text


def test_senha_e_guardada_so_como_hash_argon2(cliente):
    cadastrar(cliente)
    (usuario,) = consultar(cliente, select(Usuario))
    assert usuario.senha_hash.startswith("$argon2id$")
    assert SENHA not in usuario.senha_hash


def test_sessao_guarda_so_o_hash_do_token(cliente):
    token = cadastrar(cliente).cookies["nami_sessao"]
    (sessao,) = consultar(cliente, select(Sessao))
    assert sessao.token_hash != token


def test_nome_repetido_ignora_maiusculas(cliente):
    cadastrar(cliente, "Ana")
    sair(cliente)
    resposta = cadastrar(cliente, "ana")
    assert resposta.status_code == 400
    assert "já está em uso" in resposta.text


@pytest.mark.parametrize(
    ("username", "senha", "senha2", "mensagem"),
    [
        ("ana", "curta", None, "pelo menos 8"),
        ("ana", SENHA, "outra-senha-123", "não são iguais"),
        ("a", SENHA, None, "de 3 a 32"),
        ("ana com espaço", SENHA, None, "de 3 a 32"),
        ("anaana12", "anaana12", None, "igual ao nome"),
    ],
)
def test_cadastro_invalido(cliente, username, senha, senha2, mensagem):
    resposta = cadastrar(cliente, username, senha, senha2)
    assert resposta.status_code == 400
    assert mensagem in resposta.text
    assert contar(cliente, Usuario) == 0


def test_login_volta_pra_pagina_pedida(cliente):
    cadastrar(cliente)
    sair(cliente)
    resposta = entrar(cliente, "ANA", proximo="/favoritos")
    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/favoritos"


@pytest.mark.parametrize(
    "proximo", ["//site-falso.example/x", "https://site-falso.example", "/\\site-falso.example", "favoritos", ""]
)
def test_destino_nunca_sai_do_site(proximo):
    assert destino_seguro(proximo) == "/"


def test_destino_dentro_do_site():
    assert destino_seguro("/obra/mangadex/x?idioma=en") == "/obra/mangadex/x?idioma=en"


def test_senha_errada(cliente):
    cadastrar(cliente)
    sair(cliente)
    resposta = entrar(cliente, senha="senha-errada")
    assert resposta.status_code == 400
    assert "incorretos" in resposta.text
    assert "nami_sessao" not in resposta.cookies


def test_muitas_tentativas_bloqueiam_o_ip(cliente):
    cadastrar(cliente)
    sair(cliente)
    for _ in range(10):
        assert entrar(cliente, senha="senha-errada").status_code == 400
    bloqueado = entrar(cliente)  # nem a senha certa passa durante o bloqueio
    assert bloqueado.status_code == 429


def test_sair_apaga_a_sessao(cliente):
    cadastrar(cliente)
    sair(cliente)
    assert contar(cliente, Sessao) == 0
    assert cliente.get("/conta", follow_redirects=False).status_code == 303


def test_pagina_restrita_manda_pro_login(cliente):
    resposta = cliente.get("/historico", follow_redirects=False)
    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/entrar?proximo=/historico"


def test_conta_desativada_perde_o_acesso(cliente):
    cadastrar(cliente)
    with cliente.app.state.sessoes() as db:
        db.scalar(select(Usuario)).ativo = False
        db.commit()
    assert cliente.get("/conta", follow_redirects=False).status_code == 303
    resposta = entrar(cliente)
    assert resposta.status_code == 403
    assert "desativada" in resposta.text


def test_trocar_senha_desconecta_os_outros_aparelhos(cliente):
    cadastrar(cliente)
    outro_aparelho = TestClient(cliente.app)
    assert entrar(outro_aparelho).status_code == 303

    resposta = cliente.post(
        "/conta/senha",
        data={"atual": SENHA, "nova": "senha-nova-456", "nova2": "senha-nova-456"},
        follow_redirects=False,
    )
    assert resposta.status_code == 303
    assert cliente.get("/conta").status_code == 200
    assert outro_aparelho.get("/conta", follow_redirects=False).status_code == 303
    assert entrar(outro_aparelho, senha="senha-nova-456").status_code == 303


def test_trocar_senha_exige_a_atual(cliente):
    cadastrar(cliente)
    resposta = cliente.post("/conta/senha", data={"atual": "chute-errado", "nova": "x" * 10, "nova2": "x" * 10})
    assert resposta.status_code == 400
    assert "senha atual está errada" in resposta.text


def test_formulario_de_outro_site_e_recusado(cliente):
    resposta = cliente.post(
        "/cadastro",
        data={"username": "ana", "senha": SENHA, "senha2": SENHA},
        headers={"Origin": "https://site-malicioso.example"},
    )
    assert resposta.status_code == 403
    assert contar(cliente, Usuario) == 0


def test_cadastro_fechado(config, mangadex):
    app = criar_app(config.model_copy(update={"cadastro_aberto": False}), mangadex=mangadex)
    with TestClient(app) as cliente:
        assert cliente.get("/cadastro").status_code == 404
        assert cadastrar(cliente).status_code == 404


# ------------------------------------------------------------------ +18


def test_logado_ve_tambem_conteudo_sugestivo(cliente, api):
    cadastrar(cliente)
    api.responder("GET", f"{API}/manga", json=lista(manga()))
    cliente.get("/busca", params={"q": "x"})
    assert api.chamadas[-1].url.params.get_list("contentRating[]") == ["safe", "suggestive"]


def _verificar(cliente, **dados):
    return cliente.post("/conta/maioridade", data={"acao": "ligar", **dados}, follow_redirects=False)


def test_18_nao_liga_mais_pelas_preferencias(cliente):
    cadastrar(cliente)
    conta = cliente.get("/conta").text
    assert 'name="mostrar_adulto"' not in conta
    assert 'href="/conta/maioridade"' in conta  # só um link discreto no fim da página
    cliente.post("/conta/preferencias", data={"mostrar_adulto": "on", "confirmo_maioridade": "on"})
    assert cliente.get("/secao/adulto").status_code == 404


def test_18_exige_senha_e_data_de_nascimento(cliente):
    cadastrar(cliente)
    pagina = cliente.get("/conta/maioridade")
    assert 'name="nascimento"' in pagina.text and 'name="senha"' in pagina.text

    errada = _verificar(cliente, senha="outra-senha-qualquer", nascimento="1990-05-10")
    assert errada.status_code == 400 and "Senha incorreta" in errada.text
    sem_data = _verificar(cliente, senha=SENHA)
    assert sem_data.status_code == 400 and "data de nascimento" in sem_data.text
    assert cliente.get("/secao/adulto").status_code == 404
    (usuario,) = consultar(cliente, select(Usuario))
    assert usuario.maioridade_confirmada_em is None and not usuario.mostrar_adulto


def test_18_ligado_libera_a_secao_e_pode_ser_desligado(cliente, api):
    cadastrar(cliente)
    ligar_adulto(cliente)
    api.responder("GET", f"{API}/manga", json=lista(manga(classificacao="erotica")))

    secao = cliente.get("/secao/adulto")
    assert secao.status_code == 200
    assert api.chamadas[-1].url.params.get_list("contentRating[]") == ["erotica", "pornographic"]
    assert 'href="/secao/adulto"' in secao.text  # aparece no menu
    assert "+18 ligado" in cliente.get("/conta").text

    desligar = cliente.post("/conta/maioridade", data={"acao": "desligar"}, follow_redirects=False)
    assert desligar.status_code == 303  # desligar não pede senha
    assert cliente.get("/secao/adulto").status_code == 404
    (usuario,) = consultar(cliente, select(Usuario))
    assert usuario.maioridade_confirmada_em is not None  # a confirmação fica registrada

    # Pra ligar de novo, só a senha: a data já foi confirmada.
    assert 'name="nascimento"' not in cliente.get("/conta/maioridade").text
    assert _verificar(cliente, senha=SENHA).status_code == 303
    assert cliente.get("/secao/adulto").status_code == 200


def test_18_data_de_menor_bloqueia_a_conta(cliente):
    cadastrar(cliente)
    menor = _verificar(cliente, senha=SENHA, nascimento="2015-03-01")
    assert menor.status_code == 400 and "menos de 18 anos" in menor.text
    # Trocar a data não adianta: só um admin desbloqueia.
    de_novo = _verificar(cliente, senha=SENHA, nascimento="1980-01-01")
    assert de_novo.status_code == 400 and "bloqueado" in de_novo.text
    assert cliente.get("/secao/adulto").status_code == 404
    assert "fale com o suporte" in cliente.get("/conta/maioridade").text
    (usuario,) = consultar(cliente, select(Usuario))
    assert usuario.adulto_bloqueado


def test_18_senha_errada_conta_no_limite_do_login(cliente):
    cadastrar(cliente)
    cliente.app.state.limite_login_conta.maximo = 2
    for _ in range(2):
        assert _verificar(cliente, senha="errada-errada", nascimento="1990-05-10").status_code == 400
    assert _verificar(cliente, senha=SENHA, nascimento="1990-05-10").status_code == 429
