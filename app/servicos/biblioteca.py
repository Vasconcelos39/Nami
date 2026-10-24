"""Biblioteca local: importa arquivos .cbz/.cbr e guarda as páginas no disco.

Um .cbz é um ZIP de imagens; um .cbr é um RAR. Cada arquivo enviado vira um
capítulo (ou volume). As páginas ficam em

    data/biblioteca/<obra>/<capitulo>/0001.jpg, 0002.png, ...

Cuidados com arquivos enviados (mesmo sendo só o admin quem envia):
- os nomes de dentro do arquivo nunca viram caminho no disco (as páginas são
  renomeadas pra 0001, 0002...), então um "../../algo" não escapa da pasta;
- cada imagem é aberta pelo Pillow pra confirmar que é imagem de verdade;
- há limites de quantidade e tamanho contra "bombas" de compactação (um
  arquivo pequeno que vira gigabytes ao descompactar).
"""

import io
import logging
import os
import re
import shutil
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError

log = logging.getLogger("nami.biblioteca")

MAX_PAGINAS = 3000
MAX_BYTES_POR_PAGINA = 64 * 1024 * 1024
MAX_BYTES_DESCOMPACTADOS = 4 * 1024 * 1024 * 1024
MAX_BYTES_COMICINFO = 1024 * 1024

_EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}
# Formatos guardados como vieram; o resto (BMP, TIFF...) é convertido pra JPEG.
_FORMATOS_MANTIDOS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}
TIPO_POR_EXTENSAO = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}

ID_LOCAL = re.compile(r"[0-9a-f]{32}")


class ErroDeImportacao(Exception):
    """Problema com o arquivo enviado; a mensagem aparece pro admin."""


@dataclass
class ComicInfo:
    """Metadados que alguns .cbz/.cbr trazem num ComicInfo.xml."""

    serie: str = ""
    titulo: str = ""
    numero: str = ""
    volume: str = ""
    autores: list[str] = field(default_factory=list)
    resumo: str = ""
    tags: list[str] = field(default_factory=list)
    ano: int | None = None
    idioma: str = ""


@dataclass
class CapituloImportado:
    id: str
    pasta: str  # relativa a data/biblioteca
    total_paginas: int
    primeira_pagina: bytes
    comicinfo: ComicInfo | None


def novo_id() -> str:
    return uuid.uuid4().hex


# ----------------------------------------------------------- abrir arquivos


@contextmanager
def abrir(caminho: Path) -> Iterator[zipfile.ZipFile]:
    """Abre um .cbz ou .cbr. O formato é descoberto pelo conteúdo, não pela
    extensão: muitos ".cbr" por aí são ZIPs renomeados."""
    with open(caminho, "rb") as arquivo:
        assinatura = arquivo.read(8)
    if assinatura.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        try:
            compactado = zipfile.ZipFile(caminho)
        except zipfile.BadZipFile as erro:
            raise ErroDeImportacao("O arquivo ZIP (.cbz) está corrompido.") from erro
    elif assinatura.startswith(b"Rar!\x1a\x07"):
        compactado = _abrir_rar(caminho)
    else:
        raise ErroDeImportacao("Isso não parece um .cbz nem um .cbr (o conteúdo não é ZIP nem RAR).")
    try:
        yield compactado
    finally:
        compactado.close()


def _abrir_rar(caminho: Path):
    # O rarfile imita a interface do zipfile, mas depende de um programa
    # externo (unar, unrar, bsdtar ou 7z) pra descompactar.
    import rarfile

    try:
        rarfile.tool_setup()
    except rarfile.RarCannotExec as erro:
        raise ErroDeImportacao(
            "Pra abrir .cbr o servidor precisa do programa unar (ou unrar/7z) instalado. "
            "No Docker da Nami ele já vem; no PC, instale um deles ou converta o arquivo pra .cbz."
        ) from erro
    try:
        return rarfile.RarFile(caminho)
    except rarfile.Error as erro:
        raise ErroDeImportacao("O arquivo RAR (.cbr) está corrompido.") from erro


def ordem_natural(nome: str) -> list:
    """"pag2" vem antes de "pag10" (a ordem alfabética pura poria o 10 antes)."""
    return [int(parte) if parte.isdigit() else parte.lower() for parte in re.split(r"(\d+)", nome)]


