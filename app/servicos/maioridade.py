"""Verificação de idade pra ligar o conteúdo +18.

Nenhum site pequeno consegue provar a idade de alguém, mas isto deixa de ser
"marcar uma caixinha":
- a opção fica numa página própria (/conta/maioridade), com um link discreto
  no fim de "Sua conta";
- pra ligar, a pessoa digita a senha da conta, então quem pega um celular já
  logado não liga sozinho; na primeira vez, informa também a data de nascimento;
- uma data de menos de 18 anos bloqueia o +18 da conta. Tentar de novo com
  outra data não adianta: só um admin desbloqueia;
- a data de nascimento não é guardada, só o dia em que a maioridade foi confirmada.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.models import Usuario, agora
from app.servicos.auth import senha_confere

IDADE_MINIMA = 18

BLOQUEADO = "O conteúdo +18 está bloqueado nesta conta. Se acha que é engano, fale com o suporte."


class ErroDeVerificacao(Exception):
    """Algo que a pessoa precisa corrigir; a mensagem aparece na página."""


class SenhaErrada(ErroDeVerificacao):
    """Conta no mesmo limite de tentativas do login."""


def idade(nascimento: date, hoje: date) -> int:
    anos = hoje.year - nascimento.year
    if (hoje.month, hoje.day) < (nascimento.month, nascimento.day):
        anos -= 1  # ainda não fez aniversário este ano
    return anos


def _data(texto: str | None, hoje: date) -> date:
    try:
        nascimento = date.fromisoformat((texto or "").strip())
    except ValueError:
        raise ErroDeVerificacao("Informe a sua data de nascimento.") from None
    if nascimento > hoje or nascimento.year < 1900:
        raise ErroDeVerificacao("Essa data de nascimento não parece certa. Confira e tente de novo.")
    return nascimento


def ligar(db: Session, usuario: Usuario, senha: str | None, nascimento: str | None, hoje: date | None = None) -> None:
    """Liga o +18, ou levanta ErroDeVerificacao dizendo o que faltou."""
    hoje = hoje or agora().date()
    if usuario.adulto_bloqueado:
        raise ErroDeVerificacao(BLOQUEADO)
    # A senha vem antes da data: sem ela, ninguém consegue nem bloquear a conta de outra pessoa.
    if not senha_confere(usuario.senha_hash, senha or ""):
        raise SenhaErrada("Senha incorreta.")
    if usuario.maioridade_confirmada_em is None:
        if idade(_data(nascimento, hoje), hoje) < IDADE_MINIMA:
            bloquear(db, usuario)
            raise ErroDeVerificacao(
                "Pela data informada, você tem menos de 18 anos. O conteúdo +18 ficou bloqueado "
                "nesta conta; se foi engano na data, fale com o suporte."
            )
        usuario.maioridade_confirmada_em = agora()
    usuario.mostrar_adulto = True
    db.commit()


def desligar(db: Session, usuario: Usuario) -> None:
    """Desligar não pede nada: a confirmação da idade continua registrada."""
    usuario.mostrar_adulto = False
    db.commit()


def bloquear(db: Session, usuario: Usuario) -> None:
    """Desliga o +18 e impede de ligar de novo até um admin desbloquear."""
    usuario.adulto_bloqueado = True
    usuario.mostrar_adulto = False
    usuario.maioridade_confirmada_em = None
    db.commit()


def desbloquear(db: Session, usuario: Usuario) -> None:
    """A pessoa volta a poder ligar o +18, passando pela verificação desde o começo."""
    usuario.adulto_bloqueado = False
    db.commit()
