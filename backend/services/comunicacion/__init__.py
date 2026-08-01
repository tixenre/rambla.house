"""services.comunicacion — capa única de comunicación al cliente (multi-canal).

Materializa _2026-05-27 — Notificaciones canal-agnósticas_: un **registro** fuente única
de eventos de comunicación (`eventos.REGISTRO`: cada evento → su template por canal + su
estrategia) + un **despachador** (`despacho.notificar_pedido`) que despacha por estrategia
(plan A/B: WhatsApp primero, mail de respaldo; _2026-07-12_) reusando los senders de cada
canal (mail `services/email`, WhatsApp `services/whatsapp`) sin reimplementar el envío.

Es un **facade + registro** (molde `services/finanzas_flujo`), NO CQRS-lite: comunicación
es orquestación + logs append-only (que viven en cada sender), no una superficie de
mutación de dominio con invariantes. Si algún día suma preferencias por cliente + cola de
mensajes con estados, ahí aparecería un `commands/` — no antes.
"""
from __future__ import annotations

from services.comunicacion.despacho import (
    ics_adjunto_pedido,
    notificar_pedido,
    pedido_email_context,
)
from services.comunicacion.eventos import REGISTRO, CanalMail, EventoComunicacion

__all__ = [
    "notificar_pedido",
    "pedido_email_context",
    "ics_adjunto_pedido",
    "REGISTRO",
    "EventoComunicacion",
    "CanalMail",
]
