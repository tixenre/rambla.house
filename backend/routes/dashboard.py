"""
routes/dashboard.py — Dashboard de métricas y calendario de pedidos.
"""

import datetime

from fastapi import APIRouter, Depends, Query

from database import get_db, now_ar, row_to_dict
from auth.guards import require_admin
from pedidos_vinculados import SIN_PRINCIPAL_SQL
from tipos_pedido import TIPOS_SIN_RETIRO_SQL

router = APIRouter()


def _turnos_embebidos_del_dia(conn, campo: str, valor: str):
    """Turnos EMBEBIDOS (`alquiler_turnos_estudio`, #1308 rediseño "turno como
    ítem") cuya PROPIA `campo` (`fecha_desde`/`fecha_hasta` — literal interno,
    solo lo pasan los 3 call sites de este archivo, nunca input) cae en `valor`
    (YYYY-MM-DD). Mismo shape que las filas de `alquileres` de salen_hoy/
    devuelven_hoy/devuelven_manana, pero con la fecha/hora PROPIA del turno —
    que puede no coincidir con el retiro/devolución de equipos del pedido
    contenedor (`a`, que sigue siendo `tipo='diaria'`) — y su monto propio
    (no el del pedido completo, que puede incluir equipos ajenos al turno)."""
    return conn.execute(f"""
        SELECT a.id, a.cliente_nombre, ate.fecha_desde, ate.fecha_hasta,
               COALESCE((SELECT SUM(subtotal) FROM alquiler_items
                         WHERE turno_estudio_id = ate.id), 0) AS monto_total
        FROM alquiler_turnos_estudio ate
        JOIN alquileres a ON a.id = ate.pedido_id
        WHERE a.estado IN ('confirmado','retirado') AND a.{SIN_PRINCIPAL_SQL}
          AND ate.{campo}::date = %s
        ORDER BY ate.fecha_desde
    """, (valor,)).fetchall()


@router.get("/dashboard")
def get_dashboard(_admin: dict = Depends(require_admin)):
    # now_ar(), no date.today() — este último corre en UTC en la nube/CI y
    # desfasa un día entre 00:00-03:00 UTC (21:00-24:00 hora Argentina),
    # ver services/fechas.py.
    hoy_date = now_ar().date()
    hoy     = hoy_date.isoformat()
    manana  = (hoy_date + datetime.timedelta(days=1)).isoformat()
    mes_ini = hoy[:7] + "-01"
    with get_db() as conn:
        # `SIN_PRINCIPAL_SQL` en los conteos y listas de PEDIDOS: un turno del
        # Estudio vinculado no es un pedido aparte (#1308) — su principal ya está
        # en la lista. `ingresos_mes` (una SUM sin identidad) y el `calendario`
        # (agenda real del espacio) NO lo llevan a propósito: ahí la fila del
        # turno aporta plata/ocupación reales que no están duplicadas.
        pendientes = conn.execute(
            f"SELECT COUNT(*) FROM alquileres WHERE estado='solicitado' AND {SIN_PRINCIPAL_SQL}"
        ).fetchone()[0]

        activos = conn.execute(
            "SELECT COUNT(*) FROM alquileres WHERE estado IN ('confirmado','retirado') "
            f"AND fecha_hasta >= %s AND {SIN_PRINCIPAL_SQL}", (hoy,)
        ).fetchone()[0]

        # Cada lista suma los turnos EMBEBIDOS cuya PROPIA fecha cae hoy/mañana
        # (#1308 rediseño "turno como ítem") — sin esto, un pedido `diaria`
        # mixto cuyo equipo se retira otro día pero tiene un turno del Estudio
        # hoy no aparecería en ningún lado. Se re-ordena por fecha_desde tras
        # combinar (dos queries separadas, no UNION, por la subquery de monto
        # propio del turno).
        salen_hoy = [row_to_dict(r) for r in conn.execute(f"""
            SELECT p.id, p.cliente_nombre, p.fecha_desde, p.fecha_hasta, p.monto_total
            FROM alquileres p
            WHERE estado IN ('confirmado','retirado')
              AND p.tipo NOT IN {TIPOS_SIN_RETIRO_SQL}
              AND p.{SIN_PRINCIPAL_SQL}
              AND p.fecha_desde::date = %s
            ORDER BY p.fecha_desde
        """, (hoy,)).fetchall()]
        salen_hoy.extend(row_to_dict(r) for r in _turnos_embebidos_del_dia(conn, "fecha_desde", hoy))
        salen_hoy.sort(key=lambda r: r["fecha_desde"])

        devuelven_hoy = [row_to_dict(r) for r in conn.execute(f"""
            SELECT p.id, p.cliente_nombre, p.fecha_desde, p.fecha_hasta, p.monto_total
            FROM alquileres p
            WHERE estado IN ('confirmado','retirado') AND p.tipo NOT IN {TIPOS_SIN_RETIRO_SQL}
              AND p.{SIN_PRINCIPAL_SQL}
              AND p.fecha_hasta::date = %s
            ORDER BY p.fecha_hasta
        """, (hoy,)).fetchall()]
        devuelven_hoy.extend(row_to_dict(r) for r in _turnos_embebidos_del_dia(conn, "fecha_hasta", hoy))
        devuelven_hoy.sort(key=lambda r: r["fecha_hasta"])

        devuelven_manana = [row_to_dict(r) for r in conn.execute(f"""
            SELECT p.id, p.cliente_nombre, p.fecha_desde, p.fecha_hasta, p.monto_total
            FROM alquileres p
            WHERE estado IN ('confirmado','retirado') AND p.tipo NOT IN {TIPOS_SIN_RETIRO_SQL}
              AND p.{SIN_PRINCIPAL_SQL}
              AND p.fecha_hasta::date = %s
            ORDER BY p.fecha_hasta
        """, (manana,)).fetchall()]
        devuelven_manana.extend(
            row_to_dict(r) for r in _turnos_embebidos_del_dia(conn, "fecha_hasta", manana)
        )
        devuelven_manana.sort(key=lambda r: r["fecha_hasta"])

        ingresos_mes = conn.execute("""
            SELECT COALESCE(SUM(monto_total), 0) FROM alquileres
            WHERE estado = 'finalizado'
              AND monto_total > 0
              AND monto_pagado >= monto_total
              AND fecha_desde >= %s
        """, (mes_ini,)).fetchone()[0]

        total_clientes = conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]

        equipos_afuera = conn.execute("""
            SELECT e.nombre, mb.nombre AS marca, SUM(pi.cantidad) AS cantidad,
                   p.cliente_nombre, p.fecha_hasta
            FROM alquiler_items pi
            JOIN equipos e ON e.id = pi.equipo_id
            LEFT JOIN marcas mb ON mb.id = e.brand_id
            JOIN alquileres p ON p.id = pi.pedido_id
            WHERE p.estado IN ('confirmado','retirado') AND p.fecha_hasta >= %s
              AND e.es_recurso_interno = FALSE
            GROUP BY pi.equipo_id, p.id, e.nombre, mb.nombre, p.cliente_nombre, p.fecha_hasta
            ORDER BY p.fecha_hasta
        """, (hoy,)).fetchall()

        return {
            "pendientes":       pendientes,
            "activos":          activos,
            "ingresos_mes":     ingresos_mes,
            "total_clientes":   total_clientes,
            "salen_hoy":        salen_hoy,
            "devuelven_hoy":    devuelven_hoy,
            "devuelven_manana": devuelven_manana,
            "equipos_afuera":   [row_to_dict(r) for r in equipos_afuera],
        }


