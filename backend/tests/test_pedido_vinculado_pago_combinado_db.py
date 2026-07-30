"""Pago combinado: un pedido principal + sus turnos del Estudio vinculados
(#1308 — "un pago, reparte solo", decisión confirmada por el dueño) contra
Postgres REAL.

Un solo "Registrar pago" en el pedido principal reparte el monto: primero
satura la resta del PRINCIPAL, después cada turno vinculado por
`fecha_desde` ascendente; un turno `cancelado` queda excluido (no participa,
no bloquea el resto); el sobrante se acredita siempre en el PRINCIPAL. Cada
parte del reparto es una fila REAL de `alquiler_pagos` con su `pedido_id`
propio — nunca una tabla/concepto de "pago compartido".

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_pedido_vinculado_pago_combinado_db.py -v -m integration
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

CLIENTE_ID = 9_478_002
PEDIDO_PRINCIPAL_ID = 9_478_010


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_pagos WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_id = %s OR id = %s)",
        (CLIENTE_ID, PEDIDO_PRINCIPAL_ID),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE cliente_id = %s OR id = %s",
        (CLIENTE_ID, PEDIDO_PRINCIPAL_ID),
    )
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
            "VALUES (%s,'Pago','Combinado','pagocombinado@test.com','+5491100000020')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, fecha_desde, fecha_hasta, numero_pedido, monto_total) "
            "VALUES (%s,%s,'Pago Combinado','pagocombinado@test.com','+5491100000020',"
            "'confirmado','2032-06-01','2032-06-05',947801,50000)",
            (PEDIDO_PRINCIPAL_ID, CLIENTE_ID),
        )
        conn.execute(
            "UPDATE estudio SET precio_hora=10000, buffer_horas=0, min_horas=1, "
            "open_hour=0, close_hour=24, anticipacion_min_horas=0 WHERE id=1"
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


def _crear_turno(client, fecha, espacio_monto, estado="confirmado"):
    r = client.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": fecha, "start": "10:00", "horas": 1,
            "pedido_principal_id": PEDIDO_PRINCIPAL_ID,
            "estado": estado,
            "espacio_monto": espacio_monto,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _fila(conn, pedido_id):
    return conn.execute(
        "SELECT monto_total, monto_pagado FROM alquileres WHERE id=%s", (pedido_id,)
    ).fetchone()


def test_pago_combinado_prioriza_principal_luego_turnos_por_fecha(client_con_db, setup):
    """Principal resta=50000; turno A (fecha más próxima) resta=30000; turno
    B (fecha más lejana) resta=20000. Pagar 60000 → principal saldado
    (50000), turno A recibe el remanente (10000, parcial), turno B nada.
    Discrimina D2: con el orden invertido, turno B recibiría los 10000."""
    from database import get_db

    turno_a = _crear_turno(client_con_db, "2032-06-02", espacio_monto=30000)
    turno_b = _crear_turno(client_con_db, "2032-06-10", espacio_monto=20000)

    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}/pagos-combinado", json={"monto": 60000}
    )
    assert r.status_code == 201, r.text

    conn = get_db()
    try:
        principal = _fila(conn, PEDIDO_PRINCIPAL_ID)
        a = _fila(conn, turno_a)
        b = _fila(conn, turno_b)
    finally:
        conn.close()

    assert principal["monto_pagado"] == 50000
    assert a["monto_pagado"] == 10000, "turno A (más próximo) debe recibir el remanente"
    assert b["monto_pagado"] == 0, "turno B (más lejano) no debe recibir nada"


def test_pago_combinado_excedente_se_acredita_al_principal(client_con_db, setup):
    """Principal y turno YA saldados de antes (vía /pagos real); un pago
    combinado adicional es puro excedente — tiene que quedar acreditado en
    el PRINCIPAL, nunca en el turno."""
    from database import get_db

    turno = _crear_turno(client_con_db, "2032-06-02", espacio_monto=5000)

    r1 = client_con_db.post(f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}/pagos", json={"monto": 50000})
    assert r1.status_code == 201, r1.text
    r2 = client_con_db.post(f"/api/alquileres/{turno}/pagos", json={"monto": 5000})
    assert r2.status_code == 201, r2.text

    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}/pagos-combinado",
        json={"monto": 1000, "concepto": "Cobro de más"},
    )
    assert r.status_code == 201, r.text

    conn = get_db()
    try:
        pagos_principal = conn.execute(
            "SELECT monto, concepto FROM alquiler_pagos WHERE pedido_id=%s ORDER BY id",
            (PEDIDO_PRINCIPAL_ID,),
        ).fetchall()
        turno_pagado = _fila(conn, turno)["monto_pagado"]
    finally:
        conn.close()

    assert turno_pagado == 5000, "el turno no debe recibir el excedente"
    excedentes = [p for p in pagos_principal if "(excedente)" in (p["concepto"] or "")]
    assert len(excedentes) == 1
    assert excedentes[0]["monto"] == 1000


def test_pago_combinado_ignora_turno_cancelado_sin_bloquear_el_resto(client_con_db, setup):
    """Un turno cancelado (resta=20000 si no estuviera cancelado) NO debe
    participar del reparto ni bloquear el resto. Pagar 50000 (30000 del
    principal + 20000 que, sin el filtro D4, se intentarían aplicar al
    turno cancelado y tirarían 400) — el resultado esperado es que el
    sobrante se acredite al PRINCIPAL como excedente, sin tocar el turno."""
    from database import get_db

    conn0 = get_db()
    try:
        conn0.execute(
            "UPDATE alquileres SET monto_total=30000 WHERE id=%s", (PEDIDO_PRINCIPAL_ID,)
        )
        conn0.commit()
    finally:
        conn0.close()

    turno = _crear_turno(client_con_db, "2032-06-02", espacio_monto=20000, estado="confirmado")
    r_cancel = client_con_db.patch(f"/api/alquileres/{turno}", json={"estado": "cancelado"})
    assert r_cancel.status_code == 200, r_cancel.text

    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}/pagos-combinado", json={"monto": 50000}
    )
    assert r.status_code == 201, r.text

    conn = get_db()
    try:
        principal = _fila(conn, PEDIDO_PRINCIPAL_ID)
        turno_fila = _fila(conn, turno)
    finally:
        conn.close()

    assert principal["monto_pagado"] == 50000, "30000 propios + 20000 de excedente"
    assert turno_fila["monto_pagado"] == 0, "el turno cancelado no debe recibir nada"


def test_pago_combinado_inserta_filas_reales_por_pedido_id(client_con_db, setup):
    """Cada parte del reparto es una fila REAL en alquiler_pagos con su
    pedido_id propio — nunca un concepto/tabla de 'pago compartido'."""
    from database import get_db

    turno = _crear_turno(client_con_db, "2032-06-02", espacio_monto=20000)

    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}/pagos-combinado", json={"monto": 60000}
    )
    assert r.status_code == 201, r.text

    conn = get_db()
    try:
        pagos_principal = conn.execute(
            "SELECT monto FROM alquiler_pagos WHERE pedido_id=%s", (PEDIDO_PRINCIPAL_ID,)
        ).fetchall()
        pagos_turno = conn.execute(
            "SELECT monto FROM alquiler_pagos WHERE pedido_id=%s", (turno,)
        ).fetchall()
    finally:
        conn.close()

    assert len(pagos_principal) == 1 and pagos_principal[0]["monto"] == 50000
    assert len(pagos_turno) == 1 and pagos_turno[0]["monto"] == 10000


def test_pago_combinado_sin_turnos_igual_a_pago_individual(client_con_db, setup):
    """Regresión: sin turnos vinculados, /pagos-combinado se comporta
    byte-idéntico a /pagos (superset seguro, no un camino paralelo)."""
    from database import get_db

    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}/pagos-combinado",
        json={"monto": 20000, "concepto": "Seña"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["monto_pagado"] == 20000

    conn = get_db()
    try:
        principal = _fila(conn, PEDIDO_PRINCIPAL_ID)
        pagos = conn.execute(
            "SELECT monto, concepto FROM alquiler_pagos WHERE pedido_id=%s",
            (PEDIDO_PRINCIPAL_ID,),
        ).fetchall()
    finally:
        conn.close()

    assert principal["monto_pagado"] == 20000
    assert len(pagos) == 1
    assert pagos[0]["monto"] == 20000
    assert pagos[0]["concepto"] == "Seña"
