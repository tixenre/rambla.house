"""
routes/estadisticas.py — Análisis y estadísticas de alquileres.
Lee directo de pedidos + alquiler_items + equipos. Sin tablas intermedias.
"""

from fastapi import APIRouter, Request
from database import get_db, row_to_dict
from auth.guards import require_admin

router = APIRouter()

# Fragmento SQL compartido: prorratea `alquileres.monto_total` (el NETO correcto,
# ya con el descuento GANADOR aplicado — `max(descuento_cliente_pct,
# descuento_jornadas_pct)`, ver `descuentos.queries.decision.calcular_descuento_aplicable`)
# entre los ítems de un pedido según su participación en el `subtotal` (bruto). Mismo patrón
# que `reportes/liquidacion.py::SALDADO_CTE` (fragmento SQL compartido vía f-string).
#
# Por qué hace falta prorratear en vez de leer `monto_total` directo: es a nivel
# PEDIDO, no por ítem — un pedido con 2 equipos de dueños distintos no puede
# repartir "cuánto aportó cada uno" sin esto. Las agregaciones que SÍ son a nivel
# pedido (totales, por mes, mejor/peor mes) usan `monto_total` directo, sin join a
# `alquiler_items` (evita multiplicarlo por cada línea del pedido).
#
# NO reconstruir el descuento acá (ni `descuento_pct` solo, ni
# GREATEST(descuento_pct, descuento_jornadas_pct)): `monto_total` YA es la fuente
# única del neto — recalcularlo es exactamente el bug que esto arregla (#1209).
_PRORRATEO_CTE = """
    tot AS (
        SELECT pedido_id, SUM(subtotal) AS suma_items
        FROM alquiler_items
        GROUP BY pedido_id
    )
"""


@router.get("/estadisticas")
def get_estadisticas(request: Request):
    require_admin(request)
    with get_db() as conn:
        return compute_estadisticas(conn)


