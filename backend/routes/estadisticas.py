"""
routes/estadisticas.py — Análisis y estadísticas de alquileres.
Lee directo de pedidos + alquiler_items + equipos. Sin tablas intermedias.
"""

from fastapi import APIRouter, Request
from database import get_db, row_to_dict
from auth.guards import require_admin
from tipos_pedido import TIPOS_DERIVADOS_SQL, TIPOS_ESTUDIO_SQL

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

# Fragmento SQL compartido (#1308 rediseño "turno como ítem"): cuánto de
# `alquileres.monto_total` de un pedido viene de un turno del Estudio EMBEBIDO
# (`alquiler_items.turno_estudio_id`). Un ítem de turno queda excluido del
# descuento automático del pedido (`services/precios.py::calcular_total`), así
# que su aporte al NETO es exactamente su `subtotal` — restarlo de
# `monto_total` da la porción "rental pura" del pedido, sin la plata del
# Estudio mezclada. Usado por las agregaciones a nivel PEDIDO (totales/
# por_mes/top_clientes/clientes_recurrentes/mejor_peor_mes): sin esto, un
# pedido mixto inflaría el negocio de rental con plata que es del Estudio.
# `top_equipos`/`por_dueno` NO lo necesitan (son a nivel ÍTEM, ya excluyen el
# centinela vía `es_recurso_interno` y prorratean cada ítem por su propio
# `subtotal`, sin mezclar).
_TURNO_NETO_CTE = """
    turno_neto AS (
        SELECT pedido_id, COALESCE(SUM(subtotal), 0) AS monto_turnos
        FROM alquiler_items
        WHERE turno_estudio_id IS NOT NULL
        GROUP BY pedido_id
    )
"""

