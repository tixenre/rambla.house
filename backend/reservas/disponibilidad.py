"""Camino de LECTURA del motor de reservas: disponibilidad (catálogo/calendario).

Funciones puras (reciben `conn`, sin abrir/cerrar transacción y SIN `FOR UPDATE`).
Originadas como move verbatim desde `routes/alquileres.py` (issue #501, Fase 1,
Paso 3). C4 (#635) hizo recursiva la derivación de compuestos y el conteo de
consumo (expandiendo hasta las hojas, vía `reservas.semantics`), para que un combo
anidado muestre disponibilidad correcta — antes, a 1 nivel, era optimista.

Comparten la MISMA semántica que el gate de escritura (reservas directas + vía
compuestos + mantenimiento + buffer), pero la lectura NUNCA toma locks: es para
mostrar disponibilidad, no para reservar. El gate (`_check_stock`) vive aparte.
"""
import datetime

from database import to_datetime

from reservas.estados import ESTADOS_RESERVADO
from reservas.semantics import (
    _expandir_mult,
    componentes_de,
    expandir_demanda,
    get_buffer_horas,
    rango_con_buffer,
)


def _libres_crudos(conn, fecha_desde, fecha_hasta, exclude_pedido_id=None) -> dict:
    """Disponibilidad "cruda" CON SIGNO de cada equipo como ítem suelto en
    [fecha_desde, fecha_hasta]: `{equipo_id: stock - reservado - mantenimiento}`,
    con el consumo de reservas expandido recursivamente y el buffer aplicado.

    Pipeline compartido por `calcular_disponibilidad` (que clampea a 0 y deriva)
    y `calcular_disponibilidad_draft` (que resta además la demanda de un draft y
    conserva el signo). Solo LECTURA — no lockea.
    """
    # exclude_pedido_id como NULL en SQL → (NULL IS NULL) = TRUE → no filtra nada
    excl = exclude_pedido_id  # None o int, ambos seguros como parámetro

    # Buffer: expandimos el rango consultado para exigir gap entre alquileres.
    buffer_horas = get_buffer_horas(conn)
    fd_buf, fh_buf = rango_con_buffer(fecha_desde, fecha_hasta, buffer_horas)

    # Stock propio de cada equipo (correcto para hojas; los compuestos se derivan).
    cantidad = {
        r["id"]: r["cantidad"]
        for r in conn.execute("SELECT id, cantidad FROM equipos WHERE eliminado_at IS NULL").fetchall()
    }

    # Items reservados (directos) por pedidos activos que se pisan con el rango
    # bufferizado, agregados por equipo. Excluye el propio pedido al editar.
    # COALESCE(ate.fecha_desde, p.fecha_desde): un ítem puede pertenecer a un turno del
    # Estudio EMBEBIDO (alquiler_turnos_estudio) con su propia ventana horaria, distinta
    # de la del pedido contenedor — no-op para ítems sin turno (ate.* es NULL).
    res_rows = conn.execute(f"""
        SELECT pi.equipo_id AS eid, COALESCE(SUM(pi.cantidad), 0) AS cant
        FROM alquiler_items pi
        JOIN alquileres p ON p.id = pi.pedido_id
        LEFT JOIN alquiler_turnos_estudio ate ON ate.id = pi.turno_estudio_id
        WHERE p.estado IN {ESTADOS_RESERVADO}
          AND pi.equipo_id IS NOT NULL
          AND COALESCE(ate.fecha_desde, p.fecha_desde) < %s
          AND COALESCE(ate.fecha_hasta, p.fecha_hasta) > %s
          AND (%s IS NULL OR p.id != %s)
        GROUP BY pi.equipo_id
    """, (fh_buf, fd_buf, excl, excl)).fetchall()
    reservados = {r["eid"]: r["cant"] for r in res_rows}

    # C4 #635: el consumo de cada item reservado se expande RECURSIVAMENTE hasta
    # las hojas (todos los componentes) → cuánto consume realmente cada equipo,
    # contando combos anidados. A 1 nivel un combo→kit→hoja no descontaba la hoja
    # (disponibilidad optimista falsa). Para datos NO anidados da exactamente
    # `directas + vía-kit`.
    consumo = expandir_demanda(conn, reservados, solo_esenciales=False)

    # Mantenimiento que bloquea stock (sin buffer — ventana exacta).
    mant = conn.execute("""
        SELECT equipo_id, COALESCE(SUM(cantidad), 0) AS bloqueado
        FROM equipo_mantenimiento
        WHERE bloquea_stock = TRUE
          AND fecha < %s
          AND COALESCE(fecha_hasta, fecha) > %s
        GROUP BY equipo_id
    """, (fecha_hasta, fecha_desde)).fetchall()
    en_mant = {r["equipo_id"]: r["bloqueado"] for r in mant}

    return {
        eid: cantidad.get(eid, 0) - consumo.get(eid, 0) - en_mant.get(eid, 0)
        for eid in cantidad
    }


