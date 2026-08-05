"""Liquidación: cuánto entró y cómo se reparte entre dueños (#88).

Reglas (decididas con el dueño):
- Solo cuentan pedidos **100% pagados** (`monto_pagado >= monto_total`).
- Cada pedido se atribuye al **día en que quedó saldado** (la fecha del pago con
  el que el acumulado cruzó `monto_total`) — NO por fecha de alquiler. Si se pagó
  en otro mes, cuenta para ese mes.
- El `monto_total` se prorratea entre los equipos del pedido por su participación
  en el `subtotal`, y la plata de cada equipo se reparte según su `dueno`
  (`comisiones.repartir`).

El pipeline es SQL → filas planas → `agregar` (puro), para poder testear la
matemática (prorrateo + reparto + buckets) sin DB.
"""

from collections import defaultdict

from .comisiones import cargar_modelo, repartir

# Arranque limpio de la liquidación (clean start, 2026-06). Los pedidos cuyo
# ALQUILER (`fecha_desde`) es anterior a esta fecha NO cuentan para el reporte —
# el reparto entre dueños arranca de cero en junio 2026, sin arrastrar el
# histórico. Es una decisión de una sola vez, FIJA en el código a propósito (no
# administrable desde el back-office). El corte es por fecha del alquiler (cuándo
# fue el pedido), NO por fecha de pago: un alquiler de mayo pagado en junio no
# cuenta. Aplica solo a la liquidación (la solapa Reportes); el Resumen general
# de estadísticas sigue mostrando el histórico completo.
LIQUIDACION_INICIO = "2026-06-01"

# Fragmento SQL compartido (#88, #721): define cuándo un pedido quedó "saldado"
# — el día en que el acumulado de pagos cruzó su `monto_total`, con el corte del
# clean start aplicado (solo pedidos con `fecha_desde >= LIQUIDACION_INICIO`). Es
# lógica de plata, así que vive en UN solo lugar y se compone como CTE tanto por
# el reporte (`filas_atribucion`) como por la reconciliación (chequeo de mes
# cerrado), para que las dos no puedan divergir. Expone las CTEs `acum` y
# `saldado(pedido_id, fecha_saldado)`. Se inserta justo después de `WITH`.
SALDADO_CTE = f"""
        acum AS (
            SELECT ap.pedido_id,
                   ap.fecha,
                   SUM(ap.monto) OVER (
                       PARTITION BY ap.pedido_id ORDER BY ap.fecha, ap.id
                   ) AS acumulado
            FROM alquiler_pagos ap
            WHERE NOT ap.anulado
        ),
        saldado AS (
            SELECT a.pedido_id, MIN(a.fecha) AS fecha_saldado
            FROM acum a
            JOIN alquileres al ON al.id = a.pedido_id
            WHERE al.estado <> 'cancelado'
              AND al.monto_total > 0
              AND al.fecha_desde >= '{LIQUIDACION_INICIO}'
              AND a.acumulado >= al.monto_total
            GROUP BY a.pedido_id
        )
"""


