"""
routes/estadisticas.py — Análisis y estadísticas de alquileres.
Lee directo de pedidos + alquiler_items + equipos. Sin tablas intermedias.
"""

from fastapi import APIRouter, Request
from database import get_db, row_to_dict
from auth.guards import require_admin
from tipos_pedido import TIPOS_DERIVADOS_SQL, TIPOS_ESTUDIO_SQL
from contabilidad.queries.movimientos import gastos_por_categoria
from services.ipc import IPC_FACTOR_CTE, mes_referencia

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

    **Toggle de IPC — "pesos ajustados" (`services/ipc.py`):** cada agregado de
    plata que suma por PEDIDO/ÍTEM/MOVIMIENTO trae su par `..._ajustado`, con el
    ajuste hecho EN ORIGEN (cada fila deflactada por el mes en que ocurrió, ANTES
    de sumar/agrupar) vía `IPC_FACTOR_CTE` — nunca un factor único aplicado
    post-suma, que sería matemáticamente incorrecto cuando el total mezcla varios
    meses. Alcance deliberado: el CONJUNTO de filas de cada ranking (qué entra en
    el top 15/10) se sigue eligiendo por el monto NOMINAL, igual que hoy — el
    toggle cambia qué NÚMERO se muestra para cada fila ya elegida, no cuáles
    filas se eligen (evitar que el set del ranking "salte" según el modo).
    `top_equipos_rentabilidad` (ingreso − costo de compra) queda FUERA de este
    ajuste: `costo_compra` es un desembolso puntual, no una serie mensual —
    ajustarlo requeriría además la fecha de compra del equipo, una pregunta
    aparte de "ajustar los ingresos por inflación".
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
        WITH {_TURNO_NETO_CTE}, {IPC_FACTOR_CTE}
        SELECT
            COUNT(*)                       AS total_pedidos,
            COUNT(DISTINCT p.cliente_id)   AS total_clientes,
            SUM(p.monto_total - COALESCE(tn.monto_turnos, 0)) AS total_ars,
            SUM((p.monto_total - COALESCE(tn.monto_turnos, 0)) * COALESCE(ipf.factor, 1))
                                            AS total_ars_ajustado,
            MIN(p.fecha_desde)             AS desde,
            MAX(p.fecha_desde)             AS hasta
        FROM alquileres p
        LEFT JOIN turno_neto tn ON tn.pedido_id = p.id
        LEFT JOIN ipc_factor ipf ON ipf.mes = to_char(p.fecha_desde, 'YYYY-MM')
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN {TIPOS_DERIVADOS_SQL}
    """).fetchone()

    # ── Por mes ───────────────────────────────────────────────────────────────
    por_mes = conn.execute(f"""
        WITH {_TURNO_NETO_CTE}, {IPC_FACTOR_CTE}
        SELECT
            to_char(p.fecha_desde, 'YYYY-MM')    AS mes,
            COUNT(*)                       AS pedidos,
            SUM(p.monto_total - COALESCE(tn.monto_turnos, 0)) AS total_ars,
            SUM((p.monto_total - COALESCE(tn.monto_turnos, 0)) * COALESCE(ipf.factor, 1))
                                            AS total_ars_ajustado
        FROM alquileres p
        LEFT JOIN turno_neto tn ON tn.pedido_id = p.id
        LEFT JOIN ipc_factor ipf ON ipf.mes = to_char(p.fecha_desde, 'YYYY-MM')
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
    # Sin LIMIT/ORDER BY acá: se derivan DOS rankings distintos de este mismo
    # resultado en Python (por ingreso y por rentabilidad neta, ver abajo) —
    # cortar u ordenar en SQL serviría solo a uno de los dos. `costo_compra`
    # (MAX: mismo valor para todas las filas del grupo, es un atributo del
    # equipo — la agregación es solo para que Postgres acepte la columna sin
    # sumarla al GROUP BY) es NULL para un equipo sin el dato cargado.
    _equipos_ingreso_y_costo = [
        row_to_dict(r)
        for r in conn.execute(f"""
            WITH {_PRORRATEO_CTE}, {IPC_FACTOR_CTE}
            SELECT
                e.nombre                       AS equipo,
                SUM(p.monto_total * pi.subtotal::numeric / NULLIF(t.suma_items, 0)) AS total_ars,
                SUM(p.monto_total * pi.subtotal::numeric / NULLIF(t.suma_items, 0)
                    * COALESCE(ipf.factor, 1)) AS total_ars_ajustado,
                COUNT(*)                       AS veces,
                MAX(e.costo_compra)            AS costo_compra
            FROM alquiler_items pi
            JOIN alquileres p  ON p.id  = pi.pedido_id
            JOIN equipos e  ON e.id  = pi.equipo_id
            JOIN tot t ON t.pedido_id = p.id
            LEFT JOIN ipc_factor ipf ON ipf.mes = to_char(p.fecha_desde, 'YYYY-MM')
            WHERE p.estado = 'finalizado' AND p.tipo NOT IN {TIPOS_DERIVADOS_SQL}
              AND e.es_recurso_interno = FALSE
            GROUP BY pi.equipo_id, e.nombre
        """).fetchall()
    ]
    top_equipos = sorted(
        _equipos_ingreso_y_costo, key=lambda e: e["total_ars"] or 0, reverse=True
    )[:15]

    # Rentabilidad neta (ingreso − costo de compra) — pedido del dueño: un
    # equipo puede facturar mucho y no ser el más rentable si costó caro
    # comprarlo (ejemplo real: una cámara top-of-line vs. un equipo más
    # barato con casi el mismo ingreso). Solo cuenta equipos CON el costo
    # cargado — no hay forma de comparar rentabilidad sin ese dato, y
    # mostrar un 0 inventado sería peor que no mostrar el equipo. Sin ajuste
    # por IPC (ver docstring de la función) — el ingreso que trae vía `{**e}`
    # es el NOMINAL, a propósito.
    top_equipos_rentabilidad = sorted(
        (
            {**e, "rentabilidad_neta": (e["total_ars"] or 0) - e["costo_compra"]}
            for e in _equipos_ingreso_y_costo
            if e["costo_compra"] is not None
        ),
        key=lambda e: e["rentabilidad_neta"],
        reverse=True,
    )[:15]

    # ── Top clientes ──────────────────────────────────────────────────────────
    top_clientes = conn.execute(f"""
        WITH {_TURNO_NETO_CTE}, {IPC_FACTOR_CTE}
        SELECT
            MAX(COALESCE(c.nombre || ' ' || c.apellido, p.cliente_nombre)) AS cliente,
            SUM(p.monto_total - COALESCE(tn.monto_turnos, 0)) AS total_ars,
            SUM((p.monto_total - COALESCE(tn.monto_turnos, 0)) * COALESCE(ipf.factor, 1))
                                            AS total_ars_ajustado,
            COUNT(DISTINCT p.id)           AS pedidos
        FROM alquileres p
        LEFT JOIN clientes c ON c.id = p.cliente_id
        LEFT JOIN turno_neto tn ON tn.pedido_id = p.id
        LEFT JOIN ipc_factor ipf ON ipf.mes = to_char(p.fecha_desde, 'YYYY-MM')
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
        WITH {_PRORRATEO_CTE}, {IPC_FACTOR_CTE}
        SELECT
            COALESCE(e.dueno, 'Rental')    AS dueno,
            SUM(p.monto_total * pi.subtotal::numeric / NULLIF(t.suma_items, 0)) AS total_ars,
            SUM(p.monto_total * pi.subtotal::numeric / NULLIF(t.suma_items, 0)
                * COALESCE(ipf.factor, 1)) AS total_ars_ajustado,
            COUNT(*)                       AS items
        FROM alquiler_items pi
        JOIN alquileres p ON p.id = pi.pedido_id
        JOIN equipos e ON e.id = pi.equipo_id
        JOIN tot t ON t.pedido_id = p.id
        LEFT JOIN ipc_factor ipf ON ipf.mes = to_char(p.fecha_desde, 'YYYY-MM')
        WHERE p.estado = 'finalizado' AND p.tipo NOT IN {TIPOS_DERIVADOS_SQL}
          AND e.es_recurso_interno = FALSE
        GROUP BY COALESCE(e.dueno, 'Rental')
        ORDER BY total_ars DESC
    """).fetchall()

    # ── Crecimiento mes a mes ──────────────────────────────────────────────────
    # Mismo cálculo en paralelo para nominal y ajustado — la comparación entre
    # los dos es el punto central del toggle ("¿crecí de verdad o es inflación?"):
    # un mes puede crecer +40% nominal y caer en términos reales.
    por_mes_calc = [row_to_dict(r) for r in por_mes]
    por_mes_calc.sort(key=lambda x: x['mes'])

    def _crecimiento_pct(actual, anterior):
        if anterior and anterior > 0:
            return round(((actual - anterior) / anterior) * 100, 1)
        return 0 if not actual else 100

    crecimiento = []
    for i, mes in enumerate(por_mes_calc):
        if i > 0:
            mes_anterior = por_mes_calc[i - 1]
            pct = _crecimiento_pct(mes['total_ars'], mes_anterior['total_ars'] or 0)
            pct_ajustado = _crecimiento_pct(
                mes['total_ars_ajustado'], mes_anterior['total_ars_ajustado'] or 0
            )
        else:
            pct = 0
            pct_ajustado = 0
        crecimiento.append({
            'mes':                      mes['mes'],
            'total_ars':                mes['total_ars'],
            'total_ars_ajustado':       mes['total_ars_ajustado'],
            'crecimiento_pct':          pct,
            'crecimiento_pct_ajustado': pct_ajustado,
        })
    crecimiento.sort(key=lambda x: x['mes'], reverse=True)

    # ── Clientes más recurrentes ───────────────────────────────────────────────
    clientes_recurrentes = conn.execute(f"""
        WITH {_TURNO_NETO_CTE}, {IPC_FACTOR_CTE}
        SELECT
            MAX(COALESCE(c.nombre || ' ' || c.apellido, p.cliente_nombre)) AS cliente,
            COUNT(DISTINCT p.id)           AS veces_alquiladas,
            SUM(p.monto_total - COALESCE(tn.monto_turnos, 0)) AS total_ars,
            SUM((p.monto_total - COALESCE(tn.monto_turnos, 0)) * COALESCE(ipf.factor, 1))
                                            AS total_ars_ajustado
        FROM alquileres p
        LEFT JOIN clientes c ON c.id = p.cliente_id
        LEFT JOIN turno_neto tn ON tn.pedido_id = p.id
        LEFT JOIN ipc_factor ipf ON ipf.mes = to_char(p.fecha_desde, 'YYYY-MM')
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
    # El mejor/peor mes SE ELIGE por el total NOMINAL (mismo alcance que los
    # rankings de arriba) — `mejor_total_ajustado`/`peor_total_ajustado` son el
    # valor ajustado de ESE MISMO mes ya elegido, no una re-elección por ajustado.
    mejor_peor = conn.execute(f"""
        WITH {_TURNO_NETO_CTE}, {IPC_FACTOR_CTE},
        por_mes_full AS (
            SELECT to_char(p.fecha_desde, 'YYYY-MM') AS mes,
                   SUM(p.monto_total - COALESCE(tn.monto_turnos, 0)) AS total,
                   SUM((p.monto_total - COALESCE(tn.monto_turnos, 0)) * COALESCE(ipf.factor, 1))
                                                                      AS total_ajustado
            FROM alquileres p
            LEFT JOIN turno_neto tn ON tn.pedido_id = p.id
            LEFT JOIN ipc_factor ipf ON ipf.mes = to_char(p.fecha_desde, 'YYYY-MM')
            WHERE p.estado = 'finalizado' AND p.tipo NOT IN {TIPOS_DERIVADOS_SQL}
            GROUP BY to_char(p.fecha_desde, 'YYYY-MM')
        )
        SELECT
            (SELECT mes            FROM por_mes_full ORDER BY total DESC LIMIT 1) AS mejor_mes,
            (SELECT total          FROM por_mes_full ORDER BY total DESC LIMIT 1) AS mejor_total,
            (SELECT total_ajustado FROM por_mes_full ORDER BY total DESC LIMIT 1) AS mejor_total_ajustado,
            (SELECT mes            FROM por_mes_full ORDER BY total ASC LIMIT 1)  AS peor_mes,
            (SELECT total          FROM por_mes_full ORDER BY total ASC LIMIT 1)  AS peor_total,
            (SELECT total_ajustado FROM por_mes_full ORDER BY total ASC LIMIT 1)  AS peor_total_ajustado
    """).fetchone()

    mejor_peor_dict = row_to_dict(mejor_peor) if mejor_peor else {}
    mejor_peor_mes = {
        'mejor_mes':            mejor_peor_dict.get('mejor_mes'),
        'mejor_total':          mejor_peor_dict.get('mejor_total'),
        'mejor_total_ajustado': mejor_peor_dict.get('mejor_total_ajustado'),
        'peor_mes':             mejor_peor_dict.get('peor_mes'),
        'peor_total':           mejor_peor_dict.get('peor_total'),
        'peor_total_ajustado':  mejor_peor_dict.get('peor_total_ajustado'),
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
        WITH {_TURNO_EVENTOS_CTE}, {IPC_FACTOR_CTE}
        SELECT
            to_char(fecha_desde, 'YYYY-MM')                  AS mes,
            COUNT(*) FILTER (WHERE tipo = 'estudio')         AS turnos,
            COUNT(*) FILTER (WHERE tipo = 'estudio_fijo')    AS meses_slot_fijo,
            SUM(monto)                                       AS total_ars,
            SUM(monto * COALESCE(ipf.factor, 1))             AS total_ars_ajustado,
            COALESCE(SUM(EXTRACT(EPOCH FROM (fecha_hasta - fecha_desde)) / 3600)
                     FILTER (WHERE tipo = 'estudio'), 0)      AS horas_vendidas
        FROM eventos_estudio
        LEFT JOIN ipc_factor ipf ON ipf.mes = to_char(fecha_desde, 'YYYY-MM')
        GROUP BY to_char(fecha_desde, 'YYYY-MM')
        ORDER BY to_char(fecha_desde, 'YYYY-MM') DESC
        LIMIT 24
    """).fetchall()

    estudio_totales = conn.execute(f"""
        WITH {_TURNO_EVENTOS_CTE}, {IPC_FACTOR_CTE}
        SELECT
            COUNT(*) FILTER (WHERE tipo = 'estudio')         AS total_turnos,
            COUNT(*) FILTER (WHERE tipo = 'estudio_fijo')    AS total_meses_slot_fijo,
            COUNT(DISTINCT cliente_id)                       AS total_clientes,
            SUM(monto)                                       AS total_ars,
            SUM(monto * COALESCE(ipf.factor, 1))             AS total_ars_ajustado,
            COALESCE(SUM(EXTRACT(EPOCH FROM (fecha_hasta - fecha_desde)) / 3600)
                     FILTER (WHERE tipo = 'estudio'), 0)      AS horas_vendidas
        FROM eventos_estudio
        LEFT JOIN ipc_factor ipf ON ipf.mes = to_char(fecha_desde, 'YYYY-MM')
    """).fetchone()

    # ── Gastos por categoría (histórico completo, motor único: `contabilidad`) ──
    # Reusa tal cual `gastos_por_categoria` de `contabilidad/queries/movimientos.py`
    # (la misma función que ya alimenta el P&L mensual) sin fecha → todo el
    # historial, mismo criterio que el resto de esta función. `incluir_ajustado=True`
    # es la única diferencia con el caller del P&L — aditivo, no reimplementa SQL.
    gastos_categoria = gastos_por_categoria(conn, incluir_ajustado=True)

    return {
        "totales":                  row_to_dict(totales),
        "por_mes":                  [row_to_dict(r) for r in por_mes],
        "crecimiento":              crecimiento,
        "top_equipos":              top_equipos,
        "top_equipos_rentabilidad": top_equipos_rentabilidad,
        "top_clientes":             [row_to_dict(r) for r in top_clientes],
        "clientes_recurrentes":     [row_to_dict(r) for r in clientes_recurrentes],
        "mejor_peor_mes":           mejor_peor_mes,
        "por_dueno":                [row_to_dict(r) for r in por_dueno],
        "favoritos_equipo":         [row_to_dict(r) for r in favoritos_equipo],
        "gastos_por_categoria":     gastos_categoria,
        "estudio": {
            "totales": row_to_dict(estudio_totales),
            "por_mes": [row_to_dict(r) for r in estudio_por_mes],
        },
        # Metadata del ajuste por IPC: el frontend la usa para el label del
        # toggle ("pesos ajustados a agosto 2026") — nunca para calcular nada
        # (el front no calcula plata, MEMORIA 2026-06-29).
        "ipc": {"mes_referencia": mes_referencia(conn)},
    }
