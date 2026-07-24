"""Fase 4 (#1283) contra Postgres REAL — atribución "Estudio" en liquidación/P&L.

El centinela del Estudio pasa a `dueno='Estudio'` (antes 'Rambla'): sus horas se
atribuyen al Estudio en la liquidación, NO a Rambla rental — economía separada.
Verifica el pipeline completo con un pedido "mixto" (espacio + promo + suelto,
cada uno a su dueño real) y la rendición cuando Rambla cobra plata que
"corresponde" al Estudio (mismo netting genérico de las otras 3 partes).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`).

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estudio_liquidacion_db.py -v -m integration
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
EQ_ESPACIO, EQ_PROMO, EQ_SUELTO = 9_465_001, 9_465_002, 9_465_003
PED_MIXTO = 9_465_101
PED_SOLO_ESPACIO = 9_465_102

ESPACIO_MONTO = 80_000
PROMO_MONTO = 120_000
SUELTO_MONTO = 30_000


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


def _equipo(conn, eid, nombre, dueno):
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s,%s,%s,%s)",
        (eid, nombre, 1, dueno),
    )


def _setup_pedido_mixto(conn):
    """Un pedido de Estudio con las 3 economías: espacio (Estudio), promo
    (Rambla) y un equipo suelto (su dueño real, Pablo) — ítems veraces:
    Σ subtotal = monto_total."""
    _equipo(conn, EQ_ESPACIO, "Estudio (espacio) test", "Estudio")
    _equipo(conn, EQ_PROMO, "Promo equipos test", "Rambla")
    _equipo(conn, EQ_SUELTO, "Equipo suelto test", "Pablo")

    total = ESPACIO_MONTO + PROMO_MONTO + SUELTO_MONTO
    conn.execute(
        """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                                   monto_total, monto_pagado)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (PED_MIXTO, "Cliente estudio mixto", "finalizado", "2026-06-05T08:00:00",
         "2026-06-05T12:00:00", total, total),
    )
    for eid, monto, cobro_modo in (
        (EQ_ESPACIO, ESPACIO_MONTO, "fijo"),
        (EQ_PROMO, PROMO_MONTO, "fijo"),
        (EQ_SUELTO, SUELTO_MONTO, "jornada"),
    ):
        conn.execute(
            """INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal, cobro_modo)
               VALUES (%s,%s,%s,%s,%s)""",
            (PED_MIXTO, eid, 1, monto, cobro_modo),
        )
    conn.execute(
        """INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (PED_MIXTO, total, "pago", "Rambla", "transferencia", "2026-06-05T09:00:00"),
    )
    return total


def test_liquidacion_estudio_beneficiario_db(conn):
    from reportes.cierres import rango_mes
    from reportes.liquidacion import liquidar
    from reportes.reconciliacion import reconciliar

    _setup_pedido_mixto(conn)
    desde, hasta = rango_mes(MES)
    data = liquidar(conn, desde, hasta)

    # Atribución por dueño (pre-reparto): cada línea va a su dueño real.
    por_dueno = {d["dueno"]: d["monto_generado"] for d in data["por_dueno"]}
    assert por_dueno["Estudio"] == ESPACIO_MONTO
    assert por_dueno["Rambla"] == PROMO_MONTO
    assert por_dueno["Pablo"] == SUELTO_MONTO

    # El Estudio es 100% autónomo (su modelo no reparte con nadie más) → su
    # bucket de beneficiario es EXACTO, sin contaminarse de otros dueños.
    assert data["resumen"]["por_beneficiario"]["Estudio"] == ESPACIO_MONTO

    # "Estudio" es un dueño válido — no aparece como típo/dueño fantasma.
    rep = reconciliar(conn)
    assert "Estudio" not in rep["duenos_no_canonicos"]


def test_rendicion_estudio_db(conn):
    # Rambla cobró un pedido íntegramente de espacio (dueno=Estudio) — le
    # corresponde al Estudio, no a Rambla. El netting (ya genérico a 4 partes,
    # Fase 3) sugiere la transferencia Rambla→Estudio.
    from contabilidad.queries.rendicion import rendicion

    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s,%s,%s,%s)",
        (EQ_ESPACIO, "Estudio (espacio) test", 1, "Estudio"),
    )
    conn.execute(
        """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                                   monto_total, monto_pagado)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (PED_SOLO_ESPACIO, "Cliente turno estudio", "finalizado", "2026-06-10T08:00:00",
         "2026-06-10T10:00:00", ESPACIO_MONTO, ESPACIO_MONTO),
    )
    conn.execute(
        """INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal, cobro_modo)
           VALUES (%s,%s,%s,%s,%s)""",
        (PED_SOLO_ESPACIO, EQ_ESPACIO, 1, ESPACIO_MONTO, "fijo"),
    )
    conn.execute(
        """INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (PED_SOLO_ESPACIO, ESPACIO_MONTO, "pago", "Rambla", "transferencia", "2026-06-10T09:00:00"),
    )

    r = rendicion(conn, MES)
    assert r["cuadra"] is True  # todo lo cobrado está contabilizado, solo mal atribuido
    assert r["corresponde"]["Estudio"] == ESPACIO_MONTO
    assert r["cobrado"]["Rambla"] == ESPACIO_MONTO
    assert r["cobrado"]["Estudio"] == 0
    assert {"de": "Rambla", "a": "Estudio", "monto": ESPACIO_MONTO} in r["sugeridos"]


def test_pyl_parte_estudio(conn):
    from contabilidad.queries.pyl import ganancia_neta

    total = _setup_pedido_mixto(conn)
    gan = ganancia_neta(conn, MES)

    # Reparto DEFAULT_MODELO: Rambla 100% self + Pablo reparte 50/45/5 (Pablo/
    # Rambla/Tincho) sobre su ítem suelto → Rambla acumula promo + su tajada.
    parte_rambla_esperada = PROMO_MONTO + int(round(SUELTO_MONTO * 0.45))
    parte_pablo_esperada = int(round(SUELTO_MONTO * 0.50))
    parte_tincho_esperada = int(round(SUELTO_MONTO * 0.05))

    assert gan["facturado"] == total
    assert gan["parte_estudio"] == ESPACIO_MONTO
    # comisiones_duenos excluye TANTO Rambla como Estudio — solo Pablo/Tincho.
    assert gan["comisiones_duenos"] == parte_pablo_esperada + parte_tincho_esperada
    assert gan["ganancia_neta"] == parte_rambla_esperada - gan["gastos"]
