"""Carritos activos (services.carrito.activos) — candados de `marcar_confirmado`
contra Postgres REAL. Mirror de test_talleres_borrador_db.py: el heartbeat del
carrito viaja por `fetch` sin `await` (fire-and-forget) — `marcar_confirmado`
tiene que ganar sin importar el orden de llegada (bug 2026-08-20, mismo
patrón que `talleres_borrador.marcar_confirmado`).

OPT-IN y seguro por defecto (RESERVAS_DB_TEST=1 + DATABASE_URL a una base de
prueba).
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


def _limpiar(conn, session_ids):
    conn.execute("DELETE FROM carritos_activos WHERE session_id = ANY(%s)", (session_ids,))


@pytest.fixture
def conn():
    from database import get_db, init_db

    init_db()
    c = get_db()
    yield c
    c.close()


def test_marcar_confirmado_sin_heartbeat_previo_crea_la_fila_confirmada(conn):
    """session_id que el módulo nunca vio (form viejo sin heartbeat, o
    heartbeat que falló) — no debe tirar excepción, y la fila que crea ya
    nace confirmada (no queda "activa" en el dashboard)."""
    from services.carrito.activos import marcar_confirmado

    sid = str(uuid.uuid4())
    try:
        marcar_confirmado(sid, conn)
        conn.commit()

        row = conn.execute(
            "SELECT confirmado FROM carritos_activos WHERE session_id = %s", (sid,)
        ).fetchone()
        assert row is not None
        assert row["confirmado"] is True
    finally:
        _limpiar(conn, [sid])
        conn.commit()


def test_marcar_confirmado_antes_del_heartbeat_no_deja_carrito_activo_fantasma(conn):
    """Race real (bug 2026-08-20, mismo patrón que talleres_borrador): el
    heartbeat del carrito viaja por `fetch` sin `await` — puede llegar a la
    base DESPUÉS de que el pedido ya se confirmó (red lenta). Simulamos el
    orden invertido: confirmar ANTES de que exista cualquier heartbeat."""
    from services.carrito.activos import heartbeat_upsert, marcar_confirmado

    sid = str(uuid.uuid4())
    try:
        marcar_confirmado(sid, conn)
        conn.commit()

        # El heartbeat que venía "en vuelo" llega recién ahora, después de confirmar.
        heartbeat_upsert(conn, sid, [], None, None, None, None, None)
        conn.commit()

        row = conn.execute(
            "SELECT confirmado FROM carritos_activos WHERE session_id = %s", (sid,)
        ).fetchone()
        assert row["confirmado"] is True, (
            "un heartbeat tardío no debe resucitar como 'activo' un carrito ya confirmado"
        )
    finally:
        _limpiar(conn, [sid])
        conn.commit()


def test_marcar_confirmado_cierra_un_carrito_con_heartbeat_previo(conn):
    from services.carrito.activos import heartbeat_upsert, marcar_confirmado

    sid = str(uuid.uuid4())
    try:
        heartbeat_upsert(conn, sid, [], None, None, None, None, None)
        conn.commit()

        row = conn.execute(
            "SELECT confirmado FROM carritos_activos WHERE session_id = %s", (sid,)
        ).fetchone()
        assert row["confirmado"] is False

        marcar_confirmado(sid, conn)
        conn.commit()

        row = conn.execute(
            "SELECT confirmado FROM carritos_activos WHERE session_id = %s", (sid,)
        ).fetchone()
        assert row["confirmado"] is True
    finally:
        _limpiar(conn, [sid])
        conn.commit()
