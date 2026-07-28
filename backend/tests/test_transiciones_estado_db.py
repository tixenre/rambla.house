"""`routes.alquileres.transiciones.cambiar_estado` — el motor único de
transición de estado del pedido (sesión 2026-07-06, a pedido del dueño:
"puedo volver atrás a modificar los pedidos, porque suele pasar" + estilo
Magento para `finalizado`).

Postgres REAL (no mocks) — mismo opt-in que `test_pedido_concurrencia_db.py`:

    DATABASE_URL=postgresql://tincho@localhost/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_transiciones_estado_db.py -v -m integration
"""
import os
from urllib.parse import urlparse

import pytest
from fastapi import HTTPException

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

EQ_ID = 9_700_001
CLIENTE_ID = 9_700_201
FD, FH = "2026-09-01T08:00:00", "2026-09-02T20:00:00"
_PEDIDO_IDS = list(range(9_700_101, 9_700_112))


def _limpiar(conn):
    conn.execute("DELETE FROM facturas WHERE pedido_id = ANY(%s)", (_PEDIDO_IDS,))
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = ANY(%s)", (_PEDIDO_IDS,))
    conn.execute("DELETE FROM alquileres WHERE id = ANY(%s)", (_PEDIDO_IDS,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_ID,))


@pytest.fixture
def db_setup():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada) VALUES (%s,%s,%s,%s)",
            (EQ_ID, "Equipo test (transiciones)", 5, 1000),
        )
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, descuento) VALUES (%s,%s,%s,%s)",
            (CLIENTE_ID, "Test", "Transiciones", 0),
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


def _crear_pedido(conn, pedido_id: int, estado: str, *, monto_pagado: int = 0,
                   monto_total: int = 1000, con_items: bool = True, con_fechas: bool = True):
    conn.execute(
        "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, fecha_desde, fecha_hasta, "
        "monto_total, monto_pagado) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (pedido_id, CLIENTE_ID, "Cliente test", estado,
         FD if con_fechas else None, FH if con_fechas else None, monto_total, monto_pagado),
    )
    if con_items:
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada) VALUES (%s,%s,1,1000)",
            (pedido_id, EQ_ID),
        )
    conn.commit()


def test_transicion_hacia_adelante_ok(db_setup):
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        _crear_pedido(conn, _PEDIDO_IDS[0], "borrador")
        resultado = cambiar_estado(conn, _PEDIDO_IDS[0], "solicitado", es_admin=True, actor="system")
        conn.commit()
        assert resultado == {
            "estado_anterior": "borrador", "estado_nuevo": "solicitado", "numero_pedido_asignado": False,
            "turnos_vinculados_sin_avanzar": [],
        }
        p = conn.execute("SELECT estado FROM alquileres WHERE id=%s", (_PEDIDO_IDS[0],)).fetchone()
        assert p["estado"] == "solicitado"
    finally:
        conn.close()


def test_transicion_hacia_atras_ok(db_setup):
    """El caso que motivó el rediseño: el admin necesita poder corregir un
    pedido volviendo a un estado anterior, no solo avanzar."""
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        _crear_pedido(conn, _PEDIDO_IDS[1], "confirmado")
        resultado = cambiar_estado(conn, _PEDIDO_IDS[1], "solicitado", es_admin=True, actor="system")
        conn.commit()
        assert resultado["estado_nuevo"] == "solicitado"
        p = conn.execute("SELECT estado FROM alquileres WHERE id=%s", (_PEDIDO_IDS[1],)).fetchone()
        assert p["estado"] == "solicitado"
    finally:
        conn.close()


def test_transicion_ilegal_rechazada(db_setup):
    """`cancelado` es terminal — no hay transición definida hacia afuera."""
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        _crear_pedido(conn, _PEDIDO_IDS[2], "cancelado")
        with pytest.raises(HTTPException) as exc:
            cambiar_estado(conn, _PEDIDO_IDS[2], "confirmado", es_admin=True, actor="system")
        assert exc.value.status_code == 400
        conn.rollback()
        p = conn.execute("SELECT estado FROM alquileres WHERE id=%s", (_PEDIDO_IDS[2],)).fetchone()
        assert p["estado"] == "cancelado"
    finally:
        conn.close()


def test_bloquea_volver_a_borrador_si_ya_cobro(db_setup):
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        _crear_pedido(conn, _PEDIDO_IDS[3], "solicitado", monto_pagado=500)
        with pytest.raises(HTTPException) as exc:
            cambiar_estado(conn, _PEDIDO_IDS[3], "borrador", es_admin=True, actor="system")
        assert exc.value.status_code == 400
        assert "plata cobrada" in str(exc.value.detail)
        conn.rollback()
    finally:
        conn.close()


