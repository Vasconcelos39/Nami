"""Uma fonte de fora (o MangaDex) com o que os admins mudaram por cima.

Cumpre o mesmo contrato de fontes/base.py e repassa tudo pra fonte original,
aplicando os ajustes guardados no banco (models.AjusteObra e companhia):
- obra bloqueada some do site inteiro (listagens, página, leitor, imagens);
- classificação, título e descrição trocados;
- capa trocada (arquivo em data/ajustes/capas/);
- capítulos escondidos somem da lista e do leitor;
- capítulos extras (enviados pelo admin) entram na lista, na ordem do número.

Classificação trocada vale em toda checagem, mas as listagens vêm do MangaDex
já filtradas pela classificação de lá: uma obra "livre" reclassificada como
adulta sai do site normal, mas não passa a aparecer nas listagens da área
madura (dá pra chegar nela pelo link, pelo histórico ou pelos favoritos).

Os ajustes ficam numa cópia em memória: toda capa e toda página passam por
aqui, e consultar o banco a cada uma pesava (e chegou a esgotar as conexões).
Quem grava um ajuste chama `invalidar()` (rotas/ajustes.py), e a próxima
consulta relê tudo. A cópia é do processo: a Nami roda com um worker só.
"""

import threading
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Config
from app.dominio import Capitulo, Classificacao, Filtro, Imagem, Obra, Pagina, PaginaDeResultados
from app.fontes.base import Fonte, NaoEncontrado
from app.models import AjusteObra, CapituloExtra, CapituloOculto
from app.servicos.biblioteca import TIPO_POR_EXTENSAO

PREFIXO_EXTRA = "extra-"  # capítulo extra: "extra-<id>" (os do MangaDex são UUIDs com traço)
GRUPO_EXTRA = "Adicionado pelo admin"


def id_do_extra(capitulo_id: str) -> str | None:
    """"extra-<hex>" -> "<hex>"; qualquer outro id -> None."""
    if not capitulo_id.startswith(PREFIXO_EXTRA):
        return None
    resto = capitulo_id.removeprefix(PREFIXO_EXTRA)
    return resto if len(resto) == 32 and all(c in "0123456789abcdef" for c in resto) else None


@dataclass
class _Copia:
    """Tudo o que os admins mudaram nesta fonte, lido do banco de uma vez."""

    ajustes: dict[str, AjusteObra] = field(default_factory=dict)  # obra -> ajuste
    ocultos: set[str] = field(default_factory=set)  # capítulos escondidos
    extras: dict[str, CapituloExtra] = field(default_factory=dict)  # id -> capítulo extra
    extras_da_obra: dict[str, list[CapituloExtra]] = field(default_factory=dict)


