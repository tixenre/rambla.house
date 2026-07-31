"""Sacar el ÚLTIMO equipo de un pedido tiene que poder guardarse.

Bug reportado por el dueño ("cuando saco un equipo, no se guarda"): el editor
quedaba en "Sin guardar" para siempre y el cambio se perdía al recargar. Eran
dos capas tapándose entre sí — el front ni siquiera intentaba guardar una lista
vacía (`if (items.length === 0) return` en `usePedidoDraft`), y detrás el
backend la rechazaba con 400 "Debe tener al menos un ítem" sin excepción.

Quedarse sin equipos NO siempre es un pedido sin contenido:
  1. un BORRADOR es un presupuesto que se está armando (misma excepción que ya
     hacía `create_pedido`: un borrador nace vacío);
  2. un pedido cuyo contenido son horas de Estudio (#1308) — "2 horas de
     estudio y nada más" es un pedido perfectamente válido.
Un pedido de primera clase, ya solicitado y sin turnos, SÍ sigue necesitando al
menos un ítem: ahí vacío es un pedido sin nada.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_pedido_sin_equipos_guarda_db.py -v -m integration
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

EQ_ID = 9_499_401
MARCA_Q = "sinequiposguarda"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_nombre LIKE %s)",
        (f"%{MARCA_Q}%",),
    )
    # Los turnos vinculados primero (self-FK) — el DELETE de abajo los alcanza
    # igual porque comparten el nombre de cliente, pero el orden lo deja explícito.
    conn.execute(
        "DELETE FROM alquileres WHERE pedido_principal_id IN "
        "(SELECT id FROM alquileres WHERE cliente_nombre LIKE %s)",
        (f"%{MARCA_Q}%",),
    )
    conn.execute("DELETE FROM alquileres WHERE cliente_nombre LIKE %s", (f"%{MARCA_Q}%",))
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_ID,))


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    from database import get_db

    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada) VALUES (%s,%s,4,10000)",
            (EQ_ID, "Equipo test (sin equipos guarda)"),
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
    with TestClient(main.app, raise_server_exceptions=True) as c:
        if main.db_init_thread is not None:
            main.db_init_thread.join(timeout=60)
        yield c


def _crear(client, estado):
    r = client.post(
        "/api/alquileres",
        json={
            "cliente_nombre": f"{MARCA_Q} {estado}",
            "estado": estado,
            "fecha_desde": "2034-11-01",
            "fecha_hasta": "2034-11-03",
            "items": [{"equipo_id": EQ_ID, "cantidad": 1, "precio_jornada": 10000}],
        },
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _vaciar(client, pedido_id):
    return client.put(f"/api/alquileres/{pedido_id}/items", json={"items": []})


def test_un_borrador_puede_quedarse_sin_equipos(client_con_db, setup):
    """Discrimina: contra el código viejo esto daba 400 "Debe tener al menos un
    ítem" — el auto-guardado no podía persistir el cambio."""
    p = _crear(client_con_db, "borrador")
    r = _vaciar(client_con_db, p["id"])
    assert r.status_code == 200, r.text

    # Y quedó guardado de verdad, no solo contestó OK.
    d = client_con_db.get(f"/api/alquileres/{p['id']}").json()
    assert d["items"] == []
    assert d["monto_total"] == 0


def test_un_pedido_solicitado_sin_turnos_sigue_necesitando_un_item(client_con_db, setup):
    """La regla no se derogó: un pedido de primera clase, sin nada que lo
    justifique, no puede quedar vacío."""
    p = _crear(client_con_db, "solicitado")
    r = _vaciar(client_con_db, p["id"])
    assert r.status_code == 400, r.text
    assert "al menos un" in r.json()["detail"]

    # Y no se tocó nada.
    d = client_con_db.get(f"/api/alquileres/{p['id']}").json()
    assert len(d["items"]) == 1


def test_un_pedido_con_turno_del_estudio_puede_quedarse_sin_equipos(client_con_db, setup):
    """"2 horas de estudio y nada más" es un pedido válido (#1308): el contenido
    son las horas del turno vinculado, no los equipos."""
    p = _crear(client_con_db, "solicitado")

    from database import get_db

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO alquileres (cliente_nombre, fecha_desde, fecha_hasta, estado,
                                       monto_total, tipo, pedido_principal_id)
               VALUES (%s, %s, %s, 'solicitado', 60000, 'estudio', %s)""",
            (f"{MARCA_Q} turno", "2034-11-05 08:00", "2034-11-05 10:00", p["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    r = _vaciar(client_con_db, p["id"])
    assert r.status_code == 200, r.text
    assert client_con_db.get(f"/api/alquileres/{p['id']}").json()["items"] == []


def test_un_turno_cancelado_no_alcanza_para_dejarlo_vacio(client_con_db, setup):
    """Mismo filtro que el pago y la factura combinados: un turno cancelado ya no
    es contenido del pedido."""
    p = _crear(client_con_db, "solicitado")

    from database import get_db

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO alquileres (cliente_nombre, fecha_desde, fecha_hasta, estado,
                                       monto_total, tipo, pedido_principal_id)
               VALUES (%s, %s, %s, 'cancelado', 60000, 'estudio', %s)""",
            (f"{MARCA_Q} turno cancelado", "2034-11-06 08:00", "2034-11-06 10:00", p["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    r = _vaciar(client_con_db, p["id"])
    assert r.status_code == 400, r.text
