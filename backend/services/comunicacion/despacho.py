"""services.comunicacion.despacho — armado de contexto/adjunto + despacho plan A/B.

`notificar_pedido(evento, pedido, ctx)` lee el registro (`eventos.REGISTRO`) y despacha
el evento según su **estrategia** (plan A/B: WhatsApp primero, mail de respaldo; ver
`eventos.py`), **reusando** los senders de cada canal (mail: `services.email.send_email`;
WhatsApp: `services.whatsapp.enviar_evento_pedido`) — no reimplementa el envío. Cada
sender ya es fail-safe (nunca propaga, loguea, idempotente), así que el despacho tampoco
propaga.

El armado del contexto (`pedido_email_context`) y del `.ics` (`ics_adjunto_pedido`) vivía
en `services/pedidos_notificaciones.py` (move-verbatim); es presentación específica del
pedido, compartida por todos los canales/eventos.
"""
from __future__ import annotations

import datetime
import logging
from typing import Optional

from fastapi import BackgroundTasks

from config import SITE_URL
from database import to_datetime, to_iso
from services.comunicacion.estrategia import efectiva as estrategia_efectiva
from services.comunicacion.eventos import (
    AMBOS,
    REGISTRO,
    SOLO_MAIL,
    SOLO_WHATSAPP,
    CanalMail,
    EventoComunicacion,
)
from services.email import Attachment, send_email
from services.email.service import get_admin_to
from services.ical import build_vcalendar, google_calendar_url, reserva_to_vevent
from services.precios import jornadas_periodo
from tipos_pedido import TIPOS_ESTUDIO

logger = logging.getLogger(__name__)


def _fmt_ars(monto) -> str:
    """Formatea un monto en pesos estilo es-AR: $ 12.500."""
    try:
        n = int(round(float(monto or 0)))
    except (TypeError, ValueError):
        n = 0
    return "$ " + f"{n:,}".replace(",", ".")


def _fmt_fecha_amable(v) -> str:
    """ISO → '15 jun · 10:00' (sin año). Cae al ISO si no parsea."""
    iso = to_iso(v)
    if not iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(str(iso).replace("Z", ""))
    except (ValueError, TypeError):
        return str(iso)
    meses = ["ene", "feb", "mar", "abr", "may", "jun",
             "jul", "ago", "sep", "oct", "nov", "dic"]
    fecha = f"{dt.day} {meses[dt.month - 1]}"
    if dt.hour or dt.minute:
        return f"{fecha} · {dt.hour:02d}:{dt.minute:02d}"
    return fecha


