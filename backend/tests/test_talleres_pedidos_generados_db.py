"""Fase 1 (#1308) — puente Talleres → Pedidos: `GET /admin/ediciones/{id}/pedidos`
lista los pedidos mensuales que `_regenerar_pedidos_taller` generó para una
edición, para que el admin los vea sin tener que buscarlos a mano en
/admin/pedidos.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):

    DATABASE_URL=postgresql://tincho@localhost/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_talleres_pedidos_generados_db.py -v -m integration
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

TALLER_ID = 9_453_001
EDICION_ID = 9_453_101
EDICION_OTRA_ID = 9_453_102
PEDIDO_AGO_ID = 9_453_201
PEDIDO_SEP_ID = 9_453_202
PEDIDO_OTRA_EDICION_ID = 9_453_203
SLUG = "test-pedidos-generados-f1308"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquileres WHERE id IN (%s,%s,%s)",
        (PEDIDO_AGO_ID, PEDIDO_SEP_ID, PEDIDO_OTRA_EDICION_ID),
    )
    conn.execute("DELETE FROM ediciones_taller WHERE id IN (%s,%s)", (EDICION_ID, EDICION_OTRA_ID))
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))


@pytest.fixture
def taller_module(monkeypatch):
    import routes.talleres as t
    from database import get_db, init_db

    monkeypatch.setattr(t, "require_admin", lambda r: None)

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO talleres (id, slug, nombre) VALUES (%s,%s,'Taller test pedidos generados')",
            (TALLER_ID, SLUG),
        )
        conn.execute(
            "INSERT INTO ediciones_taller (id, taller_id, numero_edicion, slug, fecha_inicio, fecha_fin) "
            "VALUES (%s,%s,1,%s,'2026-08-01','2026-09-30')",
            (EDICION_ID, TALLER_ID, SLUG + "-ed1"),
        )
        conn.execute(
            "INSERT INTO ediciones_taller (id, taller_id, numero_edicion, slug, fecha_inicio, fecha_fin) "
            "VALUES (%s,%s,2,%s,'2026-08-01','2026-08-31')",
            (EDICION_OTRA_ID, TALLER_ID, SLUG + "-ed2"),
        )
        # Pedidos de la edición 1, insertados fuera de orden a propósito —
        # el endpoint tiene que devolverlos ordenados por mes.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, "
            "monto_total, monto_pagado, taller_edicion_id) "
            "VALUES (%s,'Taller Sep','confirmado','taller','2026-09-01T00:00:00',"
            "'2026-09-30T23:59:59',50000,0,%s)",
            (PEDIDO_SEP_ID, EDICION_ID),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, "
            "monto_total, monto_pagado, taller_edicion_id) "
            "VALUES (%s,'Taller Ago','finalizado','taller','2026-08-01T00:00:00',"
            "'2026-08-31T23:59:59',50000,50000,%s)",
            (PEDIDO_AGO_ID, EDICION_ID),
        )
        # Pedido de OTRA edición — no debe aparecer en la lista de la edición 1.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, "
            "monto_total, monto_pagado, taller_edicion_id) "
            "VALUES (%s,'Otra edicion','confirmado','taller','2026-08-01T00:00:00',"
            "'2026-08-31T23:59:59',30000,0,%s)",
            (PEDIDO_OTRA_EDICION_ID, EDICION_OTRA_ID),
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


def test_lista_solo_los_pedidos_de_esta_edicion_ordenados_por_mes(taller_module):
    t = taller_module
    out = t.admin_list_pedidos_edicion(EDICION_ID, None)

    ids = [p["id"] for p in out]
    assert ids == [PEDIDO_AGO_ID, PEDIDO_SEP_ID], "orden por fecha_desde, agosto antes que septiembre"
    assert PEDIDO_OTRA_EDICION_ID not in ids


def test_trae_estado_y_montos_para_ver_de_un_vistazo_que_esta_pagado(taller_module):
    t = taller_module
    out = t.admin_list_pedidos_edicion(EDICION_ID, None)
    ago = next(p for p in out if p["id"] == PEDIDO_AGO_ID)
    sep = next(p for p in out if p["id"] == PEDIDO_SEP_ID)

    assert ago["estado"] == "finalizado"
    assert ago["monto_total"] == 50000
    assert ago["monto_pagado"] == 50000

    assert sep["estado"] == "confirmado"
    assert sep["monto_pagado"] == 0


def test_edicion_sin_pedidos_devuelve_lista_vacia(taller_module):
    t = taller_module
    assert t.admin_list_pedidos_edicion(9_999_999, None) == []
