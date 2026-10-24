"""Tabelas do banco (SQLAlchemy).

A Fase 1 cria o schema inteiro, mas só `fonte` tem dados. As outras tabelas
passam a ser usadas nas fases 2 (contas) e 3 (biblioteca local).
"""

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.dominio import Classificacao, Tipo


def agora() -> datetime:
    """Data e hora atuais em UTC, sem fuso (o SQLite não guarda fuso)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _valores(enum) -> str:
    return ", ".join(f"'{membro.value}'" for membro in enum)


class Fonte(Base):
    """De onde vem o conteúdo: 'mangadex' ou 'local'."""

    __tablename__ = "fonte"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    nome: Mapped[str] = mapped_column(String(100))
    ativa: Mapped[bool] = mapped_column(default=True)


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NOCASE: "Nami" e "nami" contam como o mesmo nome.
    username: Mapped[str] = mapped_column(String(32, collation="NOCASE"), unique=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(default=False)
    ativo: Mapped[bool] = mapped_column(default=True)
    maioridade_confirmada_em: Mapped[datetime | None]
    mostrar_adulto: Mapped[bool] = mapped_column(default=False)
    idioma_preferido: Mapped[str] = mapped_column(String(10), default="pt-br")
    criado_em: Mapped[datetime] = mapped_column(default=agora)


class Sessao(Base):
    """Login ativo. O cookie guarda um token aleatório; aqui fica só o hash dele."""

    __tablename__ = "sessao"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuario.id", ondelete="CASCADE"), index=True
    )
    criada_em: Mapped[datetime] = mapped_column(default=agora)
    expira_em: Mapped[datetime]


class Obra(Base):
    """Obra guardada no banco.

    Locais ficam aqui inteiras. Do MangaDex fica só uma cópia "leve", criada
    quando alguém favorita ou lê (progresso e favorito precisam apontar pra algo).
    """

    __tablename__ = "obra"
    __table_args__ = (
        UniqueConstraint("fonte_id", "id_externo"),
        CheckConstraint(f"tipo IN ({_valores(Tipo)})", name="tipo"),
        CheckConstraint(f"classificacao IN ({_valores(Classificacao)})", name="classificacao"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fonte_id: Mapped[str] = mapped_column(ForeignKey("fonte.id"))
    id_externo: Mapped[str | None] = mapped_column(String(64))  # UUID no MangaDex
    titulo: Mapped[str] = mapped_column(String(500))
    autor: Mapped[str | None] = mapped_column(String(500))
    descricao: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(10))
    classificacao: Mapped[str] = mapped_column(String(15), index=True)
    status: Mapped[str | None] = mapped_column(String(20))
    ano: Mapped[int | None]
    capa: Mapped[str | None] = mapped_column(String(500))
    criado_em: Mapped[datetime] = mapped_column(default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(default=agora, onupdate=agora)

    tags: Mapped[list["Tag"]] = relationship(secondary="obra_tag")
    capitulos: Mapped[list["Capitulo"]] = relationship(
        back_populates="obra", cascade="all, delete-orphan", passive_deletes=True
    )


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(100, collation="NOCASE"), unique=True)


class ObraTag(Base):
    __tablename__ = "obra_tag"

    obra_id: Mapped[int] = mapped_column(
        ForeignKey("obra.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True)


class Capitulo(Base):
    __tablename__ = "capitulo"
    __table_args__ = (UniqueConstraint("obra_id", "id_externo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    obra_id: Mapped[int] = mapped_column(ForeignKey("obra.id", ondelete="CASCADE"), index=True)
    id_externo: Mapped[str | None] = mapped_column(String(64))  # UUID no MangaDex
    numero: Mapped[str | None] = mapped_column(String(20))  # texto: "10.5"; vazio em oneshots
    volume: Mapped[str | None] = mapped_column(String(20))
    ordem: Mapped[float | None]  # o número como decimal, pra ordenar
    titulo: Mapped[str | None] = mapped_column(String(500))
    idioma: Mapped[str] = mapped_column(String(10))
    grupo: Mapped[str | None] = mapped_column(String(500))  # crédito do scan
    total_paginas: Mapped[int] = mapped_column(default=0)
    pasta: Mapped[str | None] = mapped_column(String(500))  # só capítulos locais
    publicado_em: Mapped[datetime | None]

    obra: Mapped[Obra] = relationship(back_populates="capitulos")


class Progresso(Base):
    """Até onde cada usuário leu cada capítulo. O histórico sai daqui também."""

    __tablename__ = "progresso"
    __table_args__ = (Index("ix_progresso_usuario_data", "usuario_id", "atualizado_em"),)

    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True
    )
    capitulo_id: Mapped[int] = mapped_column(
        ForeignKey("capitulo.id", ondelete="CASCADE"), primary_key=True
    )
    pagina: Mapped[int] = mapped_column(default=1)
    concluido: Mapped[bool] = mapped_column(default=False)
    atualizado_em: Mapped[datetime] = mapped_column(default=agora, onupdate=agora)


class Favorito(Base):
    __tablename__ = "favorito"

    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True
    )
    obra_id: Mapped[int] = mapped_column(
        ForeignKey("obra.id", ondelete="CASCADE"), primary_key=True
    )
    criado_em: Mapped[datetime] = mapped_column(default=agora)
