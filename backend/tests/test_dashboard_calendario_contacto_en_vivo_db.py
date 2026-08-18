"""El Calendario general y el Dashboard admin leían `alquileres.cliente_nombre`
crudo — una foto tomada una sola vez al crear/vincular el pedido — en vez de
resolver el cliente EN VIVO como ya hace el detalle de pedido y el listado
`/api/alquileres` (decisión 2026-06-06, "contacto en vivo"). Reproduce el bug
real (pedido #466): el cliente no tenía nombre cargado cuando se vinculó al
pedido (la foto congelada quedó vacía), y se completó DESPUÉS — el calendario
seguía mostrando "Sin cliente" para siempre.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_dashboard_calendario_contacto_en_vivo_db.py -v -m integration
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

# Ids altos dedicados (bloque 9_493_xxx, sin uso en otros *_db.py).
PEDIDO_ID = 9_493_101                # cliente sin nombre al vincularse, se completa después
PEDIDO_SIN_NOMBRE_ID = 9_493_102     # control negativo: cliente sigue sin nombre real
PEDIDO_PRINCIPAL_ID = 9_493_103      # principal de un turno vinculado
PEDIDO_TURNO_VINCULADO_ID = 9_493_104
EQ_A = 9_493_201
EQ_B = 9_493_202
EQ_PRINCIPAL = 9_493_203
EQ_TURNO = 9_493_204
CLIENTE_ID = 9_493_301
CLIENTE_SIN_NOMBRE_ID = 9_493_302
CLIENTE_PRINCIPAL_ID = 9_493_303


def _limpiar(conn):
    pedido_ids = (PEDIDO_ID, PEDIDO_SIN_NOMBRE_ID, PEDIDO_PRINCIPAL_ID, PEDIDO_TURNO_VINCULADO_ID)
    ph = ",".join(["%s"] * len(pedido_ids))
    conn.execute(f"DELETE FROM alquiler_items WHERE pedido_id IN ({ph})", pedido_ids)
    conn.execute(f"DELETE FROM alquileres WHERE id IN ({ph})", pedido_ids)
    conn.execute(
        "DELETE FROM equipos WHERE id IN (%s,%s,%s,%s)", (EQ_A, EQ_B, EQ_PRINCIPAL, EQ_TURNO)
    )
    conn.execute(
        "DELETE FROM clientes WHERE id IN (%s,%s,%s)",
        (CLIENTE_ID, CLIENTE_SIN_NOMBRE_ID, CLIENTE_PRINCIPAL_ID),
    )


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
    from database import get_db, now_ar

    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    conn = get_db()
    try:
        _limpiar(conn)
        hoy = now_ar()
        # Fecha SIN componente horario (medianoche): `get_calendario` compara
        # `fecha_desde <= %s` sin castear a `::date` (a diferencia de
        # salen_hoy/devuelven_hoy, que sí castean) — un `fecha_desde` con la
        # hora actual quedaría DESPUÉS de la medianoche del `desde` del query
        # y el pedido no matchearía el rango.
        hoy_iso = hoy.date().isoformat()

        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno, es_recurso_interno) VALUES "
            "(%s,'Cámara test contacto A',1,'Rental',FALSE),"
            "(%s,'Cámara test contacto B',1,'Rental',FALSE),"
            "(%s,'Cámara test contacto principal',1,'Rental',FALSE)",
            (EQ_A, EQ_B, EQ_PRINCIPAL),
        )

        # Cliente SIN nombre cargado (cuenta liviana recién vinculada) — la
        # foto congelada del pedido (`cliente_nombre`) queda vacía.
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) VALUES (%s,'','',NULL,NULL)",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'','confirmado','diaria',%s,%s,30000)",
            (PEDIDO_ID, CLIENTE_ID, hoy_iso, hoy_iso),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,30000,30000,'jornada')",
            (PEDIDO_ID, EQ_A),
        )
        # El cliente se completa DESPUÉS (ej. verificación RENAPER) — la foto
        # congelada de `alquileres.cliente_nombre` NO se toca (a propósito:
        # así se reproduce el bug, nada la resincroniza sola).
        conn.execute(
            "UPDATE clientes SET nombre='Camila', apellido='Simoni' WHERE id=%s", (CLIENTE_ID,)
        )

        # Control negativo: cliente que SIGUE sin nombre real — el calendario
        # tiene que seguir mostrando "" (el frontend cae a "Sin cliente"
        # correctamente para este caso genuino, no lo estamos rompiendo).
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) VALUES (%s,'','',NULL,NULL)",
            (CLIENTE_SIN_NOMBRE_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'','confirmado','diaria',%s,%s,25000)",
            (PEDIDO_SIN_NOMBRE_ID, CLIENTE_SIN_NOMBRE_ID, hoy_iso, hoy_iso),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,25000,25000,'jornada')",
            (PEDIDO_SIN_NOMBRE_ID, EQ_B),
        )

        # Turno VINCULADO (pedido_principal_id, mecanismo viejo — distinto del
        # turno embebido): el principal consigue cliente DESPUÉS de que el
        # turno ya se creó — mismo bug, ahora end-to-end vía /api/calendario
        # (los tests unitarios de _enriquecer_pedido_con_cliente ya cubren la
        # función; esto confirma que la SQL nueva trae pedido_principal_id).
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) VALUES (%s,'','',NULL,NULL)",
            (CLIENTE_PRINCIPAL_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'','confirmado','diaria',%s,%s,10000)",
            (PEDIDO_PRINCIPAL_ID, CLIENTE_PRINCIPAL_ID, hoy_iso, hoy_iso),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, pedido_principal_id, "
            "estado, tipo, fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (PEDIDO_TURNO_VINCULADO_ID, CLIENTE_PRINCIPAL_ID, "", PEDIDO_PRINCIPAL_ID,
             "confirmado", "estudio", hoy_iso, hoy_iso, 15000),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,15000,15000,'jornada')",
            (PEDIDO_TURNO_VINCULADO_ID, EQ_PRINCIPAL),
        )
        conn.execute(
            "UPDATE clientes SET nombre='Principal', apellido='Turno' WHERE id=%s",
            (CLIENTE_PRINCIPAL_ID,),
        )

        conn.commit()
        yield {"hoy": hoy}
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def test_calendario_muestra_el_nombre_en_vivo_no_la_foto_vacia(client_con_db, setup):
    hoy = setup["hoy"]
    r = client_con_db.get(
        "/api/calendario",
        params={"desde": hoy.date().isoformat(), "hasta": hoy.date().isoformat()},
    )
    assert r.status_code == 200, r.text
    eventos = r.json()

    fila = next((e for e in eventos if e["id"] == PEDIDO_ID), None)
    assert fila is not None, eventos
    assert fila["cliente_nombre"] == "Camila Simoni"  # NO "" — el bug real


def test_calendario_control_negativo_sigue_mostrando_vacio(client_con_db, setup):
    hoy = setup["hoy"]
    r = client_con_db.get(
        "/api/calendario",
        params={"desde": hoy.date().isoformat(), "hasta": hoy.date().isoformat()},
    )
    assert r.status_code == 200, r.text
    eventos = r.json()

    fila = next((e for e in eventos if e["id"] == PEDIDO_SIN_NOMBRE_ID), None)
    assert fila is not None, eventos
    assert fila["cliente_nombre"] == ""  # genuinamente sin nombre — no se inventa uno


def test_calendario_turno_vinculado_resuelve_el_cliente_del_principal(client_con_db, setup):
    hoy = setup["hoy"]
    r = client_con_db.get(
        "/api/calendario",
        params={"desde": hoy.date().isoformat(), "hasta": hoy.date().isoformat()},
    )
    assert r.status_code == 200, r.text
    eventos = r.json()

    fila = next((e for e in eventos if e["id"] == PEDIDO_TURNO_VINCULADO_ID), None)
    assert fila is not None, eventos
    assert fila["cliente_nombre"] == "Principal Turno"


def test_dashboard_salen_hoy_y_devuelven_hoy_muestran_el_nombre_en_vivo(client_con_db, setup):
    r = client_con_db.get("/api/dashboard")
    assert r.status_code == 200, r.text
    data = r.json()

    fila_sale = next((p for p in data["salen_hoy"] if p["id"] == PEDIDO_ID), None)
    assert fila_sale is not None, data["salen_hoy"]
    assert fila_sale["cliente_nombre"] == "Camila Simoni"

    fila_devuelve = next((p for p in data["devuelven_hoy"] if p["id"] == PEDIDO_ID), None)
    assert fila_devuelve is not None, data["devuelven_hoy"]
    assert fila_devuelve["cliente_nombre"] == "Camila Simoni"


def test_dashboard_equipos_afuera_muestra_el_nombre_en_vivo(client_con_db, setup):
    r = client_con_db.get("/api/dashboard")
    assert r.status_code == 200, r.text
    data = r.json()

    fila = next((e for e in data["equipos_afuera"] if e.get("nombre") == "Cámara test contacto A"), None)
    assert fila is not None, data["equipos_afuera"]
    assert fila["cliente_nombre"] == "Camila Simoni"
