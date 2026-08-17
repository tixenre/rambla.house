"""Genera el pedido mensual de un taller recién cuando el mes arranca (pedido
explícito del dueño, 2026-08-13: no quiere N pedidos abiertos en simultáneo
mucho antes de que corresponda cobrarlos — antes una edición de 6 meses nacía
de una con 6 pedidos ya creados).

`_regenerar_pedidos_taller` (el motor, `services/talleres/commands/economia.py`)
ya solo inserta el pedido del MES ACTUAL — este job es lo que hace que "mes
actual" avance solo: corre 1×/día desde el mismo scheduler in-process que ya
corre recordatorios/cleanup/reconciliación (`jobs/scheduler.py`, cero costo de
infra nuevo).

**Guard anti-churn (importante):** el motor recalcula y BORRA+RECREA el
pedido del mes si no está pagado y no tiene ítems extra — correcto cuando lo
dispara un admin editando la Economía a mitad de mes, pero un job que corriera
así TODOS LOS DÍAS le cambiaría el `id`/`numero_pedido` al pedido del mes cada
vez que corre, aunque nada haya cambiado (rompe cualquier link/mail/referencia
ya mandada). Este job evita eso con una pre-condición propia: solo llama al
motor para una edición si TODAVÍA NO existe ningún pedido con `fecha_desde`
dentro del mes actual — una vez que nace, el job no la vuelve a tocar (queda
estable hasta el próximo mes, o hasta que un admin la edite a mano, que sigue
recalculando como siempre)."""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date as _dt_date

from database import get_db, now_ar

logger = logging.getLogger(__name__)


def _ediciones_a_generar(conn, inicio_mes: _dt_date, fin_mes: _dt_date) -> list[dict]:
    """Ediciones activas cuyo rango toca el mes actual y que TODAVÍA no tienen
    un pedido con `fecha_desde` en ese mes — ver guard anti-churn arriba."""
    return conn.execute(
        """
        SELECT e.*, t.nombre AS taller_nombre
        FROM ediciones_taller e
        JOIN talleres t ON t.id = e.taller_id
        WHERE e.activo
          AND e.fecha_inicio <= %(fin_mes)s AND e.fecha_fin >= %(inicio_mes)s
          AND NOT EXISTS (
            SELECT 1 FROM alquileres a
             WHERE a.taller_edicion_id = e.id
               AND a.fecha_desde >= %(inicio_mes)s AND a.fecha_desde <= %(fin_mes)s
          )
        ORDER BY e.id
        """,
        {"inicio_mes": inicio_mes, "fin_mes": fin_mes},
    ).fetchall()


def regenerar_pedidos_talleres_del_mes(conn=None) -> int:
    """Genera el pedido del mes actual para toda edición que todavía no lo
    tenga. Devuelve cuántas ediciones lo generaron en esta pasada (0 =
    no-op, esperado la mayoría de los días — la mayoría de las ediciones ya
    tienen el pedido del mes desde el día 1).

    `conn=None` abre/cierra su propia conexión (uso del scheduler, un pase de
    lectura + una transacción propia por edición: una edición que falla no
    frena a las demás); si se pasa una, la reusa para el pase de lectura
    (uso desde tests/on-demand) — mismo contrato que `reintentar_fallidos`.
    Nunca propaga: un error en una edición no debe tumbar el scheduler."""
    # Imports perezosos: evitan cargar `routes.alquileres` (y su árbol de
    # imports) solo por importar este módulo — mismo motivo que el resto de
    # `jobs/` que tocan pedidos (ver `jobs/reintentar_comunicacion.py`).
    from routes.alquileres import _next_numero_pedido
    from services.talleres.commands.economia import _regenerar_pedidos_taller

    hoy = now_ar().date()
    inicio_mes = hoy.replace(day=1)
    fin_mes = _dt_date(hoy.year, hoy.month, monthrange(hoy.year, hoy.month)[1])

    propia = conn is None
    if propia:
        conn = get_db()
    try:
        ediciones = _ediciones_a_generar(conn, inicio_mes, fin_mes)
    finally:
        if propia:
            conn.close()

    generadas = 0
    for edicion in ediciones:
        with get_db() as c:
            try:
                _regenerar_pedidos_taller(
                    c, edicion, edicion["taller_nombre"], numero_pedido_fn=_next_numero_pedido,
                )
                c.commit()
                generadas += 1
            except Exception:
                c.rollback()
                logger.exception(
                    "regenerar_pedidos_talleres: falló la edición %s en el barrido mensual",
                    edicion["id"],
                )
    if generadas:
        logger.info(
            "regenerar_pedidos_talleres: generó el pedido del mes para %d edición(es)", generadas
        )
    return generadas
