"""Estadísticas (#1209) contra Postgres REAL — reproduce el bug de reconstrucción
del descuento en las agregaciones del dashboard: `estadisticas.py` recalculaba el
ingreso con `subtotal * (1 - descuento_pct / 100)`, que solo mira el descuento de
CLIENTE — ignorando el descuento por JORNADAS cuando era el GANADOR (`max()`, ver
`descuentos.queries.decision.calcular_descuento_aplicable`). `alquileres.monto_total` YA es el neto
correcto (persistido por `_recalcular_total_pedido`); las queries ahora lo leen
directo (a nivel pedido: totales/por_mes/mejor_peor) o lo prorratean por ítem (a
nivel equipo/dueño: top_equipos/por_dueno) en vez de reconstruirlo.

También cubre el criterio del dueño (2026-07-04): Estadísticas cuenta SOLO
pedidos `estado='finalizado'` — `confirmado`/`retirado` quedan afuera de todas
las secciones (negocio devengado pero aún no cerrado).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`): se saltea
salvo `RESERVAS_DB_TEST=1` + `DATABASE_URL` a una base con 'test' en el nombre.
Ids altos + mes sin uso en otros `*_db.py` (2026-04) para no chocar con datos.

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estadisticas_db.py -v -m integration
"""
import os
from urllib.parse import urlparse

import pytest

_OPT_IN = os.getenv("RESERVAS_DB_TEST") == "1"
_DB_URL = os.getenv("DATABASE_URL", "")
_DB_NAME = urlparse(_DB_URL).path.lstrip("/") if _DB_URL else ""


def _looks_like_test_db() -> bool:
    return bool(_DB_NAME) and "test" in _DB_NAME.lower()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _OPT_IN,
        reason="opt-in: setear RESERVAS_DB_TEST=1 + DATABASE_URL a una base de prueba",
    ),
    pytest.mark.skipif(
        _OPT_IN and not _looks_like_test_db(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]

# Id alto para no chocar con datos reales/otros tests.
E_ID = 9_301_001
P_ID = 9_301_101
NOMBRE_EQUIPO = "Cámara test #1209"

# Escenario del bug: 1 equipo a $10.000/día, 7 jornadas, 0% descuento de CLIENTE
# pero 10% descuento por JORNADAS (ganador — `calcular_descuento_aplicable` toma el
# máximo, no la suma). El bug reconstruía el ingreso con `subtotal * (1 - descuento_pct /
# 100)`, que solo mira el pct de CLIENTE (0 acá) → hubiera devuelto el BRUTO
# ($70.000) en vez del NETO real cobrado y persistido en `monto_total` ($63.000).
PRECIO_JORNADA = 10_000
JORNADAS = 7
BRUTO = PRECIO_JORNADA * JORNADAS                              # 70_000
DESCUENTO_JORNADAS_PCT = 10
NETO = int(round(BRUTO * (1 - DESCUENTO_JORNADAS_PCT / 100)))  # 63_000

# Mes de fixture sin uso en otros `*_db.py` (evita compartir bucket de mes con
# datos de otro test file en `por_mes`/`mejor_peor`).
MES = "2026-04"


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (P_ID,))
    conn.execute("DELETE FROM alquileres WHERE id = %s", (P_ID,))
    conn.execute("DELETE FROM equipos WHERE id = %s", (E_ID,))


def _insertar(conn):
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno, precio_jornada) "
        "VALUES (%s, %s, 1, 'Rental', %s)",
        (E_ID, NOMBRE_EQUIPO, PRECIO_JORNADA),
    )
    conn.execute(
        """INSERT INTO alquileres
               (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                descuento_pct, descuento_jornadas_pct, monto_total)
           VALUES (%s, %s, 'finalizado', %s, %s, 0, %s, %s)""",
        (P_ID, "Cliente #1209", f"{MES}-05T09:00:00", f"{MES}-12T09:00:00",
         DESCUENTO_JORNADAS_PCT, NETO),
    )
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
        "VALUES (%s, %s, 1, %s, %s)",
        (P_ID, E_ID, PRECIO_JORNADA, BRUTO),
    )


@pytest.fixture
def conn():
    from database import get_db, init_db

    init_db()
    c = get_db()
    try:
        _limpiar(c)
        c.commit()
        yield c
    finally:
        _limpiar(c)
        c.commit()
        c.close()