# Fragmento SQL compartido (#1308 rediseño "turno como ítem"), usado SOLO por la
# sección "Estudio" de abajo: unifica los turnos STANDALONE (fila propia
# `alquileres.tipo IN ('estudio','estudio_fijo')`) con los turnos EMBEBIDOS en
# un pedido de alquiler normal (`alquiler_turnos_estudio`) en un único universo
# `eventos_estudio` — mismo shape (mes/tipo/plata/horas), UNION ALL. Sin esto,
# la plata que `_TURNO_NETO_CTE` resta del lado rental desaparecería sin
# aparecer del lado Estudio (doble error, no uno).
#
# `turno_money` pre-agrega por `turno_estudio_id` ANTES del join a
# `alquiler_turnos_estudio`/`alquileres`: un turno embebido puede tener varios
# `alquiler_items` (centinela + sueltos + promo) — joinear directo sin
# pre-agregar multiplicaría `horas_vendidas` (que sale de las fechas del
# turno, no de sus ítems) por cada línea.
#
# Todo embebido entra como `tipo='estudio'` (turno real, con horas propias) —
# nunca 'estudio_fijo': ese tipo es exclusivo de la fila recurrente standalone
# (`_regenerar_pedidos_slot`), que no tiene contraparte embebida hoy.
_TURNO_EVENTOS_CTE = f"""
    turno_money AS (
        SELECT turno_estudio_id AS tid, COALESCE(SUM(subtotal), 0) AS monto
        FROM alquiler_items
        WHERE turno_estudio_id IS NOT NULL
        GROUP BY turno_estudio_id
    ),
    eventos_estudio AS (
        SELECT p.id AS pedido_id, p.cliente_id, p.tipo,
               p.fecha_desde, p.fecha_hasta, p.monto_total AS monto
        FROM alquileres p
        WHERE p.estado = 'finalizado' AND p.tipo IN {TIPOS_ESTUDIO_SQL}
        UNION ALL
        SELECT a.id AS pedido_id, a.cliente_id, 'estudio' AS tipo,
               ate.fecha_desde, ate.fecha_hasta, tm.monto
        FROM alquiler_turnos_estudio ate
        JOIN alquileres a ON a.id = ate.pedido_id
        LEFT JOIN turno_money tm ON tm.tid = ate.id
        WHERE a.estado = 'finalizado'
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
    # `tipo NOT IN TIPOS_DERIVADOS_SQL` (`tipos_pedido.py`, fuente única — antes
    # 7 literales `('estudio','estudio_fijo','taller')` repetidos acá) en TODAS
    # las agregaciones de esta función (#1283 Fase 7 + Talleres): Estudio y
    # Talleres son economías separadas (Estudio tiene su propia sección más
    # abajo) — mezclarlas acá inflaba "Top equipos"/"por dueño" con el
    # centinela y con "clientes" falsos (`"Taller X — Julio 2026"`),
    # confundiendo el negocio de rental con el de esas líneas. Los números
    # históricos de estas tarjetas cambian (bajan) respecto de antes de cada
    # fase — es la separación intencional, no una regresión.
    totales = conn.execute(f"""
        WITH {_TURNO_NETO_CTE}
        SELECT
            COUNT(*)                       AS total_pedidos,
            COUNT(DISTINCT p.cliente_id)   AS total_clientes,
            SUM(p.monto_total - COALESCE(tn.monto_turnos, 0)) AS total_ars,
            MIN(p.fecha_desde)             AS desde,
            MAX(p.fecha_desde)             AS hasta
        FROM alquileres p
        LEFT JOIN turno_neto tn ON tn.pedido_id = p.id
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN {TIPOS_DERIVADOS_SQL}
    """).fetchone()

    # ── Por mes ───────────────────────────────────────────────────────────────
    por_mes = conn.execute(f"""
        WITH {_TURNO_NETO_CTE}
        SELECT
            to_char(p.fecha_desde, 'YYYY-MM')    AS mes,
            COUNT(*)                       AS pedidos,
            SUM(p.monto_total - COALESCE(tn.monto_turnos, 0)) AS total_ars
        FROM alquileres p
        LEFT JOIN turno_neto tn ON tn.pedido_id = p.id
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN {TIPOS_DERIVADOS_SQL}
        GROUP BY to_char(p.fecha_desde, 'YYYY-MM')
        ORDER BY to_char(p.fecha_desde, 'YYYY-MM') DESC
        LIMIT 24
    """).fetchall()

    # ── Top equipos ───────────────────────────────────────────────────────────
    # A nivel ÍTEM: prorratea `monto_total` según la participación de cada línea
    # en el `subtotal` del pedido (mismo patrón que `reportes/liquidacion.py`).
    # `e.es_recurso_interno = FALSE` (#1308 rediseño "turno como ítem"): excluye
    # el centinela del Estudio — un pedido `diaria` mixto (equipos + turno
    # EMBEBIDO) pasa el filtro de pedido de arriba (sigue siendo tipo='diaria'),
    # así que sin esto su ítem centinela ("Estudio (espacio)") contaminaría
    # "top equipo" con una línea que no es un equipo real de rental. Mismo campo
    # que ya usa `routes/dashboard.py::equipos_afuera` para lo mismo. Los
    # SUELTOS de un turno embebido (equipos reales) NO se excluyen — su uso y
    # su prorrateo de plata son reales, quedan contados como cualquier ítem.
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
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN {TIPOS_DERIVADOS_SQL}
          AND e.es_recurso_interno = FALSE
        GROUP BY pi.equipo_id, e.nombre
        ORDER BY total_ars DESC
        LIMIT 15
    """).fetchall()

    # ── Top clientes ──────────────────────────────────────────────────────────
    top_clientes = conn.execute(f"""
        WITH {_TURNO_NETO_CTE}
        SELECT
            MAX(COALESCE(c.nombre || ' ' || c.apellido, p.cliente_nombre)) AS cliente,
            SUM(p.monto_total - COALESCE(tn.monto_turnos, 0)) AS total_ars,
            COUNT(DISTINCT p.id)           AS pedidos
        FROM alquileres p
        LEFT JOIN clientes c ON c.id = p.cliente_id
        LEFT JOIN turno_neto tn ON tn.pedido_id = p.id
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN {TIPOS_DERIVADOS_SQL}
        GROUP BY COALESCE(CAST(p.cliente_id AS TEXT), 'txt:' || p.cliente_nombre)
        ORDER BY total_ars DESC
        LIMIT 10
    """).fetchall()

    # ── Por dueño (basado en equipos.dueno) ───────────────────────────────────
    # Mismo prorrateo que top_equipos, agregado por `equipos.dueno`.
    # `e.es_recurso_interno = FALSE`: mismo motivo que `top_equipos` — excluye
    # el centinela (atribuido a un dueño real solo a efectos de la liquidación
    # del Estudio, no de "por dueño" de rental).
    por_dueno = conn.execute(f"""
        WITH {_PRORRATEO_CTE}
        SELECT
            COALESCE(e.dueno, 'Rental')    AS dueno,
            SUM(p.monto_total * pi.subtotal::numeric / NULLIF(t.suma_items, 0)) AS total_ars,
            COUNT(*)                       AS items
        FROM alquiler_items pi
        JOIN alquileres p ON p.id = pi.pedido_id
        JOIN equipos e ON e.id = pi.equipo_id
        JOIN tot t ON t.pedido_id = p.id
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN {TIPOS_DERIVADOS_SQL}
          AND e.es_recurso_interno = FALSE
        GROUP BY COALESCE(e.dueno, 'Rental')
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
    clientes_recurrentes = conn.execute(f"""
        WITH {_TURNO_NETO_CTE}
        SELECT
            MAX(COALESCE(c.nombre || ' ' || c.apellido, p.cliente_nombre)) AS cliente,
            COUNT(DISTINCT p.id)           AS veces_alquiladas,
            SUM(p.monto_total - COALESCE(tn.monto_turnos, 0)) AS total_ars
        FROM alquileres p
        LEFT JOIN clientes c ON c.id = p.cliente_id
        LEFT JOIN turno_neto tn ON tn.pedido_id = p.id
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN {TIPOS_DERIVADOS_SQL}
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
    mejor_peor = conn.execute(f"""
        WITH {_TURNO_NETO_CTE},
        por_mes_full AS (
            SELECT to_char(p.fecha_desde, 'YYYY-MM') AS mes,
                   SUM(p.monto_total - COALESCE(tn.monto_turnos, 0)) AS total
            FROM alquileres p
            LEFT JOIN turno_neto tn ON tn.pedido_id = p.id
            WHERE p.estado = 'finalizado' AND p.tipo NOT IN {TIPOS_DERIVADOS_SQL}
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
    # función, ahora sobre `eventos_estudio` (#1308 rediseño "turno como
    # ítem"): une los pedidos standalone (`tipo IN ('estudio','estudio_fijo')`)
    # con los turnos EMBEBIDOS en un pedido de alquiler normal — sin esto, la
    # plata que `_TURNO_NETO_CTE` resta del lado rental (arriba) desaparecería
    # sin sumarse acá. `horas_vendidas` se computa SOLO de `tipo='estudio'`
    # (turnos reales, standalone o embebido) vía FILTER: un `estudio_fijo`
    # guarda en `fecha_desde/fecha_hasta` únicamente la PRIMERA ocurrencia
    # semanal del mes (`_primer_dia_semana`), no el total de horas de todas las
    # recurrencias — sumarlo ahí subestimaría feo las horas. La plata y el
    # conteo de pedidos SÍ combinan ambos tipos (ambos son ingreso real del
    # Estudio), solo separados en columnas propias (`turnos` vs
    # `meses_slot_fijo`) para no mezclar la unidad de negocio.
    estudio_por_mes = conn.execute(f"""
        WITH {_TURNO_EVENTOS_CTE}
        SELECT
            to_char(fecha_desde, 'YYYY-MM')                  AS mes,
            COUNT(*) FILTER (WHERE tipo = 'estudio')         AS turnos,
            COUNT(*) FILTER (WHERE tipo = 'estudio_fijo')    AS meses_slot_fijo,
            SUM(monto)                                       AS total_ars,
            COALESCE(SUM(EXTRACT(EPOCH FROM (fecha_hasta - fecha_desde)) / 3600)
                     FILTER (WHERE tipo = 'estudio'), 0)      AS horas_vendidas
        FROM eventos_estudio
        GROUP BY to_char(fecha_desde, 'YYYY-MM')
        ORDER BY to_char(fecha_desde, 'YYYY-MM') DESC
        LIMIT 24
    """).fetchall()

    estudio_totales = conn.execute(f"""
        WITH {_TURNO_EVENTOS_CTE}
        SELECT
            COUNT(*) FILTER (WHERE tipo = 'estudio')         AS total_turnos,
            COUNT(*) FILTER (WHERE tipo = 'estudio_fijo')    AS total_meses_slot_fijo,
            COUNT(DISTINCT cliente_id)                       AS total_clientes,
            SUM(monto)                                       AS total_ars,
            COALESCE(SUM(EXTRACT(EPOCH FROM (fecha_hasta - fecha_desde)) / 3600)
                     FILTER (WHERE tipo = 'estudio'), 0)      AS horas_vendidas
        FROM eventos_estudio
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
