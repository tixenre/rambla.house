"""Borradores de inscripción a un taller (services.talleres_borrador) — candados
contra Postgres REAL. Mirror de carritos_activos para el funnel de talleres
(pedido del dueño, 2026-08-13): heartbeat mientras alguien tipea en el form,
el admin ve a quién no llegó a enviar; se cierra al confirmarse la inscripción
real.

OPT-IN y seguro por defecto (RESERVAS_DB_TEST=1 + DATABASE_URL a una base de
prueba). Ids altos + limpieza antes/después.
"""

import os
import uuid
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

TALLER_ID = 9_860_001
EDICION_ID = 9_860_101
SLUG = "test-borrador-zzq"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM taller_inscripciones_borrador WHERE edicion_id = %s", (EDICION_ID,)
    )
    conn.execute("DELETE FROM taller_inscripciones WHERE edicion_id = %s", (EDICION_ID,))
    conn.execute("DELETE FROM ediciones_taller WHERE id = %s", (EDICION_ID,))
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))


@pytest.fixture
def conn():
    from database import get_db, init_db

    init_db()
    c = get_db()
    try:
        _limpiar(c)
        c.execute(
            "INSERT INTO talleres (id, slug, nombre) VALUES (%s, %s, %s)",
            (TALLER_ID, SLUG + "-base", "Taller Test Borrador"),
        )
        c.execute(
            "INSERT INTO ediciones_taller "
            "(id, taller_id, slug, fecha_inicio, fecha_fin, cupos_total, cupos_confirmados, activo) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)",
            (EDICION_ID, TALLER_ID, SLUG, "2099-01-01", "2099-01-02", 5, 0),
        )
        c.commit()
    finally:
        pass
    yield c
    _limpiar(c)
    c.commit()
    c.close()


def test_heartbeat_crea_y_reescribe_por_session_id(conn):
    from services.talleres_borrador import heartbeat_upsert

    sid = str(uuid.uuid4())
    heartbeat_upsert(conn, sid, EDICION_ID, nombre="Ana", email=None, telefono=None)
    conn.commit()
    heartbeat_upsert(conn, sid, EDICION_ID, nombre="Ana Prueba", email="ana@example.com", telefono="+5491100000000")
    conn.commit()

    rows = conn.execute(
        "SELECT nombre, email, telefono FROM taller_inscripciones_borrador WHERE session_id = %s",
        (sid,),
    ).fetchall()
    assert len(rows) == 1, "el segundo heartbeat actualiza la MISMA fila, no crea otra"
    assert rows[0]["nombre"] == "Ana Prueba"
    assert rows[0]["email"] == "ana@example.com"


def test_marcar_confirmado_cierra_el_funnel(conn):
    from services.talleres_borrador import heartbeat_upsert, marcar_confirmado, listar_borradores_admin

    sid = str(uuid.uuid4())
    heartbeat_upsert(conn, sid, EDICION_ID, nombre="Ana", email="ana@example.com", telefono=None)
    conn.commit()
    assert listar_borradores_admin(conn, EDICION_ID)["total"] == 1

    marcar_confirmado(conn, sid, EDICION_ID)
    conn.commit()
    assert listar_borradores_admin(conn, EDICION_ID)["total"] == 0, (
        "un borrador confirmado ya no aparece como 'sin enviar'"
    )


def test_marcar_confirmado_sin_heartbeat_previo_no_rompe(conn):
    """session_id que el módulo nunca vio (form viejo sin heartbeat, o
    heartbeat que falló) — no debe tirar excepción."""
    from services.talleres_borrador import marcar_confirmado

    marcar_confirmado(conn, str(uuid.uuid4()), EDICION_ID)
    conn.commit()  # no explota


