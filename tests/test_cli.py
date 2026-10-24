from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import cli
from app.models import Usuario
from app.servicos.auth import senha_confere


def usuarios(config):
    engine = create_engine(config.database_url)
    with Session(engine) as db:
        resultado = {u.username: u for u in db.scalars(select(Usuario))}
    engine.dispose()
    return resultado


def test_criar_admin(config, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "chefe")
    senhas = iter(["curta", "curta", "senha-boa-123", "senha-boa-123"])  # a primeira é recusada
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(senhas))
    cli.main(["criar-admin"], config=config)
    chefe = usuarios(config)["chefe"]
    assert chefe.is_admin
    assert senha_confere(chefe.senha_hash, "senha-boa-123")


def test_promover_e_redefinir_senha(config, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "ana")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "senha-da-ana-123")
    cli.main(["criar-admin"], config=config)
    monkeypatch.setattr("builtins.input", lambda _: "beto")
    cli.main(["criar-admin"], config=config)

    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "outra-senha-456")
    cli.main(["redefinir-senha", "beto"], config=config)
    assert senha_confere(usuarios(config)["beto"].senha_hash, "outra-senha-456")


def test_backup(config, capsys):
    cli.main(["backup"], config=config)
    backups = list((config.data_dir / "backups").glob("nami-*.db"))
    assert len(backups) == 1
    assert backups[0].stat().st_size > 0
