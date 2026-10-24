"""Cache em memória com prazo de validade (TTL).

Serve pra não repetir a mesma chamada ao MangaDex várias vezes seguidas: o
limite deles é por IP, e o IP do seu servidor é compartilhado por todos os
usuários da Nami.
"""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any, TypeVar

T = TypeVar("T")
_FALTA = object()


class CacheTTL:
    """Dicionário em que cada item expira depois de `ttl` segundos.

    Quando passa de `maximo` itens, descarta os usados há mais tempo.
    Seguro pra usar de várias threads ao mesmo tempo.
    """

    def __init__(self, maximo: int = 2000, relogio: Callable[[], float] = time.monotonic):
        self._maximo = maximo
        self._relogio = relogio
        self._dados: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def obter(self, chave: Hashable, padrao: Any = None) -> Any:
        with self._lock:
            item = self._dados.get(chave)
            if item is None:
                return padrao
            expira, valor = item
            if expira <= self._relogio():
                del self._dados[chave]
                return padrao
            self._dados.move_to_end(chave)
            return valor

    def guardar(self, chave: Hashable, valor: Any, ttl: float) -> None:
        with self._lock:
            self._dados[chave] = (self._relogio() + ttl, valor)
            self._dados.move_to_end(chave)
            while len(self._dados) > self._maximo:
                self._dados.popitem(last=False)

    def remover(self, chave: Hashable) -> None:
        with self._lock:
            self._dados.pop(chave, None)

    def obter_ou_calcular(self, chave: Hashable, ttl: float, calcular: Callable[[], T]) -> T:
        valor = self.obter(chave, _FALTA)
        if valor is _FALTA:
            valor = calcular()
            self.guardar(chave, valor, ttl)
        return valor
