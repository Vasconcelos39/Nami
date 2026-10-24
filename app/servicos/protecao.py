"""Proteções gerais do site: limite de requisições por IP e cabeçalhos de segurança."""

import math
import threading
import time
from collections.abc import Callable

from fastapi import Request

from app.config import Config


def ip_do_cliente(request: Request) -> str:
    # Atrás do proxy HTTPS (Caddy/Cloudflare), o uvicorn roda com --proxy-headers
    # e request.client já traz o IP real de quem acessa, não o do proxy.
    return request.client.host if request.client else "desconhecido"


class LimiteDeTaxa:
    """"Balde de fichas" por chave (IP): cada requisição gasta uma ficha e as
    fichas voltam aos poucos (`por_minuto` a cada minuto). Dá pra gastar até
    um minuto inteiro de uma vez (rajada), mas não manter um ritmo maior."""

    def __init__(self, por_minuto: int, relogio: Callable[[], float] = time.monotonic):
        self.por_segundo = por_minuto / 60
        self.capacidade = float(por_minuto)
        self._relogio = relogio
        self._baldes: dict[str, tuple[float, float]] = {}  # chave -> (fichas, quando)
        self._lock = threading.Lock()

    def esperar(self, chave: str) -> float:
        """0 = pode passar. Senão, quantos segundos até a próxima ficha."""
        with self._lock:
            agora = self._relogio()
            fichas, quando = self._baldes.get(chave, (self.capacidade, agora))
            fichas = min(self.capacidade, fichas + (agora - quando) * self.por_segundo)
            if fichas >= 1:
                self._baldes[chave] = (fichas - 1, agora)
                espera = 0.0
            else:
                self._baldes[chave] = (fichas, agora)
                espera = (1 - fichas) / self.por_segundo
            if len(self._baldes) > 50_000:  # esquece quem já está com o balde cheio de novo
                cheio = self.capacidade / self.por_segundo
                self._baldes = {k: v for k, v in self._baldes.items() if agora - v[1] < cheio}
            return espera


def segundos_retry(espera: float) -> str:
    return str(max(1, math.ceil(espera)))


def cabecalhos_de_seguranca(config: Config) -> dict[str, str]:
    cabecalhos = {
        # Só carrega scripts, estilos e imagens do próprio site: um script
        # injetado por algum bug não roda, e a página não pode ser embutida em outro site.
        "Content-Security-Policy": (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'"
        ),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin",  # links pra fora não contam de onde a pessoa veio
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        # Servidor pessoal: pede pros buscadores (Google etc.) não listarem o site.
        "X-Robots-Tag": "noindex, nofollow",
    }
    if config.cookie_seguro:  # com HTTPS: o navegador passa a recusar abrir o site sem HTTPS
        cabecalhos["Strict-Transport-Security"] = "max-age=31536000"
    return cabecalhos
