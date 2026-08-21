"""GET /admin/pagos ("Cobros de pedidos", el ledger global de `alquiler_pagos`)
leía `alquileres.cliente_nombre` crudo — la foto congelada al vincularse el
pedido — en vez de resolver el cliente EN VIVO como ya hacía el detalle de
pedido y el calendario/dashboard (decisión 2026-06-06, "contacto en vivo").

Mismo patrón exacto de bug que `test_dashboard_calendario_contacto_en_vivo_db.py`
(pedido real #466: el cliente no tenía nombre cargado cuando se vinculó al
pedido, se completó DESPUÉS, la foto congelada nunca se resincronizó) — ese
fix cubrió calendario/dashboard pero no este ledger, reportado en vivo por el
dueño viendo /admin/pagos.

OPT-IN y seguro por defecto (mismo gating que los demás *_db.py).
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

# Ids altos dedicados (bloque 9_466_xxx — el número del pedido real que
# reprodujo el bug).
PEDIDO_ID = 9_466_101
EQ_ID = 9_466_201
CLIENTE_ID = 9_466_301
PAGO_ID = 9_466_401


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_pagos WHERE id = %s", (PAGO_ID,))
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (PEDIDO_ID,))
    conn.execute("DELETE FROM alquileres WHERE id = %s", (PEDIDO_ID,))
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_ID,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


@pytest.fixture
def setup(monkeypatch):
    from database import get_db, init_db, now_ar

    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        hoy = now_ar().date().isoformat()

        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, es_recurso_interno) "
            "VALUES (%s,'Cámara test pagos-log',1,'Rental',FALSE)",
            (EQ_ID,),
        )
        # Cliente SIN nombre cargado al vincularse (cuenta liviana recién
        # verificada) — la foto congelada del pedido queda vacía.
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) VALUES (%s,'','',NULL,NULL)",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, numero_pedido, estado, "
            "tipo, fecha_desde, fecha_hasta, monto_total, monto_pagado) "
            "VALUES (%s,%s,'',%s,'confirmado','diaria',%s,%s,30000,10000)",
            (PEDIDO_ID, CLIENTE_ID, PEDIDO_ID, hoy, hoy),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,30000,30000,'jornada')",
            (PEDIDO_ID, EQ_ID),
        )
        conn.execute(
            "INSERT INTO alquiler_pagos (id, pedido_id, monto, concepto, destinatario, metodo) "
            "VALUES (%s,%s,10000,'Seña','Rental','transferencia')",
            (PAGO_ID, PEDIDO_ID),
        )
        # El cliente se completa DESPUÉS — la foto congelada de
        # `alquileres.cliente_nombre` NO se toca (a propósito, así se
        # reproduce el bug real).
        conn.execute(
            "UPDATE clientes SET nombre='Camila', apellido='Simoni' WHERE id=%s", (CLIENTE_ID,)
        )
        conn.commit()
        yield
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def test_pagos_log_muestra_el_nombre_en_vivo_no_la_foto_vacia(setup):
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app)
    r = client.get("/api/admin/pagos", params={"limit": 2000})
    assert r.status_code == 200, r.text
    pagos = r.json()["pagos"]

    fila = next((p for p in pagos if p["id"] == PAGO_ID), None)
    assert fila is not None, [p["id"] for p in pagos]
    assert fila["cliente_nombre"] == "Camila Simoni"  # NO "" — el bug real
