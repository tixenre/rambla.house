"""`clientes.email` es UNIQUE — Postgres permite múltiples NULL pero NO
múltiples "" (string vacío cuenta como valor real para la restricción).

`ClienteAutocomplete` (el picker rápido de ficha, usado desde el pedido) no
pide email al crear — mandaba `email=""`, así que el PRIMER cliente creado
sin email pasaba bien y CUALQUIER segundo cliente creado sin email (desde
cualquier pedido) chocaba contra esa fila con un 400 genérico "ya existe un
registro con ese valor" — encontrado en vivo por el dueño (pedido #456/457,
intentando crear la ficha de una clienta ya cargada a mano en un pedido
viejo). `crear()`/`actualizar()` ahora guardan `None` en vez de `""`.

OPT-IN y SEGURO POR DEFECTO (mismo patrón que test_clientes_update_db.py):
se saltea salvo RESERVAS_DB_TEST=1 + DATABASE_URL a una base de prueba.
"""
import os
from urllib.parse import urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_OPT_IN = os.getenv("RESERVAS_DB_TEST") == "1"
_DB_URL = os.getenv("DATABASE_URL", "")
_DB_NAME = urlparse(_DB_URL).path.lstrip("/") if _DB_URL else ""


def _looks_like_test_db() -> bool:
    return bool(_DB_NAME) and "test" in _DB_NAME.lower()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _OPT_IN, reason="opt-in: setear RESERVAS_DB_TEST=1 + DATABASE_URL a una base de prueba"
    ),
    pytest.mark.skipif(
        _OPT_IN and not _looks_like_test_db(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]


def _client() -> TestClient:
    from routes.clientes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def admin_cookie(monkeypatch):
    from auth.session import signer

    monkeypatch.setattr("auth.queries.sessions.is_active", lambda jti: {"jti": jti})
    payload = {"email": "admin@test.com", "role": "admin", "jti": "clientes-email-vacio-db"}
    return {"session": signer.dumps(payload)}


def test_dos_clientes_sin_email_no_colisionan(admin_cookie):
    """El escenario real: crear una ficha con el picker rápido (sin email) NO
    puede fallar solo porque ya existe OTRO cliente también sin email."""
    from database import get_db, init_db

    init_db()
    c = _client()
    ids: list[int] = []
    try:
        r1 = c.post(
            "/api/clientes", json={"nombre": "Denise", "apellido": "Laub"}, cookies=admin_cookie
        )
        assert r1.status_code == 201, r1.text
        ids.append(r1.json()["id"])
        assert r1.json()["email"] is None

        r2 = c.post(
            "/api/clientes", json={"nombre": "Otra", "apellido": "Persona"}, cookies=admin_cookie
        )
        assert r2.status_code == 201, r2.text
        ids.append(r2.json()["id"])
        assert r2.json()["email"] is None
    finally:
        if ids:
            with get_db() as conn:
                with conn.transaction():
                    conn.execute(
                        "DELETE FROM clientes WHERE id = ANY(%s)", (ids,)
                    )


def test_vaciar_email_en_edicion_no_colisiona(admin_cookie):
    """Mismo criterio al editar: blanquear el email de un cliente no puede
    chocar contra otro cliente que también tiene el email en blanco."""
    from database import get_db, init_db

    init_db()
    c = _client()
    ids: list[int] = []
    try:
        with get_db() as conn:
            with conn.transaction():
                sin_email_id = conn.insert_returning(
                    "INSERT INTO clientes (nombre, apellido, email) VALUES (%s,%s,NULL)",
                    ("Ya", "SinEmail"),
                )
                con_email_id = conn.insert_returning(
                    "INSERT INTO clientes (nombre, apellido, email) VALUES (%s,%s,%s)",
                    ("Con", "Email", "con-email-vaciar-test@example.com"),
                )
        ids = [sin_email_id, con_email_id]

        r = c.patch(
            f"/api/clientes/{con_email_id}", json={"email": ""}, cookies=admin_cookie
        )
        assert r.status_code == 200, r.text
        assert r.json()["email"] is None
    finally:
        if ids:
            with get_db() as conn:
                with conn.transaction():
                    conn.execute("DELETE FROM clientes WHERE id = ANY(%s)", (ids,))
