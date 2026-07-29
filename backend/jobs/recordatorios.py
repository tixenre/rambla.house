"""Job de recordatorios de retiro: el mail "mañana retirás tu pedido".

Pieza única y testeable, sin dependencia de FastAPI/request → la corre tanto el
scheduler in-process (`jobs/scheduler.py`) como el endpoint de prueba on-demand
(`POST /api/admin/recordatorios/retiro/run`).

**Idempotencia (clave):** no la garantiza este código sino el índice único
`idx_emails_log_recordatorio` (`emails_log(alquiler_id, template_key)
WHERE template_key='recordatorio_retiro' AND status='sent'`) → un solo envío
'sent' por pedido. Si el job corre dos veces el mismo día (o el backend se
reinicia después de la corrida), el segundo `send_email` choca contra el índice
y `services.email` lo traga: no re-manda. El barrido además filtra con
`NOT EXISTS` para no intentar siquiera los ya enviados.

Reusa la boca única de envío (`send_email`, canal-agnóstica — decisión
2026-05-27) y el mismo armador de contexto que el resto de los mails de pedido
(`_pedido_email_context`), así el template ve exactamente las mismas variables.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from database import get_db, now_ar, row_to_dict
from jobs.recordatorios_config import resolve as _resolve_config
from pedidos_vinculados import SIN_PRINCIPAL_SQL
from routes.alquileres import _get_alquiler_items, _pedido_email_context
from services.email import send_email
from tipos_pedido import TIPOS_SIN_RETIRO_SQL

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "recordatorio_retiro"

# Solo se le recuerda a pedidos ya **confirmados**: el cliente sabe que la
# reserva va en serio y hay una fecha de retiro firme. Un 'solicitado' todavía
# no es un compromiso → recordarle "mañana retirás" sería incorrecto.
ESTADOS_RECORDABLES = ("confirmado",)


def _pedidos_para_retiro(conn, hoy, dias_antes: int) -> list[dict]:
    """Pedidos con retiro dentro de `dias_antes` días (respecto de `hoy`,
    wall-clock AR), en estado recordable, con email, que todavía no recibieron el
    recordatorio.

    El `NOT EXISTS` contra `emails_log` es la primera línea anti-duplicado (la
    definitiva es el índice único). La ventana es `[día-objetivo 00:00, +1 00:00)`
    para cubrir el día entero sin importar la hora de retiro.

    `a.tipo NOT IN TIPOS_SIN_RETIRO_SQL` (`tipos_pedido.py`, fuente única):
    ninguno de los dos tiene "retiro" real (taller = mes contable completo;
    estudio_fijo = muestra de una recurrencia) — hoy además ninguno de los dos
    setea `cliente_email` al generarse (`_regenerar_pedidos_taller`/
    `_regenerar_pedidos_slot`), así que el filtro de abajo ya los excluye EN LA
    PRÁCTICA; este filtro es explícito a propósito, para no depender de esa
    coincidencia si algún día alguno de los dos empieza a llevar un email real.

    `SIN_PRINCIPAL_SQL` (`pedidos_vinculados.py`) excluye los turnos del Estudio
    VINCULADOS a un pedido de alquiler (#1308): son una sola venta con su
    principal, que ya manda su propio recordatorio — sin este filtro el cliente
    recibía DOS mails, uno de ellos por un "pedido" que para él no existe. Acá
    la coincidencia de `cliente_email` NO salva: el turno vinculado hereda
    forzosamente el email del principal (`_resolver_pedido_principal`) y la
    cascada lo deja en `confirmado`. Es por el EJE, no por `tipo`: un turno del
    Estudio SUELTO (sin principal) sí es un evento propio y sigue recibiendo su
    recordatorio.
    """
    dia_ini = (hoy + timedelta(days=dias_antes)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    dia_fin = dia_ini + timedelta(days=1)
    ph = ",".join(["%s"] * len(ESTADOS_RECORDABLES))
    rows = conn.execute(
        f"""
        SELECT a.id, a.numero_pedido, a.cliente_nombre, a.cliente_email,
               a.cliente_telefono, a.fecha_desde, a.fecha_hasta,
               a.monto_total, a.notas
        FROM alquileres a
        WHERE a.estado IN ({ph})
          AND a.tipo NOT IN {TIPOS_SIN_RETIRO_SQL}
          AND a.{SIN_PRINCIPAL_SQL}
          AND a.fecha_desde >= %s
          AND a.fecha_desde <  %s
          AND a.cliente_email IS NOT NULL
          AND a.cliente_email <> ''
          AND NOT EXISTS (
              SELECT 1 FROM emails_log el
              WHERE el.alquiler_id = a.id
                AND el.template_key = %s
                AND el.status = 'sent'
          )
        ORDER BY a.id
    """,
        (*ESTADOS_RECORDABLES, dia_ini, dia_fin, TEMPLATE_KEY),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def enviar_recordatorios_retiro(
    conn=None, *, hoy=None, dias_antes: int | None = None, dry_run: bool = False
) -> dict:
    """Manda (o simula, si `dry_run`) el recordatorio a cada pedido cuyo retiro
    cae dentro de `dias_antes` días. Devuelve un resumen en lenguaje de datos:
    `{fecha_retiro, dias_antes, candidatos, enviados, fallidos, dry_run, pedidos:[...]}`.

    `conn=None` → abre y cierra su propia conexión (uso del scheduler). Si se le
    pasa una, no la cierra (uso desde un endpoint que ya tiene la suya). `hoy`
    se inyecta en los tests; por defecto es el ahora AR. `dias_antes=None` →
    se resuelve de la config (env > app_settings > default 1).

    Nunca propaga: `send_email` ya traga sus errores y loguea; acá se contabiliza
    el resultado para que el barrido diario no se caiga por un pedido roto.
    """
    propia = conn is None
    if propia:
        conn = get_db()
    hoy = hoy or now_ar()
    if dias_antes is None:
        dias_antes = _resolve_config(conn)["dias_antes"]
    try:
        pedidos = _pedidos_para_retiro(conn, hoy, dias_antes)
        resumen: dict = {
            "fecha_retiro": (hoy + timedelta(days=dias_antes)).date().isoformat(),
            "dias_antes": dias_antes,
            "candidatos": len(pedidos),
            "enviados": 0,
            "fallidos": 0,
            "dry_run": dry_run,
            "pedidos": [],
        }
        for p in pedidos:
            numero = p.get("numero_pedido") or p.get("id")
            entry = {
                "id": p["id"],
                "numero_pedido": numero,
                "cliente_email": p.get("cliente_email"),
            }
            if dry_run:
                entry["status"] = "dry_run"
                resumen["pedidos"].append(entry)
                continue
            p["items"] = _get_alquiler_items(conn, p["id"])
            ctx = _pedido_email_context(p)
            ctx["dias_antes"] = dias_antes  # el copy del recordatorio lo usa
            res = send_email(TEMPLATE_KEY, p["cliente_email"], ctx, p["id"])
            if res.get("ok"):
                resumen["enviados"] += 1
                entry["status"] = "sent"
            else:
                resumen["fallidos"] += 1
                entry["status"] = "failed"
                entry["error"] = res.get("error")
            resumen["pedidos"].append(entry)
        logger.info(
            "Recordatorios de retiro (%s): %d candidatos, %d enviados, %d fallidos, dry_run=%s",
            resumen["fecha_retiro"],
            resumen["candidatos"],
            resumen["enviados"],
            resumen["fallidos"],
            dry_run,
        )
        return resumen
    finally:
        if propia:
            conn.close()
