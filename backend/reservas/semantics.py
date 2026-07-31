"""Primitivas semánticas del motor de reservas (compartidas lectura + gate).

Originadas como move verbatim desde `routes/alquileres.py` (issue #501, Fase 1,
Paso 2). C4 (#635) agregó acá el NÚCLEO de la expansión recursiva — una sola pieza
(`_expandir_mult`) que recorre el DAG de composición en cualquier dirección, más
el grafo inverso (`parientes_de`) y el conteo de consumo recursivo
(`reservado_total`) — para que lectura y gate cuenten los combos anidados sin
divergir. El lock `FOR UPDATE` y la transacción NO viven acá — son del gate.

Todos los valores van como bound params (`%s`); los únicos tokens interpolados en
SQL son la constante interna `ESTADOS_RESERVADO` y el placeholder `ph` de los IN.
"""
import datetime
import threading
import time

from database import to_datetime

from reservas.estados import ESTADOS_RESERVADO


# ── Cache del buffer global ──────────────────────────────────────────────────
# `buffer_horas_alquiler` (gap de prep entre alquileres) se lee en CADA chequeo
# de disponibilidad y en CADA confirmación, pero cambia rarísimo (lo setea el
# admin, ~1 vez/mes). Lo cacheamos a nivel proceso para no pegarle a
# `app_settings` en cada request:
#   · Invalidación explícita: el writer de settings llama
#     `invalidate_buffer_cache()` al cambiarlo → reflejo INSTANTÁNEO. Prod corre
#     un solo worker uvicorn → la invalidación es 100% efectiva, cero staleness.
#   · TTL de red de seguridad: si algún día hay multi-worker/réplica, cada
#     proceso recarga solo a los `_BUFFER_TTL_SEG`. El buffer es un gap de prep,
#     NO entra en el conteo de stock → un valor viejo por segundos nunca puede
#     causar overbooking (a lo sumo un gap de prep levemente distinto).
_BUFFER_TTL_SEG = 60.0
_buffer_lock = threading.Lock()
_buffer_valor: int | None = None
_buffer_expira_en: float = 0.0


def _leer_buffer_db(conn) -> int:
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = %s", ("buffer_horas_alquiler",)
    ).fetchone()
    if not row:
        return 0
    try:
        return max(0, int(row["value"]))
    except (ValueError, TypeError):
        return 0


def get_buffer_horas(conn) -> int:
    """Horas de prep/revisión exigidas entre alquileres (setting global, cacheado).

    Devuelve el valor cacheado mientras esté fresco; recarga de `app_settings`
    en el primer acceso, tras un cambio (vía `invalidate_buffer_cache`) o cuando
    vence el TTL. Doble-check con lock: aunque varios threads colisionen en el
    miss, solo uno pega a la DB."""
    global _buffer_valor, _buffer_expira_en
    valor = _buffer_valor
    if valor is not None and time.monotonic() < _buffer_expira_en:
        return valor
    with _buffer_lock:
        if _buffer_valor is not None and time.monotonic() < _buffer_expira_en:
            return _buffer_valor
        _buffer_valor = _leer_buffer_db(conn)
        _buffer_expira_en = time.monotonic() + _BUFFER_TTL_SEG
        return _buffer_valor


def invalidate_buffer_cache() -> None:
    """Descarta el buffer cacheado → la próxima lectura va a la DB. La llama el
    writer de settings al cambiar `buffer_horas_alquiler`; los tests la corren
    entre casos (fixture autouse) para no arrastrar valores entre escenarios."""
    global _buffer_valor, _buffer_expira_en
    with _buffer_lock:
        _buffer_valor = None
        _buffer_expira_en = 0.0


