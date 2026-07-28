"""Cascada de estado del pedido principal hacia sus turnos del Estudio
vinculados (#1308 — "avanzan juntos", decisión confirmada por el dueño)
contra Postgres REAL.

Mover el estado del pedido PRINCIPAL empuja a cada turno vinculado
(`pedido_principal_id`) al MISMO paso de `FLOW`, pero solo hacia adelante —
un turno ya más avanzado no retrocede, y un destino fuera de `FLOW`
(cancelado/borrador) no cascada en absoluto. Si un turno puntual no puede
avanzar (bloqueado por una validación de negocio), el principal NO se
revierte — queda en `turnos_vinculados_sin_avanzar` como advertencia.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_pedido_vinculado_cascada_estado_db.py -v -m integration
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

EQ_ID = 9_477_001
CLIENTE_ID = 9_477_002
PEDIDO_PRINCIPAL_ID = 9_477_010


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_id = %s OR id = %s)",
        (CLIENTE_ID, PEDIDO_PRINCIPAL_ID),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE cliente_id = %s OR id = %s",
        (CLIENTE_ID, PEDIDO_PRINCIPAL_ID),
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
            "VALUES (%s,'Cascada','Estado','cascada@test.com','+5491100000010')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada) VALUES (%s,%s,5,1000)",
            (EQ_ID, "Equipo test (cascada estado)"),
        )
        # El pedido PRINCIPAL: alquiler normal (tipo='diaria', default), con
        # al menos un ítem — hace falta para poder avanzar a confirmado/
        # retirado (`ESTADOS_REQUIEREN_FECHAS` exige equipos cargados).
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, fecha_desde, fecha_hasta, numero_pedido) "
            "VALUES (%s,%s,'Cascada Estado','cascada@test.com','+5491100000010',"
            "'solicitado','2031-06-01','2031-06-05',947701)",
            (PEDIDO_PRINCIPAL_ID, CLIENTE_ID),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada) "
            "VALUES (%s,%s,1,1000)",
            (PEDIDO_PRINCIPAL_ID, EQ_ID),
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


def _crear_turno(client, fecha, estado="solicitado"):
    r = client.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": fecha, "start": "10:00", "horas": 1,
            "pedido_principal_id": PEDIDO_PRINCIPAL_ID,
            "estado": estado,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _estado_de(conn, pedido_id):
    return conn.execute(
        "SELECT estado FROM alquileres WHERE id=%s", (pedido_id,)
    ).fetchone()["estado"]


def test_cascada_avanza_turno_al_mismo_estado_que_el_principal(client_con_db, setup):
    """Discrimina: sin la cascada, el turno se queda en 'solicitado' pese a
    que el principal avanzó a 'confirmado'."""
    from database import get_db

    turno_id = _crear_turno(client_con_db, "2031-06-02", estado="solicitado")

    r = client_con_db.patch(f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}", json={"estado": "confirmado"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "confirmado"

    conn = get_db()
    try:
        assert _estado_de(conn, turno_id) == "confirmado"
    finally:
        conn.close()


def test_cascada_no_retrocede_un_turno_mas_avanzado(client_con_db, setup):
    """El turno arranca 'retirado' (más avanzado); el principal retrocede
    hasta 'solicitado' (retirado→solicitado es legal en TRANSICIONES) — sin
    el guard `idx_actual >= idx_destino` este assert fallaría (el turno
    volvería a 'solicitado' junto con el principal)."""
    from database import get_db

    turno_id = _crear_turno(client_con_db, "2031-06-02", estado="retirado")

    client_con_db.patch(f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}", json={"estado": "confirmado"})
    client_con_db.patch(f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}", json={"estado": "retirado"})
    r = client_con_db.patch(f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}", json={"estado": "solicitado"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "solicitado"

    conn = get_db()
    try:
        assert _estado_de(conn, turno_id) == "retirado", "el turno no debería retroceder"
    finally:
        conn.close()


def test_cascada_ignora_cancelado_del_principal(client_con_db, setup):
    """D6: 'cancelado' no está en FLOW — no cascada (mismo código que
    ignoraría 'borrador', ambos fuera de FLOW por el mismo
    `if estado_nuevo not in FLOW: return []`)."""
    from database import get_db

    turno_id = _crear_turno(client_con_db, "2031-06-02", estado="solicitado")

    r = client_con_db.patch(f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}", json={"estado": "cancelado"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "cancelado"

    conn = get_db()
    try:
        assert _estado_de(conn, turno_id) == "solicitado", "un destino fuera de FLOW no debe cascadear"
    finally:
        conn.close()


def test_cascada_turno_bloqueado_no_revierte_al_principal(client_con_db, setup):
    """Un turno sin ítems (estado anómalo simulado con un DELETE directo) no
    puede pasar a 'confirmado' (`ESTADOS_REQUIEREN_FECHAS` exige equipos
    cargados) — el principal SÍ avanza igual (D5: parcial-con-warning, nunca
    revierte la transición que sí se pidió y sí es válida)."""
    from database import get_db

    turno_id = _crear_turno(client_con_db, "2031-06-02", estado="solicitado")

    conn = get_db()
    try:
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id=%s", (turno_id,))
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.patch(f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}", json={"estado": "confirmado"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "confirmado", "el principal no debe revertirse por un turno bloqueado"

    fallidos = r.json().get("turnos_vinculados_sin_avanzar") or []
    assert any(f["turno_id"] == turno_id and f["error"] for f in fallidos), fallidos

    conn = get_db()
    try:
        assert _estado_de(conn, turno_id) == "solicitado", "el turno no debe forzarse pese al error"
    finally:
        conn.close()


def test_cascada_no_sube_de_un_turno_al_principal(client_con_db, setup):
    """Transicionar un turno DIRECTO no debe mover al principal — discrimina
    una implementación que confunda 'cascada a los hijos' con 'cascada al
    padre' (ej. leer `pedido_principal_id` de la fila transicionada en vez de
    buscar filas que APUNTEN a ella)."""
    from database import get_db

    turno_id = _crear_turno(client_con_db, "2031-06-02", estado="solicitado")

    r = client_con_db.patch(f"/api/alquileres/{turno_id}", json={"estado": "confirmado"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "confirmado"

    conn = get_db()
    try:
        assert _estado_de(conn, PEDIDO_PRINCIPAL_ID) == "solicitado", (
            "transicionar un turno no debe mover al pedido principal"
        )
    finally:
        conn.close()


def test_cascada_multiples_turnos_resultados_mixtos(client_con_db, setup):
    """2 turnos vinculados: uno sano avanza junto con el principal, el otro
    (sin ítems) no — un solo call, ambos resultados verificados."""
    from database import get_db

    turno_ok_id = _crear_turno(client_con_db, "2031-06-02", estado="solicitado")
    turno_fail_id = _crear_turno(client_con_db, "2031-06-03", estado="solicitado")

    conn = get_db()
    try:
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id=%s", (turno_fail_id,))
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.patch(f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}", json={"estado": "confirmado"})
    assert r.status_code == 200, r.text

    fallidos = {f["turno_id"] for f in (r.json().get("turnos_vinculados_sin_avanzar") or [])}
    assert turno_fail_id in fallidos
    assert turno_ok_id not in fallidos

    conn = get_db()
    try:
        assert _estado_de(conn, turno_ok_id) == "confirmado"
        assert _estado_de(conn, turno_fail_id) == "solicitado"
    finally:
        conn.close()