def calcular_disponibilidad(conn, fecha_desde, fecha_hasta, exclude_pedido_id=None) -> dict:
    """Unidades libres por equipo en [fecha_desde, fecha_hasta], descontando
    reservas directas + vía kit + mantenimiento, con el buffer global aplicado.

    Devuelve `{str(equipo_id): unidades_libres}`. Solo LECTURA — no lockea.
    `exclude_pedido_id` (o None) excluye el propio pedido al editar.
    """
    crudo = _libres_crudos(conn, fecha_desde, fecha_hasta, exclude_pedido_id)
    # Disponibilidad de cada equipo como ítem suelto, nunca negativa (catálogo).
    raw = {eid: max(0, v) for eid, v in crudo.items()}
    return _derivar_compuestos(raw, componentes_de(conn))


def calcular_disponibilidad_draft(
    conn, fecha_desde, fecha_hasta, items: dict, exclude_pedido_id=None,
) -> dict:
    """Como `calcular_disponibilidad`, pero descuenta ADEMÁS la demanda de un
    DRAFT de items todavía no guardado (`{equipo_id: cantidad}`), expandida
    recursivamente hasta las hojas con la MISMA pieza que usa el gate
    (`expandir_demanda`, `solo_esenciales=False` — este número existe para
    predecir al gate, que es estricto). Es lo que el editor de pedidos muestra
    por línea: cuántas unidades más caben dado TODO el draft — sin esto, un kit
    y sus componentes sueltos en el mismo draft no se descontaban entre sí y el
    badge mentía ("2 libres" con 0 reales).

    Devuelve `{str(equipo_id): unidades}` CON SIGNO (sin clamp a 0): un valor
    negativo dice cuántas unidades FALTAN — el front lo usa para marcar
    overstock antes de que el gate rechace el guardado. Un compuesto hereda el
    faltante de sus hojas vía la derivación. Solo LECTURA — no lockea; el
    chequeo autoritativo sigue siendo el gate (`validar_stock`).
    """
    crudo = _libres_crudos(conn, fecha_desde, fecha_hasta, exclude_pedido_id)
    demanda_draft = expandir_demanda(conn, items, solo_esenciales=False)
    raw = {eid: v - demanda_draft.get(eid, 0) for eid, v in crudo.items()}
    # Derivación ESTRICTA (incluye best-effort), espejando la expansión del
    # gate: la línea de un kit hereda también el faltante de una hoja
    # best-effort — si no, el badge del kit diría "libres" y el gate rechazaría.
    return _derivar_compuestos(raw, componentes_de(conn), incluir_best_effort=True)


def _derivar_compuestos(raw: dict, comps_by: dict, incluir_best_effort: bool = False) -> dict:
    """C1+C4 #635 — derivación PURA de los equipos compuestos a partir de sus
    componentes, RECURSIVA (bottom-up / orden topológico). Dado `raw[eid]`
    (disponibilidad cruda de cada equipo como ítem suelto) y
    `comps_by[eid] = [(componente_id, cantidad, esencial), ...]`, devuelve
    `{str(eid): disponibilidad}`.

    Un compuesto está disponible tantas veces como permitan su stock propio Y sus
    componentes ESENCIALES: `min(raw[propio], min_i ⌊derivado[comp_i] / qty_i⌋)`
    sobre los componentes con `esencial=True`. C4: usa el valor DERIVADO de cada
    componente compuesto (no su `raw`), bajando hasta las hojas — un combo que
    contiene un kit hereda la (in)disponibilidad real del kit. Para hojas (sin
    componentes), devuelve `raw` sin cambio.

      · Kit: el stock propio (unidades primarias) limita junto a los componentes.
      · Combo: su `cantidad` propia es un sentinel alto (lo setea el builder en A2),
        así el min lo gobiernan los componentes — MISMO código, sin special-case
        de tipo. El motor es tipo-agnóstico, igual que el gate.

    C2: los componentes **best-effort** (`esencial=False`) NO entran en el min — un
    alargue escaso no esconde el combo (el faltante se refleja como "parcial" en
    A2). El memo da orden topológico natural; `path` corta ciclos (defensa en
    profundidad — los ciclos ya se previenen al escribir vía `_crea_ciclo_kit`).

    `incluir_best_effort=True` (SOLO el camino draft): el min cuenta TODOS los
    componentes, también los best-effort — el gate expande estricto
    (`solo_esenciales=False`), así que para PREDECIRLO la línea de un kit tiene
    que heredar también el faltante de una hoja best-effort. El camino clásico
    (catálogo) mantiene la semántica C2 sin cambios.
    """
    memo: dict[int, int] = {}

    def derivar(eid, path):
        if eid in memo:
            return memo[eid]
        if eid in path:
            return raw.get(eid, 0)  # ciclo (defensa): no memoiza para no envenenar
        comps = comps_by.get(eid)
        if not comps:
            val = raw.get(eid, 0)
        else:
            sub = path | {eid}
            limites = [
                derivar(cid, sub) // q
                for (cid, q, esencial) in comps
                if (esencial or incluir_best_effort) and q > 0
            ]
            val = min([raw.get(eid, 0), *limites]) if limites else raw.get(eid, 0)
        memo[eid] = val
        return val

    return {str(eid): derivar(eid, frozenset()) for eid in raw}


