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
