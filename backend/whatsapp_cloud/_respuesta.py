"""whatsapp_cloud._respuesta — interpretación de una respuesta de Graph. PORTABLE.

La forma de **fallar** de Meta es la misma para cualquier endpoint del Graph (mandar
un mensaje, crear un template, listarlos): un bloque `{"error": {code, message}}` que
puede venir con 200 o con 4xx, más los status crudos. Esa traducción a la taxonomía
tipada de `errores.py` vive acá UNA vez y la reusan todos los clientes — antes estaba
pegada a la extracción del `wamid` en `client.py`, que es específica del envío.

No conoce endpoints ni payloads: solo respuesta HTTP → error tipado o datos.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .errores import (
    WhatsAppAuthError,
    WhatsAppNetworkError,
    WhatsAppRateLimitError,
    WhatsAppRequestError,
    WhatsAppResponseError,
)

# Códigos de error de Meta que son SIEMPRE de credencial/permiso, sin importar el
# HTTP status con el que vengan (ej. token vencido puede llegar como 400 o 401).
# https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
CODIGOS_AUTH = frozenset({0, 3, 10, 190, 200, 299, 2500})
# Códigos de límite de tasa / throughput / spam.
CODIGOS_RATE = frozenset({4, 80007, 130429, 131048, 131056, 133016})


def retry_after(resp: httpx.Response) -> Optional[float]:
    """Segundos del header `Retry-After`, si vino y es un número."""
    valor = resp.headers.get("Retry-After")
    if not valor:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def interpretar(resp: httpx.Response, *, contexto: str) -> Any:
    """Devuelve el JSON parseado de una respuesta OK, o levanta el error tipado.

    `contexto` es una frase corta para el mensaje de error ("el envío", "la creación
    del template") — así el mensaje que ve el admin dice qué falló, no solo el código.
    """
    status = resp.status_code
    cuerpo = resp.text or ""
    try:
        data = resp.json()
    except ValueError:
        data = None

    error = data.get("error") if isinstance(data, dict) else None
    if error:
        codigo = error.get("code")
        mensaje = error.get("message") or "Error de Meta sin mensaje"
        if isinstance(codigo, int) and codigo in CODIGOS_AUTH:
            raise WhatsAppAuthError(f"Meta rechazó por credencial/permiso: {mensaje} (code {codigo})")
        if isinstance(codigo, int) and codigo in CODIGOS_RATE:
            raise WhatsAppRateLimitError(
                f"Meta aplicó límite de tasa: {mensaje} (code {codigo})",
                retry_after=retry_after(resp),
            )
        if status in (401, 403):
            raise WhatsAppAuthError(f"Meta rechazó (HTTP {status}): {mensaje}")
        if status == 429:
            raise WhatsAppRateLimitError(
                f"Meta aplicó límite de tasa (HTTP 429): {mensaje}", retry_after=retry_after(resp)
            )
        if status >= 500:
            raise WhatsAppNetworkError(f"Meta 5xx: {mensaje}")
        raise WhatsAppRequestError(
            f"Meta rechazó {contexto}: {mensaje}",
            errores=((codigo if isinstance(codigo, int) else None, mensaje),),
        )

    if status in (401, 403):
        raise WhatsAppAuthError(f"Meta rechazó (HTTP {status}) sin cuerpo interpretable")
    if status == 429:
        raise WhatsAppRateLimitError(
            "Meta aplicó límite de tasa (HTTP 429)", retry_after=retry_after(resp)
        )
    if status >= 500:
        raise WhatsAppNetworkError(f"Meta respondió HTTP {status}")
    if status >= 400:
        raise WhatsAppResponseError(
            f"Meta respondió HTTP {status} sin bloque `error` reconocible", raw=cuerpo
        )
    return data


def pedir(
    metodo: str,
    url: str,
    *,
    token: str,
    timeout: float,
    contexto: str,
    json: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Any:
    """Un request al Graph con el bearer puesto, ya interpretado. Traduce cualquier
    falla de transporte a `WhatsAppNetworkError` (timeout, DNS, TLS, conexión caída)."""
    try:
        resp = httpx.request(
            metodo,
            url,
            json=json,
            params=params,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        raise WhatsAppNetworkError(f"No se pudo conectar con Meta: {exc}") from exc
    return interpretar(resp, contexto=contexto)
