"""Cache das capas no disco do servidor.

Capas são miniaturas que aparecem em toda listagem. Guardar uma cópia local
evita baixar a mesma capa toda hora. Páginas de capítulo NÃO são guardadas:
passam pelo proxy direto pro navegador, sem tocar o disco.

Regras:
- Capa sem uso há `dias_sem_uso` dias é apagada. Cada vez que alguém vê a
  capa, a data do arquivo é renovada (é ela que marca o "último uso").
- O nome do arquivo leva a versão da capa (`obra.<versao>.jpg`). Quando a
  fonte troca a capa (ex.: volume novo), a nova é baixada e a velha apagada.
- Se mesmo assim a pasta passar de `limite_mb`, saem as usadas há mais tempo.
"""

import hashlib
import logging
import os
import re
import threading
import time
from pathlib import Path

from app.dominio import Imagem
from app.fontes.base import Fonte

log = logging.getLogger("nami.capas")

LIMPAR_A_CADA = 3600  # segundos entre uma faxina e outra

_EXTENSOES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
_TIPOS = {ext: tipo for tipo, ext in _EXTENSOES.items()}
_NOME_SEGURO = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TEMPORARIO = ".tmp-"


class CacheCapas:
    def __init__(self, pasta: Path, limite_mb: int, dias_sem_uso: int):
        self.pasta = pasta
        self.limite_bytes = limite_mb * 1024 * 1024
        self.segundos_sem_uso = dias_sem_uso * 24 * 3600
        self._lock = threading.Lock()
        self._ultima_limpeza = 0.0

    def obter(self, fonte: Fonte, obra_id: str) -> Imagem | None:
        # O id vira nome de arquivo: só aceitamos caracteres inofensivos.
        if not _NOME_SEGURO.fullmatch(fonte.id) or not _NOME_SEGURO.fullmatch(obra_id):
            return fonte.imagem_capa(obra_id)
        self._limpar_se_preciso()

        pasta = self.pasta / fonte.id
        # None = a fonte ainda não sabe a versão sem consultar a rede; aí vale a que estiver no disco.
        versao = _versao(fonte.versao_capa(obra_id))
        existentes = [a for a in pasta.glob(f"{obra_id}.*") if a.suffix in _TIPOS]
        for arquivo in existentes:
            if versao is None or arquivo.name.split(".")[1] == versao:
                try:
                    os.utime(arquivo)  # renova o "último uso"
                    return Imagem(arquivo.read_bytes(), _TIPOS[arquivo.suffix])
                except FileNotFoundError:
                    continue  # apagado pela faxina agora há pouco

        imagem = fonte.imagem_capa(obra_id)
        if imagem is not None and imagem.tipo_mime in _EXTENSOES:
            versao = _versao(fonte.versao_capa(obra_id)) or "0"
            destino = pasta / f"{obra_id}.{versao}{_EXTENSOES[imagem.tipo_mime]}"
            if self._gravar(destino, imagem.conteudo):
                for antigo in existentes:  # versões velhas da mesma capa
                    if antigo != destino:
                        _apagar(antigo)
        return imagem

    def limpar(self) -> None:
        """Apaga as capas sem uso e, se ainda passar do limite de tamanho, as usadas há mais tempo."""
        agora = time.time()
        restantes: list[tuple[float, int, Path]] = []
        for arquivo in self.pasta.rglob("*"):
            try:
                info = arquivo.stat()
            except FileNotFoundError:
                continue
            if not arquivo.is_file():
                continue
            sobra_de_gravacao = arquivo.name.startswith(_TEMPORARIO) and agora - info.st_mtime > 3600
            if sobra_de_gravacao or agora - info.st_mtime > self.segundos_sem_uso:
                _apagar(arquivo)
            else:
                restantes.append((info.st_mtime, info.st_size, arquivo))

        total = sum(tamanho for _, tamanho, _ in restantes)
        for _, tamanho, arquivo in sorted(restantes):  # do uso mais antigo pro mais recente
            if total <= self.limite_bytes:
                break
            _apagar(arquivo)
            total -= tamanho

    def _limpar_se_preciso(self) -> None:
        with self._lock:
            if time.monotonic() - self._ultima_limpeza < LIMPAR_A_CADA:
                return
            self._ultima_limpeza = time.monotonic()
        self.limpar()

    def _gravar(self, arquivo: Path, conteudo: bytes) -> bool:
        try:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            # Grava num temporário e renomeia: quem lê nunca vê arquivo pela metade.
            temporario = arquivo.with_name(f"{_TEMPORARIO}{threading.get_ident()}-{arquivo.name}")
            temporario.write_bytes(conteudo)
            os.replace(temporario, arquivo)
            return True
        except OSError as erro:
            log.warning("Não consegui gravar a capa %s: %s", arquivo, erro)
            return False


def _versao(identificador: str | None) -> str | None:
    """Encurta o identificador da capa (ex.: nome do arquivo no MangaDex) pra caber no nome."""
    return hashlib.sha1(identificador.encode()).hexdigest()[:12] if identificador else None


def _apagar(arquivo: Path) -> None:
    try:
        arquivo.unlink()
    except OSError:
        pass
