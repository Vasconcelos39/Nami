"""Testes da auditoria de segurança: limites, CSRF, CORS, erros e acessos."""

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.main import criar_app
from app.rotas import admin
from app.rotas.admin import exigir_admin
from app.servicos.auth import ErroDeConta, LimiteTentativas, validar_senha
from app.servicos.protecao import LIMITE_CORPO, LimiteDeTaxa, chave_do_cliente, limite_do_corpo
from tests.ajudantes import SENHA, cadastrar, entrar
from tests.fabrica import API, CAP1, OBRA, capitulo, feed, manga


def _pedido(ip):
    return SimpleNamespace(client=SimpleNamespace(host=ip))


# ---------------------------------------------------------- limites por IP


def test_ipv6_conta_o_bloco_inteiro():
    # Quem tem IPv6 recebe milhões de endereços: trocar de endereço não pode zerar o limite.
    a = chave_do_cliente(_pedido("2001:db8:1:2::1"))
    b = chave_do_cliente(_pedido("2001:db8:1:2:ffff::9"))
    assert a == b == "2001:db8:1:2::/64"
    assert chave_do_cliente(_pedido("2001:db8:1:3::1")) != a
    assert chave_do_cliente(_pedido("203.0.113.7")) == "203.0.113.7"
    assert chave_do_cliente(_pedido("::ffff:203.0.113.7")) == "203.0.113.7"


def _confiaveis_do_dockerfile() -> str:
    texto = (Path(__file__).parent.parent / "Dockerfile").read_text(encoding="utf-8")
    return re.search(r'FORWARDED_ALLOW_IPS="([^"]+)"', texto).group(1)


@pytest.mark.parametrize(
    ("de_onde", "encaminhado", "esperado"),
    [
        # O visitante inventa um IP; o NPM (na rede do Docker) põe o verdadeiro no fim.
        ("172.18.0.3", "1.2.3.4, 203.0.113.9", "203.0.113.9"),
        ("172.18.0.3", "203.0.113.9", "203.0.113.9"),
        # Quem fala direto com a Nami, sem passar por um proxy, não escolhe o próprio IP.
        ("203.0.113.50", "1.2.3.4", "203.0.113.50"),
    ],
)
def test_ip_real_atras_do_proxy(de_onde, encaminhado, esperado):
    vistos = []

    async def app(scope, receive, send):
        vistos.append(scope["client"][0])

    meio = ProxyHeadersMiddleware(app, trusted_hosts=_confiaveis_do_dockerfile())
    scope = {
        "type": "http",
        "scheme": "http",
        "client": (de_onde, 50000),
        "headers": [(b"x-forwarded-for", encaminhado.encode())],
    }
    asyncio.run(meio(scope, None, None))
    assert vistos == [esperado]


def test_limite_de_taxa_nao_cresce_sem_fim(monkeypatch):
    monkeypatch.setattr(LimiteDeTaxa, "MAXIMO_CHAVES", 100)
    limite = LimiteDeTaxa(por_minuto=60, relogio=lambda: 0.0)
    for i in range(1000):
        limite.esperar(f"ip-{i}")
    assert len(limite._baldes) <= 100


def test_limite_de_tentativas_nao_cresce_sem_fim(monkeypatch):
    monkeypatch.setattr(LimiteTentativas, "MAXIMO_CHAVES", 100)
    limite = LimiteTentativas(maximo=5, janela=60, relogio=lambda: 0.0)
    for i in range(1000):
        limite.registrar(f"ip-{i}")
    assert len(limite._tentativas) <= 100


def test_abrir_capitulos_tem_limite_proprio(cliente):
    codigos = [cliente.get(f"/ler/local/{'0' * 32}").status_code for _ in range(13)]
    assert codigos[:12] == [404] * 12
    assert codigos[12] == 429


# ------------------------------------------------------- tamanho do envio


def test_envio_grande_demais_e_recusado(cliente):
    resposta = cliente.post(
        "/entrar", content=b"x" * (LIMITE_CORPO + 1), headers={"content-type": "application/x-www-form-urlencoded"}
    )
    assert resposta.status_code == 413


def test_so_o_envio_de_obras_aceita_arquivos_grandes(config):
    assert limite_do_corpo("/admin/obras/nova", config) == config.upload_max_mb * 1024 * 1024
    assert limite_do_corpo("/conta/senha", config) == LIMITE_CORPO


# -------------------------------------------------------------- CSRF e CORS


@pytest.mark.parametrize(
    "cabecalhos",
    [
        {"origin": "https://outro-site.example"},
        {"origin": "null"},
        {"referer": "https://outro-site.example/pagina"},
        {"sec-fetch-site": "cross-site"},
    ],
)
def test_envio_de_outro_site_e_recusado(cliente, cabecalhos):
    resposta = cliente.post("/entrar", data={"username": "ana", "senha": SENHA}, headers=cabecalhos)
    assert resposta.status_code == 403


def test_envio_do_proprio_site_passa(cliente):
    cadastrar(cliente)
    cliente.post("/sair", follow_redirects=False)
    resposta = cliente.post(
        "/entrar",
        data={"username": "ana", "senha": SENHA},
        headers={"origin": "http://testserver", "sec-fetch-site": "same-origin"},
        follow_redirects=False,
    )
    assert resposta.status_code == 303


