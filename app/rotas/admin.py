"""Painel de admin: biblioteca local (.cbz/.cbr) e usuários.

Só quem tem `is_admin` entra. Pra qualquer outra pessoa logada, estas páginas
respondem 404, como se não existissem.
"""

import secrets
from contextlib import ExitStack
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.catalogos.anilist import AniList, FichaAniList
from app.config import Config
from app.dependencias import exigir_login, obter_anilist, obter_config, obter_db, obter_fontes
from app.dominio import Classificacao, Filtro, Tipo
from app.fontes.base import FonteIndisponivel, NaoEncontrado
from app.fontes.local import FONTE_ID
from app.fontes.registro import Registro
from app.models import Capitulo, Favorito, Noticia, Obra, Progresso, Reporte, Sessao, Ticket, Usuario, agora
from app.renderizar import NOMES_IDIOMA, NOMES_STATUS, render
from app.servicos import acervo, maioridade, noticias, reportes, suporte
from app.servicos.auth import gerar_hash
from app.servicos.biblioteca import ErroDeImportacao, salvar_envio

def exigir_admin(usuario: Usuario = Depends(exigir_login)) -> Usuario:
    if not usuario.is_admin:
        raise NaoEncontrado("admin")
    return usuario


# A checagem vale pro router inteiro: uma rota nova aqui nunca fica aberta por
# esquecimento. (As rotas que usam o admin logado pedem de novo; o FastAPI
# reaproveita o resultado, então a checagem roda uma vez só.)
router = APIRouter(prefix="/admin", dependencies=[Depends(exigir_admin)])

Texto = Annotated[str, Form(max_length=500)]
TextoLongo = Annotated[str, Form(max_length=20_000)]
Arquivos = Annotated[list[UploadFile], File()]
ArquivoOpcional = Annotated[UploadFile | None, File()]

MENSAGENS = {
    "criada": "Obra criada.",
    "salva": "Alterações salvas.",
    "capitulos": "Capítulos adicionados.",
    "capitulo": "Capítulo atualizado.",
    "capitulo-removido": "Capítulo removido.",
    "removida": "Obra removida da biblioteca.",
    "promovido": "Agora essa conta é admin.",
    "rebaixado": "Essa conta deixou de ser admin.",
    "desativado": "Conta desativada. A pessoa foi desconectada.",
    "reativado": "Conta reativada.",
    "desconectado": "A conta foi desconectada de todos os aparelhos.",
    "adulto-bloqueado": "+18 bloqueado nesta conta. A pessoa não consegue ligar de novo.",
    "adulto-desbloqueado": "+18 desbloqueado. Pra ligar, a pessoa passa pela verificação de idade de novo.",
    "noticia-rascunho": "Rascunho salvo. Só os admins veem até você publicar.",
    "noticia-publicada": "Publicada! Quem tem conta vê a bolinha em “Novidades” no menu.",
    "noticia-apagada": "Novidade apagada.",
    "resolvido": "Reporte marcado como resolvido.",
    "reaberto": "Reporte reaberto.",
}


def _opcoes(config: Config) -> dict:
    """Listas dos <select> do formulário de obra."""
    return {
        "tipos": [(t.value, t.rotulo) for t in Tipo],
        "classificacoes": [(c.value, c.rotulo) for c in Classificacao],
        "opcoes_status": [("", "—")] + [(s, NOMES_STATUS[s]) for s in acervo.STATUS],
        "idiomas": [(i, NOMES_IDIOMA.get(i, i)) for i in config.idiomas],
    }


def _metadados(
    titulo, autor, descricao, tags, tipo, classificacao, status, ano, idioma, anilist_id=""
) -> acervo.Metadados:
    return acervo.Metadados(
        titulo=titulo,
        autor=autor,
        descricao=descricao,
        tags=[t for t in tags.split(",") if t.strip()],
        tipo=tipo,
        classificacao=classificacao,
        status=status,
        ano=int(ano) if ano.strip().isdigit() else None,
        idioma=idioma,
        anilist_id=_id_anilist(anilist_id),
    )


