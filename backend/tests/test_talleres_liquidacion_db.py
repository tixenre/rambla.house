"""Talleres (pedido mensual de resumen) contra Postgres REAL — atribución en
liquidación + exclusión de Estadísticas. Espeja `test_estudio_liquidacion_db.py`
+ `test_estadisticas_estudio_db.py` (misma familia de motor-único: el Estudio
ya resolvió este problema, Talleres reusa el MISMO mecanismo genérico).

Un pedido `tipo='taller'` con 2 líneas — uso del Estudio (`equipo_id` de un
equipo con `dueno='Estudio'`) y uso de equipos de alquiler (línea
personalizada, `equipo_id=NULL`) — se atribuye 100% genérico vía
`equipos.dueno` en `filas_atribucion` (`COALESCE(dueno,'Rental')`): CERO
código de atribución nuevo. Y tras extender las 7 exclusiones de
`compute_estadisticas` a también `'taller'`, ese mismo pedido no debe
ensuciar ninguna tarjeta de rental.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`).

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_talleres_liquidacion_db.py -v -m integration
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

MES = "2026-06"
EQ_ESTUDIO_TALLER = 9_510_001
P_TALLER_MIXTO = 9_510_101

VALOR_ESTUDIO = 40_000
VALOR_EQUIPOS = 15_000
TOTAL = VALOR_ESTUDIO + VALOR_EQUIPOS


@pytest.fixture
def conn():
    from database import get_db, init_db

    init_db()
    c = get_db()
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def _insertar(conn):
    """Pedido de taller `finalizado` y saldado con sus 2 líneas — mismo shape
    que produce `_regenerar_pedidos_taller` (ver routes/talleres.py)."""
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s, %s, 1, 'Estudio')",
        (EQ_ESTUDIO_TALLER, "Estudio (espacio) test taller"),
    )
    conn.execute(
        """INSERT INTO alquileres
               (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total, monto_pagado)
           VALUES (%s, %s, 'finalizado', 'taller', %s, %s, %s, %s)""",
        (P_TALLER_MIXTO, "Taller Fotografía — junio 2026 test",
         f"{MES}-05T00:00:00", f"{MES}-30T00:00:00", TOTAL, TOTAL),
    )
    conn.execute(
        """INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal, cobro_modo)
           VALUES (%s, %s, 1, %s, 'fijo')""",
        (P_TALLER_MIXTO, EQ_ESTUDIO_TALLER, VALOR_ESTUDIO),
    )
    conn.execute(
        """INSERT INTO alquiler_items
               (pedido_id, equipo_id, nombre_libre, cantidad, subtotal, cobro_modo)
           VALUES (%s, NULL, %s, 1, %s, 'fijo')""",
        (P_TALLER_MIXTO, "Uso de equipos — Taller Fotografía test", VALOR_EQUIPOS),
    )
    conn.execute(
        """INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha)
           VALUES (%s, %s, 'pago', 'Rental', 'transferencia', %s)""",
        (P_TALLER_MIXTO, TOTAL, f"{MES}-05T09:00:00"),
    )


def test_liquidacion_taller_atribuye_estudio_y_rental_db(conn):
    from reportes.cierres import rango_mes
    from reportes.liquidacion import liquidar
    from reportes.reconciliacion import reconciliar

    _insertar(conn)
    desde, hasta = rango_mes(MES)
    data = liquidar(conn, desde, hasta)

    por_dueno = {d["dueno"]: d["monto_generado"] for d in data["por_dueno"]}
    assert por_dueno["Estudio"] == VALOR_ESTUDIO
    assert por_dueno["Rental"] == VALOR_EQUIPOS

    # "Estudio" sigue siendo un dueño válido — no aparece como huérfano.
    rep = reconciliar(conn)
    assert "Estudio" not in rep["duenos_no_canonicos"]


def test_estadisticas_excluye_pedido_de_taller_db(conn):
    """Mismo criterio que Estudio (#1283 Fase 7): un pedido `tipo='taller'`
    `finalizado` no debe sumar a NINGUNA tarjeta de rental."""
    from routes.estadisticas import compute_estadisticas

    antes = compute_estadisticas(conn)
    total_pedidos_antes = antes["totales"]["total_pedidos"] or 0
    total_ars_antes = antes["totales"]["total_ars"] or 0
    dueno_estudio_antes = next(
        (d["total_ars"] or 0 for d in antes["por_dueno"] if d["dueno"] == "Estudio"), 0
    )

    _insertar(conn)

    despues = compute_estadisticas(conn)

    assert (despues["totales"]["total_pedidos"] or 0) == total_pedidos_antes
    assert (despues["totales"]["total_ars"] or 0) == total_ars_antes
    assert not any(m["mes"] == MES for m in despues["por_mes"])
    assert not any(
        e["equipo"] == "Estudio (espacio) test taller" for e in despues["top_equipos"]
    )
    assert not any(
        "Taller Fotografía" in (c["cliente"] or "") for c in despues["top_clientes"]
    )
    assert not any(
        "Taller Fotografía" in (c["cliente"] or "") for c in despues["clientes_recurrentes"]
    )
    # `por_dueno` ya lista 'Estudio' (el centinela real le pertenece) — el
    # punto es que ESTE pedido no le sume nada ahí tampoco.
    dueno_estudio_despues = next(
        (d["total_ars"] or 0 for d in despues["por_dueno"] if d["dueno"] == "Estudio"), 0
    )
    assert dueno_estudio_despues == dueno_estudio_antes
    assert despues["mejor_peor_mes"]["mejor_mes"] != MES
    assert despues["mejor_peor_mes"]["peor_mes"] != MES
