"""Hub público de institución (`GET /instituciones/{slug}`) — candados
contra Postgres REAL: el dedupe por `taller_id` no debe mostrar 2 ediciones
del mismo taller como 2 entradas del switcher (bug real 2026-08-19, ver
docstring de `get_institucion` en `routes/talleres.py`: "no mezclar las
ediciones" — nombre duplicado en el título grande + card repetida para el
mismo taller).

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
INSTITUCION_ID = 9_820_001
SLUG_TALLER = "test-hub-dedupe-zzq"
SLUG_INSTITUCION = "test-hub-institucion-zzq"


def _limpiar(conn):
    conn.execute("DELETE FROM taller_instituciones WHERE taller_id = %s", (TALLER_ID,))
    conn.execute(
        "DELETE FROM clases_taller WHERE edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s)",
        (TALLER_ID,),
    )
    conn.execute("DELETE FROM ediciones_taller WHERE taller_id = %s", (TALLER_ID,))
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))
    conn.execute("DELETE FROM instituciones WHERE id = %s", (INSTITUCION_ID,))


@pytest.fixture
def hub_base(monkeypatch):
    import routes.talleres as t
    from database import get_db, init_db

    monkeypatch.setattr(t, "require_admin", lambda r: None)
    monkeypatch.setattr(t, "send_email", lambda *a, **k: None)
    monkeypatch.setattr(t, "get_admin_tos", lambda: ["admin@example.com"])

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_ID, SLUG_TALLER, SLUG_TALLER, "Taller hub dedupe"),
        )
        conn.execute(
            "INSERT INTO instituciones (id, nombre, slug) VALUES (%s, %s, %s)",
            (INSTITUCION_ID, "Institución hub dedupe", SLUG_INSTITUCION),
        )
        conn.execute(
            "INSERT INTO taller_instituciones (taller_id, institucion_id) VALUES (%s, %s)",
            (TALLER_ID, INSTITUCION_ID),
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


def _crear_edicion(t, numero, fecha, activo=True):
    body = t.EdicionCreateBody(
        clases=[
            t.ClaseBody(
                fecha=fecha,
                hora_inicio_min=510,
                hora_fin_min=750,
                titulo="Clase 1",
                descripcion="Temario 1",
            ),
        ],
        numero_edicion=numero,
        activo=activo,
    )
    return t.admin_create_edicion(TALLER_ID, body, None)


def test_hub_dedupea_2_ediciones_del_mismo_taller(hub_base):
    """2 ediciones ACTIVAS del mismo taller_id (cohortes con fechas
    distintas) deben aparecer como 1 sola entrada en el switcher del hub —
    no 2. Se queda con la de `fecha_inicio` MÁS PRÓXIMA como representante,
    tal como documenta `get_institucion`."""
    t = hub_base
    _crear_edicion(t, numero=1, fecha="2099-01-10")
    _crear_edicion(t, numero=2, fecha="2099-06-10")

    resp = t.get_institucion(SLUG_INSTITUCION)

    entradas = [x for x in resp["talleres"] if x["taller_id"] == TALLER_ID]
    assert len(entradas) == 1, (
        f"esperaba 1 sola entrada para el taller (dedupe por taller_id), encontré {len(entradas)}"
    )
    assert entradas[0]["fecha_inicio"] == "2099-01-10", (
        "el hub debe representar al taller con la edición de fecha_inicio más próxima"
    )


def test_hub_ignora_edicion_inactiva(hub_base):
    """Una edición `activo=False` (borrador) no cuenta para el switcher —
    mismo filtro `e.activo = TRUE` que ya usa `list_talleres`."""
    t = hub_base
    _crear_edicion(t, numero=1, fecha="2099-01-10", activo=False)
    _crear_edicion(t, numero=2, fecha="2099-06-10", activo=True)

    resp = t.get_institucion(SLUG_INSTITUCION)

    entradas = [x for x in resp["talleres"] if x["taller_id"] == TALLER_ID]
    assert len(entradas) == 1
    assert entradas[0]["fecha_inicio"] == "2099-06-10"