def rango_con_buffer(fecha_desde, fecha_hasta, buffer_horas: int):
    """Expande [desde, hasta] en `buffer_horas` por cada lado. Expandir el
    rango nuevo equivale a exigir `buffer_horas` de gap contra los alquileres
    existentes (el overlap es simétrico). Devuelve datetimes ISO completos
    (con hora) para que el overlap respete la hora de retiro/devolución —no se
    trunca a día.

    Acepta str ISO o datetime (las columnas son TIMESTAMP)."""
    if buffer_horas <= 0:
        return fecha_desde, fecha_hasta
    try:
        d0 = to_datetime(fecha_desde) - datetime.timedelta(hours=buffer_horas)
        d1 = to_datetime(fecha_hasta) + datetime.timedelta(hours=buffer_horas)
        return d0.isoformat(), d1.isoformat()
    except (ValueError, TypeError, AttributeError):
        return fecha_desde, fecha_hasta


def unidades_en_mantenimiento_batch(
    conn, equipo_ids, fecha_desde: str, fecha_hasta: str,
) -> dict[int, int]:
    """Unidades fuera de servicio por mantenimiento de VARIOS equipos en UNA query
    (#626): `{equipo_id: unidades}`. Una entrada con bloquea_stock=TRUE saca
    `cantidad` unidades durante [fecha, fecha_hasta]; el overlap usa la misma
    convención half-open que los alquileres y el buffer NO aplica (ventana exacta).

    FUENTE ÚNICA de la subquery de mantenimiento: el escalar
    `unidades_en_mantenimiento` delega acá con un solo id; el gate la usa para
    contar todos los equipos del chequeo de una. El único token interpolado es el
    placeholder `ph` del IN; los valores van como bound params. Equipos sin
    mantenimiento que bloquee NO aparecen en el dict (el caller default-ea a 0)."""
    ids = list(equipo_ids)
    if not ids:
        return {}
    ph = ",".join("%s" for _ in ids)
    rows = conn.execute(f"""
        SELECT equipo_id, COALESCE(SUM(cantidad), 0)
        FROM equipo_mantenimiento
        WHERE equipo_id IN ({ph})
          AND bloquea_stock = TRUE
          AND fecha < %s
          AND COALESCE(fecha_hasta, fecha) > %s
        GROUP BY equipo_id
    """, (*ids, fecha_hasta, fecha_desde)).fetchall()
    return {r[0]: int(r[1] or 0) for r in rows}


def unidades_en_mantenimiento(conn, equipo_id: int, fecha_desde: str, fecha_hasta: str) -> int:
    """Unidades del equipo fuera de servicio por mantenimiento en el rango (escalar;
    delega en `unidades_en_mantenimiento_batch`, la fuente única de la subquery)."""
    return unidades_en_mantenimiento_batch(
        conn, [equipo_id], fecha_desde, fecha_hasta
    ).get(equipo_id, 0)


def consolidar_items_por_equipo(items) -> dict:
    """Consolida items del mismo equipo sumando cantidades.

    Si un pedido tiene 2 items con equipo_id=42 (cantidad=2 cada uno),
    necesitamos validar 4 vs stock, no 2 cada uno por separado. Sino
    pasaría la validación con falsa negativa (cada iteración chequea
    2 < stock sin sumar el otro item del mismo equipo).

    Issue #102 — bug latente cuando el frontend permite items duplicados
    o si se usa la API directamente.

    Acepta iterable de filas con keys: equipo_id, cantidad, nombre, stock_total.
    Devuelve dict[equipo_id, {equipo_id, cantidad_total, nombre, stock_total}].
    """
    out: dict[int, dict] = {}
    for it in items:
        eq_id = it["equipo_id"]
        if eq_id not in out:
            out[eq_id] = {
                "equipo_id": eq_id,
                "cantidad": 0,
                "nombre": it["nombre"],
                "stock_total": it["stock_total"],
            }
        out[eq_id]["cantidad"] += it["cantidad"]
    return out


