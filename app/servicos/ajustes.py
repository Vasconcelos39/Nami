"""O que os admins mudam em obras de fora (MangaDex), pelo painel.

A obra continua vindo de lá: aqui só se guarda o que muda por cima. Quem
aplica os ajustes no site é fontes/ajustes.py.
"""

from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import dominio
from app.config import Config
from app.fontes.ajustes import PREFIXO_EXTRA
from app.models import AjusteObra, Capitulo, CapituloExtra, CapituloOculto, Obra, agora
from app.servicos.biblioteca import ID_LOCAL, ErroDeImportacao, apagar_pasta, gerar_capa, importar_capitulo

FONTES_AJUSTAVEIS = ("mangadex",)  # as obras da biblioteca local os admins editam direto
TITULO_MAXIMO = 300
DESCRICAO_MAXIMA = 20_000
MOTIVO_MAXIMO = 500


class ErroDeAjuste(Exception):
    """Mensagem pra mostrar no painel."""


def obter(db: Session, fonte_id: str, obra_id: str) -> AjusteObra | None:
    return db.get(AjusteObra, (fonte_id, obra_id))


def _garantir(db: Session, original: dominio.Obra) -> AjusteObra:
    ajuste = obter(db, original.fonte, original.id)
    if ajuste is None:
        ajuste = AjusteObra(fonte_id=original.fonte, obra_id=original.id, bloqueada=False, capa=False)
        db.add(ajuste)
    ajuste.titulo_original = original.titulo[:TITULO_MAXIMO]
    ajuste.atualizado_em = agora()
    return ajuste


def _texto(valor: str | None, maximo: int, nome: str) -> str | None:
    valor = (valor or "").strip()
    if len(valor) > maximo:
        raise ErroDeAjuste(f"{nome} pode ter no máximo {maximo} caracteres.")
    return valor or None


def salvar(
    db: Session,
    original: dominio.Obra,
    bloqueada: bool,
    classificacao: str | None,
    titulo: str | None,
    descricao: str | None,
    motivo: str | None,
) -> None:
    """Campo vazio = volta a valer o que vem do MangaDex."""
    classificacao = (classificacao or "").strip() or None
    if classificacao is not None and classificacao not in {c.value for c in dominio.Classificacao}:
        raise ErroDeAjuste("Classificação inválida.")
    ajuste = _garantir(db, original)
    ajuste.bloqueada = bloqueada
    ajuste.classificacao = classificacao
    ajuste.titulo = _texto(titulo, TITULO_MAXIMO, "O título")
    ajuste.descricao = _texto(descricao, DESCRICAO_MAXIMA, "A descrição")
    ajuste.motivo = _texto(motivo, MOTIVO_MAXIMO, "A anotação")
    _sincronizar_estante(db, original, ajuste)
    _apagar_se_vazio(db, ajuste)
    db.commit()


def _sincronizar_estante(db: Session, original: dominio.Obra, ajuste: AjusteObra) -> None:
    """Histórico e favoritos usam a cópia leve da obra guardada no banco: ela
    passa a ter a classificação e o título ajustados (ex.: obra reclassificada
    como adulta sai na hora do histórico do site normal)."""
    copia = db.scalar(select(Obra).where(Obra.fonte_id == original.fonte, Obra.id_externo == original.id))
    if copia is not None:
        copia.classificacao = ajuste.classificacao or original.classificacao.value
        copia.titulo = ajuste.titulo or original.titulo


def _apagar_se_vazio(db: Session, ajuste: AjusteObra) -> None:
    """Sem nada mudado, a obra sai da lista de ajustes do painel."""
    if ajuste.bloqueada or ajuste.classificacao or ajuste.titulo or ajuste.descricao or ajuste.capa or ajuste.motivo:
        return
    db.flush()
    tem_capitulos = db.scalar(
        select(func.count()).select_from(CapituloOculto).where(
            CapituloOculto.fonte_id == ajuste.fonte_id, CapituloOculto.obra_id == ajuste.obra_id
        )
    ) or db.scalar(
        select(func.count()).select_from(CapituloExtra).where(
            CapituloExtra.fonte_id == ajuste.fonte_id, CapituloExtra.obra_id == ajuste.obra_id
        )
    )
    if not tem_capitulos:
        db.delete(ajuste)


def listar(db: Session) -> list[tuple[AjusteObra, int, int]]:
    """(ajuste, capítulos escondidos, capítulos extras), do mais recente pro mais antigo."""
    ocultos = dict(
        db.execute(
            select(CapituloOculto.obra_id, func.count()).group_by(CapituloOculto.fonte_id, CapituloOculto.obra_id)
        ).all()
    )
    extras = dict(
        db.execute(
            select(CapituloExtra.obra_id, func.count()).group_by(CapituloExtra.fonte_id, CapituloExtra.obra_id)
        ).all()
    )
    ajustes = db.scalars(select(AjusteObra).order_by(AjusteObra.atualizado_em.desc())).all()
    return [(a, ocultos.get(a.obra_id, 0), extras.get(a.obra_id, 0)) for a in ajustes]


# -------------------------------------------------------------------- capa