def dias_no_disponibles(conn, items: dict[int, int], desde: str, hasta: str) -> list[str]:
    """Días (YYYY-MM-DD) en [desde, hasta] donde algún equipo de `items`
    ({equipo_id: cantidad_requerida}) NO tiene unidades libres suficientes.

    Refleja la MISMA semántica que `calcular_disponibilidad` (reservas directas +
    vía kit + mantenimiento + buffer), evaluada día por día. Fuente para
    bloquear días en el calendario del cliente sin divergir del chequeo real
    que corre al confirmar el pedido.
    """
    if not items:
        return []
    d_desde = to_datetime(desde)
    d_hasta = to_datetime(hasta)
    if d_desde is None or d_hasta is None or d_hasta < d_desde:
        return []

    # C1 #635: expandir los compuestos del carrito a demanda por equipo (stock
    # propio + componentes, espejando el gate). Un día se bloquea si CUALQUIER
    # equipo de la demanda expandida no la cubre.
    demanda = expandir_demanda(conn, items)
    if not demanda:
        return []
    ids = list(demanda.keys())
    ph = ",".join("%s" for _ in ids)

    buffer_horas = get_buffer_horas(conn)
    buf = datetime.timedelta(hours=buffer_horas)
    # Ventana amplia para traer segmentos relevantes (incluye buffer).
    win_lo = (d_desde - buf).isoformat()
    win_hi = (d_hasta + datetime.timedelta(days=1) + buf).isoformat()

    stock = {
        r["id"]: r["cantidad"]
        for r in conn.execute(
            f"SELECT id, cantidad FROM equipos WHERE id IN ({ph})", ids
        ).fetchall()
    }

    # C4 #635: segmentos de reserva expandidos RECURSIVAMENTE. Cada item reservado
    # (apunte a la hoja, a un kit o a un combo anidado) aporta su segmento a TODAS
    # las hojas/nodos que consume, multiplicado por la receta y bajando hasta el
    # fondo. A 1 nivel un combo→kit→hoja no descontaba la hoja → el calendario
    # mostraba disponible un día que el gate después rechazaba. Solo guardamos lo
    # que cae en `ids` (la demanda del carrito). Para datos NO anidados es idéntico
    # a `directas + vía-kit`.
    id_set = set(ids)
    segs: dict[int, list[tuple]] = {eid: [] for eid in ids}
    graph = componentes_de(conn)
    exp_cache: dict[int, dict] = {}
    # COALESCE: un ítem de un turno del Estudio EMBEBIDO tiene su propia ventana horaria
    # (alquiler_turnos_estudio) — no-op para ítems sin turno.
    res_segs = conn.execute(
        f"""
        SELECT pi.equipo_id AS eid, COALESCE(ate.fecha_desde, p.fecha_desde) AS fd,
               COALESCE(ate.fecha_hasta, p.fecha_hasta) AS fh, pi.cantidad AS cant
        FROM alquiler_items pi
        JOIN alquileres p ON p.id = pi.pedido_id
        LEFT JOIN alquiler_turnos_estudio ate ON ate.id = pi.turno_estudio_id
        WHERE p.estado IN {ESTADOS_RESERVADO}
          AND pi.equipo_id IS NOT NULL
          AND COALESCE(ate.fecha_hasta, p.fecha_hasta) > %s
          AND COALESCE(ate.fecha_desde, p.fecha_desde) < %s
        """,
        (win_lo, win_hi),
    ).fetchall()
    for r in res_segs:
        e = r["eid"]
        consumo = exp_cache.get(e)
        if consumo is None:
            consumo = _expandir_mult({e: 1}, graph, solo_esenciales=False)
            exp_cache[e] = consumo
        fd, fh, cant = to_datetime(r["fd"]), to_datetime(r["fh"]), r["cant"]
        for (node, mult) in consumo.items():
            if node in id_set:
                segs[node].append((fd, fh, cant * mult))

    # Mantenimiento (sin buffer).
    mant: dict[int, list[tuple]] = {eid: [] for eid in ids}
    mrows = conn.execute(
        f"""
        SELECT equipo_id AS eid, fecha AS fd, COALESCE(fecha_hasta, fecha) AS fh, cantidad AS cant
        FROM equipo_mantenimiento
        WHERE bloquea_stock = TRUE
          AND equipo_id IN ({ph})
          AND COALESCE(fecha_hasta, fecha) > %s AND fecha < %s
        """,
        (*ids, win_lo, win_hi),
    ).fetchall()
    for r in mrows:
        mant.setdefault(r["eid"], []).append((to_datetime(r["fd"]), to_datetime(r["fh"]), r["cant"]))

    return _dias_bloqueados(stock, segs, mant, demanda, d_desde, d_hasta, buf)