def filas_atribucion(conn, desde: str, hasta: str) -> list[dict]:
    """Filas `(fecha, dueno, equipo, monto)`: el monto prorrateado que cada equipo
    aportó, fechado en el día en que su pedido quedó saldado, dentro del rango.
    Incluye también `pedido_id`/`numero_pedido`/`cliente` (metadata del pedido,
    misma para todas las filas de un mismo pedido) para el detalle de "pedidos"
    por dueño en `agregar` — no se agrega en SQL, se agrupa en Python.

    Cuando `suma_items = 0` (todos los ítems del pedido tienen `subtotal` 0, ej.
    100% de descuento a nivel ítem) pero `monto_total > 0`, el prorrateo
    proporcional no tiene base — antes eso daba `NULL` (vía `NULLIF`) y la plata
    del pedido desaparecía en silencio del reporte. Fix: en ese caso se reparte
    el `monto_total` **en partes iguales** entre los ítems del pedido (fallback
    explícito, no "a Rental" — no hay forma de saber a qué dueño atribuirlo sin
    una base de prorrateo real), garantizando que la plata nunca se pierda."""
    from database import row_to_dict
    sql = f"""
        WITH {SALDADO_CTE},
        en_rango AS (
            SELECT pedido_id, fecha_saldado
            FROM saldado
            WHERE fecha_saldado::date BETWEEN %s::date AND %s::date
        ),
        tot AS (
            SELECT pedido_id, SUM(subtotal) AS suma_items, COUNT(*) AS cant_items
            FROM alquiler_items
            GROUP BY pedido_id
        )
        SELECT r.fecha_saldado::date                              AS fecha,
               -- Un turno del Estudio vinculado NO es un pedido aparte en el
               -- reporte (#1308): su aporte se agrupa bajo el pedido principal,
               -- que es la venta real. La ATRIBUCIÓN por dueño no se toca (el
               -- ítem centinela sigue atribuyendo al Estudio) — se consolida
               -- solo quién "es" el pedido. Trade-off aceptado: si el principal
               -- y su turno saldan en MESES distintos (pagos parciales, o un
               -- turno agregado después de cobrar), el mismo pedido aparece en
               -- los dos meses y el conteo multi-mes sobre-cuenta en 1 — vale
               -- más que mostrarle al dueño un pedido fantasma todos los meses.
               COALESCE(al.pedido_principal_id, al.id)            AS pedido_id,
               COALESCE(pp.numero_pedido, pp.id,
                        al.numero_pedido, al.id)                  AS numero_pedido,
               COALESCE(c.nombre || ' ' || c.apellido, al.cliente_nombre) AS cliente,
               COALESCE(e.dueno, 'Rental')                        AS dueno,
               COALESCE(e.nombre, pi.nombre_libre)                AS equipo,
               CASE
                   WHEN t.suma_items = 0 THEN al.monto_total::numeric / t.cant_items
                   ELSE al.monto_total * pi.subtotal::numeric / t.suma_items
               END                                                AS monto
        FROM en_rango r
        JOIN alquileres al ON al.id = r.pedido_id
        JOIN alquiler_items pi ON pi.pedido_id = al.id
        LEFT JOIN equipos e ON e.id = pi.equipo_id
        LEFT JOIN clientes c ON c.id = al.cliente_id
        LEFT JOIN alquileres pp ON pp.id = al.pedido_principal_id
        JOIN tot t ON t.pedido_id = al.id
    """
    rows = conn.execute(sql, (desde, hasta)).fetchall()
    return [row_to_dict(r) for r in rows]