def test_estadisticas_usa_monto_total_no_reconstruye_descuento_de_jornadas(conn):
    """Reproduce #1209: pedido con descuento por JORNADAS ganador (10%) y
    descuento de CLIENTE en 0%. El bug reconstruía el ingreso con
    `subtotal * (1 - descuento_pct/100)` = 70.000 * (1-0) = $70.000 (el BRUTO,
    ignorando el 10% de jornadas que en realidad ganó). El número que devuelve
    el endpoint tiene que coincidir con el NETO persistido en `monto_total`
    ($63.000), en cada una de las secciones del dashboard."""
    from routes.estadisticas import compute_estadisticas

    antes = compute_estadisticas(conn)
    total_antes = antes["totales"]["total_ars"] or 0
    dueno_antes = next(
        (d["total_ars"] or 0 for d in antes["por_dueno"] if d["dueno"] == "Rental"), 0
    )

    _insertar(conn)
    conn.commit()

    despues = compute_estadisticas(conn)

    # ── Totales (agregado GLOBAL, sin scoping): el delta que introduce el
    #    fixture tiene que ser el NETO, no el bruto reconstruido.
    total_despues = despues["totales"]["total_ars"] or 0
    assert total_despues - total_antes == NETO
    assert total_despues - total_antes != BRUTO

    # ── Por mes: bucket exclusivo de nuestro fixture (mes sin uso en otros
    #    *_db.py) → asserción exacta, no delta.
    fila_mes = next((m for m in despues["por_mes"] if m["mes"] == MES), None)
    assert fila_mes is not None, despues["por_mes"]
    assert fila_mes["total_ars"] == NETO
    assert fila_mes["total_ars"] != BRUTO

    # ── Top equipos: agrupado por equipo_id (id alto dedicado al fixture) →
    #    exacto. Con un solo ítem en el pedido, el prorrateo
    #    (monto_total * subtotal/suma_items) coincide con el monto_total entero.
    fila_equipo = next(
        (e for e in despues["top_equipos"] if e["equipo"] == NOMBRE_EQUIPO), None
    )
    assert fila_equipo is not None, despues["top_equipos"]
    assert fila_equipo["total_ars"] == NETO
    assert fila_equipo["total_ars"] != BRUTO

    # ── Por dueño (agregado GLOBAL por equipos.dueno='Rental'): delta.
    dueno_despues = next(
        (d["total_ars"] or 0 for d in despues["por_dueno"] if d["dueno"] == "Rental"), 0
    )
    assert dueno_despues - dueno_antes == NETO
    assert dueno_despues - dueno_antes != BRUTO

    # ── Mejor/peor mes: misma CTE (`monto_total`) que `por_mes` — no aislamos
    #    un mes ganador global (depende del resto del histórico), pero el
    #    máximo/mínimo tienen que ser coherentes con nuestro propio mes.
    mp = despues["mejor_peor_mes"]
    assert (mp["mejor_total"] or 0) >= fila_mes["total_ars"]
    assert (mp["peor_total"] or 0) <= fila_mes["total_ars"]


# ── Criterio explícito del dueño (2026-07-04): Estadísticas cuenta SOLO negocio
# devengado Y CERRADO — únicamente `estado='finalizado'`. `confirmado`/`retirado`
# todavía pueden cambiar (se cancelan, se modifican) y no deben aparecer.
E_ID2 = 9_301_002
P_ID_CONF = 9_301_103
P_ID_RET = 9_301_104
NOMBRE_EQUIPO2 = "Cámara test #1209-b (no finalizado)"


def _limpiar2(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN (%s, %s)", (P_ID_CONF, P_ID_RET)
    )
    conn.execute("DELETE FROM alquileres WHERE id IN (%s, %s)", (P_ID_CONF, P_ID_RET))
    conn.execute("DELETE FROM equipos WHERE id = %s", (E_ID2,))


