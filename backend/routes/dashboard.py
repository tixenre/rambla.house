"""
routes/dashboard.py — Dashboard de métricas y calendario de pedidos.
"""

import datetime

from fastapi import APIRouter, Depends, Query

from database import get_db, row_to_dict
from auth.guards import require_admin

router = APIRouter()

# Pedidos DERIVADOS/contables ('taller': mes calendario completo de la edición;
# 'estudio_fijo': solo la primera ocurrencia semanal del mes) — sus fechas NO
# representan un evento real de un día puntual (nadie "sale"/"retira" ese día
# ni el pedido entero "vuelve" en fecha_hasta). 'estudio' (turno real) SÍ queda:
# es un evento real, y puede llevar equipos sueltos reales que sí se retiran.
# Mismo estilo que reservas.ESTADOS_RESERVADO — string SQL ya formado, no un
# tuple Python interpolado (evita depender de que su repr() coincida con SQL).
_TIPOS_NO_RETIRO = "('taller', 'estudio_fijo')"


@router.get("/dashboard")
def get_dashboard(_admin: dict = Depends(require_admin)):
    hoy     = datetime.date.today().isoformat()
    manana  = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    mes_ini = hoy[:7] + "-01"
    with get_db() as conn:
        pendientes = conn.execute(
            "SELECT COUNT(*) FROM alquileres WHERE estado='solicitado'"
        ).fetchone()[0]

        activos = conn.execute(
            "SELECT COUNT(*) FROM alquileres WHERE estado IN ('confirmado','retirado') AND fecha_hasta >= %s", (hoy,)
        ).fetchone()[0]

        salen_hoy = conn.execute(f"""
            SELECT p.id, p.cliente_nombre, p.fecha_desde, p.fecha_hasta, p.monto_total
            FROM alquileres p
            WHERE estado IN ('confirmado','retirado')
              AND p.tipo NOT IN {_TIPOS_NO_RETIRO}
              AND p.fecha_desde::date = %s
            ORDER BY p.fecha_desde
        """, (hoy,)).fetchall()

        devuelven_hoy = conn.execute(f"""
            SELECT p.id, p.cliente_nombre, p.fecha_desde, p.fecha_hasta, p.monto_total
            FROM alquileres p
            WHERE estado IN ('confirmado','retirado') AND p.tipo NOT IN {_TIPOS_NO_RETIRO}
              AND p.fecha_hasta::date = %s
            ORDER BY p.fecha_hasta
        """, (hoy,)).fetchall()

        devuelven_manana = conn.execute(f"""
            SELECT p.id, p.cliente_nombre, p.fecha_desde, p.fecha_hasta, p.monto_total
            FROM alquileres p
            WHERE estado IN ('confirmado','retirado') AND p.tipo NOT IN {_TIPOS_NO_RETIRO}
              AND p.fecha_hasta::date = %s
            ORDER BY p.fecha_hasta
        """, (manana,)).fetchall()

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
            "salen_hoy":        [row_to_dict(r) for r in salen_hoy],
            "devuelven_hoy":    [row_to_dict(r) for r in devuelven_hoy],
            "devuelven_manana": [row_to_dict(r) for r in devuelven_manana],
            "equipos_afuera":   [row_to_dict(r) for r in equipos_afuera],
        }


@router.get("/calendario")
def get_calendario(
    desde: str = Query(..., description="YYYY-MM-DD"),
    hasta: str = Query(..., description="YYYY-MM-DD"),
    _admin: dict = Depends(require_admin),
):
    with get_db() as conn:
        rows = conn.execute(f"""
            SELECT p.id, p.numero_pedido, p.cliente_nombre, p.estado, p.tipo,
                   p.fecha_desde, p.fecha_hasta, p.monto_total,
                   STRING_AGG(e.nombre, ' / ') AS equipos
            FROM alquileres p
            JOIN alquiler_items pi ON pi.pedido_id = p.id
            JOIN equipos e ON e.id = pi.equipo_id
            WHERE p.estado IN ('solicitado','confirmado','retirado','devuelto','finalizado')
              AND p.tipo NOT IN {_TIPOS_NO_RETIRO}
              AND p.fecha_hasta >= %s AND p.fecha_desde <= %s
            GROUP BY p.id, p.numero_pedido, p.cliente_nombre, p.estado, p.tipo,
                     p.fecha_desde, p.fecha_hasta, p.monto_total
            ORDER BY p.fecha_desde
        """, (desde, hasta)).fetchall()
        return [row_to_dict(r) for r in rows]
