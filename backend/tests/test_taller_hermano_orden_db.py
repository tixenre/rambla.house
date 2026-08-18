"""Taller hermano — orden estable de principal/secundario, contra Postgres
REAL. Bug real (2026-08-19, "no quiero que se den vuelta, quiero que cada
uno quede en un lado"): con el puntero `taller_hermano_id` seteado en AMBOS
lados (la UI del admin no lo impide — cada tab de "Taller hermano" es
independiente), la versión vieja de `_resolver_hermano` resolvía "yo soy el
principal" según la fila que se estuviera consultando -> el orden se
invertía según cuál taller de la pareja se visitara. El fix ordena por id
(dato fijo, no por quién tiene el puntero) -> estos tests reproducen el
escenario bidireccional (y el unidireccional, para no regresionar el caso
común) y confirman que el orden — y el título de campaña — es el mismo
mirando desde cualquiera de los dos lados.

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

TALLER_A = 9_820_001  # menor id -> siempre "principal" tras el fix
TALLER_B = 9_820_002  # mayor id -> siempre "secundario" tras el fix


def _limpiar(conn):
    conn.execute(
        "DELETE FROM ediciones_taller WHERE taller_id IN (%s, %s)", (TALLER_A, TALLER_B)
    )
    conn.execute("DELETE FROM talleres WHERE id IN (%s, %s)", (TALLER_A, TALLER_B))


@pytest.fixture
def par_hermano():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_A, "test-hermano-a-zzq", "test-hermano-a-zzq", "Taller A"),
        )
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_B, "test-hermano-b-zzq", "test-hermano-b-zzq", "Taller B"),
        )
        conn.execute(
            "INSERT INTO ediciones_taller (taller_id, slug, fecha_inicio, fecha_fin) "
            "VALUES (%s, %s, %s, %s)",
            (TALLER_A, "test-hermano-a-ed1-zzq", "2099-01-01", "2099-01-02"),
        )
        conn.execute(
            "INSERT INTO ediciones_taller (taller_id, slug, fecha_inicio, fecha_fin) "
            "VALUES (%s, %s, %s, %s)",
            (TALLER_B, "test-hermano-b-ed1-zzq", "2099-02-01", "2099-02-02"),
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


def test_orden_estable_con_puntero_bidireccional(par_hermano):
    """El bug real: AMBOS conceptos apuntándose entre sí. Sin importar desde
    qué taller se resuelve, el de menor id tiene que quedar siempre
    `principal` — este es el assert que la versión vieja rompía (el "dueño"
    resultaba siempre ser "quien mira")."""
    from database import get_db
    from routes.talleres import _resolver_hermano

    conn = get_db()
    try:
        conn.execute(
            "UPDATE talleres SET taller_hermano_id = %s WHERE id = %s", (TALLER_B, TALLER_A)
        )
        conn.execute(
            "UPDATE talleres SET taller_hermano_id = %s WHERE id = %s", (TALLER_A, TALLER_B)
        )
        conn.commit()

        desde_a = _resolver_hermano(conn, TALLER_A)
        desde_b = _resolver_hermano(conn, TALLER_B)
    finally:
        conn.close()

    assert desde_a is not None and desde_b is not None
    assert desde_a["principal"]["taller_id"] == TALLER_A
    assert desde_a["secundario"]["taller_id"] == TALLER_B
    assert desde_b["principal"]["taller_id"] == TALLER_A
    assert desde_b["secundario"]["taller_id"] == TALLER_B


def test_orden_estable_con_puntero_unidireccional(par_hermano):
    """Caso común (un solo lado configurado): el orden sigue siendo por id,
    no por quién tiene el puntero — probado con el puntero viviendo en el de
    MAYOR id (B -> A), que es el caso que invertía el orden en la versión
    vieja al mirar desde B."""
    from database import get_db
    from routes.talleres import _resolver_hermano

    conn = get_db()
    try:
        conn.execute(
            "UPDATE talleres SET taller_hermano_id = %s WHERE id = %s", (TALLER_A, TALLER_B)
        )
        conn.commit()

        desde_a = _resolver_hermano(conn, TALLER_A)
        desde_b = _resolver_hermano(conn, TALLER_B)
    finally:
        conn.close()

    assert desde_a["principal"]["taller_id"] == TALLER_A
    assert desde_a["secundario"]["taller_id"] == TALLER_B
    assert desde_b["principal"]["taller_id"] == TALLER_A
    assert desde_b["secundario"]["taller_id"] == TALLER_B


def test_titulo_se_resuelve_desde_cualquier_lado(par_hermano):
    """El título de campaña también es simétrico: tipeado solo en el de
    MAYOR id, igual se resuelve mirando desde el de menor id."""
    from database import get_db
    from routes.talleres import _resolver_hermano

    conn = get_db()
    try:
        conn.execute(
            "UPDATE talleres SET taller_hermano_id = %s WHERE id = %s", (TALLER_B, TALLER_A)
        )
        conn.execute(
            "UPDATE talleres SET taller_hermano_titulo = %s WHERE id = %s",
            ("Copy de campaña", TALLER_B),
        )
        conn.commit()

        desde_a = _resolver_hermano(conn, TALLER_A)
    finally:
        conn.close()

    assert desde_a["titulo"] == "Copy de campaña"
