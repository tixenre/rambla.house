"""
services/ranking_service.py — Cálculo de popularidad de equipos, marcas
y categorías.

Combina lo manual (`relevancia_manual` que el admin define) con lo
automático (`popularidad_score` calculado desde el historial de pedidos
e ingresos), normalizado por categoría para que un equipo no compita
con todo el inventario sino con sus pares.

El sort final del catálogo:
    ORDER BY relevancia_manual ASC, popularidad_score DESC, nombre ASC

Convención de relevancia_manual (más bajo = más prominente):
    10  → flagship (RED Komodo X, FX9, Alexa Mini)
    30  → premium (FX3, A7S III, Sigma Art)
    60  → workhorse (BMPCC 6K, A7 III)
    100 → default
    200 → secundarios (cables, baterías, plates)

#131: extendido a marcas y categorías. La función
`recalcular_ranking_todos` ahora actualiza también `marcas.popularidad_score`
y `categorias.popularidad_score` con los mismos criterios (cant_pedidos
+ ingreso, normalizado contra el max de su universo).
"""



from services.categorias import actualizar_ranking, expandir_a_ancestros_por_equipo, root_of_categoria

# Ventana de tiempo para el cálculo de popularidad (últimos N días).
# 180 días = 6 meses. Captura tendencia reciente sin que un boom de hace
# 2 años distorsione el ranking actual.
VENTANA_DIAS_DEFAULT = 180


def _categorias_raiz_de(conn, equipo_id: int) -> list[int]:
    """Devuelve los IDs de las categorías raíz a las que pertenece el equipo,
    trepando correctamente por todo el árbol."""
    ancestors = expandir_a_ancestros_por_equipo(conn, [equipo_id])
    all_ids = ancestors.get(equipo_id, [])
    raices: set[int] = set()
    for cid in all_ids:
        raiz = root_of_categoria(conn, cid)
        if raiz is not None:
            raices.add(raiz)
    return list(raices)


def calcular_estadisticas_equipo(
    conn,
    equipo_id: int,
    ventana_dias: int = VENTANA_DIAS_DEFAULT,
) -> dict:
    """Calcula cant_pedidos e ingreso_total_ars para un equipo, desde
    `alquiler_items` joined con `alquileres` filtrados por estado y
    ventana temporal.

    Devuelve {cant_pedidos, ingreso_total_ars}.
    """
    estados_validos = ("confirmado", "retirado", "devuelto", "finalizado")
    placeholders = ",".join(["%s"] * len(estados_validos))

    # fecha_desde / fecha_hasta son TIMESTAMP. La resta date - date en PG
    # devuelve int (días directamente).
    row = conn.execute(
        f"""
        SELECT
            COUNT(DISTINCT a.id) AS cant_pedidos,
            COALESCE(SUM(
                ai.cantidad * COALESCE(ai.precio_jornada, 0) *
                -- `cobro_modo='fijo'` (líneas personalizadas, combos, turno del
                -- Estudio EMBEBIDO #1308) ya cobra el monto único — multiplicarlo
                -- por los días DEL PEDIDO (que pueden no tener nada que ver con la
                -- duración real de esa línea) inflaba el ingreso atribuido. Solo
                -- 'jornada' se multiplica por día; el resto cuenta 1 vez.
                CASE WHEN ai.cobro_modo = 'jornada'
                     THEN GREATEST(1, (a.fecha_hasta::date - a.fecha_desde::date))
                     ELSE 1
                END
            ), 0) AS ingreso_total_ars
        FROM alquiler_items ai
        JOIN alquileres a ON a.id = ai.pedido_id
        WHERE ai.equipo_id = %s
          AND a.estado IN ({placeholders})
          AND a.fecha_desde IS NOT NULL
          AND a.fecha_hasta IS NOT NULL
          AND a.fecha_desde >= CURRENT_DATE - (%s || ' days')::interval
        """,
        (equipo_id, *estados_validos, str(ventana_dias)),
    ).fetchone()

    return {
        "cant_pedidos": int(row["cant_pedidos"] or 0),
        "ingreso_total_ars": int(row["ingreso_total_ars"] or 0),
    }