def _id_anilist(valor: str) -> int | None:
    """Aceita o número ou o link da obra (https://anilist.co/manga/30013/...)."""
    valor = valor.strip()
    if "anilist.co/manga/" in valor:
        valor = valor.split("anilist.co/manga/", 1)[1].split("/", 1)[0]
    return int(valor) if valor.isdigit() and len(valor) < 10 else None


def _enviados(pilha: ExitStack, arquivos: list[UploadFile], config: Config) -> list[acervo.Envio]:
    """Salva os arquivos enviados numa pasta temporária (apagada no fim da requisição)."""
    envios = []
    for arquivo in arquivos:
        if not arquivo.filename:  # campo de arquivo vazio
            continue
        caminho = salvar_envio(arquivo.file, config.dir_temporario, config.upload_max_mb)
        pilha.callback(caminho.unlink, missing_ok=True)
        envios.append(acervo.Envio(arquivo.filename, caminho))
    return envios


def _capa(arquivo: UploadFile | None) -> bytes | None:
    if arquivo is None or not arquivo.filename:
        return None
    dados = arquivo.file.read(20 * 1024 * 1024 + 1)
    if len(dados) > 20 * 1024 * 1024:
        raise ErroDeImportacao("A imagem de capa pode ter no máximo 20 MB.")
    return dados


def _obra_ou_404(db: Session, obra_id: str) -> Obra:
    obra = acervo.obra_local(db, obra_id)
    if obra is None:
        raise NaoEncontrado(obra_id)
    return obra


# ---------------------------------------------------------------- painel


@router.get("")
def painel(request: Request, _admin: Usuario = Depends(exigir_admin), db: Session = Depends(obter_db)):
    contagem = {
        "obras": db.scalar(select(func.count()).select_from(Obra).where(Obra.fonte_id == FONTE_ID)),
        "capitulos": db.scalar(
            select(func.count()).select_from(Capitulo).join(Obra).where(Obra.fonte_id == FONTE_ID)
        ),
        "usuarios": db.scalar(select(func.count()).select_from(Usuario)),
        "reportes": reportes.abertos(db),
    }
    return render(request, "admin/painel.html", contagem=contagem)


# ---------------------------------------------------------------- suporte


ABAS_SUPORTE = [("aberto", "Esperando resposta"), ("respondido", "Respondidos"), ("fechado", "Fechados")]


