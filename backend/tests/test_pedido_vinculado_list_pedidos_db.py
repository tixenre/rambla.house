"""El turno del Estudio vinculado deja de listarse como pedido aparte en
`/admin/pedidos` (worklist operativo) y en "Cuentas por cobrar" (dashboard de
Equipos) — pero SIGUE viéndose donde la "duplicación" es información real:
el historial de pedidos de un cliente. Tanda que sigue a #1308 ("crear un
turno crea dos pedidos ahora y es aun mas confuso").

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_pedido_vinculado_list_pedidos_db.py -v -m integration
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

CLIENTE_ID = 9_499_002
PEDIDO_PRINCIPAL_ID = 9_499_010
PEDIDO_STANDALONE_ID = 9_499_020
EQ_ID = 9_499_001


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_id = %s "
        "  OR id IN (%s, %s) OR pedido_principal_id IN (%s, %s))",
        (CLIENTE_ID, PEDIDO_PRINCIPAL_ID, PEDIDO_STANDALONE_ID, PEDIDO_PRINCIPAL_ID, PEDIDO_STANDALONE_ID),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE cliente_id = %s "
        "  OR id IN (%s, %s) OR pedido_principal_id IN (%s, %s)",
        (CLIENTE_ID, PEDIDO_PRINCIPAL_ID, PEDIDO_STANDALONE_ID, PEDIDO_PRINCIPAL_ID, PEDIDO_STANDALONE_ID),
    )
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_ID,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    from database import get_db

    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'ListPedidos','Test','listpedidos@test.com','+5491100009002')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada) VALUES (%s,%s,5,1000)",
            (EQ_ID, "Equipo test (list_pedidos)"),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, fecha_desde, fecha_hasta, numero_pedido, "
            "monto_total, monto_pagado) "
            "VALUES (%s,%s,'List Pedidos','listpedidos@test.com','+5491100009002',"
            "'confirmado','2032-06-01','2032-06-05',949901,50000,10000)",
            (PEDIDO_PRINCIPAL_ID, CLIENTE_ID),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada) "
            "VALUES (%s,%s,1,1000)",
            (PEDIDO_PRINCIPAL_ID, EQ_ID),
        )
        # Turno standalone (sin pedido_principal_id) — debe seguir listándose
        # como pedido propio; guarda contra confundir este eje con el de `tipo`.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, tipo, fecha_desde, fecha_hasta, numero_pedido, "
            "monto_total, monto_pagado) "
            "VALUES (%s,%s,'List Pedidos','listpedidos@test.com','+5491100009002',"
            "'confirmado','estudio','2032-06-10 10:00','2032-06-10 12:00',949902,20000,0)",
            (PEDIDO_STANDALONE_ID, CLIENTE_ID),
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


def _crear_turno(client, numero, monto_total, monto_pagado, estado="confirmado"):
    from database import get_db

    turno_id = PEDIDO_PRINCIPAL_ID + numero
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, tipo, fecha_desde, fecha_hasta, numero_pedido, "
            "monto_total, monto_pagado, pedido_principal_id) "
            "VALUES (%s,%s,'List Pedidos','listpedidos@test.com','+5491100009002',"
            "%s,'estudio','2032-06-02 08:00','2032-06-02 10:00',%s,%s,%s,%s)",
            (turno_id, CLIENTE_ID, estado, numero, monto_total, monto_pagado, PEDIDO_PRINCIPAL_ID),
        )
        conn.commit()
    finally:
        conn.close()
    return turno_id


def test_turno_vinculado_no_aparece_como_fila_propia_en_list_pedidos(client_con_db, setup):
    """Discrimina: sin el filtro, list_pedidos devuelve 2 filas (principal +
    turno) para el mismo evento — con el filtro, solo 1."""
    _crear_turno(client_con_db, 1, 30000, 0)
    r = client_con_db.get("/api/alquileres", params={"q": "listpedidos"})
    assert r.status_code == 200, r.text
    ids = {p["id"] for p in r.json()["items"]}
    assert PEDIDO_PRINCIPAL_ID in ids
    assert PEDIDO_PRINCIPAL_ID + 1 not in ids


def test_turno_standalone_sigue_apareciendo(client_con_db, setup):
    """Guarda contra confundir el eje `pedido_principal_id` con el de `tipo`
    — un turno del Estudio SIN vincular sigue siendo un pedido de primera
    clase."""
    r = client_con_db.get("/api/alquileres", params={"q": "listpedidos"})
    assert r.status_code == 200, r.text
    ids = {p["id"] for p in r.json()["items"]}
    assert PEDIDO_STANDALONE_ID in ids


def test_badge_cuenta_turnos_vinculados_no_cancelados(client_con_db, setup):
    _crear_turno(client_con_db, 1, 30000, 0, estado="confirmado")
    _crear_turno(client_con_db, 2, 15000, 0, estado="cancelado")
    r = client_con_db.get("/api/alquileres", params={"q": "listpedidos"})
    assert r.status_code == 200, r.text
    principal = next(p for p in r.json()["items"] if p["id"] == PEDIDO_PRINCIPAL_ID)
    assert principal["turnos_vinculados_count"] == 1


def test_cuentas_por_cobrar_consolida_saldo_del_turno_en_el_principal(client_con_db, setup):
    """Discrimina: sin la consolidación, el principal (pendiente=40000) y el
    turno (pendiente=30000) aparecerían como 2 filas separadas, o el turno
    directamente no aparecería (oculto sin sumar su plata). Con el fix: 1
    fila con pendiente=70000."""
    _crear_turno(client_con_db, 1, 30000, 0, estado="confirmado")
    r = client_con_db.get("/api/admin/dashboard/uso")
    assert r.status_code == 200, r.text
    por_cobrar = r.json()["por_cobrar"]["items"]
    fila = next((f for f in por_cobrar if f["id"] == PEDIDO_PRINCIPAL_ID), None)
    assert fila is not None, "el pedido principal no aparece en cuentas por cobrar"
    assert fila["pendiente"] == 40000 + 30000
    assert not any(f["id"] == PEDIDO_PRINCIPAL_ID + 1 for f in por_cobrar)


def test_cuentas_por_cobrar_ignora_turno_cancelado(client_con_db, setup):
    _crear_turno(client_con_db, 1, 30000, 0, estado="cancelado")
    r = client_con_db.get("/api/admin/dashboard/uso")
    assert r.status_code == 200, r.text
    por_cobrar = r.json()["por_cobrar"]["items"]
    fila = next((f for f in por_cobrar if f["id"] == PEDIDO_PRINCIPAL_ID), None)
    assert fila is not None
    assert fila["pendiente"] == 40000  # solo el saldo propio del principal


def test_historial_de_cliente_sigue_mostrando_las_2_filas(client_con_db, setup):
    """NO se toca — es información real de la cuenta del cliente, no ruido."""
    _crear_turno(client_con_db, 1, 30000, 0)
    r = client_con_db.get(f"/api/clientes/{CLIENTE_ID}/pedidos")
    assert r.status_code == 200, r.text
    ids = {p["id"] for p in r.json()}
    assert PEDIDO_PRINCIPAL_ID in ids
    assert PEDIDO_PRINCIPAL_ID + 1 in ids
