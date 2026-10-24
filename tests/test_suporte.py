from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import MensagemTicket, Ticket
from app.servicos.suporte import MAX_ABERTOS, TEXTO_MAXIMO
from tests.ajudantes import cadastrar, consultar, entrar, sair, tornar_admin

JSON = {"Accept": "application/json"}


def _abrir(cliente, assunto="Capítulo não abre", texto="O capítulo 3 dá erro."):
    return cliente.post("/suporte/novo", data={"assunto": assunto, "texto": texto}, follow_redirects=False)


def _id(resposta) -> int:
    return int(resposta.headers["location"].rsplit("/", 1)[1])


def test_suporte_precisa_de_login(cliente):
    resposta = cliente.get("/suporte", follow_redirects=False)
    assert resposta.headers["location"].startswith("/entrar")


def test_abrir_conversa(cliente):
    cadastrar(cliente)
    resposta = _abrir(cliente)
    assert resposta.status_code == 303
    ticket_id = _id(resposta)

    pagina = cliente.get(f"/suporte/{ticket_id}").text
    assert "Capítulo não abre" in pagina and "O capítulo 3 dá erro." in pagina
    assert "Esperando o suporte" in pagina
    assert "Capítulo não abre" in cliente.get("/suporte").text


def test_conversa_de_outra_pessoa_nao_existe(cliente):
    cadastrar(cliente, "ana")
    ticket_id = _id(_abrir(cliente))
    sair(cliente)
    cadastrar(cliente, "bia")
    assert cliente.get(f"/suporte/{ticket_id}").status_code == 404
    assert cliente.get(f"/suporte/{ticket_id}/mensagens").status_code == 404
    assert cliente.post(f"/suporte/{ticket_id}/mensagens", data={"texto": "oi"}).status_code == 404
    assert cliente.post(f"/suporte/{ticket_id}/status", data={"acao": "fechar"}).status_code == 404
    assert len(consultar(cliente, select(MensagemTicket))) == 1


def test_admin_responde_e_a_pessoa_ve_a_resposta(cliente):
    cadastrar(cliente, "ana")
    ticket_id = _id(_abrir(cliente))
    sair(cliente)

    cadastrar(cliente, "chefe", "senha-do-chefe-123")
    tornar_admin(cliente, "chefe")
    assert "Capítulo não abre" in cliente.get("/admin/suporte").text
    assert "<strong>1</strong><span>ticket esperando resposta</span>" in cliente.get("/admin").text
    resposta = cliente.post(f"/suporte/{ticket_id}/mensagens", data={"texto": "Já arrumei!"}, headers=JSON)
    assert resposta.json()["mensagem"]["suporte"] is True
    assert resposta.json()["status"] == "respondido"
    sair(cliente)

    entrar(cliente, "ana")
    assert 'class="contador"' in cliente.get("/suporte").text  # aviso de resposta nova no menu
    novas = cliente.get(f"/suporte/{ticket_id}/mensagens", params={"depois": 0}).json()
    assert [(m["autor"], m["texto"]) for m in novas["mensagens"]] == [
        ("ana", "O capítulo 3 dá erro."),
        ("Suporte", "Já arrumei!"),  # a pessoa não vê qual admin respondeu
    ]
    ultima = novas["mensagens"][-1]["id"]
    assert cliente.get(f"/suporte/{ticket_id}/mensagens", params={"depois": ultima}).json()["mensagens"] == []

    cliente.post(f"/suporte/{ticket_id}/mensagens", data={"texto": "Valeu"})
    assert consultar(cliente, select(Ticket.status)) == ["aberto"]


def test_fechar_e_reabrir(cliente):
    cadastrar(cliente)
    ticket_id = _id(_abrir(cliente))
    cliente.post(f"/suporte/{ticket_id}/status", data={"acao": "fechar"})
    assert consultar(cliente, select(Ticket.status)) == ["fechado"]
    cliente.post(f"/suporte/{ticket_id}/mensagens", data={"texto": "Voltou a dar erro"})
    assert consultar(cliente, select(Ticket.status)) == ["aberto"]  # mensagem nova reabre


def test_limites(cliente):
    cadastrar(cliente)
    assert _abrir(cliente, assunto="x").status_code == 400
    assert _abrir(cliente, texto="   ").status_code == 400
    assert _abrir(cliente, texto="a" * (TEXTO_MAXIMO + 1)).status_code == 400
    for i in range(MAX_ABERTOS):
        assert _abrir(cliente, assunto=f"Assunto {i}").status_code == 303
    resposta = _abrir(cliente, assunto="Mais um")
    assert resposta.status_code == 400
    assert "conversas em aberto" in resposta.text


def test_mensagem_vazia_pelo_chat(cliente):
    cadastrar(cliente)
    ticket_id = _id(_abrir(cliente))
    resposta = cliente.post(f"/suporte/{ticket_id}/mensagens", data={"texto": " "}, headers=JSON)
    assert resposta.status_code == 400
    assert "Escreva" in resposta.json()["erro"]


def test_html_na_mensagem_nao_vira_codigo(cliente):
    cadastrar(cliente)
    ticket_id = _id(_abrir(cliente, texto="<script>alert(1)</script>"))
    pagina = cliente.get(f"/suporte/{ticket_id}").text
    assert "<script>alert(1)</script>" not in pagina
    assert "&lt;script&gt;" in pagina


def test_admin_no_proprio_ticket_fala_como_pessoa(cliente):
    cadastrar(cliente, "chefe", "senha-do-chefe-123")
    tornar_admin(cliente, "chefe")
    ticket_id = _id(_abrir(cliente))
    resposta = cliente.post(f"/suporte/{ticket_id}/mensagens", data={"texto": "mais detalhes"}, headers=JSON)
    assert resposta.json()["mensagem"]["suporte"] is False
    assert consultar(cliente, select(Ticket.status)) == ["aberto"]


def test_envio_sem_javascript_volta_pra_conversa(cliente):
    cadastrar(cliente)
    ticket_id = _id(_abrir(cliente))
    resposta = cliente.post(f"/suporte/{ticket_id}/mensagens", data={"texto": "oi"}, follow_redirects=False)
    assert resposta.headers["location"] == f"/suporte/{ticket_id}#fim"


def test_outro_aparelho_ve_mensagens_novas(cliente):
    # Duas abas da mesma conversa: a busca automática traz o que a outra mandou.
    cadastrar(cliente)
    ticket_id = _id(_abrir(cliente))
    outra_aba = TestClient(cliente.app, cookies=cliente.cookies)
    cliente.post(f"/suporte/{ticket_id}/mensagens", data={"texto": "segunda"})
    textos = [m["texto"] for m in outra_aba.get(f"/suporte/{ticket_id}/mensagens").json()["mensagens"]]
    assert textos == ["O capítulo 3 dá erro.", "segunda"]
