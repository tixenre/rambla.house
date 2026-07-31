"""whatsapp_cloud.modelos — data plana del cliente. PORTABLE (solo stdlib).

Modela lo mínimo del envío de un *template message* de la Cloud API: el resultado
de un envío exitoso y el armado de los `components` del template. Sin I/O, sin
estado — el adapter de cada app arma los datos y llama al cliente.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvioResult:
    """Resultado de un envío exitoso. `message_id` es el `wamid` que devuelve Meta
    (para cruzar con el estado de entrega / webhooks). `to` es el destino en E.164."""

    message_id: str
    to: str
    template_name: str


def body_components(body_params: list[str]) -> list[dict]:
    """Arma el `components` de un template a partir de los parámetros posicionales
    del cuerpo. Meta espera:

        [{"type": "body", "parameters": [{"type": "text", "text": "..."}, ...]}]

    Los `{{1}}`, `{{2}}`, ... del template aprobado se completan EN ORDEN con
    `body_params`. Devuelve `[]` si no hay parámetros (templates sin variables)."""
    if not body_params:
        return []
    return [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in body_params],
        }
    ]
