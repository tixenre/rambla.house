"""Job de reintento de envíos de comunicación fallidos (mail + WhatsApp).

Antes de esto, un envío que fallaba (Meta/Resend caídos unos minutos, timeout
de red, rate-limit) quedaba en `status='failed'` en `emails_log`/`whatsapp_log`
para siempre — un humano tenía que notarlo y reenviar a mano. Corre en el
mismo scheduler in-process (`jobs/scheduler.py`, cero costo de infra nuevo) y
reintenta, POR EVENTO del registro (`services/comunicacion/eventos.py`), los
pedidos que:

  1. tienen al menos un intento 'failed' reciente (mail o WhatsApp) para ese
     evento, dentro de `VENTANA_HORAS`;
  2. NO tienen ningún 'sent' — en NINGÚN canal — para ese evento (si el plan
     A/B ya alcanzó al cliente por el otro canal, reintentar el que falló
     mandaría un aviso DUPLICADO por otra vía, violando "nunca los dos" salvo
     que el evento sea `AMBOS`);
  3. no acumularon ya `MAX_INTENTOS` intentos totales (una credencial rota no
     se reintenta para siempre).

Reusa `comunicacion.notificar_pedido` — la MISMA puerta que el disparo
original — así el reintento hereda el plan A/B, el gating y la idempotencia
sin reimplementar nada. Nunca propaga: un pedido roto no frena a los demás.
"""
from __future__ import annotations

import logging

from database import get_db, row_to_dict
from routes.alquileres import _get_alquiler_items
from services.comunicacion import notificar_pedido, pedido_email_context
from services.comunicacion.eventos import REGISTRO, EventoComunicacion

logger = logging.getLogger(__name__)

VENTANA_HORAS = 24
MAX_INTENTOS = 3

_COLUMNAS_PEDIDO = """
    a.id, a.cliente_id, a.tipo, a.numero_pedido, a.cliente_nombre, a.cliente_email,
    a.cliente_telefono, a.fecha_desde, a.fecha_hasta, a.monto_total, a.notas
"""


def _template_keys(evento: EventoComunicacion) -> list[str]:
    """Los template_key (de cualquiera de los dos canales) que identifican a
    ESTE evento en los logs — lo que hace falta para saber si "ya llegó"."""
    keys: list[str] = []
    if evento.mail and evento.mail.template_cliente:
        keys.append(evento.mail.template_cliente)
    if evento.whatsapp:
        keys.append(evento.whatsapp)
    return keys


def _pedidos_a_reintentar(conn, template_keys: list[str]) -> list[int]:
    """Un solo scan (UNION ALL + agregación) por evento: sin duplicar el mismo
    `= ANY(%s)` cinco veces. Ver criterio 1-3 en el docstring del módulo."""
    if not template_keys:
        return []
    rows = conn.execute(
        """
        WITH logs AS (
            SELECT alquiler_id, status, sent_at FROM emails_log WHERE template_key = ANY(%s)
            UNION ALL
            SELECT alquiler_id, status, sent_at FROM whatsapp_log WHERE template_key = ANY(%s)
        ),
        agregado AS (
            SELECT alquiler_id,
                   COUNT(*) FILTER (
                       WHERE status = 'failed'
                         AND sent_at > NOW() - make_interval(hours => %s)
                   ) AS fallidos_recientes,
                   COUNT(*) FILTER (WHERE status = 'sent') AS exitosos,
                   COUNT(*) AS intentos_totales
            FROM logs
            WHERE alquiler_id IS NOT NULL
            GROUP BY alquiler_id
        )
        SELECT alquiler_id FROM agregado
         WHERE fallidos_recientes > 0 AND exitosos = 0 AND intentos_totales < %s
         ORDER BY alquiler_id
        """,
        (template_keys, template_keys, VENTANA_HORAS, MAX_INTENTOS),
    ).fetchall()
    return [r["alquiler_id"] for r in rows]


def _fetch_pedido(conn, pedido_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {_COLUMNAS_PEDIDO} FROM alquileres a WHERE a.id = %s", (pedido_id,)
    ).fetchone()
    if not row:
        return None
    pedido = row_to_dict(row)
    pedido["items"] = _get_alquiler_items(conn, pedido_id)
    return pedido


def reintentar_fallidos(conn=None) -> dict:
    """Reintenta, evento por evento, los pedidos candidatos. Devuelve
    `{evento: {candidatos, reintentados}}`. `conn=None` abre/cierra su propia
    conexión (uso del scheduler); si se pasa una, no la cierra (uso desde un
    endpoint on-demand). Nunca propaga."""
    propia = conn is None
    if propia:
        conn = get_db()
    resumen: dict[str, dict] = {}
    try:
        for evento in REGISTRO.values():
            keys = _template_keys(evento)
            try:
                candidatos = _pedidos_a_reintentar(conn, keys)
            except Exception:
                logger.exception("reintentar_comunicacion: falló buscar candidatos de %s", evento.key)
                continue
            reintentados = 0
            for pedido_id in candidatos:
                try:
                    pedido = _fetch_pedido(conn, pedido_id)
                    if pedido is None:
                        continue
                    ctx = pedido_email_context(pedido)
                    notificar_pedido(evento.key, pedido, ctx)
                    reintentados += 1
                except Exception:
                    logger.exception(
                        "reintentar_comunicacion: falló el reintento de %s para pedido %s",
                        evento.key, pedido_id,
                    )
            if candidatos:
                logger.info(
                    "reintentar_comunicacion: evento=%s candidatos=%d reintentados=%d",
                    evento.key, len(candidatos), reintentados,
                )
            resumen[evento.key] = {"candidatos": len(candidatos), "reintentados": reintentados}
        return resumen
    finally:
        if propia:
            conn.close()