class ComAjustes:
    def __init__(self, original: Fonte, sessoes: sessionmaker[Session], config: Config):
        self.original = original
        self.id = original.id
        self.nome = original.nome
        self.capa_em_cache = original.capa_em_cache
        self.sessoes = sessoes
        self.pasta_capas = config.dir_ajustes / "capas" / original.id
        self.pasta_extras = config.dir_ajustes / "extras"
        self._copia: _Copia | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------- consultas

    def invalidar(self) -> None:
        """Um admin gravou um ajuste: a próxima consulta relê do banco."""
        # O lock espera uma leitura em andamento acabar, senão ela guardaria a cópia velha.
        with self._lock:
            self._copia = None

    def _atual(self) -> _Copia:
        with self._lock:
            if self._copia is None:
                self._copia = self._ler_do_banco()
            return self._copia

    def _ler_do_banco(self) -> _Copia:
        copia = _Copia()
        with self.sessoes() as db:
            for ajuste in db.scalars(select(AjusteObra).where(AjusteObra.fonte_id == self.id)):
                copia.ajustes[ajuste.obra_id] = ajuste
            copia.ocultos = set(
                db.scalars(select(CapituloOculto.capitulo_id).where(CapituloOculto.fonte_id == self.id))
            )
            for extra in db.scalars(select(CapituloExtra).where(CapituloExtra.fonte_id == self.id)):
                copia.extras[extra.id] = extra
                copia.extras_da_obra.setdefault(extra.obra_id, []).append(extra)
        return copia

    def _ajuste(self, obra_id: str) -> AjusteObra | None:
        return self._atual().ajustes.get(obra_id)

    def _extra(self, capitulo_id: str) -> CapituloExtra:
        extra_id = id_do_extra(capitulo_id)
        extra = self._atual().extras.get(extra_id) if extra_id else None
        if extra is None:
            raise NaoEncontrado(capitulo_id)
        return extra

    def _aplicar(self, obra: Obra, ajuste: AjusteObra | None) -> Obra | None:
        """A obra com os ajustes; None se ela estiver bloqueada."""
        if ajuste is None:
            return obra
        if ajuste.bloqueada:
            return None
        mudancas = {}
        if ajuste.classificacao:
            mudancas["classificacao"] = Classificacao(ajuste.classificacao)
        if ajuste.titulo:
            mudancas["titulo"] = ajuste.titulo
        if ajuste.descricao:
            mudancas["descricao"] = ajuste.descricao
        if ajuste.capa:
            # O ?v= muda a cada ajuste: o navegador não fica com a capa antiga guardada.
            mudancas["capa_url"] = f"/capa/{self.id}/{obra.id}?v=a{int(ajuste.atualizado_em.timestamp())}"
        return replace(obra, **mudancas) if mudancas else obra

    def _capitulo_extra(self, extra: CapituloExtra) -> Capitulo:
        return Capitulo(
            fonte=self.id,
            id=PREFIXO_EXTRA + extra.id,
            obra_id=extra.obra_id,
            idioma=extra.idioma,
            numero=extra.numero,
            volume=extra.volume,
            titulo=extra.titulo,
            grupos=(GRUPO_EXTRA,),
            total_paginas=extra.total_paginas,
            publicado_em=extra.criado_em,
        )

    # --------------------------------------------------------------- obras

    def buscar(self, filtro: Filtro, pagina: int = 1, por_pagina: int = 24) -> PaginaDeResultados:
        resultado = self.original.buscar(filtro, pagina, por_pagina)
        copia = self._atual()
        if not any(o.id in copia.ajustes or o.id in copia.extras_da_obra for o in resultado.obras):
            return resultado
        obras = []
        for obra in resultado.obras:
            ajustada = self._aplicar(obra, copia.ajustes.get(obra.id))
            # Bloqueada, ou reclassificada pra fora do que foi pedido: sai da lista.
            if ajustada is None or ajustada.classificacao not in filtro.classificacoes:
                continue
            if ajustada.id in copia.extras_da_obra and ajustada.so_fora:
                ajustada = replace(ajustada, so_fora=False)  # os extras dá pra ler aqui
            obras.append(ajustada)
        return replace(resultado, obras=obras)

    def obra(self, obra_id: str) -> Obra:
        obra = self._aplicar(self.original.obra(obra_id), self._ajuste(obra_id))
        if obra is None:
            raise NaoEncontrado(obra_id)
        return obra

    def classificacao_da_obra(self, obra_id: str) -> Classificacao:
        ajuste = self._ajuste(obra_id)
        if ajuste is not None and ajuste.bloqueada:
            raise NaoEncontrado(obra_id)
        if ajuste is not None and ajuste.classificacao:
            return Classificacao(ajuste.classificacao)
        return self.original.classificacao_da_obra(obra_id)

    # ----------------------------------------------------------- capítulos

    def capitulos(self, obra_id: str, idiomas: Sequence[str]) -> list[Capitulo]:
        capitulos = self.original.capitulos(obra_id, idiomas)
        copia = self._atual()
        extras = [e for e in copia.extras_da_obra.get(obra_id, []) if e.idioma in idiomas]
        lista = [c for c in capitulos if c.id not in copia.ocultos] + [self._capitulo_extra(e) for e in extras]
        return sorted(lista, key=lambda c: (c.ordem, c.idioma))

    def capitulo(self, capitulo_id: str) -> tuple[Obra, Capitulo]:
        if capitulo_id.startswith(PREFIXO_EXTRA):
            extra = self._extra(capitulo_id)
            return self.obra(extra.obra_id), self._capitulo_extra(extra)
        if capitulo_id in self._atual().ocultos:
            raise NaoEncontrado(capitulo_id)
        obra, capitulo = self.original.capitulo(capitulo_id)
        ajustada = self._aplicar(obra, self._ajuste(obra.id))
        if ajustada is None:
            raise NaoEncontrado(capitulo_id)
        return ajustada, capitulo

    # -------------------------------------------------------------- imagens

    def paginas(self, capitulo_id: str) -> list[Pagina]:
        if capitulo_id.startswith(PREFIXO_EXTRA):
            total = self._extra(capitulo_id).total_paginas
            return [Pagina(n, f"/img/{self.id}/{capitulo_id}/{n}") for n in range(1, total + 1)]
        return self.original.paginas(capitulo_id)

    def imagem_pagina(self, capitulo_id: str, numero: int, qualidade: str) -> Imagem:
        if not capitulo_id.startswith(PREFIXO_EXTRA):
            return self.original.imagem_pagina(capitulo_id, numero, qualidade)
        extra = self._extra(capitulo_id)  # a qualidade não muda nada: a imagem já está no disco
        if not 1 <= numero <= extra.total_paginas:
            raise NaoEncontrado(f"página {numero}")
        arquivo = next((self.pasta_extras / extra.pasta).glob(f"{numero:04d}.*"), None)
        if arquivo is None or arquivo.suffix not in TIPO_POR_EXTENSAO:
            raise NaoEncontrado(f"página {numero}")
        return Imagem(arquivo.read_bytes(), TIPO_POR_EXTENSAO[arquivo.suffix])

    def arquivo_capa(self, obra_id: str) -> Path:
        return self.pasta_capas / f"{obra_id}.jpg"

    def imagem_capa(self, obra_id: str) -> Imagem | None:
        ajuste = self._ajuste(obra_id)
        if ajuste is not None and ajuste.capa and self.arquivo_capa(obra_id).exists():
            return Imagem(self.arquivo_capa(obra_id).read_bytes(), "image/jpeg")
        return self.original.imagem_capa(obra_id)

    def versao_capa(self, obra_id: str) -> str | None:
        ajuste = self._ajuste(obra_id)
        if ajuste is not None and ajuste.capa and self.arquivo_capa(obra_id).exists():
            return f"a{self.arquivo_capa(obra_id).stat().st_mtime_ns}"
        return self.original.versao_capa(obra_id)

    def encerrar(self) -> None:
        self.original.encerrar()
