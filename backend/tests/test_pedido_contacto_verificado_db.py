"""El contacto de un cliente en el admin (card del pedido, listado de pedidos,
ficha del cliente) leía SOLO las columnas base `clientes.email`/`telefono` —
nunca `verified_contacts` (donde Didit guarda el contacto verificado por OTP,
un check independiente del de DNI/RENAPER). El checkout, el envío real de
WhatsApp y el portal del cliente ya usaban el resolvedor canónico
(`identity/contacts.py`); el admin era la excepción — mostraba "sin contacto"
para un cliente que el sistema SÍ sabe contactar (caso real: pedido #466).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_pedido_contacto_verificado_db.py -v -m integration
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

# Ids altos dedicados (bloque 9_494_xxx, sin uso en otros *_db.py).
CLIENTE_ID = 9_494_101    # passkey-only: sin telefono base, verificado por Didit OTP
CLIENTE_B_ID = 9_494_102  # tiene AMBOS (base + verificado distintos) — control de no-cruce
PEDIDO_ID = 9_494_201
PEDIDO_B_ID = 9_494_202


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN (%s,%s)", (PEDIDO_ID, PEDIDO_B_ID))
    conn.execute("DELETE FROM alquileres WHERE id IN (%s,%s)", (PEDIDO_ID, PEDIDO_B_ID))
    conn.execute(
        "DELETE FROM verified_contacts WHERE cliente_id IN (%s,%s)", (CLIENTE_ID, CLIENTE_B_ID)
    )
    conn.execute("DELETE FROM clientes WHERE id IN (%s,%s)", (CLIENTE_ID, CLIENTE_B_ID))


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

        # Camila (#466): cuenta passkey-only, sin teléfono/email base — el
        # único contacto real vive en verified_contacts (Didit OTP).
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Camila','Simoni',NULL,NULL)",
            (CLIENTE_ID,),
        )
        conn.execute(
            """INSERT INTO verified_contacts (cliente_id, kind, value, source, verified_at)
               VALUES (%s, 'phone', '+5492235551234', 'didit', now())""",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_telefono, "
            "estado, tipo, fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Camila Simoni','','confirmado','diaria',NOW(),NOW(),20000)",
            (PEDIDO_ID, CLIENTE_ID),
        )

        # Cliente B: base Y verificado, DISTINTOS — control de no-cruce en el
        # batch (el listado no puede mezclar el contacto de A con el de B).
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Bruno','Diaz','bruno-base@mail.com','111-base')",
            (CLIENTE_B_ID,),
        )
        conn.execute(
            """INSERT INTO verified_contacts (cliente_id, kind, value, source, verified_at)
               VALUES (%s, 'phone', '+5492235559999', 'didit', now())""",
            (CLIENTE_B_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_telefono, "
            "estado, tipo, fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Bruno Diaz','','confirmado','diaria',NOW(),NOW(),18000)",
            (PEDIDO_B_ID, CLIENTE_B_ID),
        )

        conn.commit()
        yield {}
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def test_detalle_de_pedido_muestra_el_telefono_verificado(client_con_db, setup):
    r = client_con_db.get(f"/api/alquileres/{PEDIDO_ID}")
    assert r.status_code == 200, r.text
    pedido = r.json()
    assert pedido["cliente_telefono"] == "+5492235551234"  # NO vacío — el bug real


def test_listado_resuelve_cada_pedido_con_su_propio_contacto(client_con_db, setup):
    r = client_con_db.get("/api/alquileres", params={"per_page": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body

    fila_a = next((p for p in items if p["id"] == PEDIDO_ID), None)
    assert fila_a is not None
    assert fila_a["cliente_telefono"] == "+5492235551234"  # sin base → el verificado propio

    fila_b = next((p for p in items if p["id"] == PEDIDO_B_ID), None)
    assert fila_b is not None
    assert fila_b["cliente_telefono"] == "+5492235559999"  # verificado propio, no el de A


def test_ficha_de_cliente_suma_el_contacto_resuelto_sin_pisar_el_base(client_con_db, setup):
    r = client_con_db.get(f"/api/clientes/{CLIENTE_ID}")
    assert r.status_code == 200, r.text
    cliente = r.json()
    assert cliente["telefono"] is None  # el campo BASE del form de edición, intacto
    assert cliente["telefono_contacto"] == "+5492235551234"  # vista resuelta para display