def _cache_da_capa(config: Config, original: dominio.Obra) -> None:
    """Apaga a cópia guardada no cache de capas: a próxima visita pega a certa."""
    for arquivo in (config.dir_cache_capas / original.fonte).glob(f"{original.id}.*"):
        arquivo.unlink(missing_ok=True)


def trocar_capa(db: Session, config: Config, original: dominio.Obra, dados: bytes) -> None:
    destino = config.dir_ajustes / "capas" / original.fonte / f"{original.id}.jpg"
    try:
        gerar_capa(dados, destino)
    except ErroDeImportacao as erro:
        raise ErroDeAjuste(str(erro)) from erro
    _garantir(db, original).capa = True
    _cache_da_capa(config, original)
    db.commit()


def voltar_capa_original(db: Session, config: Config, original: dominio.Obra) -> None:
    ajuste = obter(db, original.fonte, original.id)
    if ajuste is None:
        return
    (config.dir_ajustes / "capas" / original.fonte / f"{original.id}.jpg").unlink(missing_ok=True)
    ajuste = _garantir(db, original)
    ajuste.capa = False
    _cache_da_capa(config, original)
    _apagar_se_vazio(db, ajuste)
    db.commit()


# --------------------------------------------------------------- capítulos


def ocultos(db: Session, fonte_id: str, obra_id: str) -> set[str]:
    return set(
        db.scalars(
            select(CapituloOculto.capitulo_id).where(CapituloOculto.fonte_id == fonte_id, CapituloOculto.obra_id == obra_id)
        )
    )


def esconder_capitulo(db: Session, original: dominio.Obra, capitulo_id: str, esconder: bool) -> None:
    ajuste = _garantir(db, original)
    existente = db.get(CapituloOculto, (original.fonte, capitulo_id))
    if esconder and existente is None:
        db.add(CapituloOculto(fonte_id=original.fonte, capitulo_id=capitulo_id, obra_id=original.id))
    elif not esconder and existente is not None:
        db.delete(existente)
    _apagar_se_vazio(db, ajuste)
    db.commit()


def extras(db: Session, fonte_id: str, obra_id: str) -> list[CapituloExtra]:
    lista = db.scalars(
        select(CapituloExtra).where(CapituloExtra.fonte_id == fonte_id, CapituloExtra.obra_id == obra_id)
    ).all()
    return sorted(lista, key=lambda e: (_numero(e.numero or e.volume), e.idioma))


def _numero(texto: str | None) -> float:
    try:
        return float(texto) if texto else -1.0
    except ValueError:
        return -1.0


def _limpar_numero(valor: str | None, nome: str) -> str | None:
    """"12", "12.5" ou "12,5" -> "12" / "12.5". Vazio -> None."""
    valor = (valor or "").strip().replace(",", ".")
    if not valor:
        return None
    try:
        numero = float(valor)
    except ValueError:
        raise ErroDeAjuste(f"O número do {nome} precisa ser um número (ex.: 12 ou 12.5).") from None
    if not 0 <= numero < 100_000:
        raise ErroDeAjuste(f"O número do {nome} não parece certo.")
    return f"{numero:g}"


def adicionar_extra(
    db: Session,
    config: Config,
    original: dominio.Obra,
    arquivo: Path,
    numero: str | None,
    volume: str | None,
    titulo: str | None,
    idioma: str,
) -> CapituloExtra:
    """Importa o .cbz/.cbr e põe o capítulo na lista da obra, na ordem do número."""
    numero, volume = _limpar_numero(numero, "capítulo"), _limpar_numero(volume, "volume")
    if numero is None and volume is None:
        raise ErroDeAjuste("Informe o número do capítulo (ou do volume) pra ele entrar no lugar certo da lista.")
    if idioma not in config.idiomas:
        raise ErroDeAjuste("Idioma inválido.")
    titulo = _texto(titulo, TITULO_MAXIMO, "O título")
    pasta_da_obra = original.id.replace("-", "")
    if not ID_LOCAL.fullmatch(pasta_da_obra):
        raise ErroDeAjuste("Essa obra não aceita capítulos extras.")
    try:
        importado = importar_capitulo(arquivo, config.dir_ajustes / "extras", pasta_da_obra)
    except ErroDeImportacao as erro:
        raise ErroDeAjuste(str(erro)) from erro
    extra = CapituloExtra(
        id=importado.id,
        fonte_id=original.fonte,
        obra_id=original.id,
        numero=numero,
        volume=volume,
        titulo=titulo,
        idioma=idioma,
        total_paginas=importado.total_paginas,
        pasta=importado.pasta,
    )
    db.add(extra)
    _garantir(db, original)
    db.commit()
    return extra


def remover_extra(db: Session, config: Config, original: dominio.Obra, extra: CapituloExtra) -> None:
    apagar_pasta(config.dir_ajustes / "extras", extra.pasta)
    # O progresso de quem leu esse capítulo vai junto (o histórico não aponta pra um capítulo que sumiu).
    db.execute(
        delete(Capitulo).where(
            Capitulo.id_externo == PREFIXO_EXTRA + extra.id,
            Capitulo.obra_id.in_(
                select(Obra.id).where(Obra.fonte_id == extra.fonte_id, Obra.id_externo == extra.obra_id)
            ),
        )
    )
    db.delete(extra)
    ajuste = _garantir(db, original)
    _apagar_se_vazio(db, ajuste)
    db.commit()