def _dias_bloqueados(stock, segs, mant, items, d_desde, d_hasta, buf) -> list[str]:
    """Cómputo puro: días bloqueados dado stock, segmentos de reserva (con
    buffer) y de mantenimiento (sin buffer) por equipo, ya traídos de la DB.

    Event-based (diff-array) en vez de re-escanear todos los segmentos por cada
    día: O(días + segmentos) por equipo en vez de O(días × segmentos). La
    semántica es IDÉNTICA al loop original — cada segmento aporta su `cantidad`
    a los días que pisa, con el MISMO predicado de overlap half-open:

        día i (= [dia_i, dia_i+1)) lo cubre el segmento si  dia_i < sh' ∧ dia_i+1 > sd'

    donde [sd', sh') es el segmento, expandido por el buffer para reservas
    (sd-buf, sh+buf) y exacto para mantenimiento. Reordenar `sd<hi ∧ sh>lo` con
    `lo=dia_i-buf, hi=dia_i+1+buf` da exactamente esa forma. Los índices de día
    se calculan con aritmética ENTERA de timedelta (`.days`) — nada de división
    float — para que los bordes de medianoche no sufran off-by-one.

    El test diferencial `test_dias_no_disponibles_caracterizacion.py` fija que
    coincide con la implementación vieja sobre cientos de casos aleatorios.
    """
    one = datetime.timedelta(days=1)
    micro = datetime.timedelta(microseconds=1)
    dia0 = d_desde.replace(hour=0, minute=0, second=0, microsecond=0)
    fin0 = d_hasta.replace(hour=0, minute=0, second=0, microsecond=0)
    n = (fin0 - dia0).days + 1
    if n <= 0:
        return []

    def _acumular(diff, sd, sh, c, expandir):
        """Suma `c` al rango de días [i_lo, i_hi] que el segmento cubre, vía
        diff-array (incrementa en i_lo, decrementa en i_hi+1)."""
        if sd is None or sh is None:
            return
        sd2 = sd - buf if expandir else sd
        sh2 = sh + buf if expandir else sh
        # i_lo: menor i con dia_{i+1} > sd2  ⟺ i ≥ floor((sd2-dia0)/día) = .days
        # i_hi: mayor i con dia_i < sh2  ⟺ i = ceil((sh2-dia0)/día)-1 = (sh2-dia0-1µs).days
        i_lo = max(0, (sd2 - dia0).days)
        i_hi = min(n - 1, (sh2 - micro - dia0).days)
        if i_lo <= i_hi:
            diff[i_lo] += c
            diff[i_hi + 1] -= c

    bloqueados: list[str] = []
    # Por equipo: prefix-sum de reservas + mantenimiento por día.
    reservado_por_dia: dict = {}
    for eid in items:
        d_res = [0] * (n + 1)
        d_man = [0] * (n + 1)
        for (sd, sh, c) in segs.get(eid, []):
            _acumular(d_res, sd, sh, c, expandir=True)
        for (sd, sh, c) in mant.get(eid, []):
            _acumular(d_man, sd, sh, c, expandir=False)
        res = [0] * n
        man = [0] * n
        acc_r = acc_m = 0
        for i in range(n):
            acc_r += d_res[i]
            acc_m += d_man[i]
            res[i] = acc_r
            man[i] = acc_m
        reservado_por_dia[eid] = (res, man)

    for i in range(n):
        for eid, qty in items.items():
            res, man = reservado_por_dia[eid]
            disp = stock.get(eid, 0) - res[i] - man[i]
            if disp < max(1, qty):
                bloqueados.append((dia0 + i * one).date().isoformat())
                break
    return bloqueados