def test_marcar_confirmado_antes_del_heartbeat_no_deja_fantasma(conn):
    """Race real (bug 2026-08-20): el heartbeat del form viaja por `fetch`
    sin `await` — puede llegar a la base DESPUÉS de que /inscripcion ya
    confirmó (red lenta). Simulamos el orden invertido: confirmar ANTES de
    que exista cualquier fila de heartbeat para ese session_id."""
    from services.talleres_borrador import heartbeat_upsert, marcar_confirmado, listar_borradores_admin

    sid = str(uuid.uuid4())
    marcar_confirmado(
        conn, sid, EDICION_ID, nombre="Ariana", email="ariana@example.com", telefono="+5492984153350"
    )
    conn.commit()
    assert listar_borradores_admin(conn, EDICION_ID)["total"] == 0

    # El heartbeat que venía "en vuelo" llega recién ahora, después de confirmar.
    heartbeat_upsert(
        conn, sid, EDICION_ID, nombre="Ariana", email="ariana@example.com", telefono="+5492984153350"
    )
    conn.commit()

    assert listar_borradores_admin(conn, EDICION_ID)["total"] == 0, (
        "un heartbeat tardío no debe resucitar como 'sin enviar' una inscripción ya confirmada"
    )


def test_listar_borradores_admin_kpis(conn):
    from services.talleres_borrador import heartbeat_upsert, listar_borradores_admin

    heartbeat_upsert(conn, str(uuid.uuid4()), EDICION_ID, nombre="Sin contacto", email=None, telefono=None)
    heartbeat_upsert(conn, str(uuid.uuid4()), EDICION_ID, nombre="Con mail", email="con@example.com", telefono=None)
    conn.commit()

    d = listar_borradores_admin(conn, EDICION_ID)
    assert d["total"] == 2
    assert d["con_contacto"] == 1
    assert d["abandonados"] == 0


def test_heartbeat_endpoint_end_to_end(monkeypatch):
    """Vía HTTP real: heartbeat guarda el borrador → aparece en el admin;
    enviar la inscripción real con el mismo session_id lo cierra."""
    from fastapi.testclient import TestClient
    import main
    import routes.talleres as t
    from database import get_db, init_db

    # admin_listar_borradores se llama directo (no vía HTTP, no hay cookie de
    # sesión real acá) — mismo patrón que el resto de los tests de talleres.
    monkeypatch.setattr(t, "require_admin", lambda r: None)

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO talleres (id, slug, nombre) VALUES (%s, %s, %s)",
            (TALLER_ID, SLUG + "-http", "Taller Test Borrador HTTP"),
        )
        conn.execute(
            "INSERT INTO ediciones_taller "
            "(id, taller_id, slug, fecha_inicio, fecha_fin, cupos_total, cupos_confirmados, activo) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)",
            (EDICION_ID, TALLER_ID, SLUG, "2099-01-01", "2099-01-02", 5, 0),
        )
        conn.commit()
    finally:
        conn.close()

    orig_send_email = t.send_email
    t.send_email = lambda *a, **k: None
    orig_get_admin_tos = t.get_admin_tos
    t.get_admin_tos = lambda: ["admin@example.com"]
    try:
        client = TestClient(main.app)
        sid = str(uuid.uuid4())

        r = client.post(
            f"/api/talleres/{SLUG}/inscripcion/heartbeat",
            json={"session_id": sid, "nombre": "Bruno", "email": "bruno@example.com"},
        )
        assert r.status_code == 200, r.text

        admin_list = t.admin_listar_borradores(EDICION_ID, None)
        assert admin_list["total"] == 1
        assert admin_list["borradores"][0]["email"] == "bruno@example.com"

        r2 = client.post(
            f"/api/talleres/{SLUG}/inscripcion",
            json={
                "nombre": "Bruno",
                "email": "bruno@example.com",
                "telefono": "2236898641",
                "session_id": sid,
            },
        )
        assert r2.status_code == 200, r2.text

        admin_list_after = t.admin_listar_borradores(EDICION_ID, None)
        assert admin_list_after["total"] == 0, (
            "confirmar la inscripción real cierra el borrador del funnel"
        )
    finally:
        t.send_email = orig_send_email
        t.get_admin_tos = orig_get_admin_tos
        conn = get_db()
        try:
            _limpiar(conn)
            conn.commit()
        finally:
            conn.close()


def test_heartbeat_slug_invalido_no_rompe():
    """Slug que no existe → 200 {"ok": true} silencioso, no 404 — es
    telemetría, no una acción del usuario que deba fallar visiblemente."""
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app)
    r = client.post(
        "/api/talleres/no-existe-zzq/inscripcion/heartbeat",
        json={"session_id": str(uuid.uuid4()), "nombre": "X"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
