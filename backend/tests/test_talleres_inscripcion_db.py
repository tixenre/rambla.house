"""`crear_inscripcion` — dedup por email + teléfono a E.164, contra Postgres REAL.

Candado del pedido del dueño (2026-07-12):
  1. Una persona NO se inscribe dos veces a la misma edición → el 2º POST con
     el mismo email devuelve 409 (el 1º y un email distinto pasan).
  2. El teléfono se guarda normalizado a E.164 (`+54...`) vía services.telefono.

Va por HTTP con `TestClient` (no llamada directa: `crear_inscripcion` está
rate-limited y el limiter necesita el app state). `send_email` se mockea para no
mandar mails. Edición con cupos LLENOS → camino lista de espera (no exige
comprobante), suficiente para ejercer el dedup.

OPT-IN y seguro por defecto (RESERVAS_DB_TEST=1 + DATABASE_URL a una base de
prueba). Ids altos + limpieza antes/después.
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

TALLER_ID = 9_800_001
EDICION_ID = 9_800_101
SLUG = "test-dedup-inscripcion-zzq"


def _limpiar(conn):
    conn.execute("DELETE FROM taller_inscripciones WHERE edicion_id = %s", (EDICION_ID,))
    conn.execute("DELETE FROM ediciones_taller WHERE id = %s", (EDICION_ID,))
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    import routes.talleres as t
    from database import get_db, init_db

    # No mandar mails de verdad en el test.
    monkeypatch.setattr(t, "send_email", lambda *a, **k: None)
    monkeypatch.setattr(t, "get_admin_to", lambda: "admin@example.com")

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO talleres (id, slug, nombre) VALUES (%s, %s, %s)",
            (TALLER_ID, SLUG + "-base", "Taller Test"),
        )
        # cupos LLENOS (1/1) → toda inscripción cae a lista de espera (sin comprobante).
        conn.execute(
            "INSERT INTO ediciones_taller "
            "(id, taller_id, slug, fecha_inicio, fecha_fin, cupos_total, cupos_confirmados) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (EDICION_ID, TALLER_ID, SLUG, "2099-01-01", "2099-01-02", 1, 1),
        )
        conn.commit()
    finally:
        conn.close()

    yield TestClient(main.app)

    conn = get_db()
    try:
        _limpiar(conn)
        conn.commit()
    finally:
        conn.close()


def _post(client, email, telefono):
    return client.post(
        f"/api/talleres/{SLUG}/inscripcion",
        json={"nombre": "Ana Prueba", "email": email, "telefono": telefono},
    )


def _telefono_guardado(email):
    from database import get_db

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT telefono FROM taller_inscripciones "
            "WHERE edicion_id = %s AND LOWER(email) = %s",
            (EDICION_ID, email.lower()),
        ).fetchone()
        return row["telefono"] if row else None
    finally:
        conn.close()


def test_primera_inscripcion_ok_y_telefono_en_e164(client):
    r = _post(client, "ana@example.com", "2236898641")
    assert r.status_code == 200, r.text
    assert r.json()["en_lista_espera"] is True  # cupos llenos
    # El teléfono quedó normalizado a E.164, no crudo.
    assert _telefono_guardado("ana@example.com") == "+542236898641"


def test_segunda_inscripcion_mismo_email_es_409(client):
    assert _post(client, "ana@example.com", "2236898641").status_code == 200
    # Mismo email (aunque venga con otra capitalización) → bloqueado.
    dup = _post(client, "ANA@example.com", "+54 9 223 000 0000")
    assert dup.status_code == 409
    assert "email" in dup.json()["detail"].lower()


def test_otro_email_no_se_bloquea(client):
    assert _post(client, "ana@example.com", "2236898641").status_code == 200
    otra = _post(client, "otra@example.com", "2235444704")
    assert otra.status_code == 200
