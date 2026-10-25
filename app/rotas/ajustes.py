"""Painel de admin → Ajustes: mexer em obras do MangaDex (bloquear, classificação,
título, descrição, capa, esconder capítulos e enviar capítulos extras).

Regras em servicos/ajustes.py; quem aplica os ajustes no site é fontes/ajustes.py.
"""

import re
from contextlib import ExitStack
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import Config
from app.dependencias import obter_config, obter_db, obter_fontes
from app.dominio import Classificacao, Obra
from app.fontes.ajustes import ComAjustes
from app.fontes.base import FonteIndisponivel, NaoEncontrado
from app.fontes.registro import Registro
from app.models import CapituloExtra
from app.renderizar import NOMES_IDIOMA, render
from app.rotas.admin import exigir_admin
from app.servicos import ajustes
from app.servicos.biblioteca import ErroDeImportacao, salvar_envio

router = APIRouter(prefix="/admin/ajustes", dependencies=[Depends(exigir_admin)])

Texto = Annotated[str, Form(max_length=500)]
TextoLongo = Annotated[str, Form(max_length=25_000)]
ArquivoOpcional = Annotated[UploadFile | None, File()]
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CAPA_MAXIMA_MB = 20

MENSAGENS = {
    "salvo": "Ajustes salvos.",
    "capa": "Capa trocada.",
    "capa-original": "Voltou a capa do MangaDex.",
    "escondido": "Capítulo escondido.",
    "mostrado": "Capítulo voltou a aparecer.",
    "extra": "Capítulo extra adicionado.",
    "extra-removido": "Capítulo extra removido.",
}


def _fonte(fontes: Registro, fonte_id: str) -> ComAjustes:
    if fonte_id not in ajustes.FONTES_AJUSTAVEIS:
        raise NaoEncontrado(fonte_id)
    fonte = fontes.obter(fonte_id)
    if not isinstance(fonte, ComAjustes):
        raise NaoEncontrado(fonte_id)
    return fonte


def _original(fonte: ComAjustes, obra_id: str) -> Obra:
    """A obra como vem do MangaDex, sem ajustes (aparece mesmo se estiver bloqueada)."""
    return fonte.original.obra(obra_id)


def _endereco(fonte_id: str, obra_id: str, ok: str | None = None) -> str:
    return f"/admin/ajustes/{fonte_id}/{obra_id}" + (f"?ok={ok}" if ok else "")


# ------------------------------------------------------------------ lista


@router.get("")
def lista(request: Request, erro: str | None = None, db: Session = Depends(obter_db)):
    return render(
        request,
        "admin/ajustes.html",
        linhas=ajustes.listar(db),
        erro="Não achei um id de obra do MangaDex nesse endereço." if erro == "endereco" else None,
    )


@router.get("/abrir")
def abrir(endereco: str = ""):
    """Aceita o link da obra no MangaDex (ou só o id) e abre a página de ajustes."""
    achado = _UUID.search(endereco.lower())
    if achado is None:
        return RedirectResponse("/admin/ajustes?erro=endereco", status_code=303)
    return RedirectResponse(_endereco("mangadex", achado.group(0)), status_code=303)


# ------------------------------------------------------------- uma obra


def _pagina(request: Request, db: Session, config: Config, fonte: ComAjustes, obra_id: str, status: int = 200, **extra):
    original = _original(fonte, obra_id)
    try:
        capitulos = fonte.original.capitulos(obra_id, config.idiomas)
    except FonteIndisponivel:
        capitulos = []
    ajuste = ajustes.obter(db, fonte.id, obra_id)
    efetiva_classificacao = Classificacao(ajuste.classificacao) if ajuste and ajuste.classificacao else original.classificacao
    return render(
        request,
        "admin/ajuste.html",
        status,
        original=original,
        ajuste=ajuste,
        classificacao_efetiva=efetiva_classificacao,
        capitulos=list(reversed(capitulos)),  # mais novos primeiro
        ocultos=ajustes.ocultos(db, fonte.id, obra_id),
        extras=ajustes.extras(db, fonte.id, obra_id),
        classificacoes=[(c.value, c.rotulo) for c in Classificacao],
        idiomas=[(codigo, NOMES_IDIOMA.get(codigo, codigo)) for codigo in config.idiomas],
        capa_url=(ajuste and ajuste.capa and f"/capa/{fonte.id}/{obra_id}?v=a{int(ajuste.atualizado_em.timestamp())}")
        or original.capa_url,
        **extra,
    )


@router.get("/{fonte_id}/{obra_id}")
def pagina(
    fonte_id: str,
    obra_id: str,
    request: Request,
    ok: str | None = None,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    db: Session = Depends(obter_db),
):
    return _pagina(request, db, config, _fonte(fontes, fonte_id), obra_id, mensagem=MENSAGENS.get(ok))