def recalcular_ranking_todos(
    conn,
    *,
    dry_run: bool = False,
    ventana_dias: int = VENTANA_DIAS_DEFAULT,
) -> dict:
    """Recalcula popularidad_score normalizado por categoría para todos los
    equipos. Lo que se calcula:

      1. Para cada equipo: cant_pedidos e ingreso_total_ars (en la ventana).
      2. Para cada categoría raíz: max_pedidos, max_ingreso (de sus equipos).
      3. popularidad_score = round(50 * pedidos/max_p + 50 * ingreso/max_i),
         donde max_p y max_i son los máximos de la categoría a la que pertenece.

    Equipos sin categoría: se rankean contra el universo entero (fallback).

    Devuelve un reporte con cambios y stats.
    """
    rows = conn.execute(
        """
        SELECT id, nombre, popularidad_score, cant_pedidos, ingreso_total_ars
        FROM equipos
        WHERE es_recurso_interno = FALSE
        ORDER BY id
        """
    ).fetchall()

    # Paso 1: calcular stats por equipo
    stats_por_equipo: dict[int, dict] = {}
    for r in rows:
        s = calcular_estadisticas_equipo(conn, r["id"], ventana_dias)
        s["categorias_raiz"] = _categorias_raiz_de(conn, r["id"])
        stats_por_equipo[r["id"]] = s

    # Paso 2: maxes por categoría raíz
    max_por_cat: dict[int, dict] = {}      # raiz_id → {max_pedidos, max_ingreso}
    universo = {"max_pedidos": 0, "max_ingreso": 0}
    for s in stats_por_equipo.values():
        universo["max_pedidos"] = max(universo["max_pedidos"], s["cant_pedidos"])
        universo["max_ingreso"] = max(universo["max_ingreso"], s["ingreso_total_ars"])
        for raiz_id in s["categorias_raiz"]:
            slot = max_por_cat.setdefault(raiz_id, {"max_pedidos": 0, "max_ingreso": 0})
            slot["max_pedidos"] = max(slot["max_pedidos"], s["cant_pedidos"])
            slot["max_ingreso"] = max(slot["max_ingreso"], s["ingreso_total_ars"])

    # Paso 3: calcular score y armar reporte
    cambios: list[dict] = []
    sin_cambios = 0

    for r in rows:
        eq_id = r["id"]
        s = stats_por_equipo[eq_id]

        # Tomar el máximo de las categorías a las que pertenece (si tiene
        # varias, usa el max global de esas raíces). Si no tiene categoría,
        # cae al universo.
        if s["categorias_raiz"]:
            max_p = max(max_por_cat[c]["max_pedidos"] for c in s["categorias_raiz"])
            max_i = max(max_por_cat[c]["max_ingreso"] for c in s["categorias_raiz"])
        else:
            max_p = universo["max_pedidos"]
            max_i = universo["max_ingreso"]

        score_pedidos = (s["cant_pedidos"] / max_p * 50) if max_p > 0 else 0
        score_ingreso = (s["ingreso_total_ars"] / max_i * 50) if max_i > 0 else 0
        nuevo_score = round(score_pedidos + score_ingreso)

        cambios_eq = (
            r["popularidad_score"] != nuevo_score
            or r["cant_pedidos"] != s["cant_pedidos"]
            or r["ingreso_total_ars"] != s["ingreso_total_ars"]
        )

        if cambios_eq:
            cambios.append({
                "id": eq_id,
                "nombre": r["nombre"],
                "antes": {
                    "score": r["popularidad_score"],
                    "pedidos": r["cant_pedidos"],
                    "ingreso": r["ingreso_total_ars"],
                },
                "despues": {
                    "score": nuevo_score,
                    "pedidos": s["cant_pedidos"],
                    "ingreso": s["ingreso_total_ars"],
                },
            })
            if not dry_run:
                conn.execute(
                    """
                    UPDATE equipos
                    SET popularidad_score = %s,
                        cant_pedidos = %s,
                        ingreso_total_ars = %s,
                        ranking_actualizado = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        nuevo_score,
                        s["cant_pedidos"],
                        s["ingreso_total_ars"],
                        eq_id,
                    ),
                )
        else:
            sin_cambios += 1

    # ─── Categorías y marcas (#131) ─────────────────────────────────────
    cambios_categorias = _recalcular_ranking_categorias(conn, dry_run=dry_run, ventana_dias=ventana_dias)
    cambios_marcas = _recalcular_ranking_marcas(conn, dry_run=dry_run, ventana_dias=ventana_dias)

    if not dry_run:
        conn.commit()

    return {
        "total": len(rows),
        "ventana_dias": ventana_dias,
        "cambios": cambios,
        "sin_cambios": sin_cambios,
        "cambios_categorias": cambios_categorias,
        "cambios_marcas": cambios_marcas,
        "max_por_categoria": {
            c: max_por_cat[c] for c in sorted(max_por_cat.keys())
        },
        "universo": universo,
        "dry_run": dry_run,
    }


def _recalcular_ranking_categorias(
    conn,
    *,
    dry_run: bool,
    ventana_dias: int,
) -> list[dict]:
    """Recalcula popularidad_score, cant_pedidos, ingreso_total_ars de
    cada categoría sumando los stats de todos sus equipos. Issue #131.

    Score normalizado contra el max de todas las categorías (un universo
    porque hay pocas categorías y la comparación tiene sentido entre todas).
    """
    estados_validos = ("confirmado", "retirado", "devuelto", "finalizado")
    placeholders = ",".join(["%s"] * len(estados_validos))

    # Para cada categoría: sumar pedidos e ingresos de equipos en sus
    # categoria_id (incluye sub-categorías si las hay).
    rows = conn.execute(
        f"""
        SELECT
            c.id,
            c.nombre,
            c.popularidad_score AS score_actual,
            c.cant_pedidos AS pedidos_actual,
            c.ingreso_total_ars AS ingreso_actual,
            COUNT(DISTINCT a.id) AS cant_pedidos,
            COALESCE(SUM(
                ai.cantidad * COALESCE(ai.precio_jornada, 0) *
                -- `cobro_modo='fijo'` (líneas personalizadas, combos, turno del
                -- Estudio EMBEBIDO #1308) ya cobra el monto único — multiplicarlo
                -- por los días DEL PEDIDO (que pueden no tener nada que ver con la
                -- duración real de esa línea) inflaba el ingreso atribuido. Solo
                -- 'jornada' se multiplica por día; el resto cuenta 1 vez.
                CASE WHEN ai.cobro_modo = 'jornada'
                     THEN GREATEST(1, (a.fecha_hasta::date - a.fecha_desde::date))
                     ELSE 1
                END
            ), 0) AS ingreso_total_ars
        FROM categorias c
        LEFT JOIN equipo_categorias ec ON ec.categoria_id = c.id
        LEFT JOIN alquiler_items ai ON ai.equipo_id = ec.equipo_id
        LEFT JOIN alquileres a ON a.id = ai.pedido_id
            AND a.estado IN ({placeholders})
            AND a.fecha_desde IS NOT NULL
            AND a.fecha_hasta IS NOT NULL
            AND a.fecha_desde >= CURRENT_DATE - (%s || ' days')::interval
        GROUP BY c.id, c.nombre, c.popularidad_score, c.cant_pedidos, c.ingreso_total_ars
        """,
        (*estados_validos, str(ventana_dias)),
    ).fetchall()

    max_pedidos = max((r["cant_pedidos"] or 0 for r in rows), default=0)
    max_ingreso = max((r["ingreso_total_ars"] or 0 for r in rows), default=0)

    cambios = []
    for r in rows:
        pedidos = int(r["cant_pedidos"] or 0)
        ingreso = int(r["ingreso_total_ars"] or 0)
        score_p = (pedidos / max_pedidos * 50) if max_pedidos > 0 else 0
        score_i = (ingreso / max_ingreso * 50) if max_ingreso > 0 else 0
        nuevo_score = round(score_p + score_i)

        if (
            r["score_actual"] != nuevo_score
            or r["pedidos_actual"] != pedidos
            or r["ingreso_actual"] != ingreso
        ):
            cambios.append({
                "id": r["id"],
                "nombre": r["nombre"],
                "antes": {"score": r["score_actual"], "pedidos": r["pedidos_actual"], "ingreso": r["ingreso_actual"]},
                "despues": {"score": nuevo_score, "pedidos": pedidos, "ingreso": ingreso},
            })
            if not dry_run:
                actualizar_ranking(conn, r["id"], nuevo_score, pedidos, ingreso)
    return cambios


def _recalcular_ranking_marcas(
    conn,
    *,
    dry_run: bool,
    ventana_dias: int,
) -> list[dict]:
    """Recalcula popularidad_score, cant_pedidos, ingreso_total_ars de
    cada marca sumando los stats de todos sus equipos. Issue #131.

    Las marcas se relacionan con sus equipos vía `equipos.brand_id` (FK),
    la fuente única del nombre de marca.
    """
    estados_validos = ("confirmado", "retirado", "devuelto", "finalizado")
    placeholders = ",".join(["%s"] * len(estados_validos))

    rows = conn.execute(
        f"""
        SELECT
            m.id,
            m.nombre,
            m.popularidad_score AS score_actual,
            m.cant_pedidos AS pedidos_actual,
            m.ingreso_total_ars AS ingreso_actual,
            COUNT(DISTINCT a.id) AS cant_pedidos,
            COALESCE(SUM(
                ai.cantidad * COALESCE(ai.precio_jornada, 0) *
                -- `cobro_modo='fijo'` (líneas personalizadas, combos, turno del
                -- Estudio EMBEBIDO #1308) ya cobra el monto único — multiplicarlo
                -- por los días DEL PEDIDO (que pueden no tener nada que ver con la
                -- duración real de esa línea) inflaba el ingreso atribuido. Solo
                -- 'jornada' se multiplica por día; el resto cuenta 1 vez.
                CASE WHEN ai.cobro_modo = 'jornada'
                     THEN GREATEST(1, (a.fecha_hasta::date - a.fecha_desde::date))
                     ELSE 1
                END
            ), 0) AS ingreso_total_ars
        FROM marcas m
        LEFT JOIN equipos e ON e.brand_id = m.id
        LEFT JOIN alquiler_items ai ON ai.equipo_id = e.id
        LEFT JOIN alquileres a ON a.id = ai.pedido_id
            AND a.estado IN ({placeholders})
            AND a.fecha_desde IS NOT NULL
            AND a.fecha_hasta IS NOT NULL
            AND a.fecha_desde >= CURRENT_DATE - (%s || ' days')::interval
        GROUP BY m.id, m.nombre, m.popularidad_score, m.cant_pedidos, m.ingreso_total_ars
        """,
        (*estados_validos, str(ventana_dias)),
    ).fetchall()

    max_pedidos = max((r["cant_pedidos"] or 0 for r in rows), default=0)
    max_ingreso = max((r["ingreso_total_ars"] or 0 for r in rows), default=0)

    cambios = []
    for r in rows:
        pedidos = int(r["cant_pedidos"] or 0)
        ingreso = int(r["ingreso_total_ars"] or 0)
        score_p = (pedidos / max_pedidos * 50) if max_pedidos > 0 else 0
        score_i = (ingreso / max_ingreso * 50) if max_ingreso > 0 else 0
        nuevo_score = round(score_p + score_i)

        if (
            r["score_actual"] != nuevo_score
            or r["pedidos_actual"] != pedidos
            or r["ingreso_actual"] != ingreso
        ):
            cambios.append({
                "id": r["id"],
                "nombre": r["nombre"],
                "antes": {"score": r["score_actual"], "pedidos": r["pedidos_actual"], "ingreso": r["ingreso_actual"]},
                "despues": {"score": nuevo_score, "pedidos": pedidos, "ingreso": ingreso},
            })
            if not dry_run:
                conn.execute(
                    """
                    UPDATE marcas
                    SET popularidad_score = %s,
                        cant_pedidos = %s,
                        ingreso_total_ars = %s,
                        ranking_actualizado = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (nuevo_score, pedidos, ingreso, r["id"]),
                )
    return cambios