def componentes_de(conn, equipo_ids=None) -> dict:
    """Componentes DIRECTOS (1 nivel) de cada equipo compuesto:
    `{equipo_id: [(componente_id, cantidad, esencial), ...]}`.

    Si `equipo_ids` se pasa, filtra a esos equipos; si no, trae todo el grafo de
    una. `esencial` (bool) viene de `kit_componentes.esencial` (default TRUE): un
    componente best-effort (esencial=false) NO constriñe la disponibilidad ni
    bloquea días (C2) — solo los esenciales. Es la adyacencia HACIA ABAJO; la
    expansión recursiva hasta las hojas (C4) la hace `_expandir_mult`.
    """
    if equipo_ids is not None:
        ids = list(equipo_ids)
        if not ids:
            return {}
        ph = ",".join("%s" for _ in ids)
        rows = conn.execute(
            f"SELECT equipo_id, componente_id, cantidad, "
            f"COALESCE(esencial, TRUE) AS esencial FROM kit_componentes "
            f"WHERE equipo_id IN ({ph})",
            tuple(ids),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT equipo_id, componente_id, cantidad, "
            "COALESCE(esencial, TRUE) AS esencial FROM kit_componentes"
        ).fetchall()
    out: dict[int, list] = {}
    for r in rows:
        out.setdefault(r["equipo_id"], []).append(
            (r["componente_id"], r["cantidad"], bool(r["esencial"]))
        )
    return out


def parientes_de(conn, componente_ids=None) -> dict:
    """Padres DIRECTOS (1 nivel) de cada equipo — el grafo de composición INVERSO:
    `{componente_id: [(equipo_id, cantidad, esencial), ...]}`.

    Espejo HACIA ARRIBA de `componentes_de`. Lo usa el conteo de consumo recursivo
    (`reservado_total`): para saber cuánto se reservó de una hoja hay que subir por
    todos los compuestos que la contienen (a cualquier profundidad). `esencial` es
    el flag de la arista padre→hijo. Si `componente_ids` se pasa, filtra; si no,
    trae todo el grafo inverso de una.
    """
    if componente_ids is not None:
        ids = list(componente_ids)
        if not ids:
            return {}
        ph = ",".join("%s" for _ in ids)
        rows = conn.execute(
            f"SELECT equipo_id, componente_id, cantidad, "
            f"COALESCE(esencial, TRUE) AS esencial FROM kit_componentes "
            f"WHERE componente_id IN ({ph})",
            tuple(ids),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT equipo_id, componente_id, cantidad, "
            "COALESCE(esencial, TRUE) AS esencial FROM kit_componentes"
        ).fetchall()
    out: dict[int, list] = {}
    for r in rows:
        out.setdefault(r["componente_id"], []).append(
            (r["equipo_id"], r["cantidad"], bool(r["esencial"]))
        )
    return out


def _expandir_mult(roots: dict, graph: dict, solo_esenciales: bool, max_depth: int = 64) -> dict:
    """Expansión recursiva de multiplicidades sobre el DAG de composición (C4 #635).

    NÚCLEO compartido de TODA la expansión del motor (lectura + gate). Dado un
    conjunto de `roots` ({nodo: cantidad}) y un grafo de adyacencia
    `graph[nodo] = [(vecino, cantidad_arista, esencial), ...]`, acumula la demanda
    total sobre CADA nodo alcanzable multiplicando las cantidades a lo largo de
    cada camino y SUMANDO los caminos (un diamante A→B→D y A→C→D suma las dos
    contribuciones a D). Es agnóstico de la dirección: con `componentes_de` expande
    hacia las HOJAS (demanda hacia abajo); con `parientes_de` expande hacia las
    RAÍCES (consumo hacia arriba). Una sola pieza recursiva → lectura y gate nunca
    divergen.

    `esencial` se propaga de forma CONJUNTIVA (AND a lo largo del camino): con
    `solo_esenciales=True`, una arista best-effort corta el descenso → toda su
    subrama queda fuera de la demanda dura (decisión C4: un sub-kit best-effort
    arrastra a toda su subrama como best-effort, coherente con C2 a 1 nivel). Con
    `solo_esenciales=False` se cuentan todas las aristas (semántica del gate y del
    conteo de consumo — el gate sigue estricto, igual que hoy).

    Guardas (defensa en profundidad; los ciclos ya se previenen al ESCRIBIR vía
    `_crea_ciclo_kit`): `path` corta back-edges (ciclo en el camino actual, sin
    impedir diamantes legítimos) y `max_depth` acota la profundidad. Aristas con
    cantidad <= 0 no aportan demanda.
    """
    demanda: dict = {}

    def visit(node, mult, depth, path):
        demanda[node] = demanda.get(node, 0) + mult
        if depth >= max_depth:
            return
        for (vecino, cant, esencial) in graph.get(node, ()):
            if (solo_esenciales and not esencial) or cant <= 0 or vecino in path:
                continue
            visit(vecino, mult * cant, depth + 1, path | {node})

    for (node, qty) in roots.items():
        if qty and qty > 0:
            visit(node, qty, 0, frozenset())
    return demanda


