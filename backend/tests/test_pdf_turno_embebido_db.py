"""#1308 rediseño "turno como ítem", Fase 2.4 — el Remito/Presupuesto de un
pedido `diaria` MIXTO (equipo normal + turno del Estudio EMBEBIDO) muestra la
fila del turno con su PROPIA fecha/hora + "N horas" — no hereda el período de
jornadas del documento (el rango de retiro/devolución de los EQUIPOS, que
puede no coincidir con el del turno).

Verifica el camino completo DB → `_get_alquiler_items` (JOIN a
`alquiler_turnos_estudio`) → `pdf_templates._turno_embebido_label` → HTML,
vía `GET /alquileres/{id}/remito?format=html` (el mismo preview que usa el
front, sin pasar por Playwright).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_pdf_turno_embebido_db.py -v -m integration
"""
import os
from datetime import datetime
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

# Ids altos dedicados (bloque 9_485_xxx, sin uso en otros *_db.py).
CLIENTE_ID = 9_485_001
EQ_RENTAL_ID = 9_485_010
PEDIDO_ID = 9_485_020

TURNO_DESDE = "2031-06-10 14:00"
TURNO_HASTA = "2031-06-10 16:00"  # 2 horas


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (PEDIDO_ID,))
    conn.execute("DELETE FROM alquiler_turnos_estudio WHERE pedido_id = %s", (PEDIDO_ID,))
    conn.execute("DELETE FROM alquileres WHERE id = %s", (PEDIDO_ID,))
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_RENTAL_ID,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


@pytest.fixture(scope="module")
def client_con_db():
    from database import init_db
    from fastapi.testclient import TestClient

    init_db()
    with TestClient(main.app, raise_server_exceptions=True) as c:
        if main.db_init_thread is not None:
            main.db_init_thread.join(timeout=60)
        yield c


@pytest.fixture
def setup(monkeypatch):
    from database import get_db

    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Turno','PDF','turno-pdf-embebido@test.com','+5491100000095')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno) "
            "VALUES (%s,'Cámara test PDF turno embebido',1,'Rental')",
            (EQ_RENTAL_ID,),
        )
        centinela_id = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]

        # Pedido mixto: equipo normal (3 jornadas) + turno embebido (2hs).
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Turno PDF','confirmado','diaria','2031-06-10','2031-06-13',45000)",
            (PEDIDO_ID, CLIENTE_ID),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,10000,30000,'jornada')",
            (PEDIDO_ID, EQ_RENTAL_ID),
        )
        turno_id = conn.execute(
            "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
            "VALUES (%s,%s,%s) RETURNING id",
            (PEDIDO_ID, TURNO_DESDE, TURNO_HASTA),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo, turno_estudio_id) VALUES (%s,%s,1,15000,15000,'fijo',%s)",
            (PEDIDO_ID, centinela_id, turno_id),
        )
        conn.commit()
        yield
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def test_remito_muestra_fecha_propia_del_turno_embebido(client_con_db, setup):
    from pdf_templates import _DOW

    r = client_con_db.get(f"/api/alquileres/{PEDIDO_ID}/remito", params={"format": "html"})
    assert r.status_code == 200, r.text
    html = r.text

    d0 = datetime.strptime(TURNO_DESDE, "%Y-%m-%d %H:%M")
    esperado = f"{_DOW[d0.weekday()]} 10/06 14:00–16:00 · 2 horas"
    assert esperado in html, html

    # Solo el ítem del turno lleva la sub-línea "Turno" — el equipo normal no.
    assert html.count(">Turno<") == 1

    # El equipo normal sigue mostrándose con su nombre, sin la sub-línea.
    assert "Cámara test PDF turno embebido" in html


def test_remito_sin_turno_embebido_no_muestra_sub_linea(client_con_db, setup):
    """Control: un ítem normal (sin turno_estudio_id) nunca lleva la sub-línea
    'Turno' — ya cubierto arriba por conteo, pero se deja explícito acá con un
    pedido puramente rental para no depender de la aritmética del conteo."""
    from database import get_db

    otro_id = PEDIDO_ID + 1
    conn = get_db()
    try:
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (otro_id,))
        conn.execute("DELETE FROM alquileres WHERE id = %s", (otro_id,))
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Turno PDF control','confirmado','diaria','2031-06-10','2031-06-13',30000)",
            (otro_id, CLIENTE_ID),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,10000,30000,'jornada')",
            (otro_id, EQ_RENTAL_ID),
        )
        conn.commit()

        r = client_con_db.get(f"/api/alquileres/{otro_id}/remito", params={"format": "html"})
        assert r.status_code == 200, r.text
        assert ">Turno<" not in r.text
    finally:
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (otro_id,))
        conn.execute("DELETE FROM alquileres WHERE id = %s", (otro_id,))
        conn.commit()
        conn.close()
