"""whatsapp_cloud.retry — retry/backoff opcional. PORTABLE (solo stdlib).

Espeja `arca_fe.retry`: `with_retry` es un helper genérico, NO se aplica
automáticamente adentro de `WhatsAppClient` — es opt-in explícito del consumidor,
para no esconder latencia/reintentos detrás de una llamada que hoy es predecible.

Solo tiene sentido reintentar `WhatsAppNetworkError` (transporte: timeout/HTTP 5xx/TLS)
y `WhatsAppRateLimitError` (429 / spam-rate-limit — esperar y volver a intentar). Un
`WhatsAppRequestError` (Meta rechazó por número/template) o un `WhatsAppAuthError`
(token mal) dan el mismo resultado si se reintentan sin cambiar nada.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from .errores import WhatsAppNetworkError, WhatsAppRateLimitError

T = TypeVar("T")


def with_retry(
    fn: Callable[[], T],
    *,
    intentos: int = 3,
    backoff_inicial: float = 0.5,
    excepciones: tuple[type[BaseException], ...] = (
        WhatsAppNetworkError,
        WhatsAppRateLimitError,
    ),
) -> T:
    """Ejecuta `fn()` reintentando con backoff exponencial simple si levanta alguna de
    `excepciones` (default: network + rate-limit). `intentos` es el total de intentos
    (no de reintentos) — `intentos=3` corre `fn()` hasta 3 veces. Backoff:
    `backoff_inicial * 2**intento` entre cada intento fallido; si la excepción es un
    `WhatsAppRateLimitError` con `retry_after`, se respeta ese valor (Meta manda cuánto
    esperar).

    Si el último intento también falla, la excepción se propaga tal cual (sin envolver)."""
    ultimo_exc: BaseException | None = None
    for intento in range(intentos):
        try:
            return fn()
        except excepciones as exc:
            ultimo_exc = exc
            if intento < intentos - 1:
                espera = backoff_inicial * (2**intento)
                retry_after = getattr(exc, "retry_after", None)
                if retry_after:
                    espera = max(espera, float(retry_after))
                time.sleep(espera)
    assert ultimo_exc is not None
    raise ultimo_exc
