"""Contas: senhas, sessões e proteção contra tentativas de senha em massa.

- Senhas: argon2id (o hash recomendado hoje). Nunca guardamos a senha em si.
- Sessão: o cookie leva um token aleatório; o banco guarda só o hash dele.
  Se o banco vazar, ninguém consegue usar as sessões. Desativar uma conta ou
  trocar a senha derruba as sessões na hora.
"""

import hashlib
import re
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Sessao, Usuario, agora

COOKIE_SESSAO = "nami_sessao"

USERNAME = re.compile(r"[A-Za-z0-9_.-]{3,32}")
SENHA_MINIMA = 8
SENHA_MAXIMA = 128

# Senhas que aparecem no topo das listas de senhas vazadas: são as primeiras
# que alguém tenta ao adivinhar. Com 8+ caracteres, sobram estas.
_SENHAS_COMUNS = frozenset(
    """
    12345678 123456789 1234567890 0123456789 87654321 11111111 00000000 12341234
    123123123 112233445566 password password1 password123 passw0rd senha123
    senha1234 senha12345 minhasenha qwerty123 qwertyuiop 1q2w3e4r 1q2w3e4r5t
    abc12345 abcd1234 abcdefgh asdfghjk asdf1234 iloveyou princesa princess
    admin123 administrator letmein1 welcome1 sunshine football baseball
    starwars superman dragonball onepiece naruto123 pokemon123 flamengo
    corinthians palmeiras brasil123 mudar123 trocar123 teste123 testando
    """.split()
)

_hasher = PasswordHasher()  # argon2id com os parâmetros recomendados (RFC 9106)
# Cada hash usa ~64 MB de RAM. Limitar quantos rodam ao mesmo tempo impede que
# uma enxurrada de logins derrube o Orange Pi por falta de memória.
_hashes_simultaneos = threading.BoundedSemaphore(2)


class ErroDeConta(Exception):
    """Problema que o usuário precisa corrigir; a mensagem aparece no formulário."""


class LoginNecessario(Exception):
    """A página exige login (tratado em main.py: manda pra tela de entrar)."""


# ------------------------------------------------------------------- senhas


def gerar_hash(senha: str) -> str:
    with _hashes_simultaneos:
        return _hasher.hash(senha)


def senha_confere(hash_salvo: str, senha: str) -> bool:
    with _hashes_simultaneos:
        try:
            return _hasher.verify(hash_salvo, senha)
        except (VerificationError, InvalidHashError):
            return False


# Hash de uma senha qualquer, conferido quando o usuário não existe: assim o
# login demora o mesmo tanto nos dois casos e ninguém descobre quais nomes têm conta.
_HASH_FALSO = gerar_hash(secrets.token_urlsafe(16))


def validar_username(username: str) -> str:
    username = username.strip()
    if not USERNAME.fullmatch(username):
        raise ErroDeConta("O nome de usuário precisa ter de 3 a 32 caracteres: letras, números, ponto, hífen ou _.")
    return username


