from sqlalchemy import select

from app.models import Reporte
from app.servicos.reportes import MAX_POR_DIA
from tests.ajudantes import cadastrar, consultar, contar, sair, tornar_admin
from tests.fabrica import API, OBRA, manga


def _obra(api, **kwargs):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga(**kwargs)})


def _reportar(cliente, motivo="capa", detalhe="A capa é de outra obra."):
    return cliente.post(
        f"/obra/mangadex/{OBRA}/reportar", data={"motivo": motivo, "detalhe": detalhe}, follow_redirects=False
    )


def test_reportar_precisa_de_login(cliente, api):
    resposta = cliente.get(f"/obra/mangadex/{OBRA}/reportar", follow_redirects=False)
    assert resposta.status_code == 303
    assert resposta.headers["location"].startswith("/entrar?proximo=")
    assert api.chamadas == []


def test_reportar_problema(cliente, api):
    _obra(api)
    cadastrar(cliente)
    assert "Capa errada" in cliente.get(f"/obra/mangadex/{OBRA}/reportar").text

    resposta = _reportar(cliente)
    assert resposta.status_code == 303
    assert resposta.headers["location"] == f"/obra/mangadex/{OBRA}?reportado=1"

    [reporte] = consultar(cliente, select(Reporte))
    assert (reporte.fonte_id, reporte.obra_externa, reporte.titulo) == ("mangadex", OBRA, "Obra Teste")
    assert (reporte.motivo, reporte.detalhe, reporte.resolvido_em) == ("capa", "A capa é de outra obra.", None)


def test_mesmo_reporte_de_novo_so_atualiza(cliente, api):
    _obra(api)
    cadastrar(cliente)
    _reportar(cliente, detalhe="primeira")
    _reportar(cliente, detalhe="segunda")
    assert [r.detalhe for r in consultar(cliente, select(Reporte))] == ["segunda"]


def test_motivo_invalido(cliente, api):
    _obra(api)
    cadastrar(cliente)
    resposta = _reportar(cliente, motivo="qualquer")
    assert resposta.status_code == 400
    assert "Escolha o tipo de problema." in resposta.text
    assert contar(cliente, Reporte) == 0


def test_limite_de_reportes_por_dia(cliente, api):
    _obra(api)
    cadastrar(cliente)
    motivos = ["capa", "capitulos", "informacoes", "classificacao", "outro"]
    for i in range(MAX_POR_DIA):
        # muda o motivo/obra pra não cair na regra de "mesmo reporte"
        with cliente.app.state.sessoes() as db:
            db.add(Reporte(usuario_id=1, fonte_id="mangadex", obra_externa=f"obra-{i}", titulo="X", motivo=motivos[i % 5]))
            db.commit()
    resposta = _reportar(cliente)
    assert resposta.status_code == 400
    assert "muitos avisos" in resposta.text


def test_obra_adulta_escondida_nao_pode_ser_reportada(cliente, api):
    _obra(api, classificacao="pornographic")
    cadastrar(cliente)
    assert cliente.get(f"/obra/mangadex/{OBRA}/reportar").status_code == 404
    assert _reportar(cliente).status_code == 404


def test_admin_ve_e_resolve_reportes(cliente, api):
    _obra(api)
    cadastrar(cliente)
    _reportar(cliente)

    assert cliente.get("/admin/reportes").status_code == 404  # ainda não é admin
    tornar_admin(cliente)
    lista = cliente.get("/admin/reportes").text
    assert "Obra Teste" in lista and "Capa errada" in lista and "A capa é de outra obra." in lista
    assert "reporte em aberto" in cliente.get("/admin").text

    [reporte] = consultar(cliente, select(Reporte))
    resposta = cliente.post(f"/admin/reportes/{reporte.id}", data={"acao": "resolver"}, follow_redirects=False)
    assert resposta.headers["location"] == "/admin/reportes?ok=resolvido"
    assert "Nenhum reporte em aberto." in cliente.get("/admin/reportes").text
    assert "Obra Teste" in cliente.get("/admin/reportes?resolvidos=1").text

    cliente.post(f"/admin/reportes/{reporte.id}", data={"acao": "reabrir"})
    assert consultar(cliente, select(Reporte))[0].resolvido_em is None


def test_reporte_continua_se_a_conta_sair(cliente, api):
    _obra(api)
    cadastrar(cliente)
    _reportar(cliente)
    sair(cliente)
    assert contar(cliente, Reporte) == 1