# ── Calendario de disponibilidad por equipo (#808) ──────────────────────────
#
# Estado por día de UN equipo, catálogo-facing: 🟢 libre / 🟠 parcial / 🔴 reservado.
# A diferencia de `dias_no_disponibles` (que colapsa a "¿se puede reservar el día
# entero?" con buffer, vía diff-array que SUMA todo segmento que toca el día), acá
# hace falta un BARRIDO TEMPORAL real: distinguir "1 unidad ocupada todo el día"
# (rojo) de "liberada a las 10am" (naranja) necesita la ocupación CONCURRENTE
# instante a instante, no la suma por día. Por eso `_estado_diario` es un sweep de
# eventos. SIN buffer: el calendario muestra ocupación FÍSICA (lo que el dueño
# describió), no bookability — puede diferir del date-picker a propósito.


def _estado_diario(stock, segs, mant, d_desde, d_hasta) -> dict[str, str]:
    """Cómputo PURO (testeable sin DB): estado por día de un equipo.

    `stock`: unidades totales. `segs`/`mant`: listas de `(desde, hasta, cantidad)`
    (datetimes) de reservas y de mantenimiento — ambos OCUPAN unidades. Devuelve
    `{YYYY-MM-DD: 'libre'|'parcial'|'reservado'}` para cada día en [d_desde, d_hasta].

    Barrido de eventos (+c al empezar, −c al terminar) ordenado en el tiempo; por
    cada día se toma el `max` y el `min` de la ocupación concurrente. Con
    `free = stock − ocupacion`:
      - `libre`     ⟺ max_ocupacion == 0 (nada encima en todo el día).
      - `reservado` ⟺ free_max == 0  (min_ocupacion ≥ stock: 0 libres todo el día).
      - `parcial`   ⟺ resto (quedan algunas unidades, o se libera/ocupa a mitad de día).
    """
    one = datetime.timedelta(days=1)
    dia0 = d_desde.replace(hour=0, minute=0, second=0, microsecond=0)
    fin0 = d_hasta.replace(hour=0, minute=0, second=0, microsecond=0)
    n = (fin0 - dia0).days + 1
    if n <= 0:
        return {}

    # Eventos de ocupación (reservas + mantenimiento). Cada segmento [sd, sh) suma
    # su cantidad mientras está activo. Segmentos vacíos/invertidos se ignoran.
    eventos: list[tuple] = []
    for (sd, sh, c) in list(segs) + list(mant):
        if sd is None or sh is None or sh <= sd:
            continue
        eventos.append((sd, c))
        eventos.append((sh, -c))
    eventos.sort(key=lambda e: e[0])

    resultado: dict[str, str] = {}
    ei = 0
    ocup = 0
    # Consumir lo que arranca ANTES del primer día (carry-in).
    while ei < len(eventos) and eventos[ei][0] < dia0:
        ocup += eventos[ei][1]
        ei += 1
    for i in range(n):
        day_start = dia0 + i * one
        day_end = day_start + one
        # Aplicar los eventos EXACTAMENTE al inicio del día (medianoche) ANTES de
        # medir: una reserva que arranca/termina a las 00:00 define la ocupación
        # del primer instante del día (half-open [day_start, day_end)).
        while ei < len(eventos) and eventos[ei][0] <= day_start:
            ocup += eventos[ei][1]
            ei += 1
        # Ocupación al inicio del día (carry) + en cada cambio dentro del día.
        mn = mx = ocup
        while ei < len(eventos) and eventos[ei][0] < day_end:
            ocup += eventos[ei][1]
            ei += 1
            if ocup < mn:
                mn = ocup
            if ocup > mx:
                mx = ocup
        if mx <= 0:
            estado = "libre"
        elif stock - mn <= 0:   # free_max == 0 → 0 libres en todo instante
            estado = "reservado"
        else:
            estado = "parcial"
        resultado[(dia0 + i * one).date().isoformat()] = estado
    return resultado


