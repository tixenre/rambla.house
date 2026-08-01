"""Dashboard de uso + equipos sin serie (#501 fase a — extraído de `core`).

Endpoints admin de estadísticas/auditoría del catálogo (ranking de uso, por
cobrar, equipos sin serie). Registran sus rutas en el router compartido del
paquete `routes.equipos`. `admin_dashboard_uso` y `admin_equipos_sin_serie` los
importan tests (test_estudio) vía el `__init__` del paquete (re-export).
"""
from fastapi import Request

from auth.guards import require_admin
from database import MARCA_SUBQUERY, get_db, row_to_dict
from pedidos_vinculados import SIN_PRINCIPAL_SQL, TURNO_VINCULADO_SQL
from routes.equipos.core import router


@router.get("/admin/dashboard/uso")
def admin_dashboard_uso(request: Request, dias_sin_uso: int = 90):
    """Dashboard de uso de equipos: top alquilados, sin movimiento, revenue
    por categoría. v1 con métricas clave (#205).

    `dias_sin_uso` (default 90): umbral para considerar un equipo "sin
    movimiento". Equipos cuyo último alquiler fue hace más días aparecen
    como candidatos a revisar/vender.
    """
    require_admin(request)
    with get_db() as conn:
        # ── Top 10 más alquilados (cantidad de pedidos + revenue total) ──
        top_alquilados = conn.execute(f"""
            SELECT
                e.id, e.nombre, {MARCA_SUBQUERY}, e.modelo, e.foto_url,
                COUNT(DISTINCT p.id) AS cant_pedidos,
                SUM(
                    COALESCE(pi.precio_jornada, 0) * COALESCE(pi.cantidad, 1)
                    -- `cobro_modo='fijo'` (líneas personalizadas, combos, turno del
                    -- Estudio EMBEBIDO #1308) ya cobra el monto único — multiplicarlo
                    -- por los días DEL PEDIDO (container, puede no tener nada que ver
                    -- con la duración real de esa línea) inflaba el revenue atribuido.
                    * CASE WHEN pi.cobro_modo = 'jornada'
                           THEN GREATEST(1, (p.fecha_hasta::date - p.fecha_desde::date))
                           ELSE 1
                      END::INTEGER
                ) AS revenue_total
            FROM equipos e
            JOIN alquiler_items pi ON pi.equipo_id = e.id
            JOIN alquileres p ON p.id = pi.pedido_id
            WHERE e.eliminado_at IS NULL AND e.es_recurso_interno = FALSE
            GROUP BY e.id, e.nombre, e.modelo, e.foto_url
            ORDER BY cant_pedidos DESC, revenue_total DESC
            LIMIT 10
        """).fetchall()

        # ── Equipos sin movimiento (último alquiler hace > N días, o nunca) ──
        sin_uso = conn.execute(f"""
            SELECT
                e.id, e.nombre, {MARCA_SUBQUERY}, e.modelo, e.foto_url, e.valor_reposicion,
                MAX(p.fecha_desde) AS ultimo_alquiler,
                COUNT(DISTINCT p.id) AS total_alquileres
            FROM equipos e
            LEFT JOIN alquiler_items pi ON pi.equipo_id = e.id
            LEFT JOIN alquileres p ON p.id = pi.pedido_id
            WHERE e.eliminado_at IS NULL AND e.es_recurso_interno = FALSE
            GROUP BY e.id, e.nombre, e.modelo, e.foto_url, e.valor_reposicion
            HAVING (MAX(p.fecha_desde) IS NULL OR MAX(p.fecha_desde) < (CURRENT_DATE - (%s || ' days')::INTERVAL))
            ORDER BY ultimo_alquiler ASC NULLS FIRST
            LIMIT 25
        """, (dias_sin_uso,)).fetchall()

        # ── Revenue por categoría (top 10) ──
        por_categoria = conn.execute("""
            SELECT
                cat.id, cat.nombre,
                COUNT(DISTINCT p.id) AS cant_pedidos,
                SUM(
                    COALESCE(pi.precio_jornada, 0) * COALESCE(pi.cantidad, 1)
                    -- `cobro_modo='fijo'` (líneas personalizadas, combos, turno del
                    -- Estudio EMBEBIDO #1308) ya cobra el monto único — multiplicarlo
                    -- por los días DEL PEDIDO (container, puede no tener nada que ver
                    -- con la duración real de esa línea) inflaba el revenue atribuido.
                    * CASE WHEN pi.cobro_modo = 'jornada'
                           THEN GREATEST(1, (p.fecha_hasta::date - p.fecha_desde::date))
                           ELSE 1
                      END::INTEGER
                ) AS revenue_total
            FROM categorias cat
            JOIN equipo_categorias ec ON ec.categoria_id = cat.id
            JOIN alquiler_items pi ON pi.equipo_id = ec.equipo_id
            JOIN alquileres p ON p.id = pi.pedido_id
            JOIN equipos e ON e.id = ec.equipo_id
            -- `es_recurso_interno = FALSE` (hallazgo de auditoría, #1308): sin
            -- esto, si el centinela del Estudio ("Estudio (espacio)") alguna vez
            -- tuviera una categoría asignada, su revenue inflaría esa categoría
            -- — mismo filtro que ya usan top_alquilados/sin_uso/totales acá.
            WHERE e.eliminado_at IS NULL AND e.es_recurso_interno = FALSE
            GROUP BY cat.id, cat.nombre
            ORDER BY revenue_total DESC NULLS LAST
            LIMIT 10
        """).fetchall()

        # ── Stats globales ──
        totales = conn.execute("""
            SELECT
                COUNT(DISTINCT e.id) AS total_equipos,
                COUNT(DISTINCT CASE WHEN e.visible_catalogo = 1 THEN e.id END) AS total_visibles,
                COUNT(DISTINCT p.id) AS total_pedidos,
                SUM(
                    COALESCE(pi.precio_jornada, 0) * COALESCE(pi.cantidad, 1)
                    -- `cobro_modo='fijo'` (líneas personalizadas, combos, turno del
                    -- Estudio EMBEBIDO #1308) ya cobra el monto único — multiplicarlo
                    -- por los días DEL PEDIDO (container, puede no tener nada que ver
                    -- con la duración real de esa línea) inflaba el revenue atribuido.
                    * CASE WHEN pi.cobro_modo = 'jornada'
                           THEN GREATEST(1, (p.fecha_hasta::date - p.fecha_desde::date))
                           ELSE 1
                      END::INTEGER
                ) AS revenue_total
            FROM equipos e
            LEFT JOIN alquiler_items pi ON pi.equipo_id = e.id
            LEFT JOIN alquileres p ON p.id = pi.pedido_id
            WHERE e.eliminado_at IS NULL AND e.es_recurso_interno = FALSE
        """).fetchone()

        # ── Cuentas por cobrar ───────────────────────────────────────────
        # Suma de (monto_total - monto_pagado) sobre pedidos confirmados pero
        # no totalmente pagos. Independiente de la fecha del alquiler — incluye
        # los que ya terminaron y siguen debiendo, y los futuros que ya están
        # confirmados.
        #
        # Excluye estados borrador / presupuesto (todavía no son ventas) y
        # cancelado (ventas que no van).
        #
        # Un turno del Estudio vinculado (`pedido_principal_id`) no tiene fila
        # propia acá (`SIN_PRINCIPAL_SQL`) — su saldo pendiente se suma al de
        # su pedido principal (subquery `t`, excluye turnos cancelados) para
        # no subestimar lo cobrable con una fila oculta.
        por_cobrar_rows = conn.execute(f"""
            SELECT
                p.id,
                p.numero_pedido,
                p.estado,
                COALESCE(c.nombre || ' ' || c.apellido, p.cliente_nombre) AS cliente,
                p.fecha_desde, p.fecha_hasta,
                p.monto_total,
                p.monto_pagado,
                (
                    COALESCE(p.monto_total, 0) - COALESCE(p.monto_pagado, 0)
                    + COALESCE(t.pendiente_turnos, 0)
                ) AS pendiente
            FROM alquileres p
            LEFT JOIN clientes c ON c.id = p.cliente_id
            LEFT JOIN (
                SELECT pedido_principal_id AS principal_id,
                       SUM(COALESCE(monto_total, 0) - COALESCE(monto_pagado, 0)) AS pendiente_turnos
                FROM alquileres
                WHERE {TURNO_VINCULADO_SQL} AND estado <> 'cancelado'
                GROUP BY pedido_principal_id
            ) t ON t.principal_id = p.id
            WHERE p.estado IN ('confirmado', 'retirado', 'devuelto', 'finalizado')
              AND {SIN_PRINCIPAL_SQL}
              AND (
                    COALESCE(p.monto_total, 0) - COALESCE(p.monto_pagado, 0)
                    + COALESCE(t.pendiente_turnos, 0)
                  ) > 0
            ORDER BY pendiente DESC
            LIMIT 50
        """).fetchall()

        por_cobrar_items = [row_to_dict(r) for r in por_cobrar_rows]
        por_cobrar_total = sum(r.get("pendiente") or 0 for r in por_cobrar_items)

        return {
            "totales": row_to_dict(totales) if totales else {},
            "top_alquilados": [row_to_dict(r) for r in top_alquilados],
            "sin_uso": [row_to_dict(r) for r in sin_uso],
            "por_categoria": [row_to_dict(r) for r in por_categoria],
            "dias_sin_uso_threshold": dias_sin_uso,
            "por_cobrar": {
                "total": por_cobrar_total,
                "count": len(por_cobrar_items),
                "items": por_cobrar_items[:20],   # top 20 mostrados; el resto suma al total
            },
        }


@router.get("/admin/equipos/sin-serie")
def admin_equipos_sin_serie(request: Request):
    """Lista equipos sin número de serie cargado.

    Útil para que el admin priorice completar el inventario (issue #91).
    Ordena por valor de reposición DESC — primero los equipos más caros
    (importantes para identificar en caso de pérdida/daño).

    Considera \"sin serie\" cualquier valor NULL, vacío o solo espacios.
    NOTA: 'N/A' es un valor válido — significa \"no aplica\" (reflectores,
    cables sin serie, etc.). El admin lo seteó explícitamente, no falta.
    """
    require_admin(request)
    with get_db() as conn:
        rows = conn.execute(f"""
            SELECT e.id, e.nombre, {MARCA_SUBQUERY}, e.modelo, e.foto_url,
                   e.valor_reposicion, e.dueno, e.cantidad
            FROM equipos e
            WHERE e.es_recurso_interno = FALSE
              AND (e.serie IS NULL OR TRIM(e.serie) = '')
            ORDER BY COALESCE(e.valor_reposicion, 0) DESC, e.id ASC
        """).fetchall()
        return {
            "total": len(rows),
            "equipos": [row_to_dict(r) for r in rows],
        }
