"""Acervo da biblioteca local: criar, editar e remover obras e capítulos.

Usado pelo painel de admin. A parte de abrir os arquivos e extrair as
páginas fica em `biblioteca.py`; aqui é o banco de dados e as pastas.
"""

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import dominio
from app.config import Config
from app.fontes.local import FONTE_ID
from app.models import Capitulo, Obra, Tag, agora
from app.servicos.biblioteca import (
    CapituloImportado,
    ComicInfo,
    ErroDeImportacao,
    apagar_pasta,
    gerar_capa,
    importar_capitulo,
    inferir_numeros,
    novo_id,
)

STATUS = ("ongoing", "completed", "hiatus", "cancelled")


@dataclass
class Metadados:
    titulo: str = ""
    autor: str = ""
    descricao: str = ""
    tags: list[str] = field(default_factory=list)
    tipo: str = dominio.Tipo.MANGA.value
    classificacao: str = dominio.Classificacao.SAFE.value
    status: str = ""
    ano: int | None = None
    idioma: str = "pt-br"
    anilist_id: int | None = None  # preenchido ao usar os dados do AniList

    def validar(self, idiomas: list[str]) -> None:
        self.titulo = self.titulo.strip()
        if self.tipo not in {t.value for t in dominio.Tipo}:
            raise ErroDeImportacao("Tipo inválido.")
        if self.classificacao not in {c.value for c in dominio.Classificacao}:
            raise ErroDeImportacao("Classificação inválida.")
        if self.status and self.status not in STATUS:
            raise ErroDeImportacao("Status inválido.")
        if self.idioma not in idiomas:
            raise ErroDeImportacao("Idioma inválido.")
        if self.ano is not None and not 1800 < self.ano < 2200:
            raise ErroDeImportacao("Ano inválido.")
        if self.anilist_id is not None and not 0 < self.anilist_id < 10**9:
            raise ErroDeImportacao("Id do AniList inválido.")

    def completar_com(self, info: ComicInfo | None, nome_arquivo: str) -> None:
        """Preenche o que o admin deixou em branco com o ComicInfo.xml (ou o nome do arquivo)."""
        if info is not None:
            self.titulo = self.titulo or info.serie or info.titulo
            self.autor = self.autor or ", ".join(info.autores)
            self.descricao = self.descricao or info.resumo
            self.tags = self.tags or info.tags
            self.ano = self.ano or info.ano
        self.titulo = self.titulo or Path(nome_arquivo).stem.replace("_", " ").strip() or "Sem título"


@dataclass(frozen=True)
class Envio:
    """Um arquivo enviado, já salvo numa pasta temporária."""

    nome: str  # nome original (do computador de quem enviou)
    caminho: Path


def _ordem(numero: str | None, volume: str | None) -> float:
    return dominio.Capitulo(fonte=FONTE_ID, id="", obra_id="", idioma="", numero=numero, volume=volume).ordem


def _novo_capitulo(obra: Obra, importado: CapituloImportado, envio: Envio, idioma: str) -> Capitulo:
    info = importado.comicinfo
    numero, volume = inferir_numeros(envio.nome)
    titulo = None
    if info is not None:
        numero = info.numero or numero
        volume = info.volume or volume
        if info.serie and info.titulo:  # com série informada, "Title" é o título do capítulo
            titulo = info.titulo[:500]
    return Capitulo(
        obra_id=obra.id,
        id_externo=importado.id,
        numero=numero,
        volume=volume,
        ordem=_ordem(numero, volume),
        titulo=titulo,
        idioma=idioma,
        total_paginas=importado.total_paginas,
        pasta=importado.pasta,
        publicado_em=agora(),
    )


def _definir_tags(db: Session, obra: Obra, nomes: list[str]) -> None:
    tags = []
    for nome in dict.fromkeys(n.strip()[:100] for n in nomes if n.strip()):
        tag = db.scalar(select(Tag).where(Tag.nome == nome))  # NOCASE: "Ação" = "ação"
        if tag is None:
            tag = Tag(nome=nome)
            db.add(tag)
        tags.append(tag)
    obra.tags = tags


