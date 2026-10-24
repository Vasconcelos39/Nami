from fastapi.testclient import TestClient

from app.main import criar_app
from app.servicos.protecao import LimiteDeTaxa


class Relogio:
    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora


def test_balde_de_fichas():
    relogio = Relogio()
    limite = LimiteDeTaxa(por_minuto=60, relogio=relogio)  # 1 por segundo, rajada de 60
    assert all(limite.esperar("ip") == 0 for _ in range(60))
    assert limite.esperar("ip") > 0
    assert limite.esperar("outro-ip") == 0  # cada IP tem o seu balde
    relogio.agora += 1
    assert limite.esperar("ip") == 0


def test_limite_de_requisicoes_por_ip(config, mangadex):
    app = criar_app(config.model_copy(update={"limite_por_minuto": 3}), mangadex=mangadex)
    with TestClient(app) as cliente:
        codigos = [cliente.get("/busca").status_code for _ in range(4)]
        assert codigos == [200, 200, 200, 429]
        bloqueada = cliente.get("/busca")
        assert int(bloqueada.headers["retry-after"]) >= 1
        # arquivos estáticos e o /healthz não contam
        assert cliente.get("/static/sem-capa.svg").status_code == 200
        assert cliente.get("/healthz").status_code == 200


def test_cabecalhos_de_seguranca(cliente):
    resposta = cliente.get("/busca")
    assert "default-src 'self'" in resposta.headers["content-security-policy"]
    assert resposta.headers["x-frame-options"] == "DENY"
    assert resposta.headers["x-robots-tag"] == "noindex, nofollow"
    assert "strict-transport-security" not in resposta.headers  # só com HTTPS


def test_hsts_com_https(config, mangadex):
    app = criar_app(config.model_copy(update={"cookie_seguro": True}), mangadex=mangadex)
    with TestClient(app) as cliente:
        assert cliente.get("/busca").headers["strict-transport-security"].startswith("max-age=")


def test_robots_txt(cliente):
    assert "Disallow: /" in cliente.get("/robots.txt").text


def test_favicon_na_raiz(cliente):
    resposta = cliente.get("/favicon.ico")
    assert resposta.status_code == 200
    assert len(resposta.content) > 0


def test_capas_adultas_ficam_desfocadas_fora_da_secao_18(cliente, api):
    from tests.ajudantes import cadastrar, ligar_adulto
    from tests.fabrica import API, lista, manga

    cadastrar(cliente)
    ligar_adulto(cliente)
    api.responder("GET", f"{API}/manga", json=lista(manga(classificacao="erotica")))
    assert "capa-adulta" in cliente.get("/busca", params={"q": "x"}).text
    assert "capa-adulta" not in cliente.get("/secao/adulto").text
