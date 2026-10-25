"""Área de Novidades: posts do admin, rascunhos, bolinha no menu e o texto simples."""

import pytest
from sqlalchemy import select

from app.models import Noticia
from app.servicos.noticias import formatar
from tests.ajudantes import cadastrar, consultar, entrar, sair, tornar_admin

PONTO = 'class="ponto-novo"'


@pytest.fixture
def admin(cliente):
    cadastrar(cliente, "chefe", "senha-do-chefe-123")
    tornar_admin(cliente, "chefe")
    return cliente


def _escrever(cliente, acao="publicar", titulo="Saiu a 0.8", texto="Tem **coisa nova**.\n\n- busca\n- ícone"):
    return cliente.post(
        "/admin/novidades/nova", data={"titulo": titulo, "texto": texto, "acao": acao}, follow_redirects=False
    )


def _id(cliente):
    return consultar(cliente, select(Noticia.id))[-1]


# ------------------------------------------------------------------ texto


def test_texto_simples_vira_paragrafos_listas_negrito_e_links():
    html = formatar("Oi **gente**!\nVeja https://exemplo.com/a?b=1&c=2.\n\n- um\n- dois")
    assert html == (
        '<p>Oi <strong>gente</strong>!<br>Veja <a href="https://exemplo.com/a?b=1&amp;c=2" target="_blank" '
        'rel="noopener">https://exemplo.com/a?b=1&amp;c=2</a>.</p>\n<ul><li>um</li><li>dois</li></ul>'
    )


@pytest.mark.parametrize(
    "texto",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        'https://x.com/"onmouseover="alert(1)',
        "javascript:alert(1)",
        "**<b>negrito com tag</b>**",
    ],
)
def test_texto_simples_nunca_vira_html_do_admin(texto):
    html = str(formatar(texto))
    assert "<script" not in html and "<img" not in html and "<b>" not in html
    assert 'href="javascript' not in html
    assert '"onmouseover' not in html


# ------------------------------------------------------------- publicação


def test_rascunho_so_o_admin_ve(admin):
    assert _escrever(admin, acao="rascunho").status_code == 303
    assert "Saiu a 0.8" in admin.get("/admin/novidades").text
    sair(admin)
    cadastrar(admin, "ana")
    pagina = admin.get("/novidades")
    assert "Saiu a 0.8" not in pagina.text
    assert "Ainda não saiu nenhuma novidade" in pagina.text
    assert PONTO not in admin.get("/conta").text


def test_publicar_acende_a_bolinha_ate_abrir(admin):
    sair(admin)
    cadastrar(admin, "ana")
    sair(admin)
    entrar(admin, "chefe", "senha-do-chefe-123")
    resposta = _escrever(admin)
    assert resposta.headers["location"].endswith("?ok=noticia-publicada")
    sair(admin)

    entrar(admin, "ana")
    assert PONTO in admin.get("/conta").text  # no menu, e no atalho da página da conta
    pagina = admin.get("/novidades")
    assert "Saiu a 0.8" in pagina.text
    assert "<strong>coisa nova</strong>" in pagina.text
    assert ">nova<" in pagina.text
    assert PONTO not in pagina.text  # abriu: a bolinha some na hora
    assert PONTO not in admin.get("/conta").text
    assert ">nova<" not in admin.get("/novidades").text


def test_corrigir_post_publicado_nao_acende_de_novo(admin):
    _escrever(admin)
    noticia = _id(admin)
    admin.get("/novidades")  # o próprio admin leu
    resposta = admin.post(
        f"/admin/novidades/{noticia}", data={"titulo": "Saiu a 0.8!", "texto": "Corrigido.", "acao": "salvar"}
    )
    assert resposta.status_code == 200
    assert "Corrigido." in resposta.text
    assert PONTO not in admin.get("/conta").text


def test_voltar_pra_rascunho_e_apagar(admin):
    _escrever(admin)
    noticia = _id(admin)
    admin.post(f"/admin/novidades/{noticia}", data={"titulo": "Saiu a 0.8", "texto": "x", "acao": "despublicar"})
    assert "Saiu a 0.8" not in admin.get("/novidades").text
    admin.post(f"/admin/novidades/{noticia}/apagar")
    assert consultar(admin, select(Noticia)) == []
    assert admin.get(f"/admin/novidades/{noticia}").status_code == 404


def test_campos_obrigatorios(admin):
    sem_titulo = _escrever(admin, titulo="  ")
    assert sem_titulo.status_code == 400 and "Escreva um título" in sem_titulo.text
    sem_texto = _escrever(admin, texto="")
    assert sem_texto.status_code == 400
    assert 'value="Saiu a 0.8"' in sem_texto.text  # o que foi digitado não se perde
    assert consultar(admin, select(Noticia)) == []


def test_visitante_vai_pro_login(cliente):
    assert cliente.get("/novidades", follow_redirects=False).status_code == 303