def _eh_pagina(nome: str) -> bool:
    caminho = PurePosixPath(nome.replace("\\", "/"))
    if "__MACOSX" in caminho.parts or any(parte.startswith(".") for parte in caminho.parts):
        return False
    return caminho.suffix.lower() in _EXTENSOES_IMAGEM


def _ler(compactado, info, limite: int) -> bytes:
    with compactado.open(info) as arquivo:
        dados = arquivo.read(limite + 1)
    if len(dados) > limite:
        raise ErroDeImportacao(f"A imagem {info.filename} passa do limite de {limite // 1024 // 1024} MB.")
    return dados


# -------------------------------------------------------------- imagens


def normalizar_imagem(dados: bytes) -> tuple[bytes, str] | None:
    """Confere que é imagem e devolve (bytes, extensão). None = não é imagem utilizável."""
    try:
        with Image.open(io.BytesIO(dados)) as imagem:
            formato = imagem.format
            imagem.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        return None
    if formato in _FORMATOS_MANTIDOS:
        return dados, _FORMATOS_MANTIDOS[formato]
    try:  # formato que o Pillow lê mas navegador não mostra bem: vira JPEG
        with Image.open(io.BytesIO(dados)) as imagem:
            saida = io.BytesIO()
            imagem.convert("RGB").save(saida, "JPEG", quality=90)
            return saida.getvalue(), ".jpg"
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def gerar_capa(dados: bytes, destino: Path) -> None:
    """Miniatura da capa (até 512x768) a partir de uma imagem qualquer."""
    try:
        with Image.open(io.BytesIO(dados)) as imagem:
            imagem = imagem.convert("RGB")
            # Página de webtoon (bem mais alta que larga): usa só o topo, na proporção de capa.
            if imagem.height > imagem.width * 1.6:
                imagem = imagem.crop((0, 0, imagem.width, int(imagem.width * 1.5)))
            imagem.thumbnail((512, 768))
            destino.parent.mkdir(parents=True, exist_ok=True)
            temporario = destino.with_name(f".tmp-{destino.name}")
            imagem.save(temporario, "JPEG", quality=85, optimize=True)
            os.replace(temporario, destino)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as erro:
        raise ErroDeImportacao("Não consegui usar essa imagem como capa.") from erro


# ----------------------------------------------------------- ComicInfo


def _ler_comicinfo(compactado) -> ComicInfo | None:
    info = next(
        (i for i in compactado.infolist() if PurePosixPath(i.filename.replace("\\", "/")).name.lower() == "comicinfo.xml"),
        None,
    )
    if info is None or info.file_size > MAX_BYTES_COMICINFO:
        return None
    try:
        raiz = ET.fromstring(_ler(compactado, info, MAX_BYTES_COMICINFO))
    except (ET.ParseError, ErroDeImportacao):
        return None

    def campo(nome: str) -> str:
        return (raiz.findtext(nome) or "").strip()

    def lista(*nomes: str) -> list[str]:
        itens = []
        for nome in nomes:
            itens += [parte.strip() for parte in campo(nome).split(",") if parte.strip()]
        return list(dict.fromkeys(itens))

    ano = campo("Year")
    return ComicInfo(
        serie=campo("Series"),
        titulo=campo("Title"),
        numero=_limpar_numero(campo("Number")) or "",
        volume=_limpar_numero(campo("Volume")) or "",
        autores=lista("Writer", "Penciller"),
        resumo=campo("Summary"),
        tags=lista("Genre", "Tags"),
        ano=int(ano) if ano.isdigit() and 1800 < int(ano) < 2200 else None,
        idioma=campo("LanguageISO").lower(),
    )


# ------------------------------------------------- números pelo nome do arquivo

