"""Fase 2 de la economía del Estudio: `transiciones.cambiar_estado` sobre un
pedido del Estudio revalida con el buffer PROPIO del espacio, NUNCA con el
buffer GLOBAL de equipos (`app_settings.buffer_horas_alquiler`).

Bug real encontrado auditando la economía del Estudio: antes de este fix,
`cambiar_estado` llamaba al `_check_stock` genérico para CUALQUIER pedido —
ese gate lee el ítem centinela como un equipo más (stock=1) y expande su
rango con el buffer GLOBAL, no con `estudio.buffer_horas`.

Escenario que discrimina el bug: buffer GLOBAL grande (4h) + buffer PROPIO
del estudio en 0. Dos turnos ADYACENTES sin gap (10-12 y 12-14hs).
Confirmar el segundo turno DEBE poder hacerse — con el bug, el buffer
global expandiría la ocupación del primero a 6-16hs y rechazaría el segundo
con 422 pese a que el espacio queda libre a partir de las 12.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://tincho@localhost/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estudio_transiciones_stock_db.py -v -m integration
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

PEDIDO_A = 9_495_101  # turno 10:00-12:00, se confirma primero
PEDIDO_B = 9_495_102  # turno 12:00-14:00, adyacente sin gap
FD_A, FH_A = "2030-04-01T10:00:00", "2030-04-01T12:00:00"
FD_B, FH_B = "2030-04-01T12:00:00", "2030-04-01T14:00:00"


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN (%s,%s)", (PEDIDO_A, PEDIDO_B))
    conn.execute("DELETE FROM alquileres WHERE id IN (%s,%s)", (PEDIDO_A, PEDIDO_B))


@pytest.fixture
def setup():
    from database import get_db, init_db
    from reservas import invalidate_buffer_cache

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        centinela_id = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]
        assert centinela_id, "el seed de init_db() debería crear el centinela"

        # Buffer GLOBAL grande (equipos) vs. buffer PROPIO del estudio en 0.
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES ('buffer_horas_alquiler', '4') "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )
        conn.execute("UPDATE estudio SET buffer_horas=0 WHERE id=1")

        for pid, fd, fh, monto in ((PEDIDO_A, FD_A, FH_A, 20000), (PEDIDO_B, FD_B, FH_B, 20000)):
            conn.execute(
                "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total) "
                "VALUES (%s,'Cliente test transiciones estudio','solicitado','estudio',%s,%s,%s)",
                (pid, fd, fh, monto),
            )
            conn.execute(
                "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
                "VALUES (%s,%s,1,%s,%s,'fijo')",
                (pid, centinela_id, monto, monto),
            )
        conn.commit()
    finally:
        conn.close()

    invalidate_buffer_cache()
    yield

    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute("DELETE FROM app_settings WHERE key = 'buffer_horas_alquiler'")
        conn.commit()
    finally:
        conn.close()
    invalidate_buffer_cache()


def test_confirmar_turnos_adyacentes_no_usa_buffer_global(setup):
    """Confirmar dos turnos del estudio ADYACENTES (sin gap) tiene que
    funcionar — el buffer que aplica es el propio del espacio (0), no el
    buffer global de equipos (4h, que rechazaría cualquier gap < 4hs)."""
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        r1 = cambiar_estado(conn, PEDIDO_A, "confirmado", es_admin=True, actor="test")
        conn.commit()
        assert r1["estado_nuevo"] == "confirmado"

        r2 = cambiar_estado(conn, PEDIDO_B, "confirmado", es_admin=True, actor="test")
        conn.commit()
        assert r2["estado_nuevo"] == "confirmado"
    finally:
        conn.close()

    conn = get_db()
    try:
        estados = conn.execute(
            "SELECT id, estado FROM alquileres WHERE id IN (%s,%s)", (PEDIDO_A, PEDIDO_B)
        ).fetchall()
        assert {r["id"]: r["estado"] for r in estados} == {PEDIDO_A: "confirmado", PEDIDO_B: "confirmado"}
    finally:
        conn.close()
