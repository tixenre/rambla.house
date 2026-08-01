"""routes/calendar.py — feed iCal suscribible de las reservas.

Expone las reservas como un calendario `.ics` que se puede **suscribir** en
Google/Apple/Outlook Calendar (el patrón "pegá esta URL" de Booqable). Es de una
sola vía y **solo lectura**: el motor de reservas (`backend/reservas/`) sigue
siendo la única fuente de verdad; el calendario es un espejo.

La generación del iCal vive en `services/ical.py` (fuente única, compartida con el
adjunto del mail de confirmación). Acá solo está el endpoint público (protegido
por token) y los dos endpoints admin para obtener/rotar ese token.

Seguridad: el token vive en `app_settings['ical_feed_token']`. NO se expone por el
`GET /settings/{key}` (que es público) → por eso hay endpoints admin dedicados.
"""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, Request, Response

from config import SITE_URL
from database import get_db, now_ar, MARCA_NOMBRE_EXPR
from rate_limit import limiter
from services.ical import build_vcalendar, reserva_to_vevent
from auth.guards import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()

_TOKEN_KEY = "ical_feed_token"
_CAL_NAME = "Rambla Rental — Reservas"
_VENTANA_DIAS = 60  # cuánto hacia atrás incluimos (acota el tamaño del .ics)

# Estados que se muestran en el calendario: confirmados en adelante. Es
# DISTINTO de `reservas.estados.ESTADOS_RESERVADO` (que incluye 'solicitado'
# porque reserva stock) — acá el dueño eligió NO mostrar cotizaciones tentativas.
_ESTADOS_FEED = ("confirmado", "retirado", "devuelto", "finalizado")


# ── Token (app_settings) ─────────────────────────────────────────────────────

def _get_token(conn) -> str:
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = %s", (_TOKEN_KEY,)
    ).fetchone()
    return (row["value"] or "").strip() if row else ""


def _set_token(conn, token: str, actor: str) -> None:
    conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at, updated_by)
        VALUES (%s, %s, CURRENT_TIMESTAMP, %s)
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value,
            updated_at = CURRENT_TIMESTAMP,
            updated_by = EXCLUDED.updated_by
        """,
        (_TOKEN_KEY, token, actor),
    )
    conn.commit()


def _ensure_token(conn, actor: str) -> str:
    """Devuelve el token; si todavía no hay uno, lo genera y persiste."""
    token = _get_token(conn)
    if not token:
        token = secrets.token_urlsafe(32)
        _set_token(conn, token, actor)
    return token


def _feed_url(token: str) -> str:
    return f"{SITE_URL}/calendar/feed.ics?token={token}"


# ── Endpoint público (suscripción) ───────────────────────────────────────────

@router.get("/calendar/feed.ics", include_in_schema=False)
@limiter.limit("30/minute")
def feed_ical(request: Request, token: str = ""):
    """Feed iCal de reservas confirmadas. Protegido por token en la query.

    Token inválido/ausente → 404 (no 401: no revelamos que el recurso existe).
    Si la BD falla, devolvemos un VCALENDAR vacío válido (no 500), como degrada
    el sitemap. Rate-limit por IP (defensa ante scraping del endpoint público).
    """
    vevents: list[str] = []
    try:
        with get_db() as conn:
            real = _get_token(conn)
            # compare_digest evita timing attacks; si no hay token configurado,
            # el feed está deshabilitado → 404 ante cualquier valor.
            if not real or not token or not secrets.compare_digest(token, real):
                return Response(status_code=404)

            corte = now_ar() - timedelta(days=_VENTANA_DIAS)
            reservas = conn.execute(
                f"""
                SELECT id, numero_pedido, cliente_nombre, estado, tipo,
                       fecha_desde, fecha_hasta
                FROM alquileres
                WHERE estado IN ({','.join('%s' for _ in _ESTADOS_FEED)})
                  AND fecha_hasta >= %s
                ORDER BY fecha_desde
                """,
                (*_ESTADOS_FEED, corte),
            ).fetchall()

            items_por_pedido = _items_por_pedido(conn, [r["id"] for r in reservas])
            for r in reservas:
                # El feed es del dueño → link al back-office del pedido.
                ve = reserva_to_vevent(
                    r, items_por_pedido.get(r["id"], []),
                    link=f"{SITE_URL}/admin/pedidos/{r['id']}",
                )
                if ve:
                    vevents.append(ve)
    except Exception:
        logger.error("feed_ical: error generando el calendario", exc_info=True)
        vevents = []

    body = build_vcalendar(vevents, method="PUBLISH", cal_name=_CAL_NAME)
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": 'inline; filename="rambla-reservas.ics"',
        },
    )


def _items_por_pedido(conn, pedido_ids: list[int]) -> dict[int, list[dict]]:
    """Trae los equipos de varios pedidos en una query (evita N+1)."""
    if not pedido_ids:
        return {}
    placeholders = ",".join("%s" for _ in pedido_ids)
    rows = conn.execute(
        f"""
        SELECT pi.pedido_id, pi.cantidad, e.nombre, {MARCA_NOMBRE_EXPR} AS marca
        FROM alquiler_items pi
        JOIN equipos e ON e.id = pi.equipo_id
        WHERE pi.pedido_id IN ({placeholders})
          -- `turno_estudio_id IS NULL` (#1308 rediseño "turno como ítem"): el
          -- centinela/sueltos/pintura de un turno del Estudio EMBEBIDO se usan
          -- ENTERO adentro del Estudio — nunca salen con el cliente — así que
          -- no pertenecen a la descripción de "equipos" del evento del
          -- calendario (mismo criterio que Contrato/Detalle de seguro/
          -- Checklist de retiro, hallazgo de auditoría).
          AND pi.turno_estudio_id IS NULL
        """,
        pedido_ids,
    ).fetchall()
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(r["pedido_id"], []).append(
            {"nombre": r["nombre"], "marca": r["marca"], "cantidad": r["cantidad"]}
        )
    return out


# ── Endpoints admin (gestión del token / URL) ────────────────────────────────

def _actor(session) -> str:
    """Quién hizo el cambio, para `app_settings.updated_by`. Mismo idiom que
    `routes/settings.py` (trunca a 255 — la columna es VARCHAR(255))."""
    if not isinstance(session, dict):
        return "admin"
    return (session.get("email") or session.get("user_id") or "admin")[:255]


@router.get("/api/admin/calendar/feed")
def get_calendar_feed(request: Request):
    """Devuelve la URL del feed (genera el token la primera vez)."""
    guard = require_admin(request)
    actor = _actor(guard)
    with get_db() as conn:
        token = _ensure_token(conn, actor)
    return {"url": _feed_url(token), "token": token, "enabled": bool(token)}


@router.post("/api/admin/calendar/feed/regenerate")
def regenerate_calendar_feed(request: Request):
    """Rota el token → la URL anterior deja de funcionar."""
    guard = require_admin(request)
    actor = _actor(guard)
    with get_db() as conn:
        token = secrets.token_urlsafe(32)
        _set_token(conn, token, actor)
    return {"url": _feed_url(token), "token": token, "enabled": True}