def test_estadisticas_excluye_confirmado_y_retirado(conn):
    """Un pedido `confirmado` o `retirado` (negocio aún no cerrado) NO debe sumar
    en ninguna sección — ni siquiera aparecer en `top_equipos`/`por_dueno`."""
    from routes.estadisticas import compute_estadisticas

    _limpiar2(conn)
    conn.commit()
    try:
        antes = compute_estadisticas(conn)
        total_antes = antes["totales"]["total_ars"] or 0
        dueno_antes = next(
            (d["total_ars"] or 0 for d in antes["por_dueno"] if d["dueno"] == "Rental"), 0
        )

        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, precio_jornada) "
            "VALUES (%s, %s, 1, 'Rental', %s)",
            (E_ID2, NOMBRE_EQUIPO2, PRECIO_JORNADA),
        )
        for pid, estado in ((P_ID_CONF, "confirmado"), (P_ID_RET, "retirado")):
            conn.execute(
                """INSERT INTO alquileres
                       (id, cliente_nombre, estado, fecha_desde, fecha_hasta, monto_total)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (pid, "Cliente #1209-b", estado, f"{MES}-05T09:00:00", f"{MES}-12T09:00:00", NETO),
            )
            conn.execute(
                "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
                "VALUES (%s, %s, 1, %s, %s)",
                (pid, E_ID2, PRECIO_JORNADA, BRUTO),
            )
        conn.commit()

        despues = compute_estadisticas(conn)

        assert (despues["totales"]["total_ars"] or 0) == total_antes
        assert not any(e["equipo"] == NOMBRE_EQUIPO2 for e in despues["top_equipos"])
        dueno_despues = next(
            (d["total_ars"] or 0 for d in despues["por_dueno"] if d["dueno"] == "Rental"), 0
        )
        assert dueno_despues == dueno_antes
    finally:
        _limpiar2(conn)
        conn.commit()


# ── `gastos_por_categoria` (motor único `contabilidad`, reusado tal cual — sin
# fecha, histórico completo, mismo criterio que el resto de esta función).
CUENTA_ID_GASTOS = 9_301_201
MONTO_GASTO_TEST = 12_345


def _limpiar_gastos_categoria(conn):
    conn.execute("DELETE FROM movimientos WHERE cuenta_origen_id = %s", (CUENTA_ID_GASTOS,))
    conn.execute("DELETE FROM cuentas WHERE id = %s", (CUENTA_ID_GASTOS,))


def test_estadisticas_incluye_gastos_por_categoria(conn):
    """`compute_estadisticas` expone `gastos_por_categoria` reusando tal cual
    `contabilidad.queries.movimientos.gastos_por_categoria` — un gasto nuevo en
    una categoría existente ('Mantenimiento') tiene que sumar ahí."""
    from routes.estadisticas import compute_estadisticas

    _limpiar_gastos_categoria(conn)
    conn.commit()
    try:
        cat_id = conn.execute(
            "SELECT id FROM gasto_categorias WHERE nombre = 'Mantenimiento'"
        ).fetchone()[0]

        antes = compute_estadisticas(conn)
        monto_antes = next(
            (g["monto"] for g in antes["gastos_por_categoria"] if g["categoria"] == "Mantenimiento"),
            0,
        )

        conn.execute(
            "INSERT INTO cuentas (id, nombre, tipo, moneda) VALUES (%s, %s, 'caja', 'ARS')",
            (CUENTA_ID_GASTOS, "Caja test #estadisticas-gastos"),
        )
        conn.execute(
            "INSERT INTO movimientos (tipo, monto, cuenta_origen_id, categoria_id, fecha) "
            "VALUES ('gasto', %s, %s, %s, CURRENT_DATE)",
            (MONTO_GASTO_TEST, CUENTA_ID_GASTOS, cat_id),
        )
        conn.commit()

        despues = compute_estadisticas(conn)
        monto_despues = next(
            (g["monto"] for g in despues["gastos_por_categoria"] if g["categoria"] == "Mantenimiento"),
            0,
        )
        assert monto_despues - monto_antes == MONTO_GASTO_TEST
    finally:
        _limpiar_gastos_categoria(conn)
        conn.commit()


# ── `top_equipos_rentabilidad` (ingreso − costo_compra) — el escenario real
# que motivó el pedido: un equipo caro puede facturar más que uno barato y
# aun así ser MENOS rentable neto. `costo_compra` es nullable — un equipo sin
# el dato cargado sigue en `top_equipos` (por ingreso) pero queda AFUERA de
# `top_equipos_rentabilidad` (no hay con qué comparar su rentabilidad).
E_CARA = 9_301_301
E_BARATA = 9_301_302
E_SIN_COSTO = 9_301_303
P_CARA = 9_301_311
P_BARATA = 9_301_312
P_SIN_COSTO = 9_301_313
PRECIO_CARA = 100_000
COSTO_CARA = 90_000  # rentabilidad neta: 10_000
PRECIO_BARATA = 60_000
COSTO_BARATA = 20_000  # rentabilidad neta: 40_000 — MÁS que la cara, pese a facturar menos
PRECIO_SIN_COSTO = 80_000


def _limpiar_rentabilidad(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN (%s, %s, %s)",
        (P_CARA, P_BARATA, P_SIN_COSTO),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE id IN (%s, %s, %s)", (P_CARA, P_BARATA, P_SIN_COSTO)
    )
    conn.execute(
        "DELETE FROM equipos WHERE id IN (%s, %s, %s)", (E_CARA, E_BARATA, E_SIN_COSTO)
    )


def test_top_equipos_rentabilidad_descuenta_el_costo_de_compra(conn):
    """El equipo CARO factura más pero es MENOS rentable neto que el barato
    (mismo patrón que el pedido real: la cámara top-of-line vs. una más
    barata) — el ranking por rentabilidad tiene que invertir el orden del
    ranking por ingreso. El equipo sin costo_compra cargado sigue en
    `top_equipos` pero desaparece de `top_equipos_rentabilidad`."""
    from routes.estadisticas import compute_estadisticas

    _limpiar_rentabilidad(conn)
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, precio_jornada, costo_compra) "
            "VALUES (%s, %s, 1, 'Rental', %s, %s)",
            (E_CARA, "Cámara top-of-line #rentabilidad", PRECIO_CARA, COSTO_CARA),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, precio_jornada, costo_compra) "
            "VALUES (%s, %s, 1, 'Rental', %s, %s)",
            (E_BARATA, "Cámara económica #rentabilidad", PRECIO_BARATA, COSTO_BARATA),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, precio_jornada, costo_compra) "
            "VALUES (%s, %s, 1, 'Rental', %s, NULL)",
            (E_SIN_COSTO, "Cámara sin costo cargado #rentabilidad", PRECIO_SIN_COSTO),
        )
        for pid, eid, precio in (
            (P_CARA, E_CARA, PRECIO_CARA),
            (P_BARATA, E_BARATA, PRECIO_BARATA),
            (P_SIN_COSTO, E_SIN_COSTO, PRECIO_SIN_COSTO),
        ):
            conn.execute(
                """INSERT INTO alquileres
                       (id, cliente_nombre, estado, fecha_desde, fecha_hasta, monto_total)
                   VALUES (%s, %s, 'finalizado', %s, %s, %s)""",
                (pid, "Cliente #rentabilidad", f"{MES}-05T09:00:00", f"{MES}-06T09:00:00", precio),
            )
            conn.execute(
                "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
                "VALUES (%s, %s, 1, %s, %s)",
                (pid, eid, precio, precio),
            )
        conn.commit()

        data = compute_estadisticas(conn)

        por_nombre = {e["equipo"]: e for e in data["top_equipos_rentabilidad"]}
        assert "Cámara top-of-line #rentabilidad" in por_nombre
        assert "Cámara económica #rentabilidad" in por_nombre
        # El sin-costo NO aparece acá — no hay con qué comparar.
        assert "Cámara sin costo cargado #rentabilidad" not in por_nombre

        cara = por_nombre["Cámara top-of-line #rentabilidad"]
        barata = por_nombre["Cámara económica #rentabilidad"]
        assert cara["rentabilidad_neta"] == PRECIO_CARA - COSTO_CARA
        assert barata["rentabilidad_neta"] == PRECIO_BARATA - COSTO_BARATA
        assert barata["rentabilidad_neta"] > cara["rentabilidad_neta"]

        # El orden del ranking está invertido respecto al ingreso puro: la
        # barata rentabiliza más pese a facturar menos.
        nombres_por_rentabilidad = [e["equipo"] for e in data["top_equipos_rentabilidad"]]
        assert nombres_por_rentabilidad.index(
            "Cámara económica #rentabilidad"
        ) < nombres_por_rentabilidad.index("Cámara top-of-line #rentabilidad")

        # Pero el sin-costo SÍ sigue en `top_equipos` (por ingreso) — nullable
        # no significa invisible en el resto de la pantalla.
        nombres_top_equipos = [e["equipo"] for e in data["top_equipos"]]
        assert "Cámara sin costo cargado #rentabilidad" in nombres_top_equipos
    finally:
        _limpiar_rentabilidad(conn)
        conn.commit()


# ── Calendario de actividad (heatmap estilo GitHub/Apple Fitness) — un pedido
# de N días "enciende" N celdas (equipo AFUERA ese día), no solo el día de
# inicio; excluye Estudio/Talleres y pedidos no-finalizado (mismo universo que
# el resto de la página); los tiers de color vienen de percentiles del propio
# año. Año ficticio propio 1898 (no choca con `MES="2026-04"` de arriba ni con
# `1899-11/12` del fixture de IPC, aunque cada test limpia lo suyo).
ANIO_CAL = 1898
E_CAL = 9_301_501
P_CAL_LARGO = 9_301_511  # 3 días: 1898-04-10 → 1898-04-12
P_CAL_CORTO_A = 9_301_512  # 1 día: 1898-04-20
P_CAL_CORTO_B = 9_301_513  # 1 día: 1898-04-20 (mismo día que el anterior → 2 activos)
P_CAL_NO_FINALIZADO = 9_301_514  # confirmado, no debe contar
P_CAL_ESTUDIO = 9_301_515  # tipo='estudio', no debe contar
IDS_CAL = [P_CAL_LARGO, P_CAL_CORTO_A, P_CAL_CORTO_B, P_CAL_NO_FINALIZADO, P_CAL_ESTUDIO]


def _limpiar_calendario(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = ANY(%s)", (IDS_CAL,))
    conn.execute("DELETE FROM alquileres WHERE id = ANY(%s)", (IDS_CAL,))
    conn.execute("DELETE FROM equipos WHERE id = %s", (E_CAL,))


def test_actividad_calendario_enciende_todos_los_dias_del_pedido(conn):
    """Un pedido de 3 días (fecha_desde=10, fecha_hasta=12) tiene que aparecer
    en LAS 3 celdas del heatmap con equipo afuera, no solo en el día 10 (el
    día de retiro) — es la diferencia central entre "día de pickup" y "día con
    actividad", que es la métrica que este heatmap muestra."""
    from routes.estadisticas import compute_actividad_calendario

    _limpiar_calendario(conn)
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, precio_jornada) "
            "VALUES (%s, %s, 1, 'Rental', 1000)",
            (E_CAL, "Cámara test #calendario"),
        )
        conn.execute(
            """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta, monto_total)
               VALUES (%s, 'Cliente calendario', 'finalizado', %s, %s, 3000)""",
            (P_CAL_LARGO, f"{ANIO_CAL}-04-10T09:00:00", f"{ANIO_CAL}-04-12T09:00:00"),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s, %s, 1, 1000, 3000)",
            (P_CAL_LARGO, E_CAL),
        )
        conn.commit()

        data = compute_actividad_calendario(conn, ANIO_CAL)

        por_dia = {d["dia"]: d for d in data["dias"]}
        for dia in (f"{ANIO_CAL}-04-10", f"{ANIO_CAL}-04-11", f"{ANIO_CAL}-04-12"):
            assert dia in por_dia, (dia, data["dias"])
            assert por_dia[dia]["pedidos_activos"] == 1
        assert f"{ANIO_CAL}-04-13" not in por_dia
        assert f"{ANIO_CAL}-04-09" not in por_dia
    finally:
        _limpiar_calendario(conn)
        conn.commit()


