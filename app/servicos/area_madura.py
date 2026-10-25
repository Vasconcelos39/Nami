"""Área madura (/madura): o único lugar da Nami com conteúdo adulto.

- Entra quem já confirmou a idade (servicos/maioridade.py), digitando a senha
  da conta de novo: quem pega um celular já logado não entra.
- A entrada vale só pro aparelho (a sessão de login) em que a senha foi
  digitada, e fecha sozinha depois de TEMPO_SEM_USO sem abrir nenhuma página
  lá dentro. "Sair da área madura" fecha na hora; sair da conta também.
- Histórico e favoritos de obras adultas só aparecem lá dentro.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Usuario, agora
from app.servicos.auth import senha_confere, sessao_do_token
from app.servicos.maioridade import SenhaErrada
from app.servicos.visibilidade import pode_entrar_na_area_madura

TEMPO_SEM_USO = timedelta(minutes=30)


class SemAcesso(Exception):
    """A conta não tem acesso à área madura (idade não confirmada ou bloqueio)."""


def abrir(db: Session, usuario: Usuario, token: str | None) -> None:
    """Abre a área neste aparelho (a senha já foi conferida por quem chama)."""
    sessao = sessao_do_token(db, token)
    if sessao is None or sessao.usuario_id != usuario.id:
        raise SemAcesso()
    sessao.madura_ate = agora() + TEMPO_SEM_USO
    db.commit()


def entrar(db: Session, usuario: Usuario, token: str | None, senha: str | None) -> None:
    if not pode_entrar_na_area_madura(usuario):
        raise SemAcesso()
    if not senha_confere(usuario.senha_hash, senha or ""):
        raise SenhaErrada("Senha incorreta.")
    abrir(db, usuario, token)


def ativa(db: Session, usuario: Usuario | None, token: str | None, renovar: bool = False) -> bool:
    """A área está aberta neste aparelho? `renovar` empurra o prazo pra frente."""
    if not pode_entrar_na_area_madura(usuario):
        return False
    sessao = sessao_do_token(db, token)
    if sessao is None or sessao.usuario_id != usuario.id:
        return False
    if sessao.madura_ate is None or sessao.madura_ate < agora():
        return False
    if renovar:
        sessao.madura_ate = agora() + TEMPO_SEM_USO
        db.commit()
    return True


def sair(db: Session, token: str | None) -> None:
    sessao = sessao_do_token(db, token)
    if sessao is not None:
        sessao.madura_ate = None
        db.commit()