def test_bloquea_volver_a_borrador_si_ya_facturado(db_setup):
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        _crear_pedido(conn, _PEDIDO_IDS[4], "confirmado")
        conn.execute(
            "INSERT INTO facturas (pedido_id, emisor, ambiente, cbte_tipo, pto_vta, doc_tipo, doc_nro, "
            "condicion_iva_receptor, concepto, imp_neto, imp_total, estado) "
            "VALUES (%s,'rambla','testing',6,1,96,'0',5,1,1000,1000,'emitida')",
            (_PEDIDO_IDS[4],),
        )
        conn.commit()
        with pytest.raises(HTTPException) as exc:
            cambiar_estado(conn, _PEDIDO_IDS[4], "borrador", es_admin=True, actor="system")
        assert exc.value.status_code == 400
        assert "factura activa" in str(exc.value.detail)
        conn.rollback()
    finally:
        conn.close()


def test_permite_volver_a_borrador_sin_plata_ni_factura(db_setup):
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        _crear_pedido(conn, _PEDIDO_IDS[5], "solicitado", monto_pagado=0)
        resultado = cambiar_estado(conn, _PEDIDO_IDS[5], "borrador", es_admin=True, actor="system")
        conn.commit()
        assert resultado["estado_nuevo"] == "borrador"
    finally:
        conn.close()


def test_numero_pedido_se_asigna_una_sola_vez_al_confirmar(db_setup):
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        _crear_pedido(conn, _PEDIDO_IDS[6], "solicitado")
        r1 = cambiar_estado(conn, _PEDIDO_IDS[6], "confirmado", es_admin=True, actor="system")
        conn.commit()
        assert r1["numero_pedido_asignado"] is True
        numero = conn.execute(
            "SELECT numero_pedido FROM alquileres WHERE id=%s", (_PEDIDO_IDS[6],)
        ).fetchone()["numero_pedido"]
        assert numero is not None

        # Retrocede y vuelve a confirmar — no debe reasignar un número nuevo.
        cambiar_estado(conn, _PEDIDO_IDS[6], "solicitado", es_admin=True, actor="system")
        conn.commit()
        r2 = cambiar_estado(conn, _PEDIDO_IDS[6], "confirmado", es_admin=True, actor="system")
        conn.commit()
        assert r2["numero_pedido_asignado"] is False
        numero2 = conn.execute(
            "SELECT numero_pedido FROM alquileres WHERE id=%s", (_PEDIDO_IDS[6],)
        ).fetchone()["numero_pedido"]
        assert numero2 == numero
    finally:
        conn.close()


def test_cliente_solo_puede_disparar_cancelado(db_setup):
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        _crear_pedido(conn, _PEDIDO_IDS[7], "solicitado")
        with pytest.raises(HTTPException) as exc:
            cambiar_estado(conn, _PEDIDO_IDS[7], "confirmado", es_admin=False, actor="cliente@test.com")
        assert exc.value.status_code == 400
        conn.rollback()
    finally:
        conn.close()


def test_cliente_no_puede_cancelar_desde_retirado(db_setup):
    """Espeja la restricción de siempre: cancelado solo desde estados
    pre-retirado — ahora enforzada por el grafo, no por un chequeo ad-hoc."""
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        _crear_pedido(conn, _PEDIDO_IDS[8], "retirado")
        with pytest.raises(HTTPException) as exc:
            cambiar_estado(conn, _PEDIDO_IDS[8], "cancelado", es_admin=False, actor="cliente@test.com")
        assert exc.value.status_code == 400
        conn.rollback()
        # Tampoco al admin — cancelado no es alcanzable desde retirado.
        with pytest.raises(HTTPException):
            cambiar_estado(conn, _PEDIDO_IDS[8], "cancelado", es_admin=True, actor="system")
        conn.rollback()
    finally:
        conn.close()


def test_finalizar_manual_desde_devuelto_con_monto_cero(db_setup):
    """El escape hatch real (botón "Finalizar" del admin): un pedido
    monto_total=0 (comp/cortesía) nunca cumple la condición de
    `_maybe_finalizar` (exige monto_total > 0) y quedaría trabado en
    'devuelto' para siempre sin poder forzarlo a mano."""
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        _crear_pedido(conn, _PEDIDO_IDS[9], "devuelto", monto_total=0, monto_pagado=0)
        resultado = cambiar_estado(conn, _PEDIDO_IDS[9], "finalizado", es_admin=True, actor="system")
        conn.commit()
        assert resultado["estado_nuevo"] == "finalizado"
        p = conn.execute("SELECT estado FROM alquileres WHERE id=%s", (_PEDIDO_IDS[9],)).fetchone()
        assert p["estado"] == "finalizado"
    finally:
        conn.close()


def test_revertir_finalizado_a_devuelto_si_no_esta_realmente_pago(db_setup):
    """Reversión manual (por si se clickeó "Finalizar" de más) — se sostiene
    porque el pedido NO está realmente pago (monto_total=0), así que
    `_maybe_finalizar` no lo vuelve a mandar para adelante."""
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        _crear_pedido(conn, _PEDIDO_IDS[10], "finalizado", monto_total=0, monto_pagado=0)
        resultado = cambiar_estado(conn, _PEDIDO_IDS[10], "devuelto", es_admin=True, actor="system")
        conn.commit()
        assert resultado["estado_nuevo"] == "devuelto"
        p = conn.execute("SELECT estado FROM alquileres WHERE id=%s", (_PEDIDO_IDS[10],)).fetchone()
        assert p["estado"] == "devuelto"
    finally:
        conn.close()
