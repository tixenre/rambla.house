"""services.comunicacion.eventos — registro FUENTE ÚNICA de los eventos de comunicación.

Un solo lugar donde cada evento (algo que le comunicamos al cliente) declara **qué
template usa en cada canal** y **cómo se alcanza al cliente** (la estrategia). El
despachador (`comunicacion.despacho`) lee este registro y resuelve el envío a los
senders de cada canal — así no hay nombres de template hardcodeados y desparramados
por routes/jobs.

Nota sobre templates: NO es "un template para los dos canales". Cada medio tiene el
suyo por diseño — el mail es HTML nuestro (editable en `/admin/email-templates`,
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
    estrategia: str = FALLBACK
    mail: Optional[CanalMail] = None
    whatsapp: Optional[str] = None


REGISTRO: dict[str, EventoComunicacion] = {
    "pedido_creado": EventoComunicacion(
        key="pedido_creado",
        descripcion="Entró una solicitud de reserva (acuse al cliente por WhatsApp/mail + aviso al admin por mail).",
        estrategia=FALLBACK,
        mail=CanalMail(template_cliente="pedido_creado_cliente", template_admin="pedido_creado_admin"),
        whatsapp="pedido_creado",
    ),
    "pedido_confirmado": EventoComunicacion(
        key="pedido_confirmado",
        descripcion="La reserva pasó a confirmada: WhatsApp de confirmación + un mail que lleva el .ics.",
        estrategia=AMBOS,
        mail=CanalMail(template_cliente="pedido_confirmado_cliente", con_adjunto_ics=True),
        whatsapp="pedido_confirmado",
    ),
    "recordatorio_retiro": EventoComunicacion(
        key="recordatorio_retiro",
        descripcion="Recordatorio D-1 del retiro del equipo (WhatsApp plan A, mail plan B).",
        estrategia=FALLBACK,
        mail=CanalMail(template_cliente="recordatorio_retiro"),
        whatsapp="recordatorio_retiro",
    ),
    # Los recordatorios de devolución nacieron con el canal WhatsApp (no hay template
    # de mail): solo WhatsApp. Si algún día se quiere el mail, se suma su template y
    # se cambia la estrategia a FALLBACK.
    "recordatorio_devolucion_d1": EventoComunicacion(
        key="recordatorio_devolucion_d1",
        descripcion="Recordatorio la víspera de la devolución (D-1).",
        estrategia=SOLO_WHATSAPP,
        whatsapp="recordatorio_devolucion_d1",
    ),
    "recordatorio_devolucion_d0": EventoComunicacion(
        key="recordatorio_devolucion_d0",
        descripcion="Aviso el día de la devolución (D-0).",
        estrategia=SOLO_WHATSAPP,
        whatsapp="recordatorio_devolucion_d0",
    ),
    "recordatorio_devolucion_vencido": EventoComunicacion(
        key="recordatorio_devolucion_vencido",
        descripcion="Aviso al día siguiente si el equipo figura sin devolver (D+1).",
        estrategia=SOLO_WHATSAPP,
        whatsapp="recordatorio_devolucion_vencido",
    ),
}