def test_proxy_que_tira_a_porta_do_host(cliente):
    # HTTPS numa porta que não é a 443, atrás de um proxy que repassa o Host sem porta.
    cadastrar(cliente)
    cliente.post("/sair", follow_redirects=False)
    resposta = cliente.post(
        "/entrar",
        data={"username": "ana", "senha": SENHA},
        headers={"origin": "https://testserver:8443"},
        follow_redirects=False,
    )
    assert resposta.status_code == 303
    outro = cliente.post("/entrar", data={"username": "ana", "senha": SENHA}, headers={"origin": "https://testserver.example:8443"})
    assert outro.status_code == 403


def test_sem_cors_pra_outros_sites(cliente):
    preflight = cliente.options(
        "/progresso/mangadex/x",
        headers={"origin": "https://outro-site.example", "access-control-request-method": "POST"},
    )
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in cliente.get("/busca", headers={"origin": "https://outro-site.example"}).headers


# ------------------------------------------------------------- erros e debug


def test_sem_documentacao_automatica_da_api(cliente):
    for caminho in ("/docs", "/redoc", "/openapi.json"):
        assert cliente.get(caminho).status_code == 404


def test_erro_inesperado_nao_mostra_detalhes(config, mangadex, anilist):
    app = criar_app(config, mangadex=mangadex, anilist=anilist)

    def explodir():
        raise RuntimeError("segredo interno")

    app.add_api_route("/explodir", explodir)
    with TestClient(app, raise_server_exceptions=False) as cliente:
        resposta = cliente.get("/explodir")
    assert resposta.status_code == 500
    assert "Algo deu errado" in resposta.text
    assert "segredo interno" not in resposta.text and "Traceback" not in resposta.text
    assert resposta.headers["x-frame-options"] == "DENY"


def test_cache_dos_arquivos_estaticos(cliente):
    from app.renderizar import templates

    versao = templates.env.globals["versao"]
    assert versao.startswith("0.") and "-" in versao  # versão do app + resumo dos arquivos
    com_versao = cliente.get(f"/static/css/nami.css?v={versao}")
    assert "immutable" in com_versao.headers["cache-control"]
    assert cliente.get("/static/marca/nami-onda.png").headers["cache-control"] == "no-cache"
    assert f"/static/css/nami.css?v={versao}" in cliente.get("/busca").text


def test_cabecalhos_novos(cliente):
    cabecalhos = cliente.get("/busca").headers
    assert cabecalhos["cross-origin-opener-policy"] == "same-origin"
    assert cabecalhos["cross-origin-resource-policy"] == "same-origin"
    assert "worker-src 'self'" in cabecalhos["content-security-policy"]


# ------------------------------------------------------------ acesso e login


def test_toda_rota_do_admin_exige_admin(cliente):
    assert any(d.dependency is exigir_admin for d in admin.router.dependencies)
    # Na prática: visitante vai pro login e conta comum recebe 404 em todas.
    caminhos = [
        (metodo, re.sub(r"\{[^}]+\}", "1", rota.path))
        for rota in admin.router.routes
        for metodo in rota.methods
    ]
    assert len(caminhos) > 10
    for metodo, caminho in caminhos:
        assert cliente.request(metodo, caminho, follow_redirects=False).status_code == 303, caminho
    cadastrar(cliente)
    for metodo, caminho in caminhos:
        assert cliente.request(metodo, caminho, follow_redirects=False).status_code == 404, caminho


def test_senha_comum_e_recusada():
    for senha in ("12345678", "Password1", "aaaaaaaaaa"):
        with pytest.raises(ErroDeConta):
            validar_senha(senha, "ana")
    validar_senha("cavalo-bateria-grampo", "ana")


def test_limite_de_tentativas_por_conta(cliente):
    cadastrar(cliente)
    cliente.post("/sair", follow_redirects=False)
    # Simula várias redes: o limite por IP fica alto, sobra o limite da conta.
    cliente.app.state.limite_login = LimiteTentativas(maximo=1000, janela=900)
    for _ in range(20):
        assert entrar(cliente, senha="senha-errada").status_code == 400
    assert entrar(cliente).status_code == 429  # nem a senha certa passa por 15 minutos


def test_sair_de_todos_os_outros_aparelhos(cliente):
    cadastrar(cliente)
    outro_aparelho = TestClient(cliente.app)  # outro navegador, com o cookie dele
    assert entrar(outro_aparelho).status_code == 303
    assert outro_aparelho.get("/conta", follow_redirects=False).status_code == 200

    resposta = cliente.post("/conta/sessoes", follow_redirects=False)
    assert resposta.headers["location"] == "/conta?ok=sessoes"
    assert outro_aparelho.get("/conta", follow_redirects=False).status_code == 303  # caiu
    assert cliente.get("/conta", follow_redirects=False).status_code == 200  # este continua


# ----------------------------------------------------------------------- XSS


def test_link_externo_so_aceita_http(cliente, api):
    api.responder("GET", f"{API}/manga/{OBRA}", json={"data": manga()})
    api.responder(
        "GET", f"{API}/manga/{OBRA}/feed", json=feed(capitulo(CAP1, externo="javascript:alert(1)"))
    )
    texto = cliente.get(f"/obra/mangadex/{OBRA}").text
    assert "javascript:" not in texto


def test_texto_de_usuario_e_escapado(cliente, api):
    api.responder("GET", f"{API}/manga", json={"result": "ok", "data": [], "total": 0})
    texto = cliente.get("/busca", params={"q": "<script>alert(1)</script>"}).text
    assert "<script>alert(1)</script>" not in texto
    assert "&lt;script&gt;" in texto
