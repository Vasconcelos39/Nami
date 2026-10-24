"""Atalhos usados pelos testes de contas, estante e biblioteca."""

import io
import zipfile

from PIL import Image
from sqlalchemy import func, select

from app.models import Usuario

SENHA = "senha-da-ana-123"


def imagem(cor=(200, 40, 40), tamanho=(60, 90), formato="PNG") -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", tamanho, cor).save(saida, formato)
    return saida.getvalue()


def cbz(paginas: dict[str, bytes], comicinfo: str | None = None) -> bytes:
    """Um .cbz (ZIP) em memória com as páginas pedidas."""
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as arquivo:
        for nome, dados in paginas.items():
            arquivo.writestr(nome, dados)
        if comicinfo is not None:
            arquivo.writestr("ComicInfo.xml", comicinfo)
    return saida.getvalue()


def cbz_simples(n=3) -> bytes:
    return cbz({f"{i:02d}.png": imagem((i * 40 % 255, 80, 160)) for i in range(1, n + 1)})


def tornar_admin(cliente, username="ana"):
    with cliente.app.state.sessoes() as db:
        db.scalar(select(Usuario).where(Usuario.username == username)).is_admin = True
        db.commit()


def cadastrar(cliente, username="ana", senha=SENHA, senha2=None):
    dados = {"username": username, "senha": senha, "senha2": senha if senha2 is None else senha2}
    return cliente.post("/cadastro", data=dados, follow_redirects=False)


def entrar(cliente, username="ana", senha=SENHA, **extra):
    return cliente.post("/entrar", data={"username": username, "senha": senha, **extra}, follow_redirects=False)


def sair(cliente):
    # Sem seguir o redirecionamento: a página inicial chamaria o MangaDex.
    assert cliente.post("/sair", follow_redirects=False).status_code == 303


def ligar_adulto(cliente):
    resposta = cliente.post(
        "/conta/preferencias", data={"mostrar_adulto": "on", "confirmo_maioridade": "on"}, follow_redirects=False
    )
    assert resposta.status_code == 303


def consultar(cliente, consulta):
    """Roda uma consulta numa sessão nova do banco (vê tudo que o app já gravou)."""
    with cliente.app.state.sessoes() as sessao:
        return sessao.execute(consulta).scalars().all()


def contar(cliente, modelo) -> int:
    return consultar(cliente, select(func.count()).select_from(modelo))[0]
