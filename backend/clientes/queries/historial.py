"""
Historial de pedidos de un cliente — resumen LIVIANO para la ficha admin (una
línea por pedido, equipos aplanados a texto). No es el mismo caso de uso que
"mis pedidos" del portal (`routes/cliente_portal/pedidos.py`): ese devuelve
el detalle rico (items completos, pagos, desglose, documentos) para el
dashboard de autoservicio — dominios de lectura distintos, no se fuerzan a
una sola forma.
"""
from database import row_to_dict
from pedidos_vinculados import SIN_PRINCIPAL_SQL, TURNO_VINCULADO_SQL


def resumen(conn, cliente_id: int) -> list[dict]:
    """Una línea por pedido REAL del cliente. Un turno del Estudio vinculado
    (`pedido_principal_id`) no es un pedido propio (#1308): se excluye de la
    lista y su plata se consolida en la fila de su principal — igual que en
    "Cuentas por cobrar" (`routes/equipos/dashboard.py`) y en el portal. Sin
    consolidar, ocultar la fila haría que el "total gastado" de la ficha
    quedara por debajo de lo que el cliente realmente pagó.

    `turnos_estudio` deja ver cuántos turnos aporta la fila (suma VINCULADOS +
    EMBEBIDOS, #1308 rediseño "turno como ítem" — antes solo contaba
    vinculados, mostrando 0 para un pedido cuyo turno es embebido). Un turno
    EMBEBIDO no suma plata acá (a diferencia del vinculado): su monto YA está
    adentro de `p.monto_total`/`p.monto_pagado` — sumarlo de nuevo duplicaría.
    """
    rows = conn.execute(
        f"""
        SELECT p.id, p.numero_pedido, p.estado, p.fecha_desde, p.fecha_hasta,
               p.monto_total + COALESCE(t.total_turnos, 0)   AS monto_total,
               p.monto_pagado + COALESCE(t.pagado_turnos, 0) AS monto_pagado,
               COALESCE(t.cant_turnos, 0) + COALESCE(te.cant_embebidos, 0) AS turnos_estudio,
               p.descuento_pct, p.created_at,
               STRING_AGG(e.nombre, ' · ') AS equipos
        FROM alquileres p
        -- `turno_estudio_id IS NULL`: el centinela/sueltos/pintura de un turno
        -- del Estudio EMBEBIDO no son equipo que este cliente "alquiló" en el
        -- sentido de este resumen — se usan enteros adentro del Estudio
        -- (mismo criterio que Contrato/Detalle de seguro/Checklist de retiro).
        LEFT JOIN alquiler_items pi ON pi.pedido_id = p.id AND pi.turno_estudio_id IS NULL
        LEFT JOIN equipos e ON e.id = pi.equipo_id
        LEFT JOIN (
            SELECT pedido_principal_id AS principal_id,
                   COUNT(*)                     AS cant_turnos,
                   COALESCE(SUM(monto_total), 0)  AS total_turnos,
                   COALESCE(SUM(monto_pagado), 0) AS pagado_turnos
            FROM alquileres
            WHERE {TURNO_VINCULADO_SQL} AND estado <> 'cancelado'
            GROUP BY pedido_principal_id
        ) t ON t.principal_id = p.id
        LEFT JOIN (
            SELECT pedido_id, COUNT(*) AS cant_embebidos
            FROM alquiler_turnos_estudio
            GROUP BY pedido_id
        ) te ON te.pedido_id = p.id
        WHERE p.cliente_id = %s AND p.{SIN_PRINCIPAL_SQL}
        GROUP BY p.id, p.numero_pedido, p.estado, p.fecha_desde, p.fecha_hasta,
                 p.monto_total, p.monto_pagado, p.descuento_pct, p.created_at,
                 t.cant_turnos, t.total_turnos, t.pagado_turnos, te.cant_embebidos
        ORDER BY p.created_at DESC NULLS LAST, p.numero_pedido DESC
        """,
        (cliente_id,),
    ).fetchall()
    return [row_to_dict(r) for r in rows]