def _aplicar(db: Session, obra: Obra, metadados: Metadados) -> None:
    obra.titulo = metadados.titulo[:500]
    obra.autor = metadados.autor.strip()[:500] or None
    obra.descricao = metadados.descricao.strip() or None
    obra.tipo = metadados.tipo
    obra.classificacao = metadados.classificacao
    obra.status = metadados.status or None
    obra.ano = metadados.ano
    obra.anilist_id = metadados.anilist_id
    obra.atualizado_em = agora()
    _definir_tags(db, obra, metadados.tags)


def criar_obra(
    db: Session, config: Config, metadados: Metadados, envios: list[Envio], capa: bytes | None = None
) -> tuple[Obra, int]:
    """Cria a obra com um capítulo por arquivo enviado. Devolve (obra, nº de capítulos)."""
    if not envios:
        raise ErroDeImportacao("Escolha pelo menos um arquivo .cbz ou .cbr.")
    metadados.validar(config.idiomas)
    obra_id = novo_id()
    try:
        importados = [importar_capitulo(e.caminho, config.dir_biblioteca, obra_id) for e in envios]
        metadados.completar_com(importados[0].comicinfo, envios[0].nome)
        gerar_capa(capa or importados[0].primeira_pagina, config.dir_biblioteca / obra_id / "capa.jpg")

        obra = Obra(fonte_id=FONTE_ID, id_externo=obra_id, titulo="", tipo="", classificacao="")
        _aplicar(db, obra, metadados)
        obra.capa = f"/capa/{FONTE_ID}/{obra_id}"
        db.add(obra)
        db.flush()  # gera obra.id pros capítulos
        db.add_all(_novo_capitulo(obra, i, e, metadados.idioma) for i, e in zip(importados, envios))
        db.commit()
    except BaseException:
        db.rollback()
        apagar_pasta(config.dir_biblioteca, obra_id)
        raise
    return obra, len(importados)


def adicionar_capitulos(db: Session, config: Config, obra: Obra, envios: list[Envio], idioma: str) -> int:
    if not envios:
        raise ErroDeImportacao("Escolha pelo menos um arquivo .cbz ou .cbr.")
    if idioma not in config.idiomas:
        raise ErroDeImportacao("Idioma inválido.")
    importados: list[CapituloImportado] = []
    try:
        for envio in envios:
            importados.append(importar_capitulo(envio.caminho, config.dir_biblioteca, obra.id_externo))
        db.add_all(_novo_capitulo(obra, i, e, idioma) for i, e in zip(importados, envios))
        obra.atualizado_em = agora()
        db.commit()
    except BaseException:
        db.rollback()
        for importado in importados:
            apagar_pasta(config.dir_biblioteca, importado.pasta)
        raise
    return len(importados)


def atualizar_obra(db: Session, config: Config, obra: Obra, metadados: Metadados, capa: bytes | None) -> None:
    metadados.validar(config.idiomas)
    if not metadados.titulo:
        raise ErroDeImportacao("O título não pode ficar vazio.")
    if capa:
        gerar_capa(capa, config.dir_biblioteca / obra.id_externo / "capa.jpg")
    _aplicar(db, obra, metadados)
    db.commit()


def atualizar_capitulo(db: Session, capitulo: Capitulo, numero: str, volume: str, titulo: str) -> None:
    capitulo.numero = numero.strip()[:20] or None
    capitulo.volume = volume.strip()[:20] or None
    capitulo.titulo = titulo.strip()[:500] or None
    capitulo.ordem = _ordem(capitulo.numero, capitulo.volume)
    db.commit()


def remover_capitulo(db: Session, config: Config, capitulo: Capitulo) -> None:
    pasta = capitulo.pasta
    db.delete(capitulo)  # o progresso de leitura desse capítulo vai junto (cascade)
    db.commit()
    if pasta:
        apagar_pasta(config.dir_biblioteca, pasta)


def remover_obra(db: Session, config: Config, obra: Obra) -> None:
    obra_id = obra.id_externo
    db.delete(obra)  # capítulos, progresso e favoritos vão junto (cascade)
    db.commit()
    apagar_pasta(config.dir_biblioteca, obra_id)


def obra_local(db: Session, obra_id: str) -> Obra | None:
    return db.scalar(select(Obra).where(Obra.fonte_id == FONTE_ID, Obra.id_externo == obra_id))
