"""`_anular_pago` (services/alquileres/commands/pagos.py) contra Postgres REAL.

Sin ningún test hoy (hallazgo de auditoría del split CQRS-lite, #1313/#1314) pese
a ser el camino de soft-delete del ledger de pagos (`alquiler_pagos`, la fuente
única de "pagado"). Cubre: anular resta `monto_pagado` (vía
`_recalcular_monto_pagado`), un pago ya anulado da 404 (no re-anula), un
`pago_id` de OTRO pedido da 404 (scoping real, no solo por `id` del pago), y
anular el pago que completaba un `finalizado` lo revierte a `devuelto`.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_anular_pago_db.py -v -m integration
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

CLIENTE_ID = 9_478_100
PEDIDO_A_ID = 9_478_110
PEDIDO_B_ID = 9_478_111


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_pagos WHERE pedido_id IN (%s, %s)",
        (PEDIDO_A_ID, PEDIDO_B_ID),
    )
    conn.execute("DELETE FROM alquileres WHERE id IN (%s, %s)", (PEDIDO_A_ID, PEDIDO_B_ID))
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
            "VALUES (%s,'Anular','Pago','anularpago@test.com','+5491100000030')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, fecha_desde, fecha_hasta, numero_pedido, monto_total) "
            "VALUES (%s,%s,'Anular Pago A','anularpago@test.com','+5491100000030',"
            "'retirado','2032-07-01','2032-07-05',947811,10000)",
            (PEDIDO_A_ID, CLIENTE_ID),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, fecha_desde, fecha_hasta, numero_pedido, monto_total) "
            "VALUES (%s,%s,'Anular Pago B','anularpago@test.com','+5491100000030',"
            "'retirado','2032-07-01','2032-07-05',947812,5000)",
            (PEDIDO_B_ID, CLIENTE_ID),
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


def _fila_pedido(conn, pedido_id):
    return conn.execute(
        "SELECT estado, monto_total, monto_pagado FROM alquileres WHERE id=%s", (pedido_id,)
    ).fetchone()


def _fila_pago(conn, pago_id):
    return conn.execute(
        "SELECT anulado, anulado_por, anulado_at, anulado_motivo FROM alquiler_pagos WHERE id=%s",
        (pago_id,),
    ).fetchone()


def test_anular_resta_el_monto_del_pago_del_total_pagado(client_con_db, setup):
    from database import get_db

    r = client_con_db.post(f"/api/alquileres/{PEDIDO_A_ID}/pagos", json={"monto": 10000})
    assert r.status_code == 201, r.text
    pago_id = client_con_db.get(f"/api/alquileres/{PEDIDO_A_ID}/pagos").json()[0]["id"]

    conn = get_db()
    try:
        assert _fila_pedido(conn, PEDIDO_A_ID)["monto_pagado"] == 10000
    finally:
        conn.close()

    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_A_ID}/pagos/{pago_id}/anular",
        json={"motivo": "Cheque rechazado"},
    )
    assert r.status_code == 200, r.text

    conn = get_db()
    try:
        pedido = _fila_pedido(conn, PEDIDO_A_ID)
        pago = _fila_pago(conn, pago_id)
    finally:
        conn.close()

    assert pedido["monto_pagado"] == 0, "el pago anulado no debe contar en monto_pagado"
    assert pago["anulado"] is True
    assert pago["anulado_por"] is not None
    assert pago["anulado_at"] is not None
    assert pago["anulado_motivo"] == "Cheque rechazado"


def test_anular_sin_motivo_funciona_y_conserva_la_trazabilidad(client_con_db, setup):
    """El motivo es OPCIONAL desde 2026-08 (pedido del dueño: anular un pago es
    deshacer una carga propia, y exigir prosa para corregir un tipeo era fricción
    sin contraparte). Lo que importa se conserva: sigue siendo soft-delete y
    `anulado_por`/`anulado_at` siguen diciendo quién y cuándo."""
    from database import get_db

    client_con_db.post(f"/api/alquileres/{PEDIDO_A_ID}/pagos", json={"monto": 10000})
    pago_id = client_con_db.get(f"/api/alquileres/{PEDIDO_A_ID}/pagos").json()[0]["id"]

    # Sin `motivo` en el body — antes esto daba 400.
    r = client_con_db.post(f"/api/alquileres/{PEDIDO_A_ID}/pagos/{pago_id}/anular", json={})
    assert r.status_code == 200, r.text

    conn = get_db()
    try:
        pedido = _fila_pedido(conn, PEDIDO_A_ID)
        pago = _fila_pago(conn, pago_id)
    finally:
        conn.close()

    assert pedido["monto_pagado"] == 0
    assert pago["anulado"] is True
    assert pago["anulado_motivo"] is None
    assert pago["anulado_por"] is not None, "quién lo anuló se sigue registrando"
    assert pago["anulado_at"] is not None, "cuándo se anuló se sigue registrando"


def test_anular_un_pago_ya_anulado_da_404(client_con_db, setup):
    from database import get_db

    r = client_con_db.post(f"/api/alquileres/{PEDIDO_A_ID}/pagos", json={"monto": 4000})
    assert r.status_code == 201, r.text
    pago_id = client_con_db.get(f"/api/alquileres/{PEDIDO_A_ID}/pagos").json()[0]["id"]

    r1 = client_con_db.post(
        f"/api/alquileres/{PEDIDO_A_ID}/pagos/{pago_id}/anular", json={"motivo": "primero"}
    )
    assert r1.status_code == 200, r1.text

    r2 = client_con_db.post(
        f"/api/alquileres/{PEDIDO_A_ID}/pagos/{pago_id}/anular", json={"motivo": "segundo"}
    )
    assert r2.status_code == 404, r2.text

    conn = get_db()
    try:
        pago = _fila_pago(conn, pago_id)
    finally:
        conn.close()
    # El segundo intento no debe haber pisado el motivo/actor del primero.
    assert pago["anulado_motivo"] == "primero"


def test_pago_id_de_otro_pedido_da_404(client_con_db, setup):
    """El pago existe, pero pertenece al pedido B — pedirlo vía la URL del
    pedido A no debe encontrarlo (scoping real por `pedido_id`, no solo `id`)."""
    from database import get_db

    r = client_con_db.post(f"/api/alquileres/{PEDIDO_B_ID}/pagos", json={"monto": 5000})
    assert r.status_code == 201, r.text
    pago_id_de_b = client_con_db.get(f"/api/alquileres/{PEDIDO_B_ID}/pagos").json()[0]["id"]

    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_A_ID}/pagos/{pago_id_de_b}/anular",
        json={"motivo": "intento cruzado"},
    )
    assert r.status_code == 404, r.text

    conn = get_db()
    try:
        pago = _fila_pago(conn, pago_id_de_b)
        pedido_b = _fila_pedido(conn, PEDIDO_B_ID)
    finally:
        conn.close()
    assert pago["anulado"] is False, "el pago de B no debe haberse anulado por el intento cruzado"
    assert pedido_b["monto_pagado"] == 5000


def test_anular_el_pago_que_completaba_revierte_finalizado_a_devuelto(client_con_db, setup):
    """`_maybe_finalizar` prende `finalizado` solo cuando `devuelto` + pagado
    completo. Si se anula el pago que lo completaba, el pedido deja de estar
    realmente pago — `_anular_pago` debe revertirlo a `devuelto`, no dejarlo
    'finalizado' con saldo pendiente."""
    from database import get_db

    conn = get_db()
    try:
        conn.execute("UPDATE alquileres SET estado='devuelto' WHERE id=%s", (PEDIDO_A_ID,))
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.post(f"/api/alquileres/{PEDIDO_A_ID}/pagos", json={"monto": 10000})
    assert r.status_code == 201, r.text
    pago_id = client_con_db.get(f"/api/alquileres/{PEDIDO_A_ID}/pagos").json()[0]["id"]

    conn = get_db()
    try:
        assert _fila_pedido(conn, PEDIDO_A_ID)["estado"] == "finalizado", (
            "monto_total=10000 pagado completo + devuelto → debería auto-finalizar"
        )
    finally:
        conn.close()

    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_A_ID}/pagos/{pago_id}/anular",
        json={"motivo": "pago revertido por el banco"},
    )
    assert r.status_code == 200, r.text

    conn = get_db()
    try:
        pedido = _fila_pedido(conn, PEDIDO_A_ID)
    finally:
        conn.close()
    assert pedido["estado"] == "devuelto", "no puede quedar 'finalizado' con saldo pendiente"
    assert pedido["monto_pagado"] == 0