def agregar(filas: list[dict], modelo: dict) -> dict:
    """Agrega filas planas en el reporte. Puro (sin DB). Aplica el reparto de
    comisiones por fila y arma resumen + serie mensual + serie diaria + detalle
    por dueño. Los montos se redondean a enteros ARS al serializar."""
    total = 0.0
    por_benef: dict[str, float] = defaultdict(float)
    mes_total: dict[str, float] = defaultdict(float)
    mes_benef: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    dia_total: dict[str, float] = defaultdict(float)
    dia_benef: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    dueno_generado: dict[str, float] = defaultdict(float)
    dueno_reparto: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    dueno_equipos: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    # Conteo de "veces alquilado" = pedidos DISTINTOS (solo cobrados), para el
    # resumen mensual por dueño.
    pedidos_global: set = set()
    dueno_pedidos: dict[str, set] = defaultdict(set)
    equipo_pedidos: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    # Detalle de "rentals" por dueño (2026-07-04): cuánto aportó cada PEDIDO
    # (no equipo) a cada dueño — un pedido con equipos de 2 dueños distintos
    # aporta un monto DISTINTO a cada uno. `pedido_meta` es la metadata (fecha/
    # cliente/numero_pedido) del pedido, igual para todas sus filas.
    dueno_pedido_monto: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    pedido_meta: dict[int, dict] = {}

    for f in filas:
        monto = float(f["monto"] or 0)
        if monto == 0:
            continue
        dueno = f["dueno"]
        equipo = f["equipo"]
        fecha = str(f["fecha"])
        mes, dia = fecha[:7], fecha[:10]

        total += monto
        mes_total[mes] += monto
        dia_total[dia] += monto
        dueno_generado[dueno] += monto
        dueno_equipos[dueno][equipo] += monto

        pid = f.get("pedido_id")
        if pid is not None:
            pedidos_global.add(pid)
            dueno_pedidos[dueno].add(pid)
            equipo_pedidos[dueno][equipo].add(pid)
            dueno_pedido_monto[dueno][pid] += monto
            pedido_meta.setdefault(
                pid,
                {
                    "numero_pedido": f.get("numero_pedido") or pid,
                    "cliente": f.get("cliente") or "",
                    "fecha": fecha,
                },
            )

        for benef, m in repartir(dueno, monto, modelo).items():
            por_benef[benef] += m
            mes_benef[mes][benef] += m
            dia_benef[dia][benef] += m
            dueno_reparto[dueno][benef] += m

    def rd(d: dict) -> dict:
        return {k: int(round(v)) for k, v in d.items()}

    por_mes = [
        {"mes": m, "total": int(round(mes_total[m])), "por_beneficiario": rd(mes_benef[m])}
        for m in sorted(mes_total)
    ]
    por_dia = [
        {"dia": d, "total": int(round(dia_total[d])), "por_beneficiario": rd(dia_benef[d])}
        for d in sorted(dia_total)
    ]
    por_dueno = [
        {
            "dueno": dn,
            "monto_generado": int(round(dueno_generado[dn])),
            "pedidos": len(dueno_pedidos[dn]),
            "reparto": rd(dueno_reparto[dn]),
            "equipos": sorted(
                (
                    {
                        "equipo": e,
                        "monto": int(round(v)),
                        "veces": len(equipo_pedidos[dn][e]),
                    }
                    for e, v in dueno_equipos[dn].items()
                ),
                key=lambda x: x["monto"],
                reverse=True,
            ),
            # Detalle de pedidos/rentals (2026-07-04): el mismo total de arriba,
            # visto por PEDIDO en vez de por equipo — # de pedido, cliente, fecha
            # de saldado, monto que ese pedido aportó a ESTE dueño.
            "pedidos_detalle": sorted(
                (
                    {
                        "pedido_id": pid,
                        "numero_pedido": pedido_meta[pid]["numero_pedido"],
                        "cliente": pedido_meta[pid]["cliente"],
                        "fecha": pedido_meta[pid]["fecha"],
                        "monto": int(round(v)),
                    }
                    for pid, v in dueno_pedido_monto[dn].items()
                ),
                key=lambda x: x["monto"],
                reverse=True,
            ),
        }
        for dn in sorted(dueno_generado, key=lambda k: dueno_generado[k], reverse=True)
    ]

    return {
        "resumen": {
            "total": int(round(total)),
            "pedidos": len(pedidos_global),
            "por_beneficiario": rd(por_benef),
        },
        "por_mes": por_mes,
        "por_dia": por_dia,
        "por_dueno": por_dueno,
    }


