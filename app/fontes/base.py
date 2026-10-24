"""O contrato que toda fonte de conteúdo cumpre.

Pra adicionar uma fonte nova: criar uma classe com estes métodos, que devolva
os tipos de `app.dominio`, e registrá-la em `app/fontes/registro.py`.
"""

from collections.abc import Sequence
from typing import Protocol

from app.dominio import Capitulo, Classificacao, Filtro, Imagem, Obra, Pagina, PaginaDeResultados


class FonteIndisponivel(Exception):
    """A fonte não respondeu: fora do ar, limite de requisições, etc."""


class NaoEncontrado(Exception):
    """A obra, o capítulo ou a página não existe (ou não pode ser vista)."""


class Fonte(Protocol):
    id: str
    nome: str
    # True = o proxy guarda cópia das capas no disco (fonte remota, como o MangaDex).
    capa_em_cache: bool

    def buscar(self, filtro: Filtro, pagina: int = 1, por_pagina: int = 24) -> PaginaDeResultados:
        """Lista obras. Nunca devolve classificações fora de `filtro.classificacoes`."""
        ...

    def obra(self, obra_id: str) -> Obra: ...

    def classificacao_da_obra(self, obra_id: str) -> Classificacao:
        """O mesmo que obra(obra_id).classificacao, mas pode ser mais barato.

        O proxy de capas chama isso pra cada capa exibida.
        """
        ...

    def capitulos(self, obra_id: str, idiomas: Sequence[str]) -> list[Capitulo]:
        """Capítulos da obra nos idiomas pedidos, em ordem crescente."""
        ...

    def capitulo(self, capitulo_id: str) -> tuple[Obra, Capitulo]:
        """Um capítulo e a obra a que ele pertence."""
        ...

    def paginas(self, capitulo_id: str) -> list[Pagina]: ...

    def imagem_pagina(self, capitulo_id: str, numero: int, qualidade: str) -> Imagem: ...

    def imagem_capa(self, obra_id: str) -> Imagem | None:
        """A capa da obra, ou None se ela não tiver capa."""
        ...

    def versao_capa(self, obra_id: str) -> str | None:
        """Algo que muda quando a capa muda (ex.: o nome do arquivo na origem).

        Precisa ser barato: devolve None se não souber sem consultar a rede.
        O cache de capas usa isso pra trocar a cópia do disco quando a capa muda.
        """
        ...