_VOLUME = re.compile(r"\b(?:v|vol|volume)\.?\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)
_CAPITULO = re.compile(
    r"(?:\b(?:c|ch|chap|chapter|cap|capitulo|capítulo|ep|episodio|episódio)\.?\s*|#)(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def _limpar_numero(texto: str) -> str | None:
    """"012" → "12", "10,5" → "10.5"."""
    try:
        numero = float(texto.replace(",", "."))
    except ValueError:
        return None
    return str(int(numero)) if numero.is_integer() else str(numero)


def inferir_numeros(nome_arquivo: str) -> tuple[str | None, str | None]:
    """Tenta achar (capítulo, volume) no nome do arquivo, ex.: "One Piece v02 c015.cbz"."""
    base = Path(nome_arquivo).stem.replace("_", " ")
    base = re.sub(r"\[[^\]]*\]|\((?:19|20)\d\d\)", " ", base)  # [grupo], (2012)
    volume = _VOLUME.search(base)
    capitulo = _CAPITULO.search(base)
    if capitulo is None:
        resto = _VOLUME.sub(" ", base)
        numeros = re.findall(r"\d+(?:[.,]\d+)?", resto)
        numero = numeros[-1] if numeros else None
    else:
        numero = capitulo.group(1)
    return (
        _limpar_numero(numero) if numero else None,
        _limpar_numero(volume.group(1)) if volume else None,
    )


# ------------------------------------------------------------- importar


def salvar_envio(origem, destino_dir: Path, limite_mb: int) -> Path:
    """Copia o arquivo enviado (UploadFile.file) pra uma pasta temporária, respeitando o limite."""
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / f"envio-{novo_id()}"
    limite = limite_mb * 1024 * 1024
    copiado = 0
    try:
        with open(destino, "wb") as saida:
            while bloco := origem.read(1024 * 1024):
                copiado += len(bloco)
                if copiado > limite:
                    raise ErroDeImportacao(f"O arquivo passa do limite de {limite_mb} MB.")
                saida.write(bloco)
    except BaseException:
        destino.unlink(missing_ok=True)
        raise
    return destino


def importar_capitulo(caminho: Path, dir_biblioteca: Path, obra_id: str) -> CapituloImportado:
    """Extrai as páginas de um .cbz/.cbr pra data/biblioteca/<obra>/<capitulo>/."""
    if not ID_LOCAL.fullmatch(obra_id):
        raise ValueError(obra_id)
    capitulo_id = novo_id()
    final = dir_biblioteca / obra_id / capitulo_id
    temporaria = dir_biblioteca / obra_id / f".tmp-{capitulo_id}"
    temporaria.mkdir(parents=True)
    try:
        with abrir(caminho) as compactado:
            try:
                infos = [i for i in compactado.infolist() if not i.is_dir() and _eh_pagina(i.filename)]
                comicinfo = _ler_comicinfo(compactado)
            except ErroDeImportacao:
                raise
            except Exception as erro:  # cada formato tem suas exceções; todas viram mensagem amigável
                raise ErroDeImportacao("Não consegui ler o arquivo (corrompido ou protegido por senha?).") from erro
            infos.sort(key=lambda i: ordem_natural(i.filename))
            if len(infos) > MAX_PAGINAS:
                raise ErroDeImportacao(f"O arquivo tem mais de {MAX_PAGINAS} imagens.")
            if sum(i.file_size for i in infos) > MAX_BYTES_DESCOMPACTADOS:
                raise ErroDeImportacao("O arquivo descompactado ficaria grande demais.")

            total, primeira, ignoradas = 0, b"", 0
            for info in infos:
                try:
                    dados = _ler(compactado, info, MAX_BYTES_POR_PAGINA)
                except ErroDeImportacao:
                    raise
                except Exception as erro:
                    raise ErroDeImportacao("Não consegui ler o arquivo (corrompido ou protegido por senha?).") from erro
                normalizada = normalizar_imagem(dados)
                if normalizada is None:
                    ignoradas += 1
                    continue
                conteudo, extensao = normalizada
                total += 1
                (temporaria / f"{total:04d}{extensao}").write_bytes(conteudo)
                if total == 1:
                    primeira = conteudo
        if total == 0:
            raise ErroDeImportacao("Não achei nenhuma imagem dentro do arquivo.")
        if ignoradas:
            log.info("%s: %d arquivo(s) que não eram imagem foram ignorados", caminho.name, ignoradas)
        os.replace(temporaria, final)
    except BaseException:
        shutil.rmtree(temporaria, ignore_errors=True)
        raise
    return CapituloImportado(capitulo_id, f"{obra_id}/{capitulo_id}", total, primeira, comicinfo)


def apagar_pasta(dir_biblioteca: Path, relativa: str) -> None:
    """Apaga uma pasta da biblioteca, conferindo que ela fica mesmo lá dentro."""
    alvo = (dir_biblioteca / relativa).resolve()
    if dir_biblioteca.resolve() in alvo.parents:
        shutil.rmtree(alvo, ignore_errors=True)
