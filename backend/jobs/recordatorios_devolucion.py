"""Job de recordatorios de DEVOLUCIÓN.

Pieza única y testeable (sin FastAPI/request), la corre el scheduler in-process y
un endpoint de prueba on-demand. Tres ventanas independientes sobre pedidos en
estado 'retirado' (el equipo está afuera), según cuándo cae `fecha_hasta`:
  - D-1: la devolución es mañana (víspera).
  - D-0: la devolución es hoy.
  - vencido (D+1): la devolución era ayer y el pedido sigue 'retirado'.

Despacha por la capa única de comunicación (`comunicacion.notificar_pedido`): por
dónde sale cada ventana lo decide su evento — nacieron canal-WhatsApp (ese sigue
siendo su default) pero el dueño puede pasarlas a mail o a los dos desde
/admin/comunicacion. Por eso el barrido no re-lista un pedido ya alcanzado por
CUALQUIER canal (`whatsapp_log` **o** `emails_log`) y cuenta "enviado" sin importar
por cuál salió — mismo criterio que `jobs/recordatorios.py` (retiro).
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
# El offset de "d1" (la víspera) es el DEFAULT: la antelación real es configurable
# desde el back-office (`recordatorios_devolucion_dias_antes`, 1-14) y entra por
# `dias_antes` en `enviar_recordatorios_devolucion`. D-0 y "vencido" NO se mueven:
# están atados al día de la devolución y al día siguiente, no son "antelación".
VENTANAS = {
    "d1": ("recordatorio_devolucion_d1", 1),        # víspera (antelación configurable)
    "d0": ("recordatorio_devolucion_d0", 0),        # devuelve hoy
    "vencido": ("recordatorio_devolucion_vencido", -1),  # venció ayer, sin devolver
}

# La única ventana cuya antelación se puede elegir (las otras dos son puntos fijos).
VENTANA_CONFIGURABLE = "d1"


def _pedidos_para_devolucion(conn, hoy, offset_dias: int, template_key: str) -> list[dict]:
    """Pedidos 'retirado' cuya `fecha_hasta` cae en el día `hoy + offset_dias`
    (ventana [00:00, +1 00:00)), que todavía no recibieron ESTE aviso por NINGÚN
    canal (el evento puede salir por WhatsApp, por mail o por los dos)."""
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
          AND NOT EXISTS (
              SELECT 1 FROM emails_log el
              WHERE el.alquiler_id = a.id
                AND el.template_key = %s
                AND el.status = 'sent'
          )
        ORDER BY a.id
    """,
        (ESTADO_RECORDABLE, dia_ini, dia_fin, template_key, template_key),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def enviar_recordatorios_devolucion(
    conn=None, *, hoy=None, ventanas=None, dias_antes: int | None = None, dry_run: bool = False
) -> dict:
    """Manda (o simula, si `dry_run`) el recordatorio de devolución por WhatsApp para
    cada ventana activa. `ventanas` es un iterable de claves de `VENTANAS` (default:
    todas). `dias_antes` es la antelación de la ventana "víspera" (default: la
    configurada en el back-office). Devuelve
    `{fecha, dias_antes, ventanas:{clave:{candidatos,enviados,fallidos,...}}}`.

    `conn=None` abre y cierra su propia conexión. Nunca propaga: `enviar_evento_pedido`
    ya traga y loguea sus errores; acá se contabiliza el resultado."""
    propia = conn is None
    if propia:
        conn = get_db()
    hoy = hoy or now_ar()
    activas = set(ventanas) if ventanas is not None else set(VENTANAS)
    if dias_antes is None:
        from jobs.recordatorios_devolucion_config import resolve as _resolve_dev

        dias_antes = _resolve_dev(conn)["dias_antes"]
    try:
        resumen: dict = {
            "fecha": hoy.date().isoformat(),
            "dry_run": dry_run,
            "dias_antes": dias_antes,
            "ventanas": {},
        }
        for clave in VENTANAS:  # orden estable
            if clave not in activas:
                continue
            template_key, offset = VENTANAS[clave]
            # La víspera usa la antelación elegida; D-0 y "vencido" son fijos.
            if clave == VENTANA_CONFIGURABLE:
                offset = dias_antes
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
                # El canal lo decide la estrategia del evento (WhatsApp, mail o
                # los dos): se cuenta "enviado" si el cliente fue alcanzado por
                # CUALQUIERA de los dos.
                res = notificar_pedido(template_key, p, ctx)
                wa = res.get("whatsapp") or {}
                mail_res = (res.get("mail") or [None])[0] or {}
                wa_ok = wa.get("ok") and not wa.get("skipped")
                if wa_ok or (mail_res.get("ok") and not mail_res.get("skipped")):
                    v["enviados"] += 1
                    entry["status"] = "sent"
                    entry["canal"] = "whatsapp" if wa_ok else "mail"
                elif wa.get("skipped") or mail_res.get("skipped"):
                    v["saltados"] += 1
                    entry["status"] = "skipped"
                    entry["reason"] = wa.get("reason") or mail_res.get("reason")
                else:
                    v["fallidos"] += 1
                    entry["status"] = "failed"
                    entry["error"] = wa.get("error") or mail_res.get("error")
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
