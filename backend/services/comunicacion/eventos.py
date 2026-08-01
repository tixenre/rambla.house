"""services.comunicacion.eventos — registro FUENTE ÚNICA de los eventos de comunicación.

Un solo lugar donde cada evento (algo que le comunicamos al cliente) declara **qué
template usa en cada canal** y **cómo se alcanza al cliente** (la estrategia). El
despachador (`comunicacion.despacho`) lee este registro y resuelve el envío a los
senders de cada canal — así no hay nombres de template hardcodeados y desparramados
por routes/jobs.

Nota sobre templates: NO es "un template para los dos canales". Cada medio tiene el
suyo por diseño — el mail es HTML nuestro (editable en `/admin/comunicacion`,
tabla `email_templates`), el WhatsApp es un template **pre-aprobado por Meta**
(rígido, con `{{n}}`, registrado en `services/whatsapp/plantillas.py`). Lo que este
registro unifica es el **evento**: el mismo disparador y contexto eligen, por canal,
su template — y cómo se despacha.

## Estrategia de canal (plan A/B) — cómo se alcanza al CLIENTE

Decisión del dueño (2026-07-12): **WhatsApp es plan A, el mail es plan B** (fallback,
NO los dos). Cada evento declara su `estrategia`:

- `FALLBACK`   → intenta WhatsApp; si no llegó (sin opt-in / sin E.164 / canal apagado /
                 falló), recién ahí manda el mail. Uno u otro, nunca los dos.
- `AMBOS`      → WhatsApp **y** mail. Es el caso de la confirmación: el WhatsApp confirma
                 y el mail **lleva el `.ics`** de la reserva (WhatsApp no adjunta calendario).
- `SOLO_MAIL`  → solo mail. Comunicaciones formales (contrato / documentos) van siempre
                 por mail, no por WhatsApp.
- `SOLO_WHATSAPP` → solo WhatsApp (recordatorios de devolución: nacieron canal-only).

El **mail al admin** (`CanalMail.template_admin`) es **independiente** de la estrategia
del cliente: si el evento lo declara, sale SIEMPRE por mail (el admin no entra en el
plan A/B — se entera del pedido por mail pase lo que pase con el cliente).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── Estrategias de canal para el cliente ─────────────────────────────────────
FALLBACK = "fallback"          # WhatsApp plan A → mail plan B (uno u otro)
AMBOS = "ambos"                # WhatsApp + mail (mail lleva el .ics: confirmación)
SOLO_MAIL = "solo_mail"        # solo mail (contrato / documentos formales)
SOLO_WHATSAPP = "solo_whatsapp"  # solo WhatsApp (recordatorios de devolución)

ESTRATEGIAS = (FALLBACK, AMBOS, SOLO_MAIL, SOLO_WHATSAPP)

# Vocabulario humano de cada estrategia — FUENTE ÚNICA para el back-office (la
# pantalla de Comunicación lo muestra tal cual) y para cualquier doc que la explique.
# Vive acá, junto a las constantes, para que agregar una estrategia obligue a
# nombrarla en el mismo lugar (no en el front, que si no se desincroniza).
ESTRATEGIA_LABEL: dict[str, str] = {
    FALLBACK: "WhatsApp primero, mail de respaldo",
    AMBOS: "WhatsApp y mail",
    SOLO_MAIL: "Solo mail",
    SOLO_WHATSAPP: "Solo WhatsApp",
}

ESTRATEGIA_DETALLE: dict[str, str] = {
    FALLBACK: (
        "Se intenta por WhatsApp. Si no llega (el cliente no dio su OK, no tiene "
        "teléfono válido, o el canal está apagado), recién ahí sale el mail. Nunca los dos."
    ),
    AMBOS: (
        "Salen los dos a propósito: el WhatsApp avisa y el mail lleva el archivo de "
        "calendario (.ics), que WhatsApp no puede adjuntar."
    ),
    SOLO_MAIL: "Siempre por mail. Es lo que corresponde para lo formal (contrato, documentos).",
    SOLO_WHATSAPP: "Solo por WhatsApp. No tiene plantilla de mail.",
}


@dataclass(frozen=True)
class CanalMail:
    """Config del canal mail para un evento. Los templates son keys de
    `email_templates`. `template_admin` = copia al admin (solo algunos eventos;
    sale SIEMPRE, fuera del plan A/B del cliente). `con_adjunto_ics` = adjunta el
    `.ics` de la reserva al mail del cliente (confirmación)."""

    template_cliente: Optional[str] = None
    template_admin: Optional[str] = None
    con_adjunto_ics: bool = False


@dataclass(frozen=True)
class EventoComunicacion:
    """Un evento de comunicación: su template por canal + la estrategia con la que se
    alcanza al cliente. `whatsapp` es la key en `services/whatsapp/plantillas.REGISTRO`
    (o None si el evento no sale por WhatsApp). `estrategia` decide el plan A/B."""

    key: str
    descripcion: str
    # Nombre corto y humano del evento (lo muestra el back-office como título de
    # su tarjeta). Vive acá, con el resto de la definición del evento.
    titulo: str = ""
    estrategia: str = FALLBACK
    mail: Optional[CanalMail] = None
    whatsapp: Optional[str] = None
    # Aviso INTERNO al equipo por WhatsApp (Pablo, Tincho). Independiente de la
    # estrategia del cliente, igual que `CanalMail.template_admin`: el equipo se
    # entera del pedido pase lo que pase con el canal del cliente.
    whatsapp_admin: Optional[str] = None


REGISTRO: dict[str, EventoComunicacion] = {
    "pedido_creado": EventoComunicacion(
        key="pedido_creado",
        titulo="Entró una solicitud",
        descripcion="El cliente mandó su pedido: le acusamos recibo y avisamos al equipo.",
        estrategia=FALLBACK,
        mail=CanalMail(template_cliente="pedido_creado_cliente", template_admin="pedido_creado_admin"),
        whatsapp="pedido_creado",
        whatsapp_admin="pedido_creado_admin",
    ),
    "pedido_confirmado": EventoComunicacion(
        key="pedido_confirmado",
        titulo="Reserva confirmada",
        descripcion="El pedido pasó a confirmado: se lo confirmamos al cliente.",
        estrategia=AMBOS,
        mail=CanalMail(template_cliente="pedido_confirmado_cliente", con_adjunto_ics=True),
        whatsapp="pedido_confirmado",
    ),
    "recordatorio_retiro": EventoComunicacion(
        key="recordatorio_retiro",
        titulo="Recordatorio de retiro",
        descripcion="Le recordamos al cliente que se acerca el día de retirar el equipo.",
        estrategia=FALLBACK,
        mail=CanalMail(template_cliente="recordatorio_retiro"),
        whatsapp="recordatorio_retiro",
    ),
    # Los recordatorios de devolución nacieron canal-WhatsApp: ese sigue siendo su
    # DEFAULT. Tienen su plantilla de mail para que el dueño pueda elegir el otro
    # canal (o los dos) desde /admin/comunicacion — ver `estrategia.py`.
    "recordatorio_devolucion_d1": EventoComunicacion(
        key="recordatorio_devolucion_d1",
        titulo="Se acerca la devolución",
        descripcion="Aviso antes del día en que tiene que devolver el equipo.",
        estrategia=SOLO_WHATSAPP,
        mail=CanalMail(template_cliente="recordatorio_devolucion_d1"),
        whatsapp="recordatorio_devolucion_d1",
    ),
    "recordatorio_devolucion_d0": EventoComunicacion(
        key="recordatorio_devolucion_d0",
        titulo="Devolución hoy",
        descripcion="Aviso el mismo día en que vence la reserva.",
        estrategia=SOLO_WHATSAPP,
        mail=CanalMail(template_cliente="recordatorio_devolucion_d0"),
        whatsapp="recordatorio_devolucion_d0",
    ),
    "recordatorio_devolucion_vencido": EventoComunicacion(
        key="recordatorio_devolucion_vencido",
        titulo="Devolución vencida",
        descripcion="Al día siguiente, si el equipo todavía figura sin devolver.",
        estrategia=SOLO_WHATSAPP,
        mail=CanalMail(template_cliente="recordatorio_devolucion_vencido"),
        whatsapp="recordatorio_devolucion_vencido",
    ),
}
