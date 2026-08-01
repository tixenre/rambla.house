"""whatsapp_cloud.errores — taxonomía de excepciones del cliente. PORTABLE (solo stdlib).

Espeja `arca_fe.errores`: toda excepción que el cliente levanta hacia el consumidor
hereda de `WhatsAppError`, para que quien use la librería pueda `except WhatsAppError`
y atrapar cualquier falla — y discriminar por subtipo cuando le importa el porqué:

    try:
        res = client.enviar_template(to=..., template_name=..., lang_code=..., body_params=[...])
    except WhatsAppRequestError as e:   # Meta rechazó (número inválido, template no aprobado)
        for codigo, msg in e.errores: ...
    except WhatsAppAuthError:           # token inválido/vencido, permiso faltante
        ...
    except WhatsAppRateLimitError:      # 429 / spam-rate-limit → esperar y reintentar
        ...
    except WhatsAppNetworkError:        # timeout / caído / 5xx / TLS
        ...
    except WhatsAppResponseError:       # Meta contestó algo que no entendimos
        ...

Criterio de diseño (igual que arca_fe): el tipo ES la información. Una librería pública
que otros implementan no puede obligar a parsear strings para saber si reintentar (network/
rate-limit), avisar al usuario (request/business), o abrir un ticket (response inesperada).

`WhatsAppError` hereda de `Exception` (base limpia) — es el contrato público del paquete. La
validación de INPUT del programador (un `to` vacío, un template sin nombre) se queda en
`ValueError` de stdlib a propósito: eso es un bug del que llama, no "algo pasó hablando con Meta".
"""

from __future__ import annotations

from typing import Optional


class WhatsAppError(Exception):
    """Base de toda falla del cliente WhatsApp. `except WhatsAppError` atrapa todo."""


class WhatsAppAuthError(WhatsAppError):
    """Falla de autenticación/autorización: token inválido o vencido, permiso no
    otorgado sobre el número, app/WABA sin acceso. No hay envío posible hasta
    resolverla — reintentar sin cambiar el token da lo mismo."""


class WhatsAppRateLimitError(WhatsAppError):
    """Meta aplicó un límite de tasa (HTTP 429, o códigos de spam/throughput). Es la
    clase de error donde ESPERAR y reintentar tiene sentido. `retry_after` es la
    sugerencia en segundos (si Meta la mandó en el header), o None."""

    def __init__(self, mensaje: str, *, retry_after: Optional[float] = None):
        super().__init__(mensaje)
        self.retry_after = retry_after


class WhatsAppNetworkError(WhatsAppError):
    """Falla de transporte al hablar con Meta: timeout, conexión caída, TLS, o HTTP
    5xx. Distinta de un rechazo de negocio (que reintentado da lo mismo) — acá
    reintentar puede tener sentido."""


class WhatsAppResponseError(WhatsAppError):
    """Meta respondió, pero en una forma que no pudimos interpretar: falta el
    `messages[0].id` esperado en un 200, JSON malformado, o una estructura
    inesperada. NO es "número inválido" ni "template no aprobado" (eso es
    request/negocio) — es "el contrato con Meta no se cumplió como esperábamos".

    `raw` guarda un fragmento de la respuesta cruda (truncado) para diagnóstico."""

    def __init__(self, mensaje: str, *, raw: Optional[str] = None):
        super().__init__(mensaje)
        self.raw = (raw or "")[:2000]


class WhatsAppRequestError(WhatsAppError):
    """Meta recibió y entendió el pedido y lo RECHAZÓ por una regla propia: número
    de destino inválido/no-WhatsApp, destinatario fuera de la allowlist de un número
    de test, template inexistente o no aprobado, parámetros que no matchean el
    template. El pedido viajó y se entendió — Meta dijo que no. Reintentar sin
    cambiar nada da lo mismo.

    `errores` lleva los pares (código, mensaje) tal cual los devolvió Meta
    (`error.code`, `error.message`), para que el consumidor los muestre/loguee sin
    re-parsear el string."""

    def __init__(
        self,
        mensaje: str,
        *,
        errores: tuple[tuple[Optional[int], str], ...] = (),
    ):
        super().__init__(mensaje)
        self.errores = errores

    @property
    def codigo(self) -> Optional[int]:
        """El primer código de error, o None. Atajo para el caso de un solo error."""
        return self.errores[0][0] if self.errores else None