def test_actividad_calendario_excluye_no_finalizado_y_estudio(conn):
    """Un pedido `confirmado` y uno `tipo='estudio'` (finalizado) NO deben
    sumar al conteo del día — mismo universo (`estado='finalizado'` +
    `tipo NOT IN TIPOS_DERIVADOS_SQL`) que el resto de Estadísticas."""
    from routes.estadisticas import compute_actividad_calendario

    _limpiar_calendario(conn)
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, precio_jornada) "
            "VALUES (%s, %s, 1, 'Rental', 1000)",
            (E_CAL, "Cámara test #calendario-excl"),
        )
        dia_test = f"{ANIO_CAL}-04-15"
        conn.execute(
            """INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total)
               VALUES (%s, 'C', 'confirmado', 'diaria', %s, %s, 1000)""",
            (P_CAL_NO_FINALIZADO, f"{dia_test}T09:00:00", f"{dia_test}T09:00:00"),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s, %s, 1, 1000, 1000)",
            (P_CAL_NO_FINALIZADO, E_CAL),
        )
        conn.execute(
            """INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total)
               VALUES (%s, 'C', 'finalizado', 'estudio', %s, %s, 1000)""",
            (P_CAL_ESTUDIO, f"{dia_test}T09:00:00", f"{dia_test}T09:00:00"),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s, %s, 1, 1000, 1000)",
            (P_CAL_ESTUDIO, E_CAL),
        )
        conn.commit()

        data = compute_actividad_calendario(conn, ANIO_CAL)

        por_dia = {d["dia"]: d for d in data["dias"]}
        assert dia_test not in por_dia, por_dia.get(dia_test)
    finally:
        _limpiar_calendario(conn)
        conn.commit()


