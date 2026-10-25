"""Área "Novidades": posts do admin contando o que mudou no site.

O texto é simples de propósito (nada de HTML ou Markdown completo):
- linha em branco separa parágrafos;
- linhas começando com "- " viram uma lista;
- **assim** fica em negrito;
- endereços http(s) viram links.
Tudo é escapado antes de virar HTML, então nada que o admin digite vira código.
"""

import re

from markupsafe import Markup, escape
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Noticia, Usuario, agora

TITULO_MAXIMO = 120
TEXTO_MAXIMO = 10_000


class ErroDeNoticia(Exception):
    """Mensagem pra mostrar no formulário."""


# ------------------------------------------------------------------ leitura


def publicadas(db: Session) -> list[Noticia]:
    return list(
        db.scalars(select(Noticia).where(Noticia.publicada_em.is_not(None)).order_by(Noticia.publicada_em.desc()))
    )


def todas(db: Session) -> list[Noticia]:
    """Pro painel: rascunhos primeiro, depois as publicadas da mais nova pra mais velha."""
    return list(
        db.scalars(
            select(Noticia).order_by(Noticia.publicada_em.is_not(None), Noticia.publicada_em.desc(), Noticia.id.desc())
        )
    )


def tem_nova(db: Session, usuario: Usuario) -> bool:
    """Saiu post depois da última vez que a pessoa abriu /novidades? (a bolinha do menu)"""
    publicada = Noticia.publicada_em.is_not(None)
    if usuario.noticias_vistas_em is not None:
        publicada = publicada & (Noticia.publicada_em > usuario.noticias_vistas_em)
    return bool(db.scalar(select(exists().where(publicada))))


def marcar_vistas(db: Session, usuario: Usuario) -> None:
    usuario.noticias_vistas_em = agora()
    db.commit()


# ---------------------------------------------------------------- escrita


def _validar(titulo: str, texto: str) -> tuple[str, str]:
    titulo, texto = titulo.strip(), texto.strip()
    if not titulo:
        raise ErroDeNoticia("Escreva um título.")
    if len(titulo) > TITULO_MAXIMO:
        raise ErroDeNoticia(f"O título pode ter no máximo {TITULO_MAXIMO} caracteres.")
    if not texto:
        raise ErroDeNoticia("Escreva o texto da novidade.")
    if len(texto) > TEXTO_MAXIMO:
        raise ErroDeNoticia(f"O texto pode ter no máximo {TEXTO_MAXIMO:,} caracteres.".replace(",", "."))
    return titulo, texto


def criar(db: Session, autor: Usuario, titulo: str, texto: str, publicar: bool) -> Noticia:
    titulo, texto = _validar(titulo, texto)
    noticia = Noticia(titulo=titulo, texto=texto, autor_id=autor.id, publicada_em=agora() if publicar else None)
    db.add(noticia)
    db.commit()
    return noticia


def editar(db: Session, noticia: Noticia, titulo: str, texto: str, publicada: bool) -> None:
    """Publicar mantém a data da primeira publicação: corrigir um erro de
    digitação não acende a bolinha de todo mundo de novo."""
    noticia.titulo, noticia.texto = _validar(titulo, texto)
    if publicada and noticia.publicada_em is None:
        noticia.publicada_em = agora()
    elif not publicada:
        noticia.publicada_em = None
    noticia.atualizada_em = agora()
    db.commit()


def apagar(db: Session, noticia: Noticia) -> None:
    db.delete(noticia)
    db.commit()


# ------------------------------------------------------------ formatação

_LINK = re.compile(r"https?://[^\s<>\"']+")
_NEGRITO = re.compile(r"\*\*(.+?)\*\*")
_FIM_DE_FRASE = ".,;:!?)"


def formatar(texto: str) -> Markup:
    """Texto simples -> HTML seguro (parágrafos, listas, negrito e links)."""
    blocos = re.split(r"\n[ \t]*\n", texto.replace("\r\n", "\n").strip())
    html = []
    for bloco in blocos:
        linhas = [linha.strip() for linha in bloco.split("\n") if linha.strip()]
        if not linhas:
            continue
        if all(linha.startswith(("- ", "* ")) for linha in linhas):
            itens = "".join(f"<li>{_linha(linha[2:])}</li>" for linha in linhas)
            html.append(f"<ul>{itens}</ul>")
        else:
            html.append("<p>" + "<br>".join(_linha(linha) for linha in linhas) + "</p>")
    return Markup("\n".join(html))


def _linha(texto: str) -> str:
    # Os links são achados no texto original e cada pedaço é escapado sozinho:
    # assim um link nunca "engole" um pedaço já transformado em HTML.
    partes, inicio = [], 0
    for achado in _LINK.finditer(texto):
        url = achado.group(0).rstrip(_FIM_DE_FRASE)  # "veja https://x.com." -> sem o ponto
        partes.append(_negrito(escape(texto[inicio : achado.start()])))
        partes.append(f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(url)}</a>')
        inicio = achado.start() + len(url)
    partes.append(_negrito(escape(texto[inicio:])))
    return "".join(partes)


def _negrito(seguro: str) -> str:
    return _NEGRITO.sub(r"<strong>\1</strong>", str(seguro))
