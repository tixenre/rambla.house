"""Fase 3 (#1283) contra Postgres REAL — el Estudio como cobrador/parte/caja.

Economía separada: el Estudio pasa a ser un cobrador más (`COBRADORES`) y una
parte más de la rendición (`PARTES`), con su propia caja real (`Caja Estudio`,
`tipo='fondo'`, `socio='Estudio'` — mismo puente 1:1 que Fondo Rambla). Nada de
esto es un caso especial: es la constante generalizada a una 4ta fila, y estos
tests lo confirman contra la DB real (la matemática pura ya está cubierta en
`test_contabilidad_rendicion.py`/`test_contabilidad_saldos.py`).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`).

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_contabilidad_caja_estudio_db.py -v -m integration
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

PED = 9_460_001


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


def _saldo(conn, nombre: str):
    from contabilidad.queries.saldos import saldos
    for f in saldos(conn)["cuentas"]:
        if f["nombre"] == nombre:
            return f["saldo"]
    return None


def _cuenta_id(conn, nombre: str):
    row = conn.execute("SELECT id FROM cuentas WHERE nombre = %s", (nombre,)).fetchone()
    return row[0] if row else None


def _pedido_y_pago(conn, monto, destinatario, ped=PED):
    conn.execute(
        """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                                   monto_total, monto_pagado)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (ped, "Cliente estudio", "finalizado", "2026-06-05T08:00:00",
         "2026-06-06T20:00:00", monto, monto),
    )
    conn.execute(
        """INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (ped, monto, "pago", destinatario, "transferencia", "2026-06-15T10:00:00"),
    )


def test_caja_estudio_seed_existe_como_fondo_de_estudio(conn):
    row = conn.execute(
        "SELECT tipo, socio, activa FROM cuentas WHERE nombre = %s", ("Caja Estudio",)
    ).fetchone()
    assert row is not None
    assert row["tipo"] == "fondo"
    assert row["socio"] == "Estudio"
    assert row["activa"] is True


def test_cobro_de_estudio_alimenta_su_caja(conn):
    # Mismo mecanismo que Fondo Rambla: un cobro con destinatario='Estudio' cae
    # en su caja SOLO por derivación (sin cargar ningún movimiento a mano).
    base = _saldo(conn, "Caja Estudio")
    _pedido_y_pago(conn, 90000, "Estudio")
    assert _saldo(conn, "Caja Estudio") - base == 90000


def test_el_cobro_de_estudio_no_toca_otras_cajas(conn):
    base_rambla = _saldo(conn, "Fondo Rambla")
    base_tincho = _saldo(conn, "Caja Tincho")
    _pedido_y_pago(conn, 90000, "Estudio")
    assert _saldo(conn, "Fondo Rambla") == base_rambla
    assert _saldo(conn, "Caja Tincho") == base_tincho


def test_ingresos_derivados_agrupa_estudio(conn):
    from contabilidad.queries.saldos import ingresos_derivados

    base = ingresos_derivados(conn).get("Estudio", 0)
    _pedido_y_pago(conn, 45000, "Estudio")
    assert ingresos_derivados(conn).get("Estudio", 0) - base == 45000


def test_cuenta_de_parte_resuelve_caja_estudio(conn):
    from contabilidad.queries.rendicion import cuenta_de_parte

    assert cuenta_de_parte(conn, "Estudio") == _cuenta_id(conn, "Caja Estudio")


def test_crear_cuenta_persiste_socio_para_tipo_fondo(conn):
    # Bug real encontrado en esta fase: crear_cuenta solo persistía `socio`
    # cuando tipo == 'socio' — un fondo nuevo (ej. Caja Estudio) lo perdía en
    # silencio. El seed de Caja Estudio se inserta por SQL directo (no pasa por
    # este comando), así que este test es el único que ejerce el fix.
    # idx_cuentas_socio es único por socio ACTIVO → hay que liberar el que ya
    # ocupa 'Estudio' (el seed) antes de crear uno nuevo con el mismo cobrador.
    from contabilidad.commands.cuentas import crear_cuenta, desactivar_cuenta

    desactivar_cuenta(conn, _cuenta_id(conn, "Caja Estudio"), por="test")
    nueva = crear_cuenta(conn, nombre="Caja Estudio Nueva", tipo="fondo", socio="Estudio",
                         por="test")
    assert nueva["socio"] == "Estudio"
    assert nueva["tipo"] == "fondo"


def test_socios_coinciden_con_destinatarios_de_pago_incluye_estudio(conn):
    from contabilidad.constants import COBRADORES
    from routes.alquileres import DESTINATARIOS_PAGO

    assert "Estudio" in COBRADORES
    assert "Estudio" in DESTINATARIOS_PAGO
    assert set(COBRADORES) == set(DESTINATARIOS_PAGO)