def compute_estadisticas(conn) -> dict:
    """Calcula el dict completo de estadísticas a partir de una conexión.

    Fuente única (barra de calidad: modularidad) — la usan tanto el endpoint
    `get_estadisticas` (transporte HTTP) como el PDF de Reportes (sección
    'Resumen general'). No abre ni cierra la conexión: el caller la administra.
    """
    # ── Totales generales (SOLO pedidos `finalizado` — devengado + cerrado) ───
    # Criterio explícito del dueño (2026-07-04): Estadísticas cuenta negocio YA
    # cerrado, no `confirmado`/`retirado` (que todavía pueden cambiar). A nivel
    # PEDIDO: `monto_total` directo, sin join a `alquiler_items` — sumarlo por
    # ítem lo multiplicaría por cada línea del pedido. Todo pedido `finalizado`
    # tiene ≥1 ítem (invariante de creación, `routes/alquileres/core.py`), así
    # que no hace falta el join para filtrar "tiene ítems".
    #
    # `tipo NOT IN ('estudio','estudio_fijo')` en TODAS las agregaciones de esta
    # función (#1283 Fase 7): el Estudio es una economía separada con su propia
    # sección más abajo — mezclarlo acá inflaba "Top equipos"/"por dueño" con el
    # centinela (un recurso interno, no un equipo real) y confundía el negocio
    # de rental con el del Estudio. Los números históricos de estas tarjetas
    # cambian (bajan) respecto de antes de esta fase — es la separación
    # intencional, no una regresión.
    totales = conn.execute("""
        SELECT
            COUNT(*)                       AS total_pedidos,
            COUNT(DISTINCT p.cliente_id)   AS total_clientes,
            SUM(p.monto_total)             AS total_ars,
            MIN(p.fecha_desde)             AS desde,
            MAX(p.fecha_desde)             AS hasta
        FROM alquileres p
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN ('estudio', 'estudio_fijo')
    """).fetchone()

    # ── Por mes ───────────────────────────────────────────────────────────────
    por_mes = conn.execute("""
        SELECT
            to_char(p.fecha_desde, 'YYYY-MM')    AS mes,
            COUNT(*)                       AS pedidos,
            SUM(p.monto_total)             AS total_ars
        FROM alquileres p
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN ('estudio', 'estudio_fijo')
        GROUP BY to_char(p.fecha_desde, 'YYYY-MM')
        ORDER BY to_char(p.fecha_desde, 'YYYY-MM') DESC
        LIMIT 24
    """).fetchall()

    # ── Top equipos ───────────────────────────────────────────────────────────
    # A nivel ÍTEM: prorratea `monto_total` según la participación de cada línea
    # en el `subtotal` del pedido (mismo patrón que `reportes/liquidacion.py`).
    top_equipos = conn.execute(f"""
        WITH {_PRORRATEO_CTE}
        SELECT
            e.nombre                       AS equipo,
            SUM(p.monto_total * pi.subtotal::numeric / NULLIF(t.suma_items, 0)) AS total_ars,
            COUNT(*)                       AS veces
        FROM alquiler_items pi
        JOIN alquileres p  ON p.id  = pi.pedido_id
        JOIN equipos e  ON e.id  = pi.equipo_id
        JOIN tot t ON t.pedido_id = p.id
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN ('estudio', 'estudio_fijo')
        GROUP BY pi.equipo_id, e.nombre
        ORDER BY total_ars DESC
        LIMIT 15
    """).fetchall()

    # ── Top clientes ──────────────────────────────────────────────────────────
    top_clientes = conn.execute("""
        SELECT
            MAX(COALESCE(c.nombre || ' ' || c.apellido, p.cliente_nombre)) AS cliente,
            SUM(p.monto_total)             AS total_ars,
            COUNT(DISTINCT p.id)           AS pedidos
        FROM alquileres p
        LEFT JOIN clientes c ON c.id = p.cliente_id
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN ('estudio', 'estudio_fijo')
        GROUP BY COALESCE(CAST(p.cliente_id AS TEXT), 'txt:' || p.cliente_nombre)
        ORDER BY total_ars DESC
        LIMIT 10
    """).fetchall()

    # ── Por dueño (basado en equipos.dueno) ───────────────────────────────────
    # Mismo prorrateo que top_equipos, agregado por `equipos.dueno`.
    por_dueno = conn.execute(f"""
        WITH {_PRORRATEO_CTE}
        SELECT
            COALESCE(e.dueno, 'Rambla')    AS dueno,
            SUM(p.monto_total * pi.subtotal::numeric / NULLIF(t.suma_items, 0)) AS total_ars,
            COUNT(*)                       AS items
        FROM alquiler_items pi
        JOIN alquileres p ON p.id = pi.pedido_id
        JOIN equipos e ON e.id = pi.equipo_id
        JOIN tot t ON t.pedido_id = p.id
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN ('estudio', 'estudio_fijo')
        GROUP BY COALESCE(e.dueno, 'Rambla')
        ORDER BY total_ars DESC
    """).fetchall()

    # ── Crecimiento mes a mes ──────────────────────────────────────────────────
    por_mes_calc = [row_to_dict(r) for r in por_mes]
    por_mes_calc.sort(key=lambda x: x['mes'])

    crecimiento = []
    for i, mes in enumerate(por_mes_calc):
        if i > 0:
            mes_anterior = por_mes_calc[i - 1]
            total_ant = mes_anterior['total_ars'] or 0
            if total_ant > 0:
                pct = ((mes['total_ars'] - total_ant) / total_ant) * 100
            else:
                pct = 0 if mes['total_ars'] == 0 else 100
        else:
            pct = 0
        crecimiento.append({
            'mes':             mes['mes'],
            'total_ars':       mes['total_ars'],
            'crecimiento_pct': round(pct, 1) if pct else 0,
        })
    crecimiento.sort(key=lambda x: x['mes'], reverse=True)

    # ── Clientes más recurrentes ───────────────────────────────────────────────
    clientes_recurrentes = conn.execute("""
        SELECT
            MAX(COALESCE(c.nombre || ' ' || c.apellido, p.cliente_nombre)) AS cliente,
            COUNT(DISTINCT p.id)           AS veces_alquiladas,
            SUM(p.monto_total)             AS total_ars
        FROM alquileres p
        LEFT JOIN clientes c ON c.id = p.cliente_id
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN ('estudio', 'estudio_fijo')
        GROUP BY COALESCE(CAST(p.cliente_id AS TEXT), 'txt:' || p.cliente_nombre)
        HAVING COUNT(DISTINCT p.id) > 1
        ORDER BY veces_alquiladas DESC
        LIMIT 10
    """).fetchall()

    # ── Mejor y peor mes ───────────────────────────────────────────────────────
    # A nivel PEDIDO, igual que `totales`/`por_mes`: una sola CTE con `monto_total`
    # (sin join a ítems), reusada 4 veces en vez de repetir la fórmula del ingreso
    # en cada subquery. Sobre TODO el histórico (sin el LIMIT 24 de `por_mes`) —
    # mismo universo que antes. `tipo NOT IN (...)` también acá (Fase 7): un mes
    # con mucho volumen de estudio no debe aparecer como "mejor mes" del rental.
    mejor_peor = conn.execute("""
        WITH por_mes_full AS (
            SELECT to_char(p.fecha_desde, 'YYYY-MM') AS mes, SUM(p.monto_total) AS total
            FROM alquileres p
            WHERE p.estado = 'finalizado' AND p.tipo NOT IN ('estudio', 'estudio_fijo')
            GROUP BY to_char(p.fecha_desde, 'YYYY-MM')
        )
        SELECT
            (SELECT mes   FROM por_mes_full ORDER BY total DESC LIMIT 1) AS mejor_mes,
            (SELECT MAX(total) FROM por_mes_full)                       AS mejor_total,
            (SELECT mes   FROM por_mes_full ORDER BY total ASC LIMIT 1) AS peor_mes,
            (SELECT MIN(total) FROM por_mes_full)                       AS peor_total
    """).fetchone()

    mejor_peor_dict = row_to_dict(mejor_peor) if mejor_peor else {}
    mejor_peor_mes = {
        'mejor_mes':   mejor_peor_dict.get('mejor_mes'),
        'mejor_total': mejor_peor_dict.get('mejor_total'),
        'peor_mes':    mejor_peor_dict.get('peor_mes'),
        'peor_total':  mejor_peor_dict.get('peor_total'),
    }

    # ── Equipos más favoriteados (analytics de comportamiento de clientes) ──
    # Tabla creada en migración e1f2a3b4c5d6 — guard por si la migración
    # aún no corrió en este ambiente.
    table_exists = conn.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'cliente_favoritos'
        )
    """).scalar()
    if table_exists:
        favoritos_equipo = conn.execute("""
            SELECT
                e.nombre                       AS equipo,
                COUNT(*)                       AS total_favoritos,
                COUNT(DISTINCT cf.cliente_id)  AS clientes_unicos
            FROM cliente_favoritos cf
            JOIN equipos e ON e.id = cf.equipo_id
            GROUP BY cf.equipo_id, e.nombre
            ORDER BY total_favoritos DESC
            LIMIT 15
        """).fetchall()
    else:
        favoritos_equipo = []

    # ── Estudio (economía separada, #1283 Fase 7) ─────────────────────────────
    # Mismo universo DEVENGADO (`estado='finalizado'`) que el resto de esta
    # función. `horas_vendidas` se computa SOLO de `tipo='estudio'` (turnos
    # reales) vía FILTER: un `estudio_fijo` guarda en `fecha_desde/fecha_hasta`
    # únicamente la PRIMERA ocurrencia semanal del mes (`_primer_dia_semana`),
    # no el total de horas de todas las recurrencias — sumarlo ahí subestimaría
    # feo las horas. La plata y el conteo de pedidos SÍ combinan ambos tipos
    # (ambos son ingreso real del Estudio), solo separados en columnas propias
    # (`turnos` vs `meses_slot_fijo`) para no mezclar la unidad de negocio.
    estudio_por_mes = conn.execute("""
        SELECT
            to_char(p.fecha_desde, 'YYYY-MM')                  AS mes,
            COUNT(*) FILTER (WHERE p.tipo = 'estudio')         AS turnos,
            COUNT(*) FILTER (WHERE p.tipo = 'estudio_fijo')    AS meses_slot_fijo,
            SUM(p.monto_total)                                 AS total_ars,
            COALESCE(SUM(EXTRACT(EPOCH FROM (p.fecha_hasta - p.fecha_desde)) / 3600)
                     FILTER (WHERE p.tipo = 'estudio'), 0)      AS horas_vendidas
        FROM alquileres p
        WHERE p.estado = 'finalizado' AND p.tipo IN ('estudio', 'estudio_fijo')
        GROUP BY to_char(p.fecha_desde, 'YYYY-MM')
        ORDER BY to_char(p.fecha_desde, 'YYYY-MM') DESC
        LIMIT 24
    """).fetchall()

    estudio_totales = conn.execute("""
        SELECT
            COUNT(*) FILTER (WHERE p.tipo = 'estudio')         AS total_turnos,
            COUNT(*) FILTER (WHERE p.tipo = 'estudio_fijo')    AS total_meses_slot_fijo,
            COUNT(DISTINCT p.cliente_id)                       AS total_clientes,
            SUM(p.monto_total)                                 AS total_ars,
            COALESCE(SUM(EXTRACT(EPOCH FROM (p.fecha_hasta - p.fecha_desde)) / 3600)
                     FILTER (WHERE p.tipo = 'estudio'), 0)      AS horas_vendidas
        FROM alquileres p
        WHERE p.estado = 'finalizado' AND p.tipo IN ('estudio', 'estudio_fijo')
    """).fetchone()

    return {
        "totales":              row_to_dict(totales),
        "por_mes":              [row_to_dict(r) for r in por_mes],
        "crecimiento":          crecimiento,
        "top_equipos":          [row_to_dict(r) for r in top_equipos],
        "top_clientes":         [row_to_dict(r) for r in top_clientes],
        "clientes_recurrentes": [row_to_dict(r) for r in clientes_recurrentes],
        "mejor_peor_mes":       mejor_peor_mes,
        "por_dueno":            [row_to_dict(r) for r in por_dueno],
        "favoritos_equipo":     [row_to_dict(r) for r in favoritos_equipo],
        "estudio": {
            "totales": row_to_dict(estudio_totales),
            "por_mes": [row_to_dict(r) for r in estudio_por_mes],
        },
    }
