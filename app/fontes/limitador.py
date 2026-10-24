"""Controle de ritmo das chamadas a uma API externa.

Se passarmos do limite do MangaDex, recebemos 429. Se insistirmos depois
disso, o IP leva ban temporário. Por isso as chamadas são espaçadas e, depois
de um 429, a Nami para de chamar até o horário que eles indicarem.
"""

import threading
import time
from collections import deque
from collections.abc import Callable

from app.fontes.base import FonteIndisponivel


class Limitador:
    """No máximo `por_segundo` chamadas por segundo, somando todas as threads.

    Quem chega quando a fila está cheia (espera maior que `espera_maxima`)
    recebe erro na hora em vez de ficar travado.
    """

    def __init__(
        self,
        por_segundo: float,
        espera_maxima: float = 10.0,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self._intervalo = 1.0 / por_segundo
        self._espera_maxima = espera_maxima
        self._relogio = relogio
        self._dormir = dormir
        self._proxima_vez = 0.0
        self._bloqueado_ate = 0.0
        self._lock = threading.Lock()

    def aguardar(self) -> None:
        with self._lock:
            agora = self._relogio()
            if agora < self._bloqueado_ate:
                raise FonteIndisponivel(
                    "O MangaDex pediu uma pausa (limite de requisições). "
                    "Tente de novo em alguns segundos."
                )
            vez = max(agora, self._proxima_vez)
            espera = vez - agora
            if espera > self._espera_maxima:
                raise FonteIndisponivel("Muitas requisições na fila. Tente de novo em instantes.")
            self._proxima_vez = vez + self._intervalo
        if espera > 0:
            self._dormir(espera)

    def bloquear(self, segundos: float) -> None:
        """Recusa todas as chamadas pelos próximos `segundos`."""
        with self._lock:
            self._bloqueado_ate = max(self._bloqueado_ate, self._relogio() + segundos)


class JanelaLimite:
    """No máximo `limite` usos a cada `janela` segundos (ex.: 40 por minuto)."""

    def __init__(self, limite: int, janela: float, relogio: Callable[[], float] = time.monotonic):
        self._limite = limite
        self._janela = janela
        self._relogio = relogio
        self._usos: deque[float] = deque()
        self._lock = threading.Lock()

    def registrar(self) -> None:
        with self._lock:
            agora = self._relogio()
            while self._usos and self._usos[0] <= agora - self._janela:
                self._usos.popleft()
            if len(self._usos) >= self._limite:
                raise FonteIndisponivel(
                    "Muitos capítulos abertos no último minuto. Espere um pouco e tente de novo."
                )
            self._usos.append(agora)
