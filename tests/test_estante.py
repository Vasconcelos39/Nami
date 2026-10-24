from sqlalchemy import select

from app.models import Capitulo, Favorito, Obra, Progresso
from tests.ajudantes import cadastrar, consultar, contar, ligar_adulto
from tests.fabrica import (
    API,
    CAP1,
    CAP2,
    OBRA,
    capitulo,
    capitulo_detalhe,
    feed,
    lista,
    manga,
    servidor,
)


def preparar_obra(api, classificacao="safe", paginas=3):
    """Um capítulo de 3 páginas (CAP1) e o seguinte (CAP2) na mesma obra."""
    api.responder("GET", f"{API}/chapter/{CAP1}", json=capitulo_detalhe(CAP1, classificacao=classificacao, paginas=paginas))
    api.responder("GET", f"{API}/at-home/server/{CAP1}", json=servidor(paginas=paginas))
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga(classificacao=classificacao)})
    api.responder(
        "GET",
        f"{API}/manga/{OBRA}/feed",
        json=feed(capitulo(CAP1, numero="1", paginas=paginas), capitulo(CAP2, numero="2")),
    )


def salvar(cliente, pagina, total=3):
    return cliente.post(f"/progresso/mangadex/{CAP1}", json={"pagina": pagina, "total": total})


def test_progresso_exige_login(cliente, api):
    assert salvar(cliente, 2).status_code == 401


def test_visitante_nao_recebe_endereco_de_progresso(cliente, api):
    preparar_obra(api)
    assert '"salvarProgresso": null' in cliente.get(f"/ler/mangadex/{CAP1}").text


def test_progresso_salvo_reabre_onde_parou(cliente, api):
    cadastrar(cliente)
    preparar_obra(api)
    assert salvar(cliente, 2).status_code == 204

    leitor = cliente.get(f"/ler/mangadex/{CAP1}")
    assert '"paginaSalva": 2' in leitor.text
    assert f'"salvarProgresso": "/progresso/mangadex/{CAP1}"' in leitor.text

    obra = cliente.get(f"/obra/mangadex/{OBRA}")
    assert f'/ler/mangadex/{CAP1}#p=2">Continuar · Cap. 1, pág. 2' in obra.text
    assert "pág. 2/3" in obra.text

    historico = cliente.get("/historico")
    assert "Obra Teste" in historico.text
    assert "página 2 de 3" in historico.text


def test_obra_e_capitulo_sao_guardados_uma_vez_so(cliente, api):
    cadastrar(cliente)
    preparar_obra(api)
    salvar(cliente, 1)
    salvar(cliente, 2)
    assert (contar(cliente, Obra), contar(cliente, Capitulo), contar(cliente, Progresso)) == (1, 1, 1)
    (obra,) = consultar(cliente, select(Obra))
    assert (obra.fonte_id, obra.id_externo, obra.classificacao) == ("mangadex", OBRA, "safe")


def test_ultima_pagina_marca_lido_e_sugere_o_proximo(cliente, api):
    cadastrar(cliente)
    preparar_obra(api)
    salvar(cliente, 3)

    obra = cliente.get(f"/obra/mangadex/{OBRA}")
    assert f'/ler/mangadex/{CAP2}">Continuar · Cap. 2' in obra.text
    assert 'class="cap-marca">lido' in obra.text

    salvar(cliente, 1)  # voltou pro começo pra reler: continua contando como lido
    (progresso,) = consultar(cliente, select(Progresso))
    assert progresso.concluido is True
    assert progresso.pagina == 1


def test_pagina_alem_do_fim_e_ajustada(cliente, api):
    cadastrar(cliente)
    preparar_obra(api)
    salvar(cliente, 99, total=99)  # o total que vale é o da fonte (3)
    (progresso,) = consultar(cliente, select(Progresso))
    assert progresso.pagina == 3


def test_progresso_de_obra_adulta_e_recusado_sem_opt_in(cliente, api):
    cadastrar(cliente)
    preparar_obra(api, classificacao="erotica")
    assert salvar(cliente, 2).status_code == 404
    assert contar(cliente, Progresso) == 0
    assert contar(cliente, Obra) == 0


def test_historico_esconde_o_que_nao_pode_mais_ver(cliente, api):
    cadastrar(cliente)
    ligar_adulto(cliente)
    preparar_obra(api, classificacao="erotica")
    assert salvar(cliente, 2).status_code == 204
    assert "Obra Teste" in cliente.get("/historico").text

    cliente.post("/conta/preferencias", data={})  # desligou o +18
    assert "Obra Teste" not in cliente.get("/historico").text


def test_remover_do_historico(cliente, api):
    cadastrar(cliente)
    preparar_obra(api)
    salvar(cliente, 2)
    cliente.post(f"/historico/remover/mangadex/{OBRA}")
    assert contar(cliente, Progresso) == 0
    assert "Nada por aqui ainda" in cliente.get("/historico").text


def test_inicio_mostra_continuar_lendo(cliente, api):
    cadastrar(cliente)
    preparar_obra(api)
    salvar(cliente, 2)
    api.responder("GET", f"{API}/manga", json=lista(manga(titulo="Outra")))
    inicio = cliente.get("/")
    assert "Continuar lendo" in inicio.text
    assert f"/ler/mangadex/{CAP1}#p=2" in inicio.text


def test_favoritar_e_desfavoritar(cliente, api):
    cadastrar(cliente)
    preparar_obra(api)

    resposta = cliente.post(f"/favoritos/mangadex/{OBRA}", follow_redirects=False)
    assert resposta.status_code == 303
    assert resposta.headers["location"] == f"/obra/mangadex/{OBRA}"
    cliente.post(f"/favoritos/mangadex/{OBRA}")  # repetir não duplica
    assert contar(cliente, Favorito) == 1
    assert "Obra Teste" in cliente.get("/favoritos").text
    assert "★ Nos favoritos" in cliente.get(f"/obra/mangadex/{OBRA}").text

    cliente.post(f"/favoritos/mangadex/{OBRA}/remover")
    assert contar(cliente, Favorito) == 0
    assert "Obra Teste" not in cliente.get("/favoritos").text


def test_nao_favorita_obra_adulta_sem_opt_in(cliente, api):
    cadastrar(cliente)
    preparar_obra(api, classificacao="pornographic")
    assert cliente.post(f"/favoritos/mangadex/{OBRA}").status_code == 404
    assert contar(cliente, Favorito) == 0


def test_visitante_que_tenta_favoritar_vai_pro_login(cliente, api):
    resposta = cliente.post(f"/favoritos/mangadex/{OBRA}", follow_redirects=False)
    assert resposta.status_code == 303
    assert resposta.headers["location"].startswith("/entrar")
