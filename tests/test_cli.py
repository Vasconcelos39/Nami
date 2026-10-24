import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import cli
from app.models import Capitulo, Obra, Usuario
from app.servicos.auth import senha_confere
from tests.ajudantes import cbz_simples


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


def test_importar_pasta_e_depois_mais_capitulos(config, tmp_path, capsys):
    pasta = tmp_path / "colecao"
    pasta.mkdir()
    for nome in ("Obra v01 c10.cbz", "Obra v01 c2.cbz", "leia-me.txt"):
        (pasta / nome).write_bytes(cbz_simples(2) if nome.endswith(".cbz") else b"texto")
    cli.main(["importar", str(pasta), "--titulo", "Obra Grande", "--tipo", "manhwa"], config=config)

    engine = create_engine(config.database_url)
    with Session(engine) as db:
        obra = db.scalar(select(Obra))
        assert (obra.titulo, obra.tipo) == ("Obra Grande", "manhwa")
        assert sorted(c.numero for c in db.scalars(select(Capitulo))) == ["10", "2"]
        obra_id = obra.id_externo
    engine.dispose()
    assert f"/obra/local/{obra_id}" in capsys.readouterr().out

    extra = tmp_path / "Obra v01 c11.cbz"
    extra.write_bytes(cbz_simples(1))
    cli.main(["importar", str(extra), "--obra", obra_id], config=config)
    engine = create_engine(config.database_url)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Capitulo)) == 3
    engine.dispose()
    assert extra.exists()  # o arquivo original fica onde estava


def test_importar_caminho_que_nao_existe(config):
    with pytest.raises(SystemExit, match="Não encontrei"):
        cli.main(["importar", "nao-existe.cbz"], config=config)


def test_backup(config, capsys):
    cli.main(["backup"], config=config)
    backups = list((config.data_dir / "backups").glob("nami-*.db"))
    assert len(backups) == 1
    assert backups[0].stat().st_size > 0