def test_actividad_calendario_tiers_por_percentil_del_propio_anio(conn):
    """Dos pedidos el mismo día (2 activos) vs. uno solo otro día (1 activo)
    tienen que quedar en tiers DISTINTOS — el día con más actividad, en un
    tier más alto. Confirma que el bucketing usa la distribución real del
    año, no un umbral fijo."""
    from routes.estadisticas import compute_actividad_calendario

    _limpiar_calendario(conn)
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, precio_jornada) "
            "VALUES (%s, %s, 2, 'Rental', 1000)",
            (E_CAL, "Cámara test #calendario-tiers"),
        )
        dia_bajo = f"{ANIO_CAL}-04-20"
        dia_alto = f"{ANIO_CAL}-04-21"
        # 1 pedido en dia_bajo, 2 pedidos en dia_alto.
        conn.execute(
            """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta, monto_total)
               VALUES (%s, 'C', 'finalizado', %s, %s, 1000)""",
            (P_CAL_CORTO_A, f"{dia_bajo}T09:00:00", f"{dia_bajo}T09:00:00"),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s, %s, 1, 1000, 1000)",
            (P_CAL_CORTO_A, E_CAL),
        )
        for pid in (P_CAL_CORTO_B, P_CAL_LARGO):
            conn.execute(
                """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta, monto_total)
                   VALUES (%s, 'C', 'finalizado', %s, %s, 1000)""",
                (pid, f"{dia_alto}T09:00:00", f"{dia_alto}T09:00:00"),
            )
            conn.execute(
                "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
                "VALUES (%s, %s, 1, 1000, 1000)",
                (pid, E_CAL),
            )
        conn.commit()

        data = compute_actividad_calendario(conn, ANIO_CAL)

        por_dia = {d["dia"]: d for d in data["dias"]}
        assert por_dia[dia_bajo]["pedidos_activos"] == 1
        assert por_dia[dia_alto]["pedidos_activos"] == 2
        assert por_dia[dia_alto]["tier"] > por_dia[dia_bajo]["tier"]
        assert ANIO_CAL in data["anios_disponibles"]
    finally:
        _limpiar_calendario(conn)
        conn.commit()


