"""Ponto de entrada do Alembic: diz qual banco e quais tabelas usar."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401  (importar registra as tabelas no Base.metadata)
from app.config import get_config
from app.db import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configurar_log", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

url = config.get_main_option("sqlalchemy.url")
if not url:
    app_config = get_config()
    app_config.data_dir.mkdir(parents=True, exist_ok=True)
    url = app_config.database_url

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conexao:
        # render_as_batch: o SQLite não altera colunas com ALTER TABLE; o
        # Alembic recria a tabela por baixo dos panos.
        context.configure(
            connection=conexao, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
