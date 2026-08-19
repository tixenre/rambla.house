"""GET /instituciones/{slug} incluye `taller_hermano` en cada taller, contra
Postgres REAL. Bug real (2026-08-19): `get_institucion` se construyó copiando
el shape de `list_talleres` (sin `taller_hermano`, correcto en ese momento —
el hub todavía mostraba cada taller apilado completo) pero el pedido del
dueño mutó a "hero compartido + solo el taller activo abajo"
(`dedupHermanos` en el front), que SÍ necesita `taller_hermano` para
detectar el par — el endpoint quedó desactualizado silenciosamente: no
rompía nada, solo nunca deduplicaba (el front veía `taller_hermano:
undefined` en los 2 talleres y renderizaba las 2 páginas completas
apiladas). Este test fija el contrato: si 2 talleres de una misma
institución son hermanos entre sí, el endpoint tiene que devolver el campo
poblado y simétrico en ambos, igual que ya hace `/talleres/{slug}`.

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

TALLER_A = 9_830_001  # menor id -> siempre "principal"
TALLER_B = 9_830_002  # mayor id -> siempre "secundario"
INSTITUCION_ID = 9_830_003


def _limpiar(conn):
    conn.execute(
        "DELETE FROM taller_instituciones WHERE taller_id IN (%s, %s)", (TALLER_A, TALLER_B)
    )
    conn.execute("DELETE FROM instituciones WHERE id = %s", (INSTITUCION_ID,))
    conn.execute(
        "DELETE FROM ediciones_taller WHERE taller_id IN (%s, %s)", (TALLER_A, TALLER_B)
    )
    conn.execute("DELETE FROM talleres WHERE id IN (%s, %s)", (TALLER_A, TALLER_B))


@pytest.fixture
def institucion_con_par_hermano():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_A, "test-inst-hermano-a-zzq", "test-inst-hermano-a-zzq", "Taller A"),
        )
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_B, "test-inst-hermano-b-zzq", "test-inst-hermano-b-zzq", "Taller B"),
        )
        # El FK a `talleres` exige que el hermano ya exista -> se linkea con
        # un UPDATE después de insertar los 2 (no en el INSERT de A).
        conn.execute(
            "UPDATE talleres SET taller_hermano_id = %s, taller_hermano_titulo = %s "
            "WHERE id = %s",
            (TALLER_B, "Campaña de prueba", TALLER_A),
        )
        conn.execute(
            "INSERT INTO ediciones_taller (taller_id, slug, fecha_inicio, fecha_fin) "
            "VALUES (%s, %s, %s, %s)",
            (TALLER_A, "test-inst-hermano-a-ed1-zzq", "2099-01-01", "2099-01-02"),
        )
        conn.execute(
            "INSERT INTO ediciones_taller (taller_id, slug, fecha_inicio, fecha_fin) "
            "VALUES (%s, %s, %s, %s)",
            (TALLER_B, "test-inst-hermano-b-ed1-zzq", "2099-02-01", "2099-02-02"),
        )
        conn.execute(
            "INSERT INTO instituciones (id, nombre, slug) VALUES (%s, %s, %s)",
            (INSTITUCION_ID, "Institución de prueba", "test-inst-zzq"),
        )
        conn.execute(
            "INSERT INTO taller_instituciones (taller_id, institucion_id, orden) "
            "VALUES (%s, %s, 0), (%s, %s, 1)",
            (TALLER_A, INSTITUCION_ID, TALLER_B, INSTITUCION_ID),
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


def test_get_institucion_incluye_taller_hermano(institucion_con_par_hermano):
    """El bug real: sin el fix, `taller_hermano` no está en el dict devuelto
    (o es None) para ninguno de los 2 talleres — acá tiene que estar
    poblado y simétrico en los 2, con el mismo orden principal/secundario
    que `/talleres/{slug}` ya garantiza."""
    from routes.talleres import get_institucion

    data = get_institucion("test-inst-zzq")

    por_id = {t["taller_id"]: t for t in data["talleres"]}
    assert set(por_id) == {TALLER_A, TALLER_B}

    for taller_id in (TALLER_A, TALLER_B):
        hermano = por_id[taller_id].get("taller_hermano")
        assert hermano is not None, f"taller_hermano ausente para {taller_id}"
        assert hermano["titulo"] == "Campaña de prueba"
        assert hermano["principal"]["taller_id"] == TALLER_A
        assert hermano["secundario"]["taller_id"] == TALLER_B