def pedido_email_context(pedido: dict) -> dict:
    """Arma el dict de variables disponibles a todos los templates de pedido.
    Mantener en sincronía con la lista de variables que se muestra en el editor del
    frontend (`/admin/email-templates`).

    A propósito NO abre conexión a la BD (función pura, testeada sin Postgres):
    `whatsapp_contacto` (el WhatsApp real del negocio, para los templates que
    invitan a escribir) lo agrega `services/whatsapp/envio.py` sobre una COPIA
    de este dict, usando la conexión que esa boca ya tiene abierta — no acá."""
    from markupsafe import escape

    items = pedido.get("items") or []

    def _nombre(it) -> str:
        return it.get("nombre_publico") or it.get("nombre") or it.get("equipo_nombre") or ""

    items_text = "\n".join(
        f"- {_nombre(it)} × {it.get('cantidad', 1)}" for it in items
    )

    # Tabla estilizada (inline) para el mail. Los nombres (datos dinámicos) se
    # escapan; la estructura/estilo la pone el helper canónico de branding
    # (`services/email/branding.py`, fuente única del look de mail).
    from services.email import branding as _eb

    filas = ""
    for it in items:
        nombre = escape(_nombre(it))
        cant = escape(str(it.get("cantidad", 1)))
        sub = it.get("subtotal")
        sub_html = escape(_fmt_ars(sub)) if sub is not None else None
        filas += _eb.item_row(nombre, cant, sub_html)

    # Fila de descuento (mismo criterio bruto→descuento→neto que el Presupuesto).
    descuento = int(pedido.get("descuento_monto") or 0)
    if descuento > 0:
        desc_pct = float(pedido.get("descuento_efectivo_pct") or 0)
        label = "Descuento" + (f" ({desc_pct:g}%)" if desc_pct else "")
        filas += _eb.discount_row(
            escape(label), escape(f"− {_fmt_ars(descuento)}")
        )

    items_html = _eb.items_table(filas)

    jornadas = pedido.get("cantidad_jornadas")
    if jornadas is None:
        d0 = to_datetime(pedido["fecha_desde"]) if pedido.get("fecha_desde") else None
        d1 = to_datetime(pedido["fecha_hasta"]) if pedido.get("fecha_hasta") else None
        jornadas = jornadas_periodo(d0, d1)

    # Período legible ("4 horas" en un pedido del Estudio, "N jornada(s)" en
    # un alquiler normal) — mismo criterio que `pdf_templates._periodo_label`
    # (display en horas del Estudio, 2026-07-23): un turno de 4hs mostrando
    # "Jornadas: 1" en el mail confundía igual que en el presupuesto/PDF.
    periodo_label = ""
    if pedido.get("tipo") in TIPOS_ESTUDIO and pedido.get("fecha_desde") and pedido.get("fecha_hasta"):
        _d0 = to_datetime(pedido["fecha_desde"])
        _d1 = to_datetime(pedido["fecha_hasta"])
        horas = max(1, round((_d1 - _d0).total_seconds() / 3600))
        periodo_label = f'{horas} hora{"s" if horas != 1 else ""}'
    elif jornadas:
        periodo_label = f'{jornadas} jornada{"s" if jornadas != 1 else ""}'

    def _num(v) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    total_num = _num(pedido.get("monto_total"))
    pagado_num = _num(pedido.get("monto_pagado"))
    saldo_num = max(total_num - pagado_num, 0.0)
    total_pagado = _fmt_ars(pagado_num)
    saldo_pendiente = _fmt_ars(saldo_num)
    if total_num <= 0:
        pago_estado = ""
    elif saldo_num <= 0:
        pago_estado = "Pago completo ✓"
    elif pagado_num > 0:
        pago_estado = f"Pagado {total_pagado} · saldo pendiente {saldo_pendiente}"
    else:
        pago_estado = "Pendiente de pago"

    return {
        "cliente_nombre": pedido.get("cliente_nombre") or "",
        "cliente_email": pedido.get("cliente_email") or "",
        "cliente_telefono": pedido.get("cliente_telefono") or "",
        "numero_pedido": pedido.get("numero_pedido") or pedido.get("id"),
        "fecha_desde": _fmt_fecha_amable(pedido.get("fecha_desde")),
        "fecha_hasta": _fmt_fecha_amable(pedido.get("fecha_hasta")),
        "cantidad_jornadas": jornadas,
        "periodo_label": periodo_label,
        "total": _fmt_ars(pedido.get("monto_total")),
        "total_pagado": total_pagado,
        "saldo_pendiente": saldo_pendiente,
        "pago_estado": pago_estado,
        "notas": pedido.get("notas") or "",
        "items_html": items_html,
        "items_text": items_text,
        "admin_url": f"{SITE_URL}/admin/pedidos/{pedido.get('id')}",
        "portal_url": f"{SITE_URL}/cliente/portal",
        "gcal_url": google_calendar_url(
            pedido, pedido.get("items") or [], link=f"{SITE_URL}/cliente/portal"
        ),
    }


def ics_adjunto_pedido(pedido: dict) -> Optional[list[Attachment]]:
    """Genera el adjunto `.ics` de la reserva para el mail ("agregar al calendario").
    Best-effort: si algo falla, devuelve None y el mail igual sale."""
    try:
        vevent = reserva_to_vevent(
            pedido, pedido.get("items") or [],
            link=f"{SITE_URL}/cliente/portal", with_reminders=True,
        )
        if not vevent:
            return None
        ics = build_vcalendar([vevent], method="PUBLISH")
        numero = pedido.get("numero_pedido") or pedido.get("id")
        return [
            Attachment(
                filename=f"pedido-{numero}.ics",
                content=ics.encode("utf-8"),
                mimetype="text/calendar; method=PUBLISH; charset=utf-8",
            )
        ]
    except Exception:
        logger.warning("No se pudo generar el .ics del pedido %s", pedido.get("id"), exc_info=True)
        return None


# ── senders (síncronos; el despacho reusa cada canal, no reimplementa) ────
def _mail_cliente(canal: Optional[CanalMail], pedido: dict, ctx: dict):
    """Manda el mail al cliente (síncrono). None si no hay template o destinatario."""
    if not (canal and canal.template_cliente):
        return None
    to = pedido.get("cliente_email")
    if not to:
        return None
    # El `.ics` se calcula solo si hay a quién mandárselo (best-effort).
    attachments = ics_adjunto_pedido(pedido) if canal.con_adjunto_ics else None
    return send_email(canal.template_cliente, to, ctx, pedido.get("id"), attachments=attachments)


def _mail_admin(canal: Optional[CanalMail], pedido: dict, ctx: dict):
    """Manda la copia al admin (síncrono). Independiente del plan A/B del cliente."""
    if not (canal and canal.template_admin):
        return None
    to = get_admin_to()
    if not to:
        return None
    return send_email(canal.template_admin, to, ctx, pedido.get("id"))