def excluir_dueno(data: dict, dueno: str) -> dict:
    """PURA. Copia de un reporte (la forma de `liquidar()`/`combinar_meses()`/
    una foto de `snapshot_de()` — las tres comparten forma) SIN la
    contribución de `dueno`: resta lo que generó de `resumen.total`/`por_mes`/
    `por_dia` (derivado de `pedidos_detalle`, que retiene fecha+monto por
    pedido de ESE dueño), le saca su fila a `por_dueno` + `beneficiarios`, y
    borra su clave de los TRES `por_beneficiario` (el de `resumen` y el de
    cada entrada de `por_mes`/`por_dia`) — no alcanza con sacarlo de la lista
    `beneficiarios`: un consumidor que iterara las claves del dict a mano
    (en vez de la lista) lo seguiría viendo. No vuelve a la DB — sirve igual
    sobre un cálculo en vivo que sobre una foto congelada.

    Nace de separar la Liquidación del Estudio y la de Rental (2026-08-03,
    pedido del dueño): el Estudio se MODELA como "otro dueño que se queda el
    100% de lo suyo" (mismo mecanismo que usa Rental para sus propios equipos,
    `comisiones.DEFAULT_MODELO`) solo para que el reparto lo calcule sin código
    aparte — pero conceptualmente no es un dueño de equipo que reparte
    comisión con Pablo/Tincho, es otra unidad de negocio, todavía en
    desarrollo. La página de Liquidación (el reparto real entre dueños de
    equipo) lo excluye vía esta función, aplicada SOLO en
    `routes/reportes.py::_data_liquidacion`; `posiciones()`/`cerrar_mes` NO
    la usan — siguen viendo al Estudio (necesitan su devengado completo para
    la posición acumulada / la foto congelada íntegra).

    `resumen.pedidos` NO se ajusta a propósito: es un hecho del negocio
    ("cuántos alquileres se cobraron"), no de atribución por dueño — un
    pedido mixto (equipos de Rental + turno del Estudio) sigue contando 1 vez
    para ese total, esté o no el Estudio en el reparto. Snapshots de antes de
    `pedidos_detalle` (2026-07-04, campo opcional) no tienen el detalle por
    pedido: en ese caso `resumen.total` sí queda bien ajustado (viene de
    `monto_generado`), pero `por_mes`/`por_dia` de esos meses viejos no
    — imprecisión histórica acotada, no vale recalcular el dato viejo para
    corregirla."""
    entrada = next((d for d in data.get("por_dueno", []) if d["dueno"] == dueno), None)
    if entrada is None:
        return data

    por_mes_dueno: dict[str, int] = defaultdict(int)
    por_dia_dueno: dict[str, int] = defaultdict(int)
    for p in entrada.get("pedidos_detalle") or []:
        fecha = str(p["fecha"])
        por_mes_dueno[fecha[:7]] += p["monto"]
        por_dia_dueno[fecha[:10]] += p["monto"]

    def _sin_beneficiario(pb: dict) -> dict:
        return {k: v for k, v in pb.items() if k != dueno}

    nuevo = dict(data)
    nuevo["resumen"] = {
        **data["resumen"],
        "total": data["resumen"]["total"] - entrada["monto_generado"],
        "por_beneficiario": _sin_beneficiario(data["resumen"]["por_beneficiario"]),
    }
    nuevo["por_mes"] = [
        {
            **m,
            "total": m["total"] - por_mes_dueno.get(m["mes"], 0),
            "por_beneficiario": _sin_beneficiario(m["por_beneficiario"]),
        }
        for m in data.get("por_mes", [])
    ]
    nuevo["por_dia"] = [
        {
            **d,
            "total": d["total"] - por_dia_dueno.get(d["dia"], 0),
            "por_beneficiario": _sin_beneficiario(d["por_beneficiario"]),
        }
        for d in data.get("por_dia", [])
    ]
    nuevo["por_dueno"] = [d for d in data.get("por_dueno", []) if d["dueno"] != dueno]
    nuevo["beneficiarios"] = [b for b in data.get("beneficiarios", []) if b != dueno]
    return nuevo


