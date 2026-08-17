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
ya mandada). Este job evita eso con una pre-condición propia, con 2 casos
INDEPENDIENTES (no un solo AND compartido — ver bug real más abajo):

- **(a) generar:** el rango de la edición TOCA el mes actual Y todavía no
  existe un pedido con `fecha_desde` dentro de ese mes.
- **(b) limpiar:** existe CUALQUIER pedido con `fecha_desde` DESPUÉS del mes
  actual — sin importar si el rango de la edición toca el mes actual o no. El
  motor ya borra solo cualquier pedido no conservado (no pasado/pagado/con
  ítems extra); esta pre-condición es lo único que faltaba para que el
  barrido los alcance sin necesitar que un admin edite la edición a mano.

**Bug real (mismo día, encontrado por el dueño en staging tras el primer
fix):** la primera versión de (b) seguía adentro del mismo `AND` que exige
que el rango de la edición toque el mes actual — pero una edición publicada
CON ANTICIPACIÓN (el caso normal: un taller se publica semanas/meses antes de
que arranque) tiene `fecha_inicio` en el FUTURO respecto a hoy mientras
todavía no le llegó su primer mes. Esa edición ya podía tener 4 pedidos
futuros de ANTES de este cambio (sep/oct/nov/dic, creados por el trigger
reactivo viejo) y quedaba completamente afuera del `WHERE` — ni (a) ni (b) se
evaluaban nunca, porque la condición de rango los tapaba a los dos. Por eso
(b) ahora es un `OR` de nivel superior, no anidado dentro del chequeo de
rango: se activa para CUALQUIER edición activa con un pedido futuro de más,
haya arrancado o no. Una vez que solo queda el mes actual (o ninguno, si
todavía no arrancó), (b) deja de disparar y el job no la vuelve a tocar."""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date as _dt_date

from database import get_db, now_ar

logger = logging.getLogger(__name__)


def _ediciones_a_generar(conn, inicio_mes: _dt_date, fin_mes: _dt_date) -> list[dict]:
    """Ediciones activas a las que TODAVÍA les falta algo por resolver: (a) su
    rango toca el mes actual y no tienen el pedido de ese mes, O (b) tienen
    CUALQUIER pedido futuro que el motor tiene que limpiar — (b) es
    independiente de si el rango toca el mes actual (una edición publicada
    con anticipación, que todavía no arrancó, puede arrastrar pedidos futuros
    de antes de este cambio) — ver guard anti-churn arriba."""
    return conn.execute(
        """
        SELECT e.*, t.nombre AS taller_nombre
        FROM ediciones_taller e
        JOIN talleres t ON t.id = e.taller_id
        WHERE e.activo
          AND (
            (
              e.fecha_inicio <= %(fin_mes)s AND e.fecha_fin >= %(inicio_mes)s
              AND NOT EXISTS (
                SELECT 1 FROM alquileres a
                 WHERE a.taller_edicion_id = e.id
                   AND a.fecha_desde >= %(inicio_mes)s AND a.fecha_desde <= %(fin_mes)s
              )
            )
            OR EXISTS (
              SELECT 1 FROM alquileres a
               WHERE a.taller_edicion_id = e.id AND a.fecha_desde > %(fin_mes)s
            )
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