@router.get("/calendario")
def get_calendario(
    desde: str = Query(..., description="YYYY-MM-DD"),
    hasta: str = Query(..., description="YYYY-MM-DD"),
    _admin: dict = Depends(require_admin),
):
    with get_db() as conn:
        # `pi.turno_estudio_id IS NULL`: un pedido `diaria` mixto (#1308) no
        # debe mostrar el centinela del turno mezclado en el label "equipos"
        # de SU fila de equipamiento — el turno tiene su propia fila abajo,
        # con su propia ventana horaria (puede no coincidir con estas fechas).
        rows = conn.execute(f"""
            SELECT p.id, p.numero_pedido, p.cliente_nombre, p.estado, p.tipo,
                   p.fecha_desde, p.fecha_hasta, p.monto_total,
                   STRING_AGG(e.nombre, ' / ') AS equipos
            FROM alquileres p
            JOIN alquiler_items pi ON pi.pedido_id = p.id AND pi.turno_estudio_id IS NULL
            JOIN equipos e ON e.id = pi.equipo_id
            WHERE p.estado IN ('solicitado','confirmado','retirado','devuelto','finalizado')
              AND p.tipo NOT IN {TIPOS_SIN_RETIRO_SQL}
              AND p.fecha_hasta >= %s AND p.fecha_desde <= %s
            GROUP BY p.id, p.numero_pedido, p.cliente_nombre, p.estado, p.tipo,
                     p.fecha_desde, p.fecha_hasta, p.monto_total
            ORDER BY p.fecha_desde
        """, (desde, hasta)).fetchall()

        # Turnos EMBEBIDOS: su propia fila, con su propia ventana horaria —
        # `tipo='estudio'` sintético (mismo criterio que `eventos_estudio` en
        # `estadisticas.py`) para que el front lo coloree vía
        # `estadoClaseEstudio` como cualquier turno del Estudio.
        rows_turnos = conn.execute("""
            SELECT a.id, a.numero_pedido, a.cliente_nombre, a.estado,
                   'estudio' AS tipo, ate.fecha_desde, ate.fecha_hasta,
                   COALESCE((SELECT SUM(subtotal) FROM alquiler_items
                             WHERE turno_estudio_id = ate.id), 0) AS monto_total,
                   (SELECT STRING_AGG(e.nombre, ' / ')
                    FROM alquiler_items ai JOIN equipos e ON e.id = ai.equipo_id
                    WHERE ai.turno_estudio_id = ate.id) AS equipos
            FROM alquiler_turnos_estudio ate
            JOIN alquileres a ON a.id = ate.pedido_id
            WHERE a.estado IN ('solicitado','confirmado','retirado','devuelto','finalizado')
              AND ate.fecha_hasta >= %s AND ate.fecha_desde <= %s
            ORDER BY ate.fecha_desde
        """, (desde, hasta)).fetchall()

        eventos = [row_to_dict(r) for r in rows]
        eventos.extend(row_to_dict(r) for r in rows_turnos)
        eventos.sort(key=lambda r: r["fecha_desde"])
        return eventos
