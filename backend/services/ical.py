"""Generación de iCalendar (RFC 5545) — fuente ÚNICA de eventos de calendario.

Lo usan las bocas del calendario de reservas:
  1. el **feed iCal** suscribible (`routes/calendar.py`) — muchas reservas;
  2. el **adjunto `.ics`** del mail de confirmación al cliente
     (`routes/alquileres.py`) — una reserva, estilo "pasaje de avión".
Y, vía las mismas primitivas (`build_vevent`/`build_vcalendar`, sin reusar el
adaptador de reserva), el **adjunto `.ics`** del mail de inscripción a un
taller (`routes/talleres.py`, adaptador `clases_taller_to_ics` más abajo) — N
clases de una edición, no una reserva.
Tener un solo generador garantiza que el evento se vea idéntico en todos lados
(barra de calidad del proyecto: modularidad a prueba de balas).

Sin dependencias externas: el formato iCal es texto plano y se arma a mano (igual
que `routes/seo.py` arma el sitemap XML). Las fechas de los pedidos se guardan
como wall-clock de Argentina (ver `database.now_ar`/`to_datetime`), así que los
eventos con hora se emiten en **tiempo flotante** (sin sufijo `Z` ni `TZID`): el
cliente de calendario los muestra tal cual, sin reinterpretar husos. Los alquileres
diarios van como eventos **all-day** (`VALUE=DATE`), donde el huso es irrelevante.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Mapping, Sequence
from urllib.parse import urlencode, urlparse

from config import settings
from database import to_datetime

PRODID = "-//Rambla Rental//Reservas//ES"
_UID_DOMAIN = urlparse(settings.SITE_URL).netloc
_TZID = "America/Argentina/Buenos_Aires"


# ── Primitivas de formato (RFC 5545) ─────────────────────────────────────────

def _escape(text) -> str:
    """Escapa un valor de texto iCal (RFC 5545 §3.3.11): `\\`, `;`, `,` y
    saltos de línea (que pasan a `\\n`)."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Pliega una línea lógica a <=75 octetos con continuación (RFC 5545 §3.1).

    Cuenta en bytes UTF-8 y corta entre caracteres (nunca al medio de un
    multibyte). Las líneas de continuación empiezan con un espacio, por eso se
    les presupuesta 1 octeto menos."""
    if len(line.encode("utf-8")) <= 75:
        return line
    pieces: list[str] = []
    cur = ""
    cur_bytes = 0
    first = True
    for ch in line:
        n = len(ch.encode("utf-8"))
        limit = 75 if first else 74  # las continuaciones llevan 1 espacio inicial
        if cur_bytes + n > limit:
            pieces.append(cur)
            first = False
            cur = ch
            cur_bytes = n
        else:
            cur += ch
            cur_bytes += n
    pieces.append(cur)
    return "\r\n ".join(pieces)


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _fmt_dt_floating(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def _fmt_dt_utc(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


# ── Bloques ──────────────────────────────────────────────────────────────────

def build_vevent(
    *,
    uid: str,
    summary: str,
    dtstart: datetime,
    dtend: datetime,
    all_day: bool,
    description: str = "",
    location: str = "",
    dtstamp: datetime | None = None,
    reminders: Sequence[str] = (),
) -> str:
    """Construye un `VEVENT` (líneas plegadas, unidas con CRLF).

    `all_day=True` → `DTSTART;VALUE=DATE`/`DTEND;VALUE=DATE` (el caller pasa el
    `dtend` ya exclusivo). `all_day=False` → fecha-hora en tiempo flotante.
    `reminders` son valores `TRIGGER` (ej. `-PT15H`, `-PT2H`): por cada uno se
    agrega un `VALARM` de tipo DISPLAY. Útil en el `.ics` que el cliente agrega
    a su calendario (su app le avisa sola); en feeds suscritos los clientes los
    ignoran, así que ahí no se pasan.
    """
    dtstamp = dtstamp or datetime.utcnow()
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_fmt_dt_utc(dtstamp)}",
    ]
    if all_day:
        lines.append(f"DTSTART;VALUE=DATE:{_fmt_date(dtstart)}")
        lines.append(f"DTEND;VALUE=DATE:{_fmt_date(dtend)}")
    else:
        lines.append(f"DTSTART:{_fmt_dt_floating(dtstart)}")
        lines.append(f"DTEND:{_fmt_dt_floating(dtend)}")
    lines.append(f"SUMMARY:{_escape(summary)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    for trigger in reminders:
        lines.extend([
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"TRIGGER:{trigger}",
            f"DESCRIPTION:{_escape(summary)}",
            "END:VALARM",
        ])
    lines.append("END:VEVENT")
    return "\r\n".join(_fold(ln) for ln in lines)


def build_vcalendar(
    vevents: Sequence[str],
    *,
    method: str = "PUBLISH",
    cal_name: str | None = None,
) -> str:
    """Envuelve N `VEVENT` ya construidos en un `VCALENDAR` completo.

    Devuelve el texto final con terminaciones CRLF y newline final, listo para
    servir como `text/calendar` o adjuntar como `.ics`.
    """
    head = [
        "BEGIN:VCALENDAR",
        f"PRODID:{PRODID}",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
    ]
    if cal_name:
        head.append(f"X-WR-CALNAME:{_escape(cal_name)}")
    chunks = ["\r\n".join(_fold(ln) for ln in head)]
    chunks.extend(v for v in vevents if v)
    chunks.append("END:VCALENDAR")
    return "\r\n".join(chunks) + "\r\n"


# ── Adaptador de dominio: una reserva → un VEVENT ────────────────────────────

def _resumen(reserva: Mapping) -> tuple[str, bool]:
    """`SUMMARY` del evento + si es reserva de estudio. Compartido por el VEVENT
    y el link de Google Calendar para que el título sea idéntico en ambos."""
    numero = reserva.get("numero_pedido") or reserva.get("id")
    cliente = (reserva.get("cliente_nombre") or "Cliente").strip()
    es_estudio = (reserva.get("tipo") or "diaria") == "estudio"
    prefijo = "🎬 Estudio: " if es_estudio else ""
    return f"{prefijo}Pedido #{numero} — {cliente}", es_estudio


def _equipos_str(items: Sequence[Mapping] | None) -> str:
    """Lista de equipos legible ("2× Sony FX3, Aputure 600d") o ""."""
    if not items:
        return ""
    equipos = []
    for it in items:
        etiqueta = f"{it.get('marca') or ''} {it.get('nombre') or ''}".strip()
        if not etiqueta:
            continue
        cant = it.get("cantidad") or 1
        equipos.append(f"{cant}× {etiqueta}" if cant and cant != 1 else etiqueta)
    return ", ".join(equipos)


def reserva_to_vevent(
    reserva: Mapping,
    items: Sequence[Mapping] | None = None,
    *,
    link: str = "",
    with_reminders: bool = False,
) -> str:
    """Mapea una fila de `alquileres` (+ sus items opcionales) a un `VEVENT`.

    `reserva` necesita: `id`, `fecha_desde`, `fecha_hasta`, y opcionalmente
    `numero_pedido`, `cliente_nombre`, `estado`, `tipo`. `items` (si se pasan)
    necesitan `nombre`/`marca`/`cantidad` para listar los equipos. `link` es la
    URL que va en la descripción — el caller elige (back-office para el feed del
    dueño; portal del cliente para el adjunto del mail) para no filtrar el link
    interno a quien no corresponde. `with_reminders=True` agrega un recordatorio
    (alquiler diario: ~1 día antes del retiro; estudio: 2h antes) — se usa en el
    `.ics` que el cliente agrega a su calendario, no en el feed suscrito.

    UID estable (`alquiler-{id}@…`) → editar una reserva **actualiza** su evento,
    no lo duplica. Devuelve `""` si la reserva no tiene fecha de inicio.
    """
    rid = reserva.get("id")
    d0 = to_datetime(reserva.get("fecha_desde"))
    if d0 is None or rid is None:
        return ""
    d1 = to_datetime(reserva.get("fecha_hasta")) or d0

    estado = reserva.get("estado") or ""
    summary, es_estudio = _resumen(reserva)

    desc_parts = [f"Estado: {estado}"] if estado else []
    equipos = _equipos_str(items)
    if equipos:
        desc_parts.append("Equipos: " + equipos)
    if link:
        desc_parts.append(link)
    description = "\n".join(desc_parts)

    uid = f"alquiler-{rid}@{_UID_DOMAIN}"
    if es_estudio:
        # Evento con hora; si las horas coinciden, garantizamos 1h de duración.
        # Recordatorio 2h antes (reserva por horas).
        return build_vevent(
            uid=uid, summary=summary, description=description,
            dtstart=d0, dtend=d1 if d1 > d0 else d0 + timedelta(hours=1),
            all_day=False,
            reminders=("-PT2H",) if with_reminders else (),
        )
    # Alquiler diario → all-day; DTEND es exclusivo → día siguiente al fin.
    # Recordatorio -PT15H = 09:00 del día anterior al retiro (el evento all-day
    # arranca a medianoche → -15h cae a las 9am del día previo).
    return build_vevent(
        uid=uid, summary=summary, description=description,
        dtstart=d0, dtend=d1 + timedelta(days=1),
        all_day=True,
        reminders=("-PT15H",) if with_reminders else (),
    )


def google_calendar_url(
    reserva: Mapping,
    items: Sequence[Mapping] | None = None,
    *,
    link: str = "",
) -> str:
    """Link "Agregar a Google Calendar" (`action=TEMPLATE`) para el cuerpo del
    mail — complementa al adjunto `.ics` para clientes que no renderizan la
    tarjeta. Reusa la MISMA distinción diaria/estudio y el mismo título que
    `reserva_to_vevent`, así el evento sale idéntico por las dos vías.

    Devuelve `""` si la reserva no tiene fecha de inicio.
    """
    rid = reserva.get("id")
    d0 = to_datetime(reserva.get("fecha_desde"))
    if d0 is None or rid is None:
        return ""
    d1 = to_datetime(reserva.get("fecha_hasta")) or d0
    summary, es_estudio = _resumen(reserva)

    params = {"action": "TEMPLATE", "text": summary}
    if es_estudio:
        # Con hora: tiempo local + ctz (Google lo ancla a esa zona).
        end = d1 if d1 > d0 else d0 + timedelta(hours=1)
        params["dates"] = f"{_fmt_dt_floating(d0)}/{_fmt_dt_floating(end)}"
        params["ctz"] = _TZID
    else:
        # All-day: fin exclusivo (día siguiente).
        params["dates"] = f"{_fmt_date(d0)}/{_fmt_date(d1 + timedelta(days=1))}"

    detalles = []
    equipos = _equipos_str(items)
    if equipos:
        detalles.append(f"Equipos: {equipos}")
    if link:
        detalles.append(link)
    if detalles:
        params["details"] = "\n".join(detalles)

    return "https://calendar.google.com/calendar/render?" + urlencode(params)


# ── Adaptador de dominio: taller ─────────────────────────────────────────────

def clase_taller_to_vevent(
    clase: Mapping,
    *,
    taller_nombre: str,
    location: str = "",
) -> str:
    """Mapea una clase de taller (fila de
    `services.talleres.queries.clases.clases_de_edicion`) a un `VEVENT`.
    `clase` necesita `id` y `fecha` (string ISO `YYYY-MM-DD`) +
    `hora_inicio_min`/`hora_fin_min`; `titulo`/`descripcion` son opcionales.

    UID estable (`taller-clase-{id}@…`) → re-generar el `.ics` no duplica el
    evento si el cliente ya lo agregó a su calendario. Devuelve `""` si falta
    fecha o id.
    """
    cid = clase.get("id")
    fecha_str = clase.get("fecha")
    if cid is None or not fecha_str:
        return ""
    base = datetime.strptime(fecha_str, "%Y-%m-%d")
    dtstart = base + timedelta(minutes=clase.get("hora_inicio_min") or 0)
    dtend = base + timedelta(minutes=clase.get("hora_fin_min") or 0)
    if dtend <= dtstart:
        dtend = dtstart + timedelta(hours=1)

    titulo = (clase.get("titulo") or "").strip()
    summary = f"{titulo} — {taller_nombre}" if titulo else taller_nombre

    return build_vevent(
        uid=f"taller-clase-{cid}@{_UID_DOMAIN}",
        summary=summary,
        dtstart=dtstart,
        dtend=dtend,
        all_day=False,
        description=clase.get("descripcion") or "",
        location=location,
        reminders=("-PT2H",),
    )


def clases_taller_to_ics(
    clases: Sequence[Mapping],
    *,
    taller_nombre: str,
    location: str = "",
) -> str:
    """Arma el `.ics` con TODAS las clases de una edición de taller — un
    `VEVENT` por clase, no un rango contable único (un taller `semanal` de 16
    clases es 16 eventos puntuales, no "una reserva de 3 meses"; ver bug #445
    / MEMORIA 2026-07-28). Pensado para el adjunto del mail de inscripción
    (reemplaza el botón "Agregar a mi calendario" que vivía en la landing
    pública). Devuelve `""` si ninguna clase tiene fecha/id válidos.
    """
    vevents = []
    for c in clases:
        v = clase_taller_to_vevent(c, taller_nombre=taller_nombre, location=location)
        if v:
            vevents.append(v)
    if not vevents:
        return ""
    return build_vcalendar(vevents, method="PUBLISH", cal_name=taller_nombre)
