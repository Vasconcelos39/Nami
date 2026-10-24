"""Conexão com o banco SQLite."""

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

from app.config import RAIZ_PROJETO

# Nomes previsíveis para índices e restrições: o Alembic precisa disso pra
# conseguir alterar tabelas no SQLite em migrations futuras.
_NOMES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_NOMES)


def criar_engine(url: str) -> Engine:
    # check_same_thread=False: o FastAPI atende cada requisição numa thread.
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _configurar_sqlite(conexao, _registro):
        cursor = conexao.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")  # sem isso o SQLite ignora chaves estrangeiras
        cursor.execute("PRAGMA journal_mode=WAL")  # leituras não travam enquanto alguém grava
        cursor.close()

    return engine


def aplicar_migracoes(url: str) -> None:
    """Cria/atualiza as tabelas rodando as migrations do Alembic (pasta migrations/)."""
    from alembic import command
    from alembic.config import Config as ConfigAlembic

    cfg = ConfigAlembic(str(RAIZ_PROJETO / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ_PROJETO / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configurar_log"] = False  # quem configura o log é o uvicorn
    command.upgrade(cfg, "head")
