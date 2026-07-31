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

from ._respuesta import interpretar as _interpretar_respuesta
from .errores import WhatsAppNetworkError, WhatsAppResponseError
from .modelos import EnvioResult, body_components

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

        return self._post(payload, to=str(to), template_name=template_name, timeout=timeout)

    def enviar_texto(
        self, *, to: str, body: str, timeout: Optional[float] = None
    ) -> EnvioResult:
        """Envía un mensaje de TEXTO LIBRE (no template). Meta solo lo entrega si `to`
        abrió una ventana de servicio de 24h con un mensaje entrante propio — no sirve
        para iniciar contacto (para eso están los templates). Lo usa el webhook para
        auto-responder a quien escribe al número de avisos.

        Raises: ValueError (input vacío) o la taxonomía de `errores.py`.
        """
        if not to or not str(to).strip():
            raise ValueError("enviar_texto: 'to' vacío")
        if not body or not str(body).strip():
            raise ValueError("enviar_texto: 'body' vacío")

        payload: dict = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": str(to),
            "type": "text",
            "text": {"body": str(body)},
        }
        return self._post(payload, to=str(to), template_name="", timeout=timeout)

    def _post(
        self, payload: dict, *, to: str, template_name: str, timeout: Optional[float]
    ) -> EnvioResult:
        """POST común a `enviar_template`/`enviar_texto`: arma la URL/headers, hace
        la request y delega la interpretación de la respuesta."""
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

        return self._interpretar(resp, to=to, template_name=template_name)

    # ── interpretación de la respuesta → resultado o error tipado ──────────
    @staticmethod
    def _interpretar(resp: httpx.Response, *, to: str, template_name: str) -> EnvioResult:
        """La taxonomía de errores la resuelve `_respuesta.interpretar` (compartida con
        el cliente de templates); acá solo queda lo propio del envío: sacar el `wamid`."""
        cuerpo = resp.text or ""
        data = _interpretar_respuesta(resp, contexto="el envío")

        if isinstance(data, dict):
            mensajes = data.get("messages")
            if isinstance(mensajes, list) and mensajes and isinstance(mensajes[0], dict):
                wamid = mensajes[0].get("id")
                if wamid:
                    return EnvioResult(message_id=str(wamid), to=to, template_name=template_name)
        raise WhatsAppResponseError(
            "Meta respondió 2xx pero sin `messages[0].id` (wamid) esperado", raw=cuerpo
        )