def _whatsapp_admin(template_key: str, pedido: dict, ctx: dict):
    """Aviso interno al equipo por WhatsApp. Fuera del plan A/B del cliente, igual
    que el mail al admin: son avisos al negocio, no al cliente."""
    from services.whatsapp import enviar_evento_admin

    return enviar_evento_admin(template_key, pedido, ctx)


def _whatsapp(template_key: str, pedido: dict, ctx: dict):
    # Import perezoso: no acopla el despacho al canal WhatsApp al importar.
    from services.whatsapp import enviar_evento_pedido

    return enviar_evento_pedido(template_key, pedido, ctx)


def _whatsapp_entregado(res) -> bool:
    """True si el WhatsApp llegó al cliente (ahora o ya antes). `wamid` = enviado
    recién; `skipped/duplicado` = ya se había enviado ese WhatsApp para este pedido
    (también llegó). Cualquier otro skip por gate (sin credencial/opt-in/E.164/canal
    apagado) o un fallo del provider → False → cae al mail (plan B)."""
    if not res:
        return False
    if res.get("wamid"):
        return True
    return bool(res.get("skipped") and res.get("reason") == "duplicado")


# ── despacho al cliente según la estrategia (plan A/B) ────────────────────
def _despachar_cliente(evento: EventoComunicacion, pedido: dict, ctx: dict) -> dict:
    """Resuelve el/los canal(es) del CLIENTE según `evento.estrategia`. SÍNCRONO —
    en modo background se corre dentro de UNA sola tarea, para que el fallback decida
    con el resultado real del WhatsApp (plan A) y no encolando dos envíos a ciegas.

    Devuelve `{"whatsapp": <res|None>, "mail": <res|None>}` (canal del cliente)."""
    # La estrategia EFECTIVA: la que el dueño eligió en /admin/comunicacion o, si no
    # eligió (o lo guardado no sirve), la que declara el registro. Ver `estrategia.py`.
    est = estrategia_efectiva(evento)
    wa = None
    mail = None

    if est == SOLO_MAIL:
        mail = _mail_cliente(evento.mail, pedido, ctx)
    elif est == SOLO_WHATSAPP:
        if evento.whatsapp:
            wa = _whatsapp(evento.whatsapp, pedido, ctx)
    elif est == AMBOS:
        # Confirmación: los dos. El WhatsApp confirma; el mail lleva el `.ics`.
        if evento.whatsapp:
            wa = _whatsapp(evento.whatsapp, pedido, ctx)
        mail = _mail_cliente(evento.mail, pedido, ctx)
    else:  # FALLBACK: WhatsApp plan A → mail plan B (uno u otro)
        if evento.whatsapp:
            wa = _whatsapp(evento.whatsapp, pedido, ctx)
        if not _whatsapp_entregado(wa):
            mail = _mail_cliente(evento.mail, pedido, ctx)

    return {"whatsapp": wa, "mail": mail}


def notificar_pedido(
    evento_key: str, pedido: dict, ctx: Optional[dict] = None, *,
    background: Optional[BackgroundTasks] = None,
) -> dict:
    """Despacha el evento de comunicación de un pedido según su estrategia (plan A/B).

    Lee `eventos.REGISTRO[evento_key]`: alcanza al **cliente** por WhatsApp/mail según
    `evento.estrategia` (fallback / ambos / solo_mail / solo_whatsapp) y —si el evento lo
    declara— manda **siempre** la copia al **admin** por mail (fuera del plan A/B).

    `ctx` opcional: si es None se arma con `pedido_email_context(pedido)` (los jobs lo
    pasan armado con extras como `dias_antes`). `background=None` corre síncrono (scripts/
    jobs) y devuelve los resultados; con `BackgroundTasks` encola **una sola tarea** (para
    que el fallback vea el resultado del WhatsApp). Nunca propaga.

    Devuelve `{"mail": [resultados...], "whatsapp": resultado|None}`. El canal del
    cliente y la copia al admin (si hubo) se acumulan en la lista `mail`."""
    evento = REGISTRO.get(evento_key)
    if evento is None:
        logger.warning("comunicacion: evento desconocido %r", evento_key)
        return {"mail": [], "whatsapp": None, "whatsapp_admin": None}

    if ctx is None:
        ctx = pedido_email_context(pedido)

    def _run() -> dict:
        cliente = _despachar_cliente(evento, pedido, ctx)
        admin = _mail_admin(evento.mail, pedido, ctx) if evento.mail else None
        mails = [m for m in (cliente["mail"], admin) if m is not None]
        wa_admin = (
            _whatsapp_admin(evento.whatsapp_admin, pedido, ctx) if evento.whatsapp_admin else None
        )
        return {"whatsapp": cliente["whatsapp"], "mail": mails, "whatsapp_admin": wa_admin}

    if background is not None:
        background.add_task(_run)
        # encolado; resultados no disponibles aún
        return {"mail": [], "whatsapp": None, "whatsapp_admin": None}
    return _run()
