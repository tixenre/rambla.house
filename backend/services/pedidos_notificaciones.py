"""services/pedidos_notificaciones.py — armado de mails/ICS del pedido.

Move-verbatim desde `routes/alquileres/core.py` (split #1254, Corte B — espeja
`services/pedidos_enriquecimiento`, 2026-07-02): armar el contexto/adjunto de un
mail no es una superficie HTTP, y todas sus dependencias ya eran de `services/`.
`core.py` re-importa `_dispatch_pedido_creado_emails` tal cual — código nuevo
debería importar de acá directo.
"""
import datetime
import logging
from typing import Optional

from fastapi import BackgroundTasks

from database import to_datetime, to_iso
from services.email import send_email, Attachment
from services.email.service import get_admin_to
from services.ical import build_vcalendar, google_calendar_url, reserva_to_vevent
from services.precios import jornadas_periodo
from tipos_pedido import TIPOS_ESTUDIO
from config import SITE_URL

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


def _pedido_email_context(pedido: dict) -> dict:
    """Arma el dict de variables disponibles a todos los templates de
    pedido. Mantener en sincronía con la lista de variables que se muestra
    en el editor del frontend (`/admin/email-templates`).
    """
    from markupsafe import escape

    items = pedido.get("items") or []

    def _nombre(it) -> str:
        return it.get("nombre_publico") or it.get("nombre") or it.get("equipo_nombre") or ""

    items_text = "\n".join(
        f"- {_nombre(it)} × {it.get('cantidad', 1)}" for it in items
    )

    # Tabla estilizada (inline) para el mail. Los nombres (datos dinámicos) se
    # escapan; la estructura/estilo la pone el helper canónico de branding
    # (`services/email/branding.py`, fuente única del look de mail) → la plantilla
    # la inyecta con |safe.
    from services.email import branding as _eb

    filas = ""
    for it in items:
        nombre = escape(_nombre(it))
        cant = escape(str(it.get("cantidad", 1)))
        sub = it.get("subtotal")
        sub_html = escape(_fmt_ars(sub)) if sub is not None else None
        filas += _eb.item_row(nombre, cant, sub_html)

    # Fila de descuento (mismo criterio bruto→descuento→neto que el
    # Presupuesto, `pdf_templates._pedido_html`): las líneas de arriba
    # muestran el bruto por ítem y el "Total" del mail es el NETO (con
    # descuento por jornadas ya aplicado, el caso común en cualquier
    # alquiler de varios días) — sin esta fila el cliente veía un ítem en
    # $X y un total menor sin ninguna aclaración de por qué.
    descuento = int(pedido.get("descuento_monto") or 0)
    if descuento > 0:
        # `descuento_efectivo_pct` (el % GANADOR, expuesto por `desglose_de_pedido`)
        # — no el `descuento_pct` crudo, que desde la Fase C-1 (#1219) es solo el
        # override manual (0 = sin override) y puede no coincidir con lo que ganó.
        desc_pct = float(pedido.get("descuento_efectivo_pct") or 0)
        label = "Descuento" + (f" ({desc_pct:g}%)" if desc_pct else "")
        filas += _eb.discount_row(
            escape(label), escape(f"− {_fmt_ars(descuento)}")
        )

    items_html = _eb.items_table(filas)

    # Jornadas: si el pedido ya viene enriquecido (`_enriquecer_pedido_con_total`)
    # lo reusamos; si no, lo derivamos con la fórmula única (mismo helper).
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

    # Estado de pago (info "estilo pasaje": total, lo abonado y el saldo). La
    # plata sigue siendo NETO persistido — no se recalcula acá, solo se formatea.
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
        # URLs absolutas: en un cliente de mail un link relativo no resuelve.
        "admin_url": f"{SITE_URL}/admin/pedidos/{pedido.get('id')}",
        "portal_url": f"{SITE_URL}/cliente/portal",
        # Link "Agregar a Google Calendar" para el cuerpo del mail (complementa
        # al adjunto .ics). Vacío si la reserva no tiene fecha → el template lo
        # renderiza como string vacía (Jinja Undefined) sin romper.
        "gcal_url": google_calendar_url(
            pedido, pedido.get("items") or [], link=f"{SITE_URL}/cliente/portal"
        ),
    }


def _ics_adjunto_pedido(pedido: dict) -> Optional[list[Attachment]]:
    """Genera el adjunto `.ics` de la reserva para el mail (estilo "pasaje de
    avión": el cliente toca "Agregar al calendario"). Best-effort: si algo
    falla, devuelve None y el mail igual sale (la confirmación no se rompe).

    Usa el generador canónico de `services/ical.py` — el mismo que el feed.
    """
    try:
        # Link al portal del cliente (NO al back-office) — el .ics se lo lleva él.
        # with_reminders: su calendario le avisa solo antes del retiro.
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


def _dispatch_pedido_creado_emails(background: Optional[BackgroundTasks], pedido: dict):
    """Encola los mails de 'pedido creado' (cliente + admin) como
    background tasks. Si no hay BackgroundTasks (llamada desde script),
    los corre síncrono — el send_email() jamás propaga errores."""
    ctx = _pedido_email_context(pedido)
    pedido_id = pedido.get("id")
    cliente_email = pedido.get("cliente_email")

    if cliente_email:
        if background is not None:
            background.add_task(
                send_email, "pedido_creado_cliente", cliente_email, ctx, pedido_id,
            )
        else:
            send_email("pedido_creado_cliente", cliente_email, ctx, pedido_id)

    admin_to = get_admin_to()
    if admin_to:
        if background is not None:
            background.add_task(
                send_email, "pedido_creado_admin", admin_to, ctx, pedido_id,
            )
        else:
            send_email("pedido_creado_admin", admin_to, ctx, pedido_id)
