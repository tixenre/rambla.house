"""Job de recordatorios de retiro: el aviso "se acerca tu retiro".

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

Despacha por la capa única de comunicación (`comunicacion.notificar_pedido`,
decisión 2026-05-27): por dónde sale lo decide la estrategia del evento
`recordatorio_retiro`, con el mismo contexto que el resto de los mails de pedido
(`comunicacion.pedido_email_context`). El barrido no re-lista un pedido ya
alcanzado por CUALQUIER canal (`emails_log` **o** `whatsapp_log`), y cuenta como
"enviado" al cliente sin importar por cuál salió.

## Dos pasadas por día (el aviso depende de la HORA del retiro)

Criterio del dueño: avisar "a las 9 del mismo día" llega tarde para quien retira
temprano. Entonces el barrido corre dos veces (ver `jobs/recordatorios_config.py`):

- **`manana`** — a la hora configurada (default 9): los retiros de HOY que
  todavía no ocurrieron. Además **rescata** a los tempranos que por algún motivo
  no recibieron el aviso de la víspera (mejor tarde que nunca; si ya lo
  recibieron, la idempotencia los saltea).
- **`vispera`** — a la hora de cierre del galpón: los retiros de MAÑANA
  anteriores al corte (los "de mañana temprano").

Ningún pedido recibe dos avisos: las dos pasadas filtran por los mismos logs y
el envío es idempotente por pedido.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from database import get_db, now_ar, row_to_dict
from jobs.recordatorios_config import resolve as _resolve_config
from pedidos_vinculados import SIN_PRINCIPAL_SQL
from routes.alquileres import _get_alquiler_items
from services.comunicacion import notificar_pedido, pedido_email_context
from tipos_pedido import TIPOS_SIN_RETIRO_SQL

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "recordatorio_retiro"

# Solo se le recuerda a pedidos ya **confirmados**: el cliente sabe que la
# reserva va en serio y hay una fecha de retiro firme. Un 'solicitado' todavía
# no es un compromiso → recordarle "mañana retirás" sería incorrecto.
ESTADOS_RECORDABLES = ("confirmado",)


PASADA_MANANA = "manana"    # a la hora configurada: los retiros de hoy
PASADA_VISPERA = "vispera"  # a la hora de cierre: los retiros de mañana temprano
PASADAS = (PASADA_MANANA, PASADA_VISPERA)


def _ventana(ahora, pasada: str, corte_manana: int):
    """`(desde, hasta)` de los retiros que le tocan a esta pasada.

    - `vispera`: mañana desde las 00:00 hasta el corte (los "de mañana temprano").
    - `manana`: desde AHORA hasta el fin de hoy — lo que todavía no pasó (incluye
      el rescate de un retiro temprano de hoy que no recibió el aviso anoche).
    """
    medianoche = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    if pasada == PASADA_VISPERA:
        manana = medianoche + timedelta(days=1)
        return manana, manana.replace(hour=corte_manana)
    return ahora, medianoche + timedelta(days=1)


def _pedidos_para_retiro(conn, desde, hasta) -> list[dict]:
    """Pedidos con retiro en `[desde, hasta)` (wall-clock AR), en estado
    recordable, con email, que todavía no recibieron el recordatorio.

    El `NOT EXISTS` contra `emails_log`/`whatsapp_log` es la primera línea
    anti-duplicado (la definitiva es el índice único) y es lo que hace que las dos
    pasadas del día no puedan pisarse.

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
    ph = ",".join(["%s"] * len(ESTADOS_RECORDABLES))
    rows = conn.execute(
        f"""
        SELECT a.id, a.cliente_id, a.numero_pedido, a.cliente_nombre, a.cliente_email,
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
          AND NOT EXISTS (
              SELECT 1 FROM whatsapp_log wl
              WHERE wl.alquiler_id = a.id
                AND wl.template_key = %s
                AND wl.status = 'sent'
          )
        ORDER BY a.id
    """,
        (*ESTADOS_RECORDABLES, desde, hasta, TEMPLATE_KEY, TEMPLATE_KEY),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def enviar_recordatorios_retiro(
    conn=None, *, hoy=None, pasada: str = PASADA_MANANA,
    corte_manana: int | None = None, dry_run: bool = False,
) -> dict:
    """Manda (o simula, si `dry_run`) el recordatorio a los pedidos que le tocan a
    esta `pasada` (`manana` = los retiros de hoy que faltan; `vispera` = los de
    mañana temprano). Devuelve un resumen en lenguaje de datos:
    `{pasada, desde, hasta, candidatos, enviados, fallidos, dry_run, pedidos:[...]}`.

    `conn=None` → abre y cierra su propia conexión (uso del scheduler). Si se le
    pasa una, no la cierra (uso desde un endpoint que ya tiene la suya). `hoy`
    (el ahora AR) se inyecta en los tests. `corte_manana=None` → se resuelve de la
    config (env > app_settings > default 12).

    Nunca propaga: `send_email` ya traga sus errores y loguea; acá se contabiliza
    el resultado para que el barrido diario no se caiga por un pedido roto.
    """
    propia = conn is None
    if propia:
        conn = get_db()
    hoy = hoy or now_ar()
    if corte_manana is None:
        corte_manana = _resolve_config(conn)["corte_manana"]
    try:
        desde, hasta = _ventana(hoy, pasada, corte_manana)
        pedidos = _pedidos_para_retiro(conn, desde, hasta)
        # El copy dice "hoy" o "mañana" según la pasada: es la MISMA distancia que
        # decidió a quién listar, no un cálculo aparte.
        dias_antes = 1 if pasada == PASADA_VISPERA else 0
        resumen: dict = {
            "pasada": pasada,
            "desde": desde.isoformat(),
            "hasta": hasta.isoformat(),
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
            ctx = pedido_email_context(p)
            ctx["dias_antes"] = dias_antes  # el copy del recordatorio lo usa
            # Despacho plan A/B por la capa única de comunicación: intenta WhatsApp
            # (gateado + idempotente por whatsapp_log) y, si no llegó, cae al mail
            # (idempotente por emails_log). Síncrono (background=None) → devuelve los
            # resultados por canal. Se cuenta "enviado" si el cliente fue alcanzado
            # por CUALQUIERA de los dos canales.
            res = notificar_pedido(TEMPLATE_KEY, p, ctx)
            wa = res.get("whatsapp") or {}
            mail_res = (res.get("mail") or [None])[0] or {}
            wa_ok = bool(
                wa.get("wamid") or (wa.get("skipped") and wa.get("reason") == "duplicado")
            )
            if wa_ok:
                resumen["enviados"] += 1
                entry["status"] = "sent"
                entry["canal"] = "whatsapp"
            elif mail_res.get("ok"):
                resumen["enviados"] += 1
                entry["status"] = "sent"
                entry["canal"] = "mail"
            else:
                resumen["fallidos"] += 1
                entry["status"] = "failed"
                entry["error"] = mail_res.get("error") or wa.get("error")
            resumen["pedidos"].append(entry)
        logger.info(
            "Recordatorios de retiro (pasada %s): %d candidatos, %d enviados, %d fallidos, dry_run=%s",
            resumen["pasada"],
            resumen["candidatos"],
            resumen["enviados"],
            resumen["fallidos"],
            dry_run,
        )
        return resumen
    finally:
        if propia:
            conn.close()