def expandir_demanda(conn, items: dict, solo_esenciales: bool = True) -> dict:
    """Expande `items` ({equipo_id: cantidad}) a demanda consolidada por equipo
    ({equipo_id: demanda}), RECURSIVAMENTE hasta las hojas (C4 #635).

    Cada compuesto aporta su propia demanda + la de cada componente (ponderada por
    la cantidad de la receta), bajando por TODO el árbol — un combo que contiene un
    kit que contiene hojas suma la demanda de las hojas (a 1 nivel se contaban de
    menos → overbooking en anidados). Espeja exactamente la expansión del gate
    (misma multiplicación, mismos componentes) → fuente única para que LECTURA y
    GATE exijan la misma demanda y no diverjan.

    `solo_esenciales=True` (default, camino de LECTURA): solo los componentes
    ESENCIALES aportan demanda — un best-effort faltante no bloquea (C2) y su
    subrama entera queda fuera (AND a lo largo del camino). `solo_esenciales=False`
    (gate / conteo de consumo): cuentan todos los componentes (gate estricto, igual
    que hoy; la lógica blanda de best-effort se resuelve afuera del gate).
    """
    return _expandir_mult(items, componentes_de(conn), solo_esenciales)


def reservado_directo_batch(
    conn, equipo_ids, excl_pedido_id: int, fh_buf, fd_buf,
) -> dict[int, int]:
    """Reserva DIRECTA de VARIOS equipos en UNA query (#626): `{equipo_id: unidades}`
    de los items que apuntan a cada equipo en otros pedidos activos que se pisan con
    el rango ya bufferizado [fd_buf, fh_buf].

    FUENTE ÚNICA de la subquery de reserva directa: el escalar `reservado_directo`
    delega acá con un solo id, y el gate la usa para PRELLENAR el cache de consumo
    de `reservado_total` con todos los nodos de un chequeo en una sola lectura, en
    vez de O(N) queries (el `cache`/memo era el medio-paso; esto lo completa). El
    gate autoritativo (`validar_stock`) y el dry-run del portal
    (`validar_stock_hipotetico`) comparten esta subquery vía el núcleo único
    `gate._validar_demanda`, sin re-copiar SQL. Todos los valores van como bound
    params; los únicos tokens interpolados son la constante interna ESTADOS_RESERVADO
    y el placeholder `ph` del IN. Equipos sin reserva NO aparecen (caller → 0).

    `COALESCE(ate.fecha_desde, p.fecha_desde)`/`fecha_hasta` (turno del Estudio EMBEBIDO,
    `alquiler_turnos_estudio`, #1308 rediseño "turno como ítem"): un ítem de OTRO pedido
    puede tener su propia ventana horaria distinta de la del pedido contenedor — sin el
    COALESCE, un turno de 2hs embebido en un pedido de 3 días contaría como reservado los
    3 días enteros. Para un ítem sin turno (100% de los casos hoy) es un no-op algebraico:
    `ate.fecha_desde` es NULL, `COALESCE` cae a `p.fecha_desde`, igual que antes.
    """
    ids = list(equipo_ids)
    if not ids:
        return {}
    ph = ",".join("%s" for _ in ids)
    rows = conn.execute(f"""
        SELECT pi2.equipo_id, COALESCE(SUM(pi2.cantidad), 0)
        FROM alquiler_items pi2
        JOIN alquileres p ON p.id = pi2.pedido_id
        LEFT JOIN alquiler_turnos_estudio ate ON ate.id = pi2.turno_estudio_id
        WHERE pi2.equipo_id IN ({ph})
          AND p.id != %s
          AND p.estado IN {ESTADOS_RESERVADO}
          AND COALESCE(ate.fecha_desde, p.fecha_desde) < %s
          AND COALESCE(ate.fecha_hasta, p.fecha_hasta) > %s
        GROUP BY pi2.equipo_id
    """, (*ids, excl_pedido_id, fh_buf, fd_buf)).fetchall()
    return {r[0]: int(r[1] or 0) for r in rows}


