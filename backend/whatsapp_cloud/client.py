"""whatsapp_cloud.client — cliente HTTP de la Cloud API (Graph). PORTABLE.

Espeja `arca_fe.wsfe`/`arca_fe.wsaa`: recibe las credenciales (token, phone_number_id)
y la `base_url` YA RESUELTA por el adapter, y traduce toda falla a la taxonomía tipada
de `errores.py`. No lee la BD, no gatea por ambiente, no elige el número: eso es del
adapter (`services/whatsapp/`).

Única dependencia externa: `httpx` (el mismo cliente HTTP que usa `arca_fe.wsaa`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

from .errores import (
    WhatsAppAuthError,
    WhatsAppNetworkError,
    WhatsAppRateLimitError,
    WhatsAppRequestError,
    WhatsAppResponseError,
)
from .modelos import EnvioResult, body_components

# Códigos de error de Meta que son SIEMPRE de credencial/permiso, sin importar el
# HTTP status con el que vengan (ej. token vencido puede llegar como 400 o 401).
# https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
_CODIGOS_AUTH = frozenset({0, 3, 10, 190, 200, 299, 2500})
# Códigos de límite de tasa / throughput / spam.
_CODIGOS_RATE = frozenset({4, 80007, 130429, 131048, 131056, 133016})

_TIMEOUT_DEFAULT = 15.0


@dataclass(frozen=True)
class WhatsAppClient:
    """Cliente de envío de la Cloud API para UN número (phone_number_id).

    `base_url` es el endpoint de Graph ya resuelto por el adapter, sin barra final
    (ej. 'https://graph.facebook.com/v21.0'). `access_token` es el token con el que
    se autoriza; `timeout` en segundos aplica a cada request."""

    phone_number_id: str
    access_token: str
    base_url: str
    timeout: float = _TIMEOUT_DEFAULT

    def enviar_template(
        self,
        *,
        to: str,
        template_name: str,
        lang_code: str,
        body_params: Optional[list[str]] = None,
        components: Optional[list[dict]] = None,
        timeout: Optional[float] = None,
    ) -> EnvioResult:
        """Envía un *template message* aprobado a `to` (E.164 sin '+', o con '+': Meta
        acepta ambos; el adapter manda E.164). Los `{{n}}` del template se completan
        con `body_params` (en orden), salvo que se pase `components` armado a mano.

        Levanta la taxonomía tipada de `errores.py`. Devuelve `EnvioResult` con el
        `wamid` en caso de éxito.

        Raises:
            ValueError: input del programador inválido (to/template vacíos).
            WhatsAppAuthError / WhatsAppRateLimitError / WhatsAppNetworkError /
            WhatsAppRequestError / WhatsAppResponseError: según qué contestó Meta.
        """
        if not to or not str(to).strip():
            raise ValueError("enviar_template: 'to' vacío")
        if not template_name or not str(template_name).strip():
            raise ValueError("enviar_template: 'template_name' vacío")
        if not lang_code:
            raise ValueError("enviar_template: 'lang_code' vacío")

        comps = components if components is not None else body_components(body_params or [])
        payload: dict = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": str(to),
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": lang_code},
            },
        }
        if comps:
            payload["template"]["components"] = comps

        url = f"{self.base_url}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        try:
            resp = httpx.post(
                url, json=payload, headers=headers, timeout=timeout or self.timeout
            )
        except httpx.RequestError as exc:
            # timeout, conexión caída, DNS, TLS → transporte
            raise WhatsAppNetworkError(f"No se pudo conectar con Meta: {exc}") from exc

        return self._interpretar(resp, to=str(to), template_name=template_name)

    # ── interpretación de la respuesta → resultado o error tipado ──────────
    @staticmethod
    def _interpretar(resp: httpx.Response, *, to: str, template_name: str) -> EnvioResult:
        status = resp.status_code
        cuerpo = resp.text or ""
        try:
            data = resp.json()
        except ValueError:
            data = None

        # Error explícito de Meta (`{"error": {...}}`) — puede venir con 200 o 4xx.
        error = data.get("error") if isinstance(data, dict) else None
        if error:
            codigo = error.get("code")
            mensaje = error.get("message") or "Error de Meta sin mensaje"
            if isinstance(codigo, int) and codigo in _CODIGOS_AUTH:
                raise WhatsAppAuthError(f"Meta rechazó por credencial/permiso: {mensaje} (code {codigo})")
            if isinstance(codigo, int) and codigo in _CODIGOS_RATE:
                raise WhatsAppRateLimitError(
                    f"Meta aplicó límite de tasa: {mensaje} (code {codigo})",
                    retry_after=_retry_after(resp),
                )
            if status in (401, 403):
                raise WhatsAppAuthError(f"Meta rechazó (HTTP {status}): {mensaje}")
            if status == 429:
                raise WhatsAppRateLimitError(
                    f"Meta aplicó límite de tasa (HTTP 429): {mensaje}",
                    retry_after=_retry_after(resp),
                )
            if status >= 500:
                raise WhatsAppNetworkError(f"Meta 5xx: {mensaje}")
            # 4xx con error de negocio (número inválido, template no aprobado, fuera de allowlist)
            raise WhatsAppRequestError(
                f"Meta rechazó el envío: {mensaje}",
                errores=((codigo if isinstance(codigo, int) else None, mensaje),),
            )

        # Sin bloque `error`: decidir por status.
        if status in (401, 403):
            raise WhatsAppAuthError(f"Meta rechazó (HTTP {status}) sin cuerpo interpretable")
        if status == 429:
            raise WhatsAppRateLimitError(
                "Meta aplicó límite de tasa (HTTP 429)", retry_after=_retry_after(resp)
            )
        if status >= 500:
            raise WhatsAppNetworkError(f"Meta respondió HTTP {status}")
        if status >= 400:
            raise WhatsAppResponseError(
                f"Meta respondió HTTP {status} sin bloque `error` reconocible", raw=cuerpo
            )

        # 2xx: extraer el wamid.
        if isinstance(data, dict):
            mensajes = data.get("messages")
            if isinstance(mensajes, list) and mensajes and isinstance(mensajes[0], dict):
                wamid = mensajes[0].get("id")
                if wamid:
                    return EnvioResult(message_id=str(wamid), to=to, template_name=template_name)
        raise WhatsAppResponseError(
            "Meta respondió 2xx pero sin `messages[0].id` (wamid) esperado", raw=cuerpo
        )


def _retry_after(resp: httpx.Response) -> Optional[float]:
    """Segundos sugeridos por Meta para reintentar (header `Retry-After`), o None."""
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
