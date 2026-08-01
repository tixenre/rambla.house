"""#1308 rediseño "turno como ítem", Fase 3.3 — atribución en liquidación de un
pedido `diaria` MIXTO (equipo normal + turno del Estudio EMBEBIDO,
`alquiler_turnos_estudio`). Espeja `test_talleres_liquidacion_db.py` (misma
familia motor-único: `filas_atribucion` es genérica por `equipos.dueno`, CERO
código de atribución nuevo hace falta — este test lo confirma para el
mecanismo NUEVO, no solo para Talleres/Estudio standalone).

Dos líneas de UN MISMO pedido, dueños distintos: el equipo normal (dueño
propio de test) y el centinela del turno embebido (dueño real del Estudio,
`turno_estudio_id` seteado) — `filas_atribucion` tiene que repartir la plata
de cada línea a SU dueño, prorrateada sobre el `monto_total` ya neto (sin
descuento aplicado al turno, Fase 3.1).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_liquidacion_turno_embebido_db.py -v -m integration
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

MES = "2026-08"
EQ_RENTAL_ID = 9_487_001
PEDIDO_MIXTO_ID = 9_487_101

DUENO_TEST = "Rental Test Liquidacion 1308"
VALOR_EQUIPO = 25_000
VALOR_TURNO = 18_000
TOTAL = VALOR_EQUIPO + VALOR_TURNO


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


def _insertar(conn) -> str:
    """Pedido `diaria` mixto `finalizado` y saldado, con 2 líneas: equipo
    normal + turno embebido. Devuelve el `dueno` real del centinela."""
    centinela_id = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]
    dueno_centinela = conn.execute(
        "SELECT dueno FROM equipos WHERE id=%s", (centinela_id,)
    ).fetchone()["dueno"] or "Rental"

    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s, %s, 1, %s)",
        (EQ_RENTAL_ID, "Cámara test liquidación turno embebido", DUENO_TEST),
    )
    conn.execute(
        """INSERT INTO alquileres
               (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total, monto_pagado)
           VALUES (%s, %s, 'finalizado', 'diaria', %s, %s, %s, %s)""",
        (PEDIDO_MIXTO_ID, "Turno Embebido Liquidacion test",
         f"{MES}-05", f"{MES}-08", TOTAL, TOTAL),
    )
    conn.execute(
        """INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
           VALUES (%s, %s, 1, %s, %s, 'jornada')""",
        (PEDIDO_MIXTO_ID, EQ_RENTAL_ID, VALOR_EQUIPO // 3, VALOR_EQUIPO),
    )
    turno_id = conn.execute(
        "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
        f"VALUES (%s, '{MES}-06 14:00', '{MES}-06 16:00') RETURNING id",
        (PEDIDO_MIXTO_ID,),
    ).fetchone()["id"]
    conn.execute(
        """INSERT INTO alquiler_items
               (pedido_id, equipo_id, cantidad, subtotal, cobro_modo, turno_estudio_id)
           VALUES (%s, %s, 1, %s, 'fijo', %s)""",
        (PEDIDO_MIXTO_ID, centinela_id, VALOR_TURNO, turno_id),
    )
    conn.execute(
        """INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha)
           VALUES (%s, %s, 'pago', 'Rental', 'transferencia', %s)""",
        (PEDIDO_MIXTO_ID, TOTAL, f"{MES}-05T09:00:00"),
    )
    return dueno_centinela


def test_liquidacion_atribuye_equipo_y_turno_embebido_a_sus_duenos(conn):
    from reportes.cierres import rango_mes
    from reportes.liquidacion import liquidar

    dueno_centinela = _insertar(conn)
    desde, hasta = rango_mes(MES)
    data = liquidar(conn, desde, hasta)

    por_dueno = {d["dueno"]: d["monto_generado"] for d in data["por_dueno"]}
    assert por_dueno[DUENO_TEST] == VALOR_EQUIPO
    assert por_dueno[dueno_centinela] == VALOR_TURNO


def test_liquidacion_no_duplica_ni_pierde_el_pedido(conn):
    """La suma de lo atribuido a los dos dueños de ESTE pedido (equipo +
    turno embebido) da exactamente su `monto_total` — ni de más (duplicado
    entre líneas) ni de menos (plata perdida). Filtrado a los dos dueños del
    fixture, no un sum() global — inmune a otros pedidos saldados el mismo
    mes que pudiera haber en la base de test."""
    from reportes.cierres import rango_mes
    from reportes.liquidacion import liquidar

    dueno_centinela = _insertar(conn)
    desde, hasta = rango_mes(MES)
    data = liquidar(conn, desde, hasta)

    duenos_del_fixture = {DUENO_TEST, dueno_centinela}
    total_generado = sum(
        d["monto_generado"] for d in data["por_dueno"] if d["dueno"] in duenos_del_fixture
    )
    assert total_generado == TOTAL