@router.get("/suporte")
def tickets(
    request: Request,
    status: str = "aberto",
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    if status not in dict(ABAS_SUPORTE):
        status = "aberto"
    return render(
        request,
        "admin/suporte.html",
        tickets=suporte.para_o_suporte(db, status),
        situacao=status,  # ("status" é o código HTTP no render)
        abas=ABAS_SUPORTE,
        contagem={valor: suporte.contar(db, valor) for valor, _ in ABAS_SUPORTE},
    )


# --------------------------------------------------------------- reportes


@router.get("/reportes")
def lista_reportes(
    request: Request,
    resolvidos: bool = False,
    ok: str | None = None,
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    return render(
        request,
        "admin/reportes.html",
        lista=reportes.listar(db, resolvidos),
        resolvidos=resolvidos,
        motivos=reportes.MOTIVOS,
        mensagem=MENSAGENS.get(ok),
    )


@router.post("/reportes/{reporte_id}")
def marcar_reporte(
    reporte_id: int,
    acao: Texto,
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    reporte = db.get(Reporte, reporte_id)
    if reporte is None:
        raise NaoEncontrado(str(reporte_id))
    resolver = acao == "resolver"
    reportes.marcar(db, reporte, resolver)
    # Volta pra lista de onde a pessoa veio.
    destino = "/admin/reportes?ok=resolvido" if resolver else "/admin/reportes?resolvidos=1&ok=reaberto"
    return RedirectResponse(destino, status_code=303)


# ------------------------------------------------------------------ obras


@router.get("/obras")
def obras(
    request: Request, ok: str | None = None, _admin: Usuario = Depends(exigir_admin), db: Session = Depends(obter_db)
):
    linhas = db.execute(
        select(Obra, func.count(Capitulo.id))
        .outerjoin(Capitulo, Capitulo.obra_id == Obra.id)
        .where(Obra.fonte_id == FONTE_ID)
        .group_by(Obra.id)
        .order_by(Obra.titulo)
    ).all()
    return render(request, "admin/obras.html", linhas=linhas, mensagem=MENSAGENS.get(ok))


@router.get("/obras/nova")
def nova_obra(request: Request, config: Config = Depends(obter_config), _admin: Usuario = Depends(exigir_admin)):
    return render(request, "admin/obra_nova.html", m=acervo.Metadados(), **_opcoes(config))


@router.post("/obras/nova")
def criar_obra(
    request: Request,
    arquivos: Arquivos,
    titulo: Texto = "",
    autor: Texto = "",
    descricao: TextoLongo = "",
    tags: Texto = "",
    tipo: Texto = "manga",
    classificacao: Texto = "safe",
    status: Texto = "",
    ano: Texto = "",
    idioma: Texto = "pt-br",
    anilist_id: Texto = "",
    capa: ArquivoOpcional = None,
    config: Config = Depends(obter_config),
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    m = _metadados(titulo, autor, descricao, tags, tipo, classificacao, status, ano, idioma, anilist_id)
    try:
        with ExitStack() as pilha:
            obra, _ = acervo.criar_obra(db, config, m, _enviados(pilha, arquivos, config), _capa(capa))
    except ErroDeImportacao as erro:
        return render(request, "admin/obra_nova.html", 400, m=m, erro=str(erro), **_opcoes(config))
    return RedirectResponse(f"/admin/obras/{obra.id_externo}?ok=criada", status_code=303)


def _pagina_obra(request: Request, db: Session, config: Config, obra: Obra, status: int = 200, **extra):
    capitulos = db.scalars(select(Capitulo).where(Capitulo.obra_id == obra.id)).all()
    capitulos = sorted(capitulos, key=lambda c: (c.ordem if c.ordem is not None else -1, c.publicado_em))
    db.refresh(obra, ["tags"])
    m = extra.pop("m", None) or acervo.Metadados(
        titulo=obra.titulo,
        autor=obra.autor or "",
        descricao=obra.descricao or "",
        tags=[t.nome for t in obra.tags],
        tipo=obra.tipo,
        classificacao=obra.classificacao,
        status=obra.status or "",
        ano=obra.ano,
        idioma=capitulos[-1].idioma if capitulos else config.idiomas[0],
        anilist_id=obra.anilist_id,
    )
    return render(
        request, "admin/obra.html", status, obra=obra, capitulos=capitulos, m=m, **_opcoes(config), **extra
    )


@router.get("/obras/{obra_id}")
def editar_obra(
    obra_id: str,
    request: Request,
    ok: str | None = None,
    config: Config = Depends(obter_config),
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    return _pagina_obra(request, db, config, _obra_ou_404(db, obra_id), mensagem=MENSAGENS.get(ok))


@router.post("/obras/{obra_id}")
def salvar_obra(
    obra_id: str,
    request: Request,
    titulo: Texto = "",
    autor: Texto = "",
    descricao: TextoLongo = "",
    tags: Texto = "",
    tipo: Texto = "manga",
    classificacao: Texto = "safe",
    status: Texto = "",
    ano: Texto = "",
    anilist_id: Texto = "",
    capa: ArquivoOpcional = None,
    config: Config = Depends(obter_config),
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    obra = _obra_ou_404(db, obra_id)
    m = _metadados(
        titulo, autor, descricao, tags, tipo, classificacao, status, ano, config.idiomas[0], anilist_id
    )
    try:
        acervo.atualizar_obra(db, config, obra, m, _capa(capa))
    except ErroDeImportacao as erro:
        db.rollback()
        return _pagina_obra(request, db, config, obra, 400, m=m, erro=str(erro))
    return RedirectResponse(f"/admin/obras/{obra_id}?ok=salva", status_code=303)


@router.post("/obras/{obra_id}/capitulos")
def adicionar_capitulos(
    obra_id: str,
    request: Request,
    arquivos: Arquivos,
    idioma: Texto = "pt-br",
    config: Config = Depends(obter_config),
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    obra = _obra_ou_404(db, obra_id)
    try:
        with ExitStack() as pilha:
            acervo.adicionar_capitulos(db, config, obra, _enviados(pilha, arquivos, config), idioma)
    except ErroDeImportacao as erro:
        return _pagina_obra(request, db, config, obra, 400, erro_capitulos=str(erro))
    return RedirectResponse(f"/admin/obras/{obra_id}?ok=capitulos", status_code=303)


def _capitulo_ou_404(db: Session, obra: Obra, capitulo_id: str) -> Capitulo:
    capitulo = db.scalar(
        select(Capitulo).where(Capitulo.obra_id == obra.id, Capitulo.id_externo == capitulo_id)
    )
    if capitulo is None:
        raise NaoEncontrado(capitulo_id)
    return capitulo


@router.post("/obras/{obra_id}/capitulos/{capitulo_id}")
def salvar_capitulo(
    obra_id: str,
    capitulo_id: str,
    numero: Annotated[str, Form(max_length=20)] = "",
    volume: Annotated[str, Form(max_length=20)] = "",
    titulo: Texto = "",
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    capitulo = _capitulo_ou_404(db, _obra_ou_404(db, obra_id), capitulo_id)
    acervo.atualizar_capitulo(db, capitulo, numero, volume, titulo)
    return RedirectResponse(f"/admin/obras/{obra_id}?ok=capitulo", status_code=303)


@router.post("/obras/{obra_id}/capitulos/{capitulo_id}/remover")
def remover_capitulo(
    obra_id: str,
    capitulo_id: str,
    config: Config = Depends(obter_config),
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    capitulo = _capitulo_ou_404(db, _obra_ou_404(db, obra_id), capitulo_id)
    acervo.remover_capitulo(db, config, capitulo)
    return RedirectResponse(f"/admin/obras/{obra_id}?ok=capitulo-removido", status_code=303)


@router.post("/obras/{obra_id}/remover")
def remover_obra(
    obra_id: str,
    request: Request,
    confirmar: Annotated[str | None, Form()] = None,
    config: Config = Depends(obter_config),
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    obra = _obra_ou_404(db, obra_id)
    if confirmar != "on":
        return _pagina_obra(
            request, db, config, obra, 400, erro_remover="Marque a confirmação pra remover a obra."
        )
    acervo.remover_obra(db, config, obra)
    return RedirectResponse("/admin/obras?ok=removida", status_code=303)


@router.get("/metadados")
def buscar_metadados(
    q: str = "",
    fonte: str = "mangadex",
    fontes: Registro = Depends(obter_fontes),
    anilist: AniList = Depends(obter_anilist),
    _admin: Usuario = Depends(exigir_admin),
):
    """Busca no MangaDex ou no AniList pra preencher o formulário de obra."""
    termo = q.strip()[:200]
    if not termo:
        return []
    try:
        if fonte == "anilist":
            return [_dados_anilist(f) for f in anilist.buscar(termo)]
        filtro = Filtro(frozenset(Classificacao), termo=termo, idiomas=())
        resultado = fontes.obter("mangadex").buscar(filtro, 1, 8)
    except FonteIndisponivel as erro:
        return JSONResponse({"erro": str(erro)}, status_code=503)
    return [
        {
            "titulo": o.titulo,
            "autor": ", ".join(o.autores),
            "descricao": o.descricao,
            "tags": ", ".join(o.tags),
            "tipo": o.tipo.value,
            "classificacao": o.classificacao.value,
            "status": o.status or "",
            "ano": o.ano or "",
            "anilist_id": o.anilist_id or "",
            "link": o.link_original,
        }
        for o in resultado.obras
    ]


def _dados_anilist(ficha: FichaAniList) -> dict:
    # O AniList só marca obras explícitas (isAdult); "Ecchi" vira Sugestivo. O admin confere.
    if ficha.adulto:
        classificacao = Classificacao.PORNOGRAPHIC
    elif "Ecchi" in ficha.generos:
        classificacao = Classificacao.SUGGESTIVE
    else:
        classificacao = Classificacao.SAFE
    return {
        "titulo": ficha.titulo,
        "autor": ", ".join(ficha.autores),
        "descricao": ficha.descricao,
        "tags": ", ".join(ficha.generos),
        "tipo": ficha.tipo.value,
        "classificacao": classificacao.value,
        "status": ficha.status or "",
        "ano": ficha.ano or "",
        "anilist_id": ficha.id,
        "formato": ficha.formato,
        "link": ficha.url,
    }


# ---------------------------------------------------------------- usuários


@router.get("/usuarios")
def usuarios(
    request: Request, _admin: Usuario = Depends(exigir_admin), db: Session = Depends(obter_db)
):
    """Só a lista. As ações ficam na página de cada conta, pra ninguém clicar sem querer."""
    lista = db.scalars(select(Usuario).order_by(Usuario.criado_em)).all()
    return render(request, "admin/usuarios.html", lista=lista)


@router.get("/usuarios/{usuario_id}")
def usuario(
    usuario_id: int,
    request: Request,
    ok: str | None = None,
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    return _pagina_usuario(request, db, _alvo(db, usuario_id), mensagem=MENSAGENS.get(ok))


def _pagina_usuario(request: Request, db: Session, alvo: Usuario, status: int = 200, **extra):
    def contar(modelo) -> int:
        return db.scalar(select(func.count()).select_from(modelo).where(modelo.usuario_id == alvo.id))

    logins = db.scalars(
        select(Sessao.criada_em).where(Sessao.usuario_id == alvo.id, Sessao.expira_em > agora())
    ).all()
    resumo = {
        "aparelhos": len(logins),
        "ultimo_login": max(logins, default=None),
        "favoritos": contar(Favorito),
        "capitulos": contar(Progresso),
        "tickets": contar(Ticket),
        "reportes": contar(Reporte),
    }
    return render(request, "admin/usuario.html", status, alvo=alvo, resumo=resumo, **extra)


def _alvo(db: Session, usuario_id: int) -> Usuario:
    alvo = db.get(Usuario, usuario_id)
    if alvo is None:
        raise NaoEncontrado(str(usuario_id))
    return alvo


def _voltar(alvo: Usuario, ok: str) -> RedirectResponse:
    return RedirectResponse(f"/admin/usuarios/{alvo.id}?ok={ok}", status_code=303)


def _desconectar(db: Session, usuario: Usuario) -> None:
    db.execute(delete(Sessao).where(Sessao.usuario_id == usuario.id))


@router.post("/usuarios/{usuario_id}/admin")
def mudar_admin(
    usuario_id: int,
    request: Request,
    acao: Texto,
    admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    alvo = _alvo(db, usuario_id)
    if alvo.id == admin.id and acao == "rebaixar":
        return _pagina_usuario(request, db, alvo, 400, erro="Você não pode tirar o seu próprio acesso de admin.")
    alvo.is_admin = acao == "promover"
    db.commit()
    return _voltar(alvo, "promovido" if alvo.is_admin else "rebaixado")


@router.post("/usuarios/{usuario_id}/ativo")
def mudar_ativo(
    usuario_id: int,
    request: Request,
    acao: Texto,
    admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    alvo = _alvo(db, usuario_id)
    if alvo.id == admin.id and acao == "desativar":
        return _pagina_usuario(request, db, alvo, 400, erro="Você não pode desativar a sua própria conta.")
    alvo.ativo = acao != "desativar"
    if not alvo.ativo:
        _desconectar(db, alvo)
    db.commit()
    return _voltar(alvo, "reativado" if alvo.ativo else "desativado")


@router.post("/usuarios/{usuario_id}/adulto")
def mudar_adulto(
    usuario_id: int, acao: Texto, _admin: Usuario = Depends(exigir_admin), db: Session = Depends(obter_db)
):
    """Bloqueia o +18 de uma conta (ex.: alguém que mentiu a idade) ou desbloqueia."""
    alvo = _alvo(db, usuario_id)
    if acao == "bloquear":
        maioridade.bloquear(db, alvo)
    else:
        maioridade.desbloquear(db, alvo)
    return _voltar(alvo, "adulto-bloqueado" if alvo.adulto_bloqueado else "adulto-desbloqueado")


@router.post("/usuarios/{usuario_id}/sessoes")
def desconectar(usuario_id: int, _admin: Usuario = Depends(exigir_admin), db: Session = Depends(obter_db)):
    """Desconecta a conta de todos os aparelhos (a senha continua a mesma)."""
    alvo = _alvo(db, usuario_id)
    _desconectar(db, alvo)
    db.commit()
    return _voltar(alvo, "desconectado")


@router.post("/usuarios/{usuario_id}/senha")
def redefinir_senha(
    usuario_id: int, request: Request, _admin: Usuario = Depends(exigir_admin), db: Session = Depends(obter_db)
):
    """Cria uma senha temporária (mostrada uma vez só) pra quem esqueceu a senha."""
    alvo = _alvo(db, usuario_id)
    temporaria = secrets.token_urlsafe(9)
    alvo.senha_hash = gerar_hash(temporaria)
    _desconectar(db, alvo)
    db.commit()
    # Mostrada direto na página (não vai pra URL nem fica salva em lugar nenhum).
    return _pagina_usuario(request, db, alvo, senha_temporaria=temporaria)


# ------------------------------------------------------------- novidades


@router.get("/novidades")
def novidades_lista(
    request: Request, ok: str | None = None, _admin: Usuario = Depends(exigir_admin), db: Session = Depends(obter_db)
):
    return render(request, "admin/novidades.html", lista=noticias.todas(db), mensagem=MENSAGENS.get(ok))


@router.get("/novidades/nova")
def novidade_nova(request: Request, _admin: Usuario = Depends(exigir_admin)):
    return render(request, "admin/novidade.html", noticia=None)


@router.post("/novidades/nova")
def criar_novidade(
    request: Request,
    titulo: Texto = "",
    texto: TextoLongo = "",
    acao: Texto = "rascunho",
    admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    try:
        noticia = noticias.criar(db, admin, titulo, texto, publicar=acao == "publicar")
    except noticias.ErroDeNoticia as erro:
        return render(request, "admin/novidade.html", 400, noticia=None, titulo=titulo, texto=texto, erro=str(erro))
    ok = "noticia-publicada" if noticia.publicada_em else "noticia-rascunho"
    return RedirectResponse(f"/admin/novidades/{noticia.id}?ok={ok}", status_code=303)


def _noticia(db: Session, noticia_id: int) -> Noticia:
    noticia = db.get(Noticia, noticia_id)
    if noticia is None:
        raise NaoEncontrado(str(noticia_id))
    return noticia


@router.get("/novidades/{noticia_id}")
def novidade(
    noticia_id: int,
    request: Request,
    ok: str | None = None,
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    return render(request, "admin/novidade.html", noticia=_noticia(db, noticia_id), mensagem=MENSAGENS.get(ok))


@router.post("/novidades/{noticia_id}")
def editar_novidade(
    noticia_id: int,
    request: Request,
    titulo: Texto = "",
    texto: TextoLongo = "",
    acao: Texto = "salvar",
    _admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(obter_db),
):
    """acao: "salvar" (mantém como está), "publicar" ou "despublicar" (volta a ser rascunho)."""
    noticia = _noticia(db, noticia_id)
    publicada = {"publicar": True, "despublicar": False}.get(acao, noticia.publicada_em is not None)
    try:
        noticias.editar(db, noticia, titulo, texto, publicada)
    except noticias.ErroDeNoticia as erro:
        db.rollback()
        return render(
            request, "admin/novidade.html", 400, noticia=noticia, titulo=titulo, texto=texto, erro=str(erro)
        )
    ok = {"publicar": "noticia-publicada", "despublicar": "noticia-rascunho"}.get(acao, "salva")
    return RedirectResponse(f"/admin/novidades/{noticia.id}?ok={ok}", status_code=303)


@router.post("/novidades/{noticia_id}/apagar")
def apagar_novidade(noticia_id: int, _admin: Usuario = Depends(exigir_admin), db: Session = Depends(obter_db)):
    noticias.apagar(db, _noticia(db, noticia_id))
    return RedirectResponse("/admin/novidades?ok=noticia-apagada", status_code=303)