@router.post("/{fonte_id}/{obra_id}")
def salvar(
    fonte_id: str,
    obra_id: str,
    request: Request,
    bloqueada: Texto = "",
    classificacao: Texto = "",
    titulo: Texto = "",
    descricao: TextoLongo = "",
    motivo: Texto = "",
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    db: Session = Depends(obter_db),
):
    fonte = _fonte(fontes, fonte_id)
    try:
        ajustes.salvar(db, _original(fonte, obra_id), bloqueada == "on", classificacao, titulo, descricao, motivo)
    except ajustes.ErroDeAjuste as erro:
        db.rollback()
        return _pagina(request, db, config, fonte, obra_id, 400, erro=str(erro))
    return RedirectResponse(_endereco(fonte_id, obra_id, "salvo"), status_code=303)


@router.post("/{fonte_id}/{obra_id}/capa")
def capa(
    fonte_id: str,
    obra_id: str,
    request: Request,
    arquivo: ArquivoOpcional = None,
    acao: Texto = "trocar",
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    db: Session = Depends(obter_db),
):
    fonte = _fonte(fontes, fonte_id)
    original = _original(fonte, obra_id)
    if acao == "original":
        ajustes.voltar_capa_original(db, config, original)
        return RedirectResponse(_endereco(fonte_id, obra_id, "capa-original"), status_code=303)
    try:
        if arquivo is None or not arquivo.filename:
            raise ajustes.ErroDeAjuste("Escolha uma imagem pra capa.")
        dados = arquivo.file.read(CAPA_MAXIMA_MB * 1024 * 1024 + 1)
        if len(dados) > CAPA_MAXIMA_MB * 1024 * 1024:
            raise ajustes.ErroDeAjuste(f"A imagem de capa pode ter no máximo {CAPA_MAXIMA_MB} MB.")
        ajustes.trocar_capa(db, config, original, dados)
    except ajustes.ErroDeAjuste as erro:
        db.rollback()
        return _pagina(request, db, config, fonte, obra_id, 400, erro_capa=str(erro))
    return RedirectResponse(_endereco(fonte_id, obra_id, "capa"), status_code=303)


@router.post("/{fonte_id}/{obra_id}/capitulos/{capitulo_id}")
def esconder(
    fonte_id: str,
    obra_id: str,
    capitulo_id: str,
    acao: Texto = "esconder",
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    db: Session = Depends(obter_db),
):
    fonte = _fonte(fontes, fonte_id)
    original = _original(fonte, obra_id)
    # Só capítulos que são mesmo desta obra (nada de guardar lixo no banco).
    if capitulo_id not in {c.id for c in fonte.original.capitulos(obra_id, config.idiomas)}:
        raise NaoEncontrado(capitulo_id)
    esconder_ = acao != "mostrar"
    ajustes.esconder_capitulo(db, original, capitulo_id, esconder_)
    return RedirectResponse(
        _endereco(fonte_id, obra_id, "escondido" if esconder_ else "mostrado") + "#capitulos", status_code=303
    )


@router.post("/{fonte_id}/{obra_id}/extras")
def adicionar_extra(
    fonte_id: str,
    obra_id: str,
    request: Request,
    arquivo: ArquivoOpcional = None,
    numero: Texto = "",
    volume: Texto = "",
    titulo: Texto = "",
    idioma: Texto = "pt-br",
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    db: Session = Depends(obter_db),
):
    fonte = _fonte(fontes, fonte_id)
    original = _original(fonte, obra_id)
    try:
        if arquivo is None or not arquivo.filename:
            raise ajustes.ErroDeAjuste("Escolha o arquivo do capítulo (.cbz ou .cbr).")
        with ExitStack() as pilha:
            try:
                caminho = salvar_envio(arquivo.file, config.dir_temporario, config.upload_max_mb)
            except ErroDeImportacao as erro:
                raise ajustes.ErroDeAjuste(str(erro)) from erro
            pilha.callback(caminho.unlink, missing_ok=True)
            ajustes.adicionar_extra(db, config, original, caminho, numero, volume, titulo, idioma)
    except ajustes.ErroDeAjuste as erro:
        db.rollback()
        return _pagina(
            request, db, config, fonte, obra_id, 400, erro_extra=str(erro),
            extra_form={"numero": numero, "volume": volume, "titulo": titulo, "idioma": idioma},
        )
    return RedirectResponse(_endereco(fonte_id, obra_id, "extra") + "#extras", status_code=303)


@router.post("/{fonte_id}/{obra_id}/extras/{extra_id}/remover")
def remover_extra(
    fonte_id: str,
    obra_id: str,
    extra_id: str,
    config: Config = Depends(obter_config),
    fontes: Registro = Depends(obter_fontes),
    db: Session = Depends(obter_db),
):
    fonte = _fonte(fontes, fonte_id)
    extra = db.get(CapituloExtra, extra_id)
    if extra is None or extra.fonte_id != fonte_id or extra.obra_id != obra_id:
        raise NaoEncontrado(extra_id)
    ajustes.remover_extra(db, config, _original(fonte, obra_id), extra)
    return RedirectResponse(_endereco(fonte_id, obra_id, "extra-removido") + "#extras", status_code=303)
