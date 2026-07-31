"""Job de recordatorios de DEVOLUCIÓN por WhatsApp (canal-only).

Pieza única y testeable (sin FastAPI/request), la corre el scheduler in-process y
un endpoint de prueba on-demand. Tres ventanas independientes sobre pedidos en
estado 'retirado' (el equipo está afuera), según cuándo cae `fecha_hasta`:
  - D-1: la devolución es mañana (víspera).
  - D-0: la devolución es hoy.
  - vencido (D+1): la devolución era ayer y el pedido sigue 'retirado'.

Solo WhatsApp: no hay template de mail de devolución (los recordatorios de
devolución nacieron con el canal WhatsApp). La idempotencia la garantiza el índice
único parcial de `whatsapp_log` (un envío 'sent' por (alquiler_id, template_key));
el `NOT EXISTS` del barrido es la primera línea anti-duplicado. Reusa la boca única
`services.whatsapp.enviar_evento_pedido` (nunca propaga, se autogatea por
credencial/opt-in/E.164) y el mismo armador de contexto que los mails.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from database import get_db, now_ar, row_to_dict
from services.comunicacion import notificar_pedido, pedido_email_context

logger = logging.getLogger(__name__)

# Solo pedidos con el equipo afuera. Un 'confirmado' todavía no se retiró; un
# 'finalizado' ya se devolvió — ninguno corresponde a un recordatorio de devolución.
ESTADO_RECORDABLE = "retirado"

# clave de ventana → (template_key, offset en días de fecha_hasta respecto de hoy).
VENTANAS = {
    "d1": ("recordatorio_devolucion_d1", 1),        # devuelve mañana
    "d0": ("recordatorio_devolucion_d0", 0),        # devuelve hoy
    "vencido": ("recordatorio_devolucion_vencido", -1),  # venció ayer, sin devolver
}


def _pedidos_para_devolucion(conn, hoy, offset_dias: int, template_key: str) -> list[dict]:
    """Pedidos 'retirado' cuya `fecha_hasta` cae en el día `hoy + offset_dias`
    (ventana [00:00, +1 00:00)), que todavía no recibieron ESTE template por
    WhatsApp."""
    dia_ini = (hoy + timedelta(days=offset_dias)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    dia_fin = dia_ini + timedelta(days=1)
    rows = conn.execute(
        """
        SELECT a.id, a.cliente_id, a.numero_pedido, a.cliente_nombre, a.cliente_email,
               a.cliente_telefono, a.fecha_desde, a.fecha_hasta, a.monto_total, a.notas
        FROM alquileres a
        WHERE a.estado = %s
          AND a.fecha_hasta >= %s
          AND a.fecha_hasta <  %s
          AND NOT EXISTS (
              SELECT 1 FROM whatsapp_log wl
              WHERE wl.alquiler_id = a.id
                AND wl.template_key = %s
                AND wl.status = 'sent'
          )
        ORDER BY a.id
    """,
        (ESTADO_RECORDABLE, dia_ini, dia_fin, template_key),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def enviar_recordatorios_devolucion(
    conn=None, *, hoy=None, ventanas=None, dry_run: bool = False
) -> dict:
    """Manda (o simula, si `dry_run`) el recordatorio de devolución por WhatsApp para
    cada ventana activa. `ventanas` es un iterable de claves de `VENTANAS` (default:
    todas). Devuelve `{fecha, ventanas:{clave:{candidatos,enviados,fallidos,...}}}`.

    `conn=None` abre y cierra su propia conexión. Nunca propaga: `enviar_evento_pedido`
    ya traga y loguea sus errores; acá se contabiliza el resultado."""
    propia = conn is None
    if propia:
        conn = get_db()
    hoy = hoy or now_ar()
    activas = set(ventanas) if ventanas is not None else set(VENTANAS)
    try:
        resumen: dict = {"fecha": hoy.date().isoformat(), "dry_run": dry_run, "ventanas": {}}
        for clave in VENTANAS:  # orden estable
            if clave not in activas:
                continue
            template_key, offset = VENTANAS[clave]
            pedidos = _pedidos_para_devolucion(conn, hoy, offset, template_key)
            v = {"candidatos": len(pedidos), "enviados": 0, "fallidos": 0, "saltados": 0, "pedidos": []}
            for p in pedidos:
                numero = p.get("numero_pedido") or p.get("id")
                entry = {"id": p["id"], "numero_pedido": numero}
                if dry_run:
                    entry["status"] = "dry_run"
                    v["pedidos"].append(entry)
                    continue
                ctx = pedido_email_context(p)
                # Evento SOLO_WHATSAPP (así lo declara el registro de comunicación):
                # el despacho devuelve el resultado del canal WhatsApp.
                res = notificar_pedido(template_key, p, ctx)["whatsapp"] or {}
                if res.get("ok") and not res.get("skipped"):
                    v["enviados"] += 1
                    entry["status"] = "sent"
                elif res.get("skipped"):
                    v["saltados"] += 1
                    entry["status"] = "skipped"
                    entry["reason"] = res.get("reason")
                else:
                    v["fallidos"] += 1
                    entry["status"] = "failed"
                    entry["error"] = res.get("error")
                v["pedidos"].append(entry)
            resumen["ventanas"][clave] = v
        logger.info(
            "Recordatorios de devolución (%s): %s",
            resumen["fecha"],
            {k: (vv["candidatos"], vv["enviados"], vv["saltados"], vv["fallidos"]) for k, vv in resumen["ventanas"].items()},
        )
        return resumen
    finally:
        if propia:
            conn.close()
