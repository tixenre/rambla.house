"""Un pedido SIN cliente asignado tiene que poder guardar cambios (fechas,
notas, descuento) — bug real reportado por el dueño: "no puedo cambiar la
fecha", con un 500 en `PATCH /api/alquileres/{id}/datos`.

Causa: `alquileres.cliente_nombre` es NOT NULL, pero el autosave del editor
manda `cliente_nombre: d.cliente_nombre || null` (`usePedidoDraft.ts`) — para
un pedido sin cliente eso es `null` → `NotNullViolation` y el guardado ENTERO
falla, aunque lo único que se estaba cambiando fuera la fecha.

Bug PRE-EXISTENTE (no lo introdujo la iniciativa #1308), pero se volvió
frecuente con ella: el flujo de "creo el pedido y le agrego un turno del
Estudio" lleva a trabajar sobre un borrador antes de asignarle el cliente.

El fix vive en `_apply_pedido_datos` (la puerta compartida por el admin Y las
propuestas del portal), no en el front — así ningún caller puede volver a
tumbar el guardado mandando `None` en un campo que la columna no acepta.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_pedido_sin_cliente_guarda_db.py -v -m integration
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

PEDIDO_ID = 9_499_210
EQ_ID = 9_499_201

# El payload EXACTO del autosave del editor admin (`usePedidoDraft.ts::datosMut`)
# para un pedido sin cliente: todos los campos de contacto en `null`.
_PAYLOAD_SIN_CLIENTE = {
    "cliente_id": None,
    "cliente_nombre": None,
    "cliente_email": None,
    "cliente_telefono": None,
    "notas": None,
    "descuento_pct": 0,
    "descuento_manual_tipo": "pct",
    "descuento_manual_monto": 0,
    "perfil_fiscal_id": None,
    "productora_id": None,
}


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (PEDIDO_ID,))
    conn.execute("DELETE FROM alquileres WHERE id = %s", (PEDIDO_ID,))
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_ID,))


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    from database import get_db

    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada) VALUES (%s,%s,3,49200)",
            (EQ_ID, "Equipo test (sin cliente)"),
        )
        # Borrador SIN cliente — `cliente_nombre=''` es como nace un pedido
        # cargado a mano antes de elegir a quién.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, "
            "fecha_hasta, numero_pedido, monto_total, monto_pagado) "
            "VALUES (%s,'','borrador','diaria','2034-09-01','2034-09-02',949921,49200,0)",
            (PEDIDO_ID,),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s,%s,1,49200,49200)",
            (PEDIDO_ID, EQ_ID),
        )
        conn.commit()
    finally:
        conn.close()

    yield

    conn = get_db()
    try:
        _limpiar(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def client_con_db():
    from database import init_db
    from fastapi.testclient import TestClient

    init_db()
    with TestClient(main.app, raise_server_exceptions=False) as c:
        if main.db_init_thread is not None:
            main.db_init_thread.join(timeout=60)
        yield c


def test_cambiar_la_fecha_de_un_pedido_sin_cliente_no_rompe(client_con_db, setup):
    """Discrimina: sin el fix esto es un 500 (`NotNullViolation` en
    `cliente_nombre`) y la fecha NO se guarda."""
    r = client_con_db.patch(
        f"/api/alquileres/{PEDIDO_ID}/datos",
        json={
            **_PAYLOAD_SIN_CLIENTE,
            "fecha_desde": "2034-09-10T00:00:00",
            "fecha_hasta": "2034-09-12T00:00:00",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["fecha_desde"].startswith("2034-09-10")
    assert r.json()["fecha_hasta"].startswith("2034-09-12")


def test_el_nombre_vacio_se_guarda_como_vacio_no_como_null(client_con_db, setup):
    """`cliente_nombre` es NOT NULL: el "sin cliente" se representa con cadena
    vacía, nunca con NULL."""
    from database import get_db

    r = client_con_db.patch(
        f"/api/alquileres/{PEDIDO_ID}/datos", json=dict(_PAYLOAD_SIN_CLIENTE)
    )
    assert r.status_code == 200, r.text

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT cliente_nombre FROM alquileres WHERE id = %s", (PEDIDO_ID,)
        ).fetchone()
    finally:
        conn.close()
    assert row["cliente_nombre"] == ""


def test_guardar_notas_de_un_pedido_sin_cliente_no_rompe(client_con_db, setup):
    """No es solo la fecha: CUALQUIER cambio moría en el mismo guardado."""
    r = client_con_db.patch(
        f"/api/alquileres/{PEDIDO_ID}/datos",
        json={**_PAYLOAD_SIN_CLIENTE, "notas": "Retira Juan por la mañana"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["notas"] == "Retira Juan por la mañana"


def test_un_nombre_real_sigue_guardandose_igual(client_con_db, setup):
    """El fix normaliza SOLO el None → '' — un nombre de verdad no se toca."""
    r = client_con_db.patch(
        f"/api/alquileres/{PEDIDO_ID}/datos",
        json={**_PAYLOAD_SIN_CLIENTE, "cliente_nombre": "Productora Ejemplo"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cliente_nombre"] == "Productora Ejemplo"
