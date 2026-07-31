"""#1308 rediseño "turno como ítem", Fase 3.2 — el motor de facturación
(`services/facturacion/engine.py::_get_pedido`) declara el período de servicio
correcto para un pedido `diaria` MIXTO (equipo normal + turno del Estudio
EMBEBIDO, `alquiler_turnos_estudio`) cuando el turno cae fuera del rango de
días del alquiler — mismo propósito que ya cubre
`test_pedido_vinculado_un_solo_pedido_db.py::test_el_periodo_de_servicio_cubre_la_franja_del_turno`
para el mecanismo VIEJO (`pedido_principal_id`), acá para el NUEVO.

También confirma el lado de la plata (sin lógica nueva — `desglose_de_pedido`
ya es item-agnóstica, Fase 1 — pero vale re-confirmarlo desde ESTE consumidor
real, no solo desde el motor de reservas): el turno embebido no duplica ni
pierde su aporte a `monto_total` al pasar por `_get_pedido`.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_facturacion_turno_embebido_db.py -v -m integration
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

import main  # noqa: E402 — importado después del gating, mismo patrón que los otros *_db.py

# Ids altos dedicados (bloque 9_486_xxx, sin uso en otros *_db.py).
CLIENTE_ID = 9_486_001
EQ_RENTAL_ID = 9_486_010
PEDIDO_ID = 9_486_020
PEDIDO_SIN_TURNO_ID = 9_486_021

MONTO_RENTAL = 40_000
MONTO_TURNO = 15_000


@pytest.fixture(scope="module")
def client_con_db():
    from database import init_db
    from fastapi.testclient import TestClient

    init_db()
    with TestClient(main.app, raise_server_exceptions=True) as c:
        if main.db_init_thread is not None:
            main.db_init_thread.join(timeout=60)
        yield c


def _limpiar(conn):
    ids = (PEDIDO_ID, PEDIDO_SIN_TURNO_ID)
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN (%s,%s)", ids)
    conn.execute("DELETE FROM alquiler_turnos_estudio WHERE pedido_id IN (%s,%s)", ids)
    conn.execute("DELETE FROM alquileres WHERE id IN (%s,%s)", ids)
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_RENTAL_ID,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


@pytest.fixture
def setup(monkeypatch):
    from database import get_db

    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Turno','Facturacion','turno-facturacion-embebido@test.com','+5491100000094')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno) "
            "VALUES (%s,'Cámara test facturación turno embebido',1,'Rental')",
            (EQ_RENTAL_ID,),
        )
        centinela_id = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]

        # Pedido mixto: equipo normal (2033-07-01 al 04) + turno embebido, fecha
        # a definir por cada test (ANTES/DESPUÉS/DENTRO del rango del alquiler).
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Turno Facturacion','confirmado','diaria','2033-07-01','2033-07-04',%s)",
            (PEDIDO_ID, CLIENTE_ID, MONTO_RENTAL + MONTO_TURNO),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,13334,%s,'jornada')",
            (PEDIDO_ID, EQ_RENTAL_ID, MONTO_RENTAL),
        )
        turno_id = conn.execute(
            "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
            "VALUES (%s,'2033-07-02 14:00','2033-07-02 16:00') RETURNING id",
            (PEDIDO_ID,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo, turno_estudio_id) VALUES (%s,%s,1,%s,%s,'fijo',%s)",
            (PEDIDO_ID, centinela_id, MONTO_TURNO, MONTO_TURNO, turno_id),
        )

        # Control: pedido normal, sin ningún turno embebido.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Turno Facturacion control','confirmado','diaria','2033-07-01','2033-07-04',%s)",
            (PEDIDO_SIN_TURNO_ID, CLIENTE_ID, MONTO_RENTAL),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,13334,%s,'jornada')",
            (PEDIDO_SIN_TURNO_ID, EQ_RENTAL_ID, MONTO_RENTAL),
        )
        conn.commit()
        yield turno_id
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def test_monto_total_incluye_el_turno_sin_duplicar(client_con_db, setup):
    from database import get_db
    from services.facturacion.engine import _get_pedido

    conn = get_db()
    try:
        pedido = _get_pedido(conn, PEDIDO_ID)
    finally:
        conn.close()

    assert pedido["monto_total"] == MONTO_RENTAL + MONTO_TURNO


def test_periodo_no_cambia_si_el_turno_cae_dentro_del_rango(client_con_db, setup):
    """El turno (2033-07-02, dentro de 07-01..07-04) no debe estirar nada —
    control negativo: sin esto, un min/max mal armado podría angostar el
    período en vez de solo expandirlo."""
    from database import get_db
    from services.facturacion.engine import _get_pedido

    conn = get_db()
    try:
        pedido = _get_pedido(conn, PEDIDO_ID)
    finally:
        conn.close()

    assert pedido["fecha_desde"].strftime("%Y-%m-%d") == "2033-07-01"
    assert pedido["fecha_hasta"].strftime("%Y-%m-%d") == "2033-07-04"


def test_periodo_se_expande_si_el_turno_cae_antes_del_rango(client_con_db, setup):
    from database import get_db
    from services.facturacion.engine import _get_pedido

    conn = get_db()
    try:
        conn.execute(
            "UPDATE alquiler_turnos_estudio SET fecha_desde='2033-06-20 10:00', "
            "fecha_hasta='2033-06-20 12:00' WHERE pedido_id=%s",
            (PEDIDO_ID,),
        )
        conn.commit()
        pedido = _get_pedido(conn, PEDIDO_ID)
    finally:
        conn.close()

    assert pedido["fecha_desde"].strftime("%Y-%m-%d") == "2033-06-20"
    assert pedido["fecha_hasta"].strftime("%Y-%m-%d") == "2033-07-04"


def test_periodo_se_expande_si_el_turno_cae_despues_del_rango(client_con_db, setup):
    from database import get_db
    from services.facturacion.engine import _get_pedido

    conn = get_db()
    try:
        conn.execute(
            "UPDATE alquiler_turnos_estudio SET fecha_desde='2033-07-20 10:00', "
            "fecha_hasta='2033-07-20 12:00' WHERE pedido_id=%s",
            (PEDIDO_ID,),
        )
        conn.commit()
        pedido = _get_pedido(conn, PEDIDO_ID)
    finally:
        conn.close()

    assert pedido["fecha_desde"].strftime("%Y-%m-%d") == "2033-07-01"
    assert pedido["fecha_hasta"].strftime("%Y-%m-%d") == "2033-07-20"


def test_pedido_sin_turno_embebido_no_cambia_periodo(client_con_db, setup):
    """Control: el 100% de los pedidos sin turno embebido —
    `expandir_periodo_turnos_embebidos` es un no-op."""
    from database import get_db
    from services.facturacion.engine import _get_pedido

    conn = get_db()
    try:
        pedido = _get_pedido(conn, PEDIDO_SIN_TURNO_ID)
    finally:
        conn.close()

    assert pedido["fecha_desde"].strftime("%Y-%m-%d") == "2033-07-01"
    assert pedido["fecha_hasta"].strftime("%Y-%m-%d") == "2033-07-04"
    assert pedido["monto_total"] == MONTO_RENTAL