def estado_diario_equipo(conn, equipo_id: int, desde: str, hasta: str) -> dict:
    """Estado por día de UN equipo en [desde, hasta] — para el calendario de la
    ficha (#808). Devuelve `{'stock': N, 'dias': {YYYY-MM-DD: estado}}`.

    Reúne los datos con los MISMOS primitivos que `dias_no_disponibles`: stock de
    `equipos.cantidad`; segmentos de reserva (estados activos, `equipo_id IS NOT
    NULL`) expandidos recursivamente con `componentes_de` + `_expandir_mult` para
    que una reserva de un kit/combo que CONTIENE el equipo cuente (a cualquier
    profundidad); mantenimiento que bloquea stock. SIN buffer (ocupación física).
    """
    d_desde = to_datetime(desde)
    d_hasta = to_datetime(hasta)
    if d_desde is None or d_hasta is None or d_hasta < d_desde:
        return {"stock": 0, "dias": {}}

    row = conn.execute(
        "SELECT cantidad FROM equipos WHERE id = %s AND eliminado_at IS NULL",
        (equipo_id,),
    ).fetchone()
    if not row:
        return None  # el route traduce a 404
    stock = row["cantidad"] or 0

    # Ventana exacta (sin buffer). half-open: traer lo que pisa [dia0, fin+1día).
    win_lo = d_desde.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    win_hi = (d_hasta.replace(hour=0, minute=0, second=0, microsecond=0)
              + datetime.timedelta(days=1)).isoformat()

    # Segmentos de reserva expandidos hasta este equipo (backward, vía la receta).
    graph = componentes_de(conn)
    exp_cache: dict[int, dict] = {}
    segs: list[tuple] = []
    # COALESCE: un ítem de un turno del Estudio EMBEBIDO tiene su propia ventana horaria
    # (alquiler_turnos_estudio) — no-op para ítems sin turno.
    res_rows = conn.execute(
        f"""
        SELECT pi.equipo_id AS eid, COALESCE(ate.fecha_desde, p.fecha_desde) AS fd,
               COALESCE(ate.fecha_hasta, p.fecha_hasta) AS fh, pi.cantidad AS cant
        FROM alquiler_items pi
        JOIN alquileres p ON p.id = pi.pedido_id
        LEFT JOIN alquiler_turnos_estudio ate ON ate.id = pi.turno_estudio_id
        WHERE p.estado IN {ESTADOS_RESERVADO}
          AND pi.equipo_id IS NOT NULL
          AND COALESCE(ate.fecha_hasta, p.fecha_hasta) > %s
          AND COALESCE(ate.fecha_desde, p.fecha_desde) < %s
        """,
        (win_lo, win_hi),
    ).fetchall()
    for r in res_rows:
        e = r["eid"]
        consumo = exp_cache.get(e)
        if consumo is None:
            consumo = _expandir_mult({e: 1}, graph, solo_esenciales=False)
            exp_cache[e] = consumo
        mult = consumo.get(equipo_id)
        if mult:
            segs.append((to_datetime(r["fd"]), to_datetime(r["fh"]), (r["cant"] or 0) * mult))

    # Mantenimiento que bloquea stock. Sin `fecha_hasta` → bloquea ese día completo.
    # `>= win_lo` (no `>` como en las queries gemelas con buffer): acá la ventana NO
    # tiene buffer, así que un mantenimiento puntual del PRIMER día (solo `fecha`,
    # COALESCE == win_lo == medianoche de `desde`) debe entrar; con `>` se perdería.
    mant: list[tuple] = []
    mrows = conn.execute(
        """
        SELECT fecha AS fd, fecha_hasta AS fh, cantidad AS cant
        FROM equipo_mantenimiento
        WHERE bloquea_stock = TRUE
          AND equipo_id = %s
          AND COALESCE(fecha_hasta, fecha) >= %s AND fecha < %s
        """,
        (equipo_id, win_lo, win_hi),
    ).fetchall()
    for r in mrows:
        fd = to_datetime(r["fd"])
        fh = to_datetime(r["fh"]) if r["fh"] else None
        if fd is None:
            continue
        if fh is None or fh <= fd:
            fh = fd.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
        mant.append((fd, fh, r["cant"] or 0))

    return {"stock": stock, "dias": _estado_diario(stock, segs, mant, d_desde, d_hasta)}
