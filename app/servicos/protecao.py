"""Proteções gerais do site: limite de requisições por IP, tamanho máximo dos
envios e cabeçalhos de segurança."""

import ipaddress
import math
import threading
import time
from collections.abc import Callable

from fastapi import Request

from app.config import Config

MB = 1024 * 1024
LIMITE_CORPO = 1 * MB  # formulários e JSON; só o envio de .cbz/.cbr pode passar disso


def ip_do_cliente(request: Request) -> str:
    # Atrás do proxy HTTPS (NPM/Caddy/Cloudflare), o uvicorn roda com
    # --proxy-headers e request.client já traz o IP real de quem acessa, não o
    # do proxy. Em quem ele confia pra isso: FORWARDED_ALLOW_IPS, no Dockerfile.
    return request.client.host if request.client else "desconhecido"


def chave_do_cliente(request: Request) -> str:
    """Quem conta como "a mesma pessoa" nos limites: o IP, ou o bloco /64 no IPv6.

    Uma conexão IPv6 comum recebe um bloco inteiro de endereços (/64); contar
    cada endereço separado deixaria uma pessoa só trocar de IP à vontade e
    escapar dos limites.
    """
    ip = ip_do_cliente(request)
    try:
        endereco = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(endereco, ipaddress.IPv6Address):
        if endereco.ipv4_mapped:
            return str(endereco.ipv4_mapped)
        return str(ipaddress.ip_network(f"{endereco}/64", strict=False))
    return str(endereco)


def limite_do_corpo(caminho: str, config: Config) -> int:
    """Tamanho máximo (bytes) do corpo de uma requisição nesse caminho."""
    if caminho.startswith(("/admin/obras", "/admin/ajustes")):  # envio de .cbz/.cbr e de capa
        return config.upload_max_mb * MB
    return LIMITE_CORPO


class LimiteDeTaxa:
    """"Balde de fichas" por chave (IP): cada requisição gasta uma ficha e as
    fichas voltam aos poucos (`por_minuto` a cada minuto). Dá pra gastar até
    um minuto inteiro de uma vez (rajada), mas não manter um ritmo maior."""

    MAXIMO_CHAVES = 50_000  # não deixa a memória crescer sem fim (muitos IPs diferentes)

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
            if len(self._baldes) > self.MAXIMO_CHAVES:
                self._faxina(agora)
            return espera

    def _faxina(self, agora: float) -> None:
        # Primeiro esquece quem já está com o balde cheio de novo (não muda nada pra ninguém).
        cheio = self.capacidade / self.por_segundo
        self._baldes = {k: v for k, v in self._baldes.items() if agora - v[1] < cheio}
        if len(self._baldes) > self.MAXIMO_CHAVES:  # ainda demais (ataque de muitos IPs)
            recentes = sorted(self._baldes.items(), key=lambda item: item[1][1])
            self._baldes = dict(recentes[-self.MAXIMO_CHAVES // 2 :])


def segundos_retry(espera: float) -> str:
    return str(max(1, math.ceil(espera)))


def cabecalhos_de_seguranca(config: Config) -> dict[str, str]:
    cabecalhos = {
        # Só carrega scripts, estilos e imagens do próprio site: um script
        # injetado por algum bug não roda, e a página não pode ser embutida em outro site.
        "Content-Security-Policy": (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; manifest-src 'self'; worker-src 'self'; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        ),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin",  # links pra fora não contam de onde a pessoa veio
        "Permissions-Policy": (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()"
        ),
        # Outros sites não conseguem abrir a Nami numa janela "ligada" à deles
        # nem embutir as imagens dela (o que gastaria a sua internet).
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        # Servidor pessoal: pede pros buscadores (Google etc.) não listarem o site.
        "X-Robots-Tag": "noindex, nofollow",
    }
    if config.cookie_seguro:  # com HTTPS: o navegador passa a recusar abrir o site sem HTTPS
        cabecalhos["Strict-Transport-Security"] = "max-age=31536000"
    return cabecalhos
