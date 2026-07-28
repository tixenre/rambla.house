"""`routes/dashboard.py` (salen_hoy/devuelven_hoy/devuelven_manana/equipos_afuera/
calendario) no debe mostrar pedidos DERIVADOS/contables ('taller', 'estudio_fijo')
como si fueran eventos reales de un día puntual — sus fechas no lo son (taller =
mes calendario completo de la edición; estudio_fijo = solo la primera ocurrencia
semanal). Tampoco debe listar el centinela ("Estudio (espacio)") en "Equipos
afuera": es un recurso interno, no un equipo físico que alguien retira.

Bug real reportado por el dueño (pedido #445): un pedido de taller aparecía
mezclado con los alquileres reales en estas superficies, con vocabulario y
semántica que no le corresponden.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://tincho@localhost/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_dashboard_excluye_derivados_db.py -v -m integration
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

PEDIDO_TALLER = 9_498_101
PEDIDO_RENTAL = 9_498_102
EQ_RENTAL = 9_498_201

HOY = None  # se resuelve en el fixture (now_ar() real, para que "hoy"/"mañana" sean reales)


def _limpiar(conn):
    ids = (PEDIDO_TALLER, PEDIDO_RENTAL)
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN (%s,%s)", ids)
    conn.execute("DELETE FROM alquileres WHERE id IN (%s,%s)", ids)
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_RENTAL,))


@pytest.fixture(scope="module")
def client_con_db():
    """TestClient con Postgres real. Espera al db_init_thread — mismo patrón
    que test_estudio_items_veraces_db.py (issue #1304)."""
    from database import init_db
    from fastapi.testclient import TestClient

    init_db()
    with TestClient(main.app, raise_server_exceptions=True) as c:
        if main.db_init_thread is not None:
            main.db_init_thread.join(timeout=60)
        yield c


@pytest.fixture
def setup(monkeypatch):
    from database import get_db, now_ar
    from datetime import timedelta

    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    conn = get_db()
    try:
        _limpiar(conn)
        centinela_id = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]
        assert centinela_id

        hoy = now_ar()
        # Pedido de TALLER: fecha_desde = HOY, fecha_hasta = MAÑANA — a
        # propósito, para que sin el fix aparezca en las 3 listas a la vez
        # (salen_hoy por fecha_desde, devuelven_hoy NO por construcción,
        # devuelven_manana por fecha_hasta) Y en el calendario (rango
        # amplio simulado con +20 días para ese chequeo puntual más abajo).
        fd_taller = hoy.isoformat()
        fh_taller = (hoy + timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s, 'Taller test dashboard', 'confirmado', 'taller', %s, %s, 50000)",
            (PEDIDO_TALLER, fd_taller, fh_taller),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
            "VALUES (%s, %s, 1, 50000, 50000, 'fijo')",
            (PEDIDO_TALLER, centinela_id),
        )

        # Pedido de RENTAL real, sale y vuelve HOY — tiene que seguir apareciendo.
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s, 'Cámara test dashboard', 1, 'Rambla')",
            (EQ_RENTAL,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s, 'Cliente test dashboard', 'confirmado', 'diaria', %s, %s, 10000)",
            (PEDIDO_RENTAL, hoy.isoformat(), hoy.isoformat()),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
            "VALUES (%s, %s, 1, 10000, 10000, 'jornada')",
            (PEDIDO_RENTAL, EQ_RENTAL),
        )
        conn.commit()
        yield hoy
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def test_dashboard_no_lista_taller_en_salen_ni_devuelven(client_con_db, setup):
    r = client_con_db.get("/api/dashboard")
    assert r.status_code == 200, r.text
    data = r.json()

    ids_salen = {p["id"] for p in data["salen_hoy"]}
    ids_devuelven_hoy = {p["id"] for p in data["devuelven_hoy"]}
    ids_devuelven_manana = {p["id"] for p in data["devuelven_manana"]}

    assert PEDIDO_TALLER not in ids_salen
    assert PEDIDO_TALLER not in ids_devuelven_hoy
    assert PEDIDO_TALLER not in ids_devuelven_manana
    # El rental real (sale y vuelve hoy) SÍ tiene que seguir apareciendo.
    assert PEDIDO_RENTAL in ids_salen
    assert PEDIDO_RENTAL in ids_devuelven_hoy


def test_dashboard_equipos_afuera_no_lista_el_centinela(client_con_db, setup):
    r = client_con_db.get("/api/dashboard")
    assert r.status_code == 200, r.text
    nombres = {e["nombre"] for e in r.json()["equipos_afuera"]}
    assert "Estudio (espacio)" not in nombres
    assert "Cámara test dashboard" in nombres


def test_calendario_no_lista_el_pedido_de_taller(client_con_db, setup):
    from datetime import timedelta

    hoy = setup
    r = client_con_db.get(
        "/api/calendario",
        params={
            "desde": (hoy - timedelta(days=5)).date().isoformat(),
            "hasta": (hoy + timedelta(days=25)).date().isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    ids = {p["id"] for p in r.json()}
    assert PEDIDO_TALLER not in ids
    assert PEDIDO_RENTAL in ids
