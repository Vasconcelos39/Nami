"""Quais fontes estão ligadas na Nami."""

from collections.abc import Iterator

from sqlalchemy.orm import Session, sessionmaker

from app.config import Config
from app.fontes.ajustes import ComAjustes
from app.fontes.base import Fonte, NaoEncontrado
from app.fontes.local import BibliotecaLocal
from app.fontes.mangadex import MangaDex


class Registro:
    def __init__(self, fontes: list[Fonte]):
        self._fontes = {fonte.id: fonte for fonte in fontes}

    def obter(self, fonte_id: str) -> Fonte:
        try:
            return self._fontes[fonte_id]
        except KeyError:
            raise NaoEncontrado(fonte_id) from None

    def __iter__(self) -> Iterator[Fonte]:
        return iter(self._fontes.values())


def criar_registro(
    config: Config, sessoes: sessionmaker[Session], mangadex: MangaDex | None = None
) -> Registro:
    # `mangadex` existe pros testes trocarem o MangaDex de verdade por um simulado.
    # As obras do MangaDex passam pelos ajustes dos admins (fontes/ajustes.py);
    # as da biblioteca local os admins editam direto.
    return Registro([ComAjustes(mangadex or MangaDex(config), sessoes, config), BibliotecaLocal(config, sessoes)])