# ── Modo `todos=True` (view "Todos los años" apilado): candado central — los
# tiers se calculan POR AÑO incluso adentro de una sola respuesta, para que un
# año chico (negocio recién arrancado) no quede aplastado por uno con más
# volumen total. Años ficticios propios 1896/1897 (no chocan con `ANIO_CAL`
# ni con los demás fixtures de este archivo).
E_CAL_TODOS = 9_301_601
ANIO_CHICO = 1896  # negocio chico: máximo 2 pedidos/día
ANIO_GRANDE = 1897  # negocio grande: máximo 10 pedidos/día
IDS_CAL_TODOS = list(range(9_301_611, 9_301_625))


def _limpiar_calendario_todos(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = ANY(%s)", (IDS_CAL_TODOS,))
    conn.execute("DELETE FROM alquileres WHERE id = ANY(%s)", (IDS_CAL_TODOS,))
    conn.execute("DELETE FROM equipos WHERE id = %s", (E_CAL_TODOS,))


def test_actividad_calendario_todos_bucketiza_tiers_por_anio_no_global(conn):
    """El view apilado (`todos=True`) tiene que preservar la misma garantía
    que el modo single-year: un año chico no queda todo gris solo por
    compararse contra uno con más volumen. Simula un año con máximo 2
    pedidos/día (negocio chico) y otro con máximo 10 (negocio grande) — el
    día "flojo" del año chico (1 pedido) tiene que quedar en un tier
    razonable DENTRO de su propio año, no aplastado a 0/1 por comparación
    con los 10 pedidos/día del año grande."""
    from routes.estadisticas import compute_actividad_calendario

    _limpiar_calendario_todos(conn)
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, precio_jornada) "
            "VALUES (%s, %s, 20, 'Rental', 1000)",
            (E_CAL_TODOS, "Cámara test #calendario-todos"),
        )
        dia_chico_bajo = f"{ANIO_CHICO}-05-01"  # 1 pedido
        dia_chico_alto = f"{ANIO_CHICO}-05-02"  # 2 pedidos
        dia_grande_bajo = f"{ANIO_GRANDE}-05-01"  # 1 pedido
        dia_grande_alto = f"{ANIO_GRANDE}-05-02"  # 10 pedidos

        pid = iter(IDS_CAL_TODOS)

        def _insertar_pedido(dia):
            p = next(pid)
            conn.execute(
                """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta, monto_total)
                   VALUES (%s, 'C', 'finalizado', %s, %s, 1000)""",
                (p, f"{dia}T09:00:00", f"{dia}T09:00:00"),
            )
            conn.execute(
                "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
                "VALUES (%s, %s, 1, 1000, 1000)",
                (p, E_CAL_TODOS),
            )

        _insertar_pedido(dia_chico_bajo)
        for _ in range(2):
            _insertar_pedido(dia_chico_alto)
        _insertar_pedido(dia_grande_bajo)
        for _ in range(10):
            _insertar_pedido(dia_grande_alto)
        conn.commit()

        data = compute_actividad_calendario(conn, todos=True)

        assert data["anio"] is None
        assert ANIO_CHICO in data["anios_disponibles"]
        assert ANIO_GRANDE in data["anios_disponibles"]

        por_dia = {d["dia"]: d for d in data["dias"]}
        assert por_dia[dia_chico_bajo]["pedidos_activos"] == 1
        assert por_dia[dia_chico_alto]["pedidos_activos"] == 2
        assert por_dia[dia_grande_bajo]["pedidos_activos"] == 1
        assert por_dia[dia_grande_alto]["pedidos_activos"] == 10

        # El candado: el día más flojo del año CHICO (1 pedido, la mitad de
        # su propio máximo de 2) tiene que quedar en un tier intermedio —
        # NO en el tier más bajo (0/1), que es lo que pasaría si se
        # comparara contra el máximo GLOBAL de 10 en vez del de su año.
        assert por_dia[dia_chico_bajo]["tier"] >= 2
        # Y el día más flojo del año GRANDE (1 de 10) SÍ tiene que quedar
        # bajo, relativo a su propio año.
        assert por_dia[dia_grande_bajo]["tier"] < por_dia[dia_grande_alto]["tier"]
        # Cada año tiene su propio pico en el tier más alto.
        assert por_dia[dia_chico_alto]["tier"] == 4
        assert por_dia[dia_grande_alto]["tier"] == 4
    finally:
        _limpiar_calendario_todos(conn)
        conn.commit()


