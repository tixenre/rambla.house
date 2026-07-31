"""Escuela v2 F3 — candados contra Postgres REAL: instructores como entidad,
mini-CRUD, N↔N con talleres, 409 al borrar vinculado.

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

TALLER_ID = 9_820_001
SLUG = "test-f3-instructores-zzq"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM taller_instructores WHERE taller_id = %s", (TALLER_ID,)
    )
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))
    conn.execute(
        "DELETE FROM instructores WHERE nombre LIKE 'Test F3 %%'"
    )


@pytest.fixture
def taller_base(monkeypatch):
    import routes.talleres as t
    from database import get_db, init_db

    monkeypatch.setattr(t, "require_admin", lambda r: None)

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_ID, SLUG, SLUG, "Taller F3"),
        )
        conn.commit()
    finally:
        conn.close()

    yield t

    conn = get_db()
    try:
        _limpiar(conn)
        conn.commit()
    finally:
        conn.close()


def test_crear_instructor_y_vincular(taller_base):
    t = taller_base
    creado = t.admin_create_instructor(
        t.InstructorBody(nombre="Test F3 Uno", rol="Director"), None
    )
    assert creado["nombre"] == "Test F3 Uno"
    assert creado["id"] > 0

    resp = t.admin_set_taller_instructores(
        TALLER_ID, t.TallerInstructoresBody(instructor_ids=[creado["id"]]), None
    )
    assert [i["nombre"] for i in resp["instructores"]] == ["Test F3 Uno"]


def test_taller_con_varios_instructores_orden(taller_base):
    """Un taller con N instructores respeta el orden pedido."""
    t = taller_base
    a = t.admin_create_instructor(t.InstructorBody(nombre="Test F3 A"), None)
    b = t.admin_create_instructor(t.InstructorBody(nombre="Test F3 B"), None)

    t.admin_set_taller_instructores(
        TALLER_ID, t.TallerInstructoresBody(instructor_ids=[b["id"], a["id"]]), None
    )
    from database import get_db
    with get_db() as conn:
        instructores = t._get_instructores_taller(conn, TALLER_ID)
    assert [i["nombre"] for i in instructores] == ["Test F3 B", "Test F3 A"]

    # Reemplazo: ahora solo "a" — "b" queda desvinculado (no borrado).
    t.admin_set_taller_instructores(
        TALLER_ID, t.TallerInstructoresBody(instructor_ids=[a["id"]]), None
    )
    with get_db() as conn:
        instructores = t._get_instructores_taller(conn, TALLER_ID)
    assert [i["nombre"] for i in instructores] == ["Test F3 A"]


def test_mismo_instructor_en_dos_talleres(taller_base):
    """Caso Filmar: un instructor da varios talleres (Principiante + Avanzado)."""
    t = taller_base
    otro_taller_id = TALLER_ID + 1
    from database import get_db
    with get_db() as conn:
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (otro_taller_id, SLUG + "-b", SLUG + "-b", "Taller F3 B"),
        )
        conn.commit()
    try:
        ins = t.admin_create_instructor(t.InstructorBody(nombre="Test F3 Multi"), None)
        t.admin_set_taller_instructores(
            TALLER_ID, t.TallerInstructoresBody(instructor_ids=[ins["id"]]), None
        )
        t.admin_set_taller_instructores(
            otro_taller_id, t.TallerInstructoresBody(instructor_ids=[ins["id"]]), None
        )
        with get_db() as conn:
            uno = t._get_instructores_taller(conn, TALLER_ID)
            dos = t._get_instructores_taller(conn, otro_taller_id)
        assert uno[0]["id"] == dos[0]["id"] == ins["id"]
    finally:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM taller_instructores WHERE taller_id = %s", (otro_taller_id,)
            )
            conn.execute("DELETE FROM talleres WHERE id = %s", (otro_taller_id,))
            conn.commit()


def test_delete_bloqueado_si_vinculado(taller_base):
    from fastapi import HTTPException
    t = taller_base
    ins = t.admin_create_instructor(t.InstructorBody(nombre="Test F3 Vinculado"), None)
    t.admin_set_taller_instructores(
        TALLER_ID, t.TallerInstructoresBody(instructor_ids=[ins["id"]]), None
    )
    with pytest.raises(HTTPException) as exc:
        t.admin_delete_instructor(ins["id"], None)
    assert exc.value.status_code == 409

    # Desvincular → ahora sí se puede borrar.
    t.admin_set_taller_instructores(TALLER_ID, t.TallerInstructoresBody(instructor_ids=[]), None)
    result = t.admin_delete_instructor(ins["id"], None)
    assert result["ok"] is True


def test_set_instructores_rechaza_id_inexistente(taller_base):
    from fastapi import HTTPException
    t = taller_base
    with pytest.raises(HTTPException) as exc:
        t.admin_set_taller_instructores(
            TALLER_ID, t.TallerInstructoresBody(instructor_ids=[999_999_999]), None
        )
    assert exc.value.status_code == 400


def test_concepto_admin_incluye_instructores(taller_base):
    """GET /admin/talleres (list, requiere >=1 edición) devuelve instructores
    anidados en el concepto."""
    t = taller_base
    from database import get_db
    with get_db() as conn:
        conn.execute(
            "INSERT INTO ediciones_taller (taller_id, numero_edicion, slug, "
            "fecha_inicio, fecha_fin) VALUES (%s, 1, %s, '2099-01-01', '2099-01-02')",
            (TALLER_ID, SLUG + "-ed1"),
        )
        conn.commit()

    ins = t.admin_create_instructor(t.InstructorBody(nombre="Test F3 Listado"), None)
    t.admin_set_taller_instructores(
        TALLER_ID, t.TallerInstructoresBody(instructor_ids=[ins["id"]]), None
    )
    conceptos = t.admin_list_talleres(None)
    match = [c for c in conceptos if c["id"] == TALLER_ID]
    assert len(match) == 1
    assert [i["nombre"] for i in match[0]["instructores"]] == ["Test F3 Listado"]