def combinar_meses(meses_data: list[dict]) -> dict:
    """Combina N reportes por-mes (cada uno con la forma de `liquidar`: `resumen`/
    `por_mes`/`por_dia`/`por_dueno`/`modelo`/`beneficiarios`) en un solo reporte
    multi-mes. A esta función le da igual si cada mes viene de una foto congelada
    (`cierres.snapshot_de`) o de un cálculo en vivo — solo suma. Es seguro porque
    un pedido se atribuye a UN ÚNICO mes de saldado (nunca se solapan entre los
    reportes de entrada), así que sumar total/pedidos/"veces alquilado" no duplica
    nada. Pura — no toca DB. La usa `cierres.liquidar_rango` para que la vista
    multi-mes/anual respete los meses cerrados en vez de recalcularlos (#1209)."""
    total = 0
    pedidos = 0
    por_benef: dict[str, int] = defaultdict(int)
    por_mes: list[dict] = []
    por_dia: list[dict] = []
    beneficiarios: list[str] = []
    modelo: dict = {}
    duenos: dict[str, dict] = {}

    for data in meses_data:
        resumen = data.get("resumen", {})
        total += resumen.get("total", 0)
        pedidos += resumen.get("pedidos", 0)
        for b, v in resumen.get("por_beneficiario", {}).items():
            por_benef[b] += v
        por_mes.extend(data.get("por_mes", []))
        por_dia.extend(data.get("por_dia", []))

        for d in data.get("por_dueno", []):
            acc = duenos.setdefault(
                d["dueno"],
                {
                    "dueno": d["dueno"],
                    "monto_generado": 0,
                    "pedidos": 0,
                    "reparto": defaultdict(int),
                    "equipos": defaultdict(lambda: [0, 0]),  # [monto, veces]
                    "pedidos_detalle": [],
                },
            )
            acc["monto_generado"] += d.get("monto_generado", 0)
            acc["pedidos"] += d.get("pedidos", 0)
            for b, v in d.get("reparto", {}).items():
                acc["reparto"][b] += v
            for eq in d.get("equipos", []):
                agg = acc["equipos"][eq["equipo"]]
                agg[0] += eq.get("monto", 0)
                agg[1] += eq.get("veces", 0)
            # Un pedido pertenece a UN ÚNICO mes de saldado (mismo invariante que
            # el resto de esta función) → concatenar es seguro, no hay dupes.
            acc["pedidos_detalle"].extend(d.get("pedidos_detalle", []))

        # El modelo/beneficiarios "representativo" es el del último mes de la
        # lista (si es abierto, el vigente hoy; si está cerrado, el que se
        # congeló) — solo metadata para mostrar columnas; cada monto ya quedó
        # repartido con el modelo correcto de SU propio mes, no con este.
        if data.get("modelo"):
            modelo = data["modelo"]
        for b in data.get("beneficiarios", []):
            if b not in beneficiarios:
                beneficiarios.append(b)

    por_dueno = [
        {
            "dueno": acc["dueno"],
            "monto_generado": acc["monto_generado"],
            "pedidos": acc["pedidos"],
            "reparto": dict(acc["reparto"]),
            "equipos": sorted(
                (
                    {"equipo": e, "monto": m, "veces": v}
                    for e, (m, v) in acc["equipos"].items()
                ),
                key=lambda x: x["monto"],
                reverse=True,
            ),
            "pedidos_detalle": sorted(
                acc["pedidos_detalle"], key=lambda x: x["monto"], reverse=True
            ),
        }
        for acc in duenos.values()
    ]
    por_dueno.sort(key=lambda d: d["monto_generado"], reverse=True)

    return {
        "resumen": {"total": total, "pedidos": pedidos, "por_beneficiario": dict(por_benef)},
        "por_mes": sorted(por_mes, key=lambda m: m["mes"]),
        "por_dia": sorted(por_dia, key=lambda d: d["dia"]),
        "por_dueno": por_dueno,
        "modelo": modelo,
        "beneficiarios": beneficiarios,
    }


def liquidar(conn, desde: str, hasta: str) -> dict:
    """Reporte completo de liquidación para el rango. Carga el modelo de comisiones,
    atribuye y agrega. Devuelve también el `modelo` aplicado (para mostrarlo)."""
    modelo = cargar_modelo(conn)
    data = agregar(filas_atribucion(conn, desde, hasta), modelo)
    data["modelo"] = modelo
    # Lista ordenada de beneficiarios que aparecen en el modelo (para la UI).
    beneficiarios: list[str] = []
    for reglas in modelo.values():
        for b in reglas:
            if b not in beneficiarios:
                beneficiarios.append(b)
    data["beneficiarios"] = beneficiarios
    return data