# ── Distribución por período cíclico (día de semana / día del mes / mes del
# año) — "¿todos los lunes sumados contra todos los martes sumados?", sobre
# TODO el historial, sin scoping por año. Año ficticio propio 1895 (no choca
# con los demás fixtures de este archivo).
E_DIST = 9_301_701
IDS_DIST = list(range(9_301_711, 9_301_720))


def _limpiar_distribucion(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = ANY(%s)", (IDS_DIST,))
    conn.execute("DELETE FROM alquileres WHERE id = ANY(%s)", (IDS_DIST,))
    conn.execute("DELETE FROM equipos WHERE id = %s", (E_DIST,))


def test_actividad_distribucion_suma_por_dia_semana_mes_y_dia_del_mes(conn):
    """3 pedidos en LUNES (1895-05-06, -13, -20 — confirmados lunes vía
    `date.weekday()`, NO asumidos a ojo) + 1 pedido en MARTES (1895-05-07)
    tienen que sumar +3/+1 en el delta de Lun/Mar de la distribución por día
    de semana, +1 en cada uno de los 4 días del mes usados (6/7/13/20 —
    todos distintos), y +4 en el delta del mes de mayo. Delta contra "antes"
    (no absoluto): la función suma sobre TODO el historial, sin scoping por
    año/id."""
    from routes.estadisticas import compute_actividad_distribucion

    _limpiar_distribucion(conn)
    conn.commit()
    try:
        antes = compute_actividad_distribucion(conn)
        lun_antes = next(d["total"] for d in antes["dia_semana"] if d["label"] == "Lun")
        mar_antes = next(d["total"] for d in antes["dia_semana"] if d["label"] == "Mar")
        may_antes = next(m["total"] for m in antes["mes"] if m["label"] == "May")
        dia_mes_antes = {d["dia"]: d["total"] for d in antes["dia_mes"]}

        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, precio_jornada) "
            "VALUES (%s, %s, 5, 'Rental', 1000)",
            (E_DIST, "Cámara test #distribucion"),
        )
        dias_lunes = ["1895-05-06", "1895-05-13", "1895-05-20"]
        dia_martes = "1895-05-07"
        for pid, dia in zip(IDS_DIST, [*dias_lunes, dia_martes]):
            conn.execute(
                """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta, monto_total)
                   VALUES (%s, 'C', 'finalizado', %s, %s, 1000)""",
                (pid, f"{dia}T09:00:00", f"{dia}T09:00:00"),
            )
            conn.execute(
                "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
                "VALUES (%s, %s, 1, 1000, 1000)",
                (pid, E_DIST),
            )
        conn.commit()

        despues = compute_actividad_distribucion(conn)
        lun_despues = next(d["total"] for d in despues["dia_semana"] if d["label"] == "Lun")
        mar_despues = next(d["total"] for d in despues["dia_semana"] if d["label"] == "Mar")
        may_despues = next(m["total"] for m in despues["mes"] if m["label"] == "May")
        dia_mes_despues = {d["dia"]: d["total"] for d in despues["dia_mes"]}

        assert lun_despues - lun_antes == 3
        assert mar_despues - mar_antes == 1
        assert may_despues - may_antes == 4
        for dia in (6, 7, 13, 20):
            assert dia_mes_despues[dia] - dia_mes_antes[dia] == 1
    finally:
        _limpiar_distribucion(conn)
        conn.commit()


# ── Toggle de IPC — el candado central: "ajustar en origen" (cada pedido
# deflactado por SU PROPIO mes antes de sumar) tiene que dar un número distinto
# de "ajustar post-suma" (un solo factor aplicado al total ya sumado), que es
# matemáticamente incorrecto cuando el total mezcla meses con inflación distinta.
# Meses ficticios propios (1899-*, no chocan con `MES="2026-04"` de arriba ni con
# los `1900-*` de `test_ipc_db.py`).
MES_A = "1899-11"  # más viejo → factor 2× (índice 100 vs 200 del mes de referencia)
MES_B = "1899-12"  # el mes de referencia de este fixture → factor 1×
E_IPC = 9_301_401
P_IPC_A = 9_301_411
P_IPC_B = 9_301_412
MONTO_IPC = 10_000