def validar_senha(senha: str, username: str) -> None:
    if len(senha) < SENHA_MINIMA:
        raise ErroDeConta(f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres.")
    if len(senha) > SENHA_MAXIMA:
        raise ErroDeConta(f"A senha pode ter no máximo {SENHA_MAXIMA} caracteres.")
    if senha.lower() == username.lower():
        raise ErroDeConta("A senha não pode ser igual ao nome de usuário.")
    if senha.lower() in _SENHAS_COMUNS or len(set(senha)) == 1:
        raise ErroDeConta("Essa senha é muito comum e fácil de adivinhar. Escolha outra.")


# ------------------------------------------------------------------- contas


def criar_conta(db: Session, username: str, senha: str) -> Usuario:
    username = validar_username(username)
    validar_senha(senha, username)
    # A coluna username usa NOCASE: "Ana" e "ana" contam como o mesmo nome.
    if db.scalar(select(Usuario.id).where(Usuario.username == username)):
        raise ErroDeConta("Esse nome de usuário já está em uso.")
    usuario = Usuario(username=username, senha_hash=gerar_hash(senha))
    db.add(usuario)
    try:
        db.commit()
    except IntegrityError:  # duas pessoas pegaram o mesmo nome ao mesmo tempo
        db.rollback()
        raise ErroDeConta("Esse nome de usuário já está em uso.") from None
    return usuario


def autenticar(db: Session, username: str, senha: str) -> Usuario | None:
    """Devolve o usuário se a senha conferir; None se o nome ou a senha estiverem errados."""
    usuario = db.scalar(select(Usuario).where(Usuario.username == username.strip()))
    if usuario is None:
        senha_confere(_HASH_FALSO, senha)
        return None
    if not senha_confere(usuario.senha_hash, senha):
        return None
    if not usuario.ativo:
        raise ErroDeConta("Esta conta foi desativada. Fale com quem administra o site.")
    if _hasher.check_needs_rehash(usuario.senha_hash):  # parâmetros do argon2 mudaram
        usuario.senha_hash = gerar_hash(senha)
        db.commit()
    return usuario


def trocar_senha(db: Session, usuario: Usuario, atual: str, nova: str, token_atual: str) -> None:
    if not senha_confere(usuario.senha_hash, atual):
        raise ErroDeConta("A senha atual está errada.")
    validar_senha(nova, usuario.username)
    usuario.senha_hash = gerar_hash(nova)
    # Quem tinha a senha antiga (outro aparelho, alguém que descobriu) perde o acesso.
    db.execute(
        delete(Sessao).where(
            Sessao.usuario_id == usuario.id, Sessao.token_hash != _hash_token(token_atual)
        )
    )
    db.commit()


# ------------------------------------------------------------------ sessões


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def criar_sessao(db: Session, usuario: Usuario, dias: int) -> str:
    """Cria a sessão e devolve o token que vai no cookie."""
    token = secrets.token_urlsafe(32)
    db.execute(delete(Sessao).where(Sessao.expira_em < agora()))  # faxina das vencidas
    db.add(
        Sessao(
            token_hash=_hash_token(token),
            usuario_id=usuario.id,
            expira_em=agora() + timedelta(days=dias),
        )
    )
    db.commit()
    return token


def sessao_do_token(db: Session, token: str | None) -> Sessao | None:
    """A sessão (login) do cookie, se ainda vale."""
    if not token or len(token) > 100:
        return None
    sessao = db.get(Sessao, _hash_token(token))
    return sessao if sessao is not None and sessao.expira_em >= agora() else None


def usuario_da_sessao(db: Session, token: str | None) -> Usuario | None:
    sessao = sessao_do_token(db, token)
    if sessao is None:
        return None
    usuario = db.get(Usuario, sessao.usuario_id)
    return usuario if usuario is not None and usuario.ativo else None


def encerrar_sessao(db: Session, token: str) -> None:
    db.execute(delete(Sessao).where(Sessao.token_hash == _hash_token(token)))
    db.commit()


def encerrar_outras_sessoes(db: Session, usuario: Usuario, token_atual: str) -> int:
    """Desconecta a conta de todos os outros aparelhos. Devolve quantos eram."""
    resultado = db.execute(
        delete(Sessao).where(
            Sessao.usuario_id == usuario.id, Sessao.token_hash != _hash_token(token_atual)
        )
    )
    db.commit()
    return resultado.rowcount


# ------------------------------------------------------- limite de tentativas


class LimiteTentativas:
    """No máximo `maximo` tentativas por chave (ex.: IP) a cada `janela` segundos.

    Fica na memória do processo: reiniciar o servidor zera as contagens.
    """

    def __init__(self, maximo: int, janela: float, relogio: Callable[[], float] = time.monotonic):
        self.maximo = maximo
        self.janela = janela
        self._relogio = relogio
        self._tentativas: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def bloqueado(self, chave: str) -> bool:
        with self._lock:
            return len(self._recentes(chave)) >= self.maximo

    MAXIMO_CHAVES = 10_000  # não deixa a memória crescer sem fim (muitos IPs diferentes)

    def registrar(self, chave: str) -> None:
        with self._lock:
            self._recentes(chave).append(self._relogio())
            if len(self._tentativas) > self.MAXIMO_CHAVES:
                for outra in list(self._tentativas):
                    if not self._recentes(outra):  # já passou da janela: esquece
                        del self._tentativas[outra]
            if len(self._tentativas) > self.MAXIMO_CHAVES:  # ainda demais: esquece as mais antigas
                for outra in list(self._tentativas)[: self.MAXIMO_CHAVES // 2]:
                    del self._tentativas[outra]

    def _recentes(self, chave: str) -> deque[float]:
        fila = self._tentativas.setdefault(chave, deque())
        limite = self._relogio() - self.janela
        while fila and fila[0] <= limite:
            fila.popleft()
        return fila
