"""Comandos de terminal da Nami.

    python -m app.cli criar-admin            cria uma conta de admin (pergunta nome e senha)
    python -m app.cli promover NOME          transforma uma conta existente em admin
    python -m app.cli redefinir-senha NOME   define uma senha nova pra uma conta
    python -m app.cli backup                 copia o banco pra data/backups/
    python -m app.cli importar CAMINHO...    adiciona .cbz/.cbr à biblioteca local
        [--titulo T] [--tipo manga|manhwa|manhua|hq] [--classificacao safe|...]
        [--idioma pt-br] [--obra ID]  (com --obra, os capítulos entram numa obra que já existe)

No Docker, coloque "docker compose exec nami" antes. Ex.:
    docker compose exec nami python -m app.cli criar-admin

"importar" serve pra arquivos grandes demais pro envio pelo site (pelo
Cloudflare Tunnel, a Cloudflare recusa envios acima de 100 MB) ou pra uma
coleção inteira de uma vez: CAMINHO pode ser uma pasta, e aí entram todos os
.cbz/.cbr dela, em ordem de nome.

Por que um comando e não "o primeiro cadastro vira admin"? Num servidor
aberto na internet, qualquer pessoa poderia se cadastrar antes de você.
"""

import argparse
import getpass
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Config, get_config
from app.db import aplicar_migracoes, criar_engine
from app.dominio import Classificacao, Tipo
from app.models import Sessao, Usuario
from app.servicos import acervo
from app.servicos.auth import ErroDeConta, criar_conta, gerar_hash, validar_senha
from app.servicos.biblioteca import ErroDeImportacao, ordem_natural


def _pedir_senha(username: str) -> str:
    while True:
        senha = getpass.getpass("Senha: ")
        if getpass.getpass("Repita a senha: ") != senha:
            print("As senhas não são iguais. Tente de novo.")
            continue
        try:
            validar_senha(senha, username)
        except ErroDeConta as erro:
            print(erro)
            continue
        return senha


def _usuario(db: Session, username: str) -> Usuario:
    usuario = db.scalar(select(Usuario).where(Usuario.username == username))
    if usuario is None:
        raise SystemExit(f"Não existe conta com o nome {username!r}.")
    return usuario


def criar_admin(db: Session) -> None:
    username = input("Nome de usuário do admin: ").strip()
    try:
        usuario = criar_conta(db, username, _pedir_senha(username))
    except ErroDeConta as erro:
        raise SystemExit(str(erro)) from None
    usuario.is_admin = True
    db.commit()
    print(f"Pronto: {usuario.username} é admin. Entre no site e abra /admin.")


def promover(db: Session, username: str) -> None:
    usuario = _usuario(db, username)
    usuario.is_admin = True
    usuario.ativo = True
    db.commit()
    print(f"Pronto: {usuario.username} agora é admin.")


def redefinir_senha(db: Session, username: str) -> None:
    usuario = _usuario(db, username)
    usuario.senha_hash = gerar_hash(_pedir_senha(usuario.username))
    db.execute(delete(Sessao).where(Sessao.usuario_id == usuario.id))  # desconecta
    db.commit()
    print(f"Senha de {usuario.username} trocada.")


def backup(config: Config) -> None:
    """Cópia consistente do banco (funciona com o site no ar)."""
    pasta = config.data_dir / "backups"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"nami-{datetime.now():%Y%m%d-%H%M%S}.db"
    # closing(): o "with" do sqlite3 sozinho não fecha a conexão.
    with closing(sqlite3.connect(config.data_dir / "nami.db")) as origem, closing(sqlite3.connect(destino)) as copia:
        origem.backup(copia)
    print(f"Backup salvo em {destino}")


EXTENSOES_IMPORTAVEIS = {".cbz", ".cbr", ".zip", ".rar"}


def _arquivos(caminhos: list[str]) -> list[Path]:
    encontrados = []
    for texto in caminhos:
        caminho = Path(texto)
        if caminho.is_dir():
            dentro = [p for p in caminho.iterdir() if p.is_file() and p.suffix.lower() in EXTENSOES_IMPORTAVEIS]
            encontrados += sorted(dentro, key=lambda p: ordem_natural(p.name))
        elif caminho.is_file():
            encontrados.append(caminho)
        else:
            raise SystemExit(f"Não encontrei {texto!r}.")
    if not encontrados:
        raise SystemExit("Nenhum arquivo .cbz ou .cbr encontrado.")
    return encontrados


def importar(db: Session, config: Config, args: argparse.Namespace) -> None:
    envios = [acervo.Envio(p.name, p) for p in _arquivos(args.caminhos)]
    print(f"Importando {len(envios)} arquivo(s). Volumes grandes podem levar alguns minutos…")
    try:
        if args.obra:
            obra = acervo.obra_local(db, args.obra)
            if obra is None:
                raise SystemExit(f"Não existe obra local com o id {args.obra!r}.")
            acervo.adicionar_capitulos(db, config, obra, envios, args.idioma)
        else:
            metadados = acervo.Metadados(
                titulo=args.titulo or "", tipo=args.tipo, classificacao=args.classificacao, idioma=args.idioma
            )
            obra, _ = acervo.criar_obra(db, config, metadados, envios)
    except ErroDeImportacao as erro:
        raise SystemExit(str(erro)) from None
    print(f"Pronto: {obra.titulo} — no site em /obra/local/{obra.id_externo}")


def main(argumentos: list[str] | None = None, config: Config | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Comandos da Nami")
    comandos = parser.add_subparsers(dest="comando", required=True)
    comandos.add_parser("criar-admin", help="cria uma conta de admin")
    comandos.add_parser("promover", help="transforma uma conta em admin").add_argument("username")
    comandos.add_parser("redefinir-senha", help="define uma senha nova").add_argument("username")
    comandos.add_parser("backup", help="copia o banco pra data/backups/")
    imp = comandos.add_parser("importar", help="adiciona .cbz/.cbr à biblioteca local")
    imp.add_argument("caminhos", nargs="+", help="arquivos .cbz/.cbr ou pastas com eles")
    imp.add_argument("--titulo", help="título da obra (sem isso: ComicInfo.xml ou nome do arquivo)")
    imp.add_argument("--tipo", default="manga", choices=[t.value for t in Tipo])
    imp.add_argument("--classificacao", default="safe", choices=[c.value for c in Classificacao])
    imp.add_argument("--idioma", default=None, help="idioma dos capítulos (padrão: o primeiro configurado)")
    imp.add_argument("--obra", help="id de uma obra local que já existe (aparece no endereço dela)")
    args = parser.parse_args(argumentos)

    config = config or get_config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    aplicar_migracoes(config.database_url)
    if args.comando == "backup":
        backup(config)
        return
    engine = criar_engine(config.database_url)
    try:
        with sessionmaker(engine)() as db:
            if args.comando == "criar-admin":
                criar_admin(db)
            elif args.comando == "promover":
                promover(db, args.username)
            elif args.comando == "importar":
                args.idioma = args.idioma or config.idiomas[0]
                importar(db, config, args)
            else:
                redefinir_senha(db, args.username)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main(sys.argv[1:])