def reservado_directo(conn, equipo_id: int, excl_pedido_id: int, fh_buf, fd_buf) -> int:
    """Unidades de `equipo_id` reservadas DIRECTAMENTE por otros pedidos activos que
    se pisan con el rango bufferizado [fd_buf, fh_buf] (escalar; delega en
    `reservado_directo_batch`, la fuente única de la subquery)."""
    return reservado_directo_batch(
        conn, [equipo_id], excl_pedido_id, fh_buf, fd_buf
    ).get(equipo_id, 0)


def consumo_nodos(rev_graph: dict, equipo_ids) -> set:
    """Conjunto de nodos cuya reserva DIRECTA entra en el consumo recursivo de
    `equipo_ids`: cada equipo más TODOS sus antecesores en el grafo inverso de
    composición (`parientes_de`), a cualquier profundidad. Permite batchear
    `reservado_directo` para todos de una (#626) y prellenar el cache de
    `reservado_total` → mismo resultado que llamarla por equipo, sin O(N) lecturas.
    Usa el MISMO núcleo de expansión (`_expandir_mult`, `solo_esenciales=False`) que
    `reservado_total`, así el set cubre exactamente los nodos que esa función visita."""
    return set(_expandir_mult({e: 1 for e in equipo_ids}, rev_graph, solo_esenciales=False))


def reservado_total(conn, equipo_id: int, excl_pedido_id: int, fh_buf, fd_buf,
                    solo_esenciales: bool = False, rev_graph=None, cache=None) -> int:
    """Unidades de `equipo_id` reservadas por OTROS pedidos activos que se pisan con
    el rango bufferizado [fd_buf, fh_buf], contando la reserva DIRECTA y la que
    llega a través de CUALQUIER compuesto que lo contenga, a CUALQUIER profundidad
    (C4 #635 — conteo de consumo recursivo).

    Reemplaza al par `reservado_directo + reservado_via_kit`, que solo veía 1 nivel
    y dejaba pasar overbooking en combos anidados: un combo→kit→hoja reservado por
    otro pedido NO sumaba a la hoja (el kit no es padre DIRECTO de la hoja). Acá se
    sube por el grafo inverso de composición (`parientes_de`) acumulando la
    multiplicidad de cada camino, y se suma
    `reservado_directo(antecesor) * multiplicidad` sobre el propio equipo y todos
    sus antecesores. Para datos NO anidados da EXACTAMENTE
    `reservado_directo + reservado_via_kit` (caracterización: el término de
    profundidad-1 es justo la vieja subquery vía-kit).

    `solo_esenciales=False` (default, gate + chequeo hipotético): cuenta TODOS los
    caminos, igual que hoy el gate. `rev_graph`/`cache` son opcionales para reusar
    el grafo inverso y memoizar las sub-consultas a lo largo de un mismo chequeo
    (el gate lockea N nodos): no cambian el resultado, solo evitan repetir lecturas.
    NO toma locks — el `SELECT ... FOR UPDATE` lo toma el caller sobre la fila del
    equipo, antes de llamar a esta función.
    """
    rev = rev_graph if rev_graph is not None else parientes_de(conn)
    multiplicidades = _expandir_mult({equipo_id: 1}, rev, solo_esenciales)
    total = 0
    for (antecesor, mult) in multiplicidades.items():
        if cache is not None and antecesor in cache:
            rd = cache[antecesor]
        else:
            rd = reservado_directo(conn, antecesor, excl_pedido_id, fh_buf, fd_buf)
            if cache is not None:
                cache[antecesor] = rd
        total += mult * rd
    return total