def _limpiar_ipc(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN (%s, %s)", (P_IPC_A, P_IPC_B))
    conn.execute("DELETE FROM alquileres WHERE id IN (%s, %s)", (P_IPC_A, P_IPC_B))
    conn.execute("DELETE FROM equipos WHERE id = %s", (E_IPC,))
    conn.execute("DELETE FROM ipc_series WHERE mes IN (%s, %s)", (MES_A, MES_B))


def test_ajuste_ipc_es_en_origen_no_post_suma(conn):
    """Dos pedidos de $10.000 cada uno, uno en MES_A (índice 100) y otro en
    MES_B (índice 200 — el más reciente, factor 1×). Nominal: $20.000 parejo,
    0% de crecimiento. Ajustado EN ORIGEN: MES_A se dobla (factor 2×) antes de
    sumar → $30.000, y el crecimiento mes a mes da -50% (la plata de MES_A
    valía el doble en términos reales) — la caída real que el toggle existe
    para mostrar, invisible en el nominal. Si alguien "simplificara" el ajuste
    a post-suma (un factor sobre el total ya sumado), este test lo cacha:
    post-suma con el factor del mes más reciente (1×) daría $20.000, igual al
    nominal — sin diferencia ninguna, ocultando la caída real."""
    from routes.estadisticas import compute_estadisticas

    _limpiar_ipc(conn)
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO ipc_series (mes, indice) VALUES (%s, 100), (%s, 200)",
            (MES_A, MES_B),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, precio_jornada) "
            "VALUES (%s, %s, 1, 'Rental', %s)",
            (E_IPC, "Cámara test #ipc-toggle", MONTO_IPC),
        )
        for pid, mes in ((P_IPC_A, MES_A), (P_IPC_B, MES_B)):
            conn.execute(
                """INSERT INTO alquileres
                       (id, cliente_nombre, estado, fecha_desde, fecha_hasta, monto_total)
                   VALUES (%s, %s, 'finalizado', %s, %s, %s)""",
                (pid, "Cliente #ipc-toggle", f"{mes}-05T09:00:00", f"{mes}-06T09:00:00", MONTO_IPC),
            )
            conn.execute(
                "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
                "VALUES (%s, %s, 1, %s, %s)",
                (pid, E_IPC, MONTO_IPC, MONTO_IPC),
            )
        conn.commit()

        data = compute_estadisticas(conn)

        fila_a = next(m for m in data["por_mes"] if m["mes"] == MES_A)
        fila_b = next(m for m in data["por_mes"] if m["mes"] == MES_B)
        assert fila_a["total_ars"] == MONTO_IPC
        assert fila_a["total_ars_ajustado"] == MONTO_IPC * 2  # factor 200/100
        assert fila_b["total_ars"] == MONTO_IPC
        assert fila_b["total_ars_ajustado"] == MONTO_IPC * 1  # el más reciente, factor 1

        # Crecimiento MES_A → MES_B: nominal parejo (0%), ajustado -50% (cayó
        # en términos reales). El ajuste "en origen" es lo único que muestra esto.
        crec_b = next(c for c in data["crecimiento"] if c["mes"] == MES_B)
        assert crec_b["crecimiento_pct"] == 0
        assert crec_b["crecimiento_pct_ajustado"] == -50.0

        # ── El candado explícito: ajustar EN ORIGEN ≠ ajustar POST-SUMA. ──────
        total_nominal = fila_a["total_ars"] + fila_b["total_ars"]
        total_ajustado_en_origen = fila_a["total_ars_ajustado"] + fila_b["total_ars_ajustado"]
        # Post-suma con el factor del mes más reciente (1×, MES_B): 20.000×1 =
        # 20.000 — igual al nominal, sin corregir nada. El ajuste real (en
        # origen) tiene que ser DISTINTO de eso.
        total_post_suma_equivocado = total_nominal * 1
        assert total_ajustado_en_origen == 30_000
        assert total_ajustado_en_origen != total_post_suma_equivocado

        # ── Metadata + otras secciones traen la variante ajustada ────────────
        assert data["ipc"]["mes_referencia"] is not None
        assert all("monto_ajustado" in g for g in data["gastos_por_categoria"])
        assert all("total_ars_ajustado" in c for c in data["top_clientes"])
        assert all("total_ars_ajustado" in d for d in data["por_dueno"])
        # `top_equipos_rentabilidad` NO lleva una rentabilidad ajustada (fuera
        # de alcance a propósito — costo_compra es un desembolso puntual, no
        # una serie mensual; ver docstring de `compute_estadisticas`).
        assert all(
            "rentabilidad_neta_ajustada" not in e for e in data["top_equipos_rentabilidad"]
        )
    finally:
        _limpiar_ipc(conn)
        conn.commit()
