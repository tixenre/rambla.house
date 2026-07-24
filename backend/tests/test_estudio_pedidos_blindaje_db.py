"""Fase 1 de la economía del Estudio (issue de tracking de la iniciativa): el
editor genérico de pedidos NO debe poder pisar la plata/ítems de un pedido
`tipo IN ('estudio', 'estudio_fijo')`.

Bug vivo real encontrado auditando la economía del Estudio (2026-07-23): los
ítems de un pedido del Estudio se insertaban con `precio_jornada=0` — la plata
real vivía HOY solo en `alquileres.monto_total` (la Fase 2 los pasó a ser
"ítems veraces", con el monto real en el ítem centinela — ver
`test_estudio_items_veraces_db.py`/`test_backfill_items_estudio_migration_db.py`).
Sin guard, editar el pedido (notas, fechas, ítems) disparaba
`_recalcular_total_pedido`/`_apply_pedido_items`, que recalculaban
`monto_total` desde esos ítems ($0) — pisando la plata real a cero.

Nota: este archivo tenía un 4to test (`test_reconciliacion_ignora_pedidos_estudio_legacy`)
que verificaba la exclusión ⏰ LEGACY de `reportes/reconciliacion.py` — la Fase 2
la revirtió a propósito (los ítems veraces hacen que el chequeo cierre solo,
sin necesitar excepciones) y el test se retiró con ella.

OPT-IN y SEGURO POR DEFECTO (mismo gating que test_pedido_concurrencia_db.py):

    DATABASE_URL=postgresql://tincho@localhost/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estudio_pedidos_blindaje_db.py -v -m integration
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

EQ_CENTINELA_ID = 9_450_001
PEDIDO_ESTUDIO_ID = 9_450_101
CLIENTE_ID = 9_450_201
# Post clean-start (LIQUIDACION_INICIO='2026-06-01') a propósito: si el guard
# de reconciliación fallara, este pedido SÍ entraría al universo de desglose.
FD, FH = "2026-09-10T14:00:00", "2026-09-10T18:00:00"


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (PEDIDO_ESTUDIO_ID,))
    conn.execute("DELETE FROM alquileres WHERE id = %s", (PEDIDO_ESTUDIO_ID,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_CENTINELA_ID,))


@pytest.fixture
def db_setup():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, visible_catalogo, dueno, es_recurso_interno) "
            "VALUES (%s,%s,1,0,'Rambla',TRUE)",
            (EQ_CENTINELA_ID, "Estudio (espacio) — test blindaje"),
        )
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido) VALUES (%s,'Test','Blindaje Estudio')",
            (CLIENTE_ID,),
        )
        # Pedido del estudio TAL COMO se crea hoy (pre-Fase-2): monto_total
        # real en el header, ítem centinela con precio_jornada=0/subtotal=0
        # (ver routes/estudio.py::crear_reserva_estudio).
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Cliente test estudio','confirmado','estudio',%s,%s,50000)",
            (PEDIDO_ESTUDIO_ID, CLIENTE_ID, FD, FH),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s,%s,1,0,0)",
            (PEDIDO_ESTUDIO_ID, EQ_CENTINELA_ID),
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


def test_editar_notas_no_pisa_monto_pedido_estudio(db_setup):
    """El front SIEMPRE re-envía fecha_desde/fecha_hasta en cada guardado de
    "datos" (ver el comentario en `_apply_pedido_datos` sobre por qué existe el
    bypass de fecha pasada) — acá se simula un guardado que solo cambia
    `notas`, re-enviando las MISMAS fechas ya persistidas. Sin el guard de
    Fase 1, esto dispara `_recalcular_total_pedido`, que recalcula desde el
    ítem centinela ($0) y pisa `monto_total` a 0."""
    from database import get_db
    from routes.alquileres.core import _apply_pedido_datos
    from routes.alquileres.modelos import PedidoDatos

    conn = get_db()
    try:
        pedido = _apply_pedido_datos(
            conn, PEDIDO_ESTUDIO_ID,
            PedidoDatos(notas="probando blindaje", fecha_desde=FD, fecha_hasta=FH),
            es_admin=True,
        )
        conn.commit()
    finally:
        conn.close()

    assert pedido["notas"] == "probando blindaje"
    assert pedido["monto_total"] == 50000, (
        f"el guard de Fase 1 debería dejar monto_total intacto (50000); fue "
        f"{pedido['monto_total']} — ¿se recalculó desde los ítems del estudio "
        f"(precio_jornada=0)?"
    )


def test_editar_fechas_pedido_estudio_rechazado(db_setup):
    """Un intento de mover fecha_desde/fecha_hasta de un pedido del estudio por
    el editor genérico se rechaza (409) — ese endpoint no revalida stock/buffer
    (ver docstring de `_apply_pedido_datos`), así que aplicarlo sin más
    movería un turno confirmado a una franja ya ocupada sin ningún chequeo."""
    from database import get_db, to_datetime
    from routes.alquileres.core import _apply_pedido_datos
    from routes.alquileres.modelos import PedidoDatos

    nueva_fh = "2026-09-10T20:00:00"  # 2hs más tarde que la persistida
    conn = get_db()
    try:
        with pytest.raises(HTTPException) as exc_info:
            _apply_pedido_datos(
                conn, PEDIDO_ESTUDIO_ID,
                PedidoDatos(fecha_desde=FD, fecha_hasta=nueva_fh),
                es_admin=True,
            )
        assert exc_info.value.status_code == 409
        conn.rollback()
    finally:
        conn.close()

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT fecha_hasta, monto_total FROM alquileres WHERE id=%s", (PEDIDO_ESTUDIO_ID,)
        ).fetchone()
        assert to_datetime(row["fecha_hasta"]) == to_datetime(FH), "la fecha NO debería haber cambiado"
        assert row["monto_total"] == 50000
    finally:
        conn.close()


def test_put_items_pedido_estudio_rechazado(db_setup):
    """Reemplazar los ítems de un pedido del estudio por el editor genérico se
    rechaza (409) — perdería el ítem centinela que bloquea el espacio y
    recalcularía subtotales con la fórmula de un alquiler normal (jornadas ×
    precio de catálogo)."""
    from database import get_db
    from routes.alquileres.core import _apply_pedido_items
    from routes.alquileres.modelos import PedidoItem

    conn = get_db()
    try:
        with pytest.raises(HTTPException) as exc_info:
            _apply_pedido_items(
                conn, PEDIDO_ESTUDIO_ID,
                [PedidoItem(equipo_id=EQ_CENTINELA_ID, cantidad=1, precio_jornada=0, cobro_modo="jornada")],
            )
        assert exc_info.value.status_code == 409
        conn.rollback()
    finally:
        conn.close()

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT monto_total FROM alquileres WHERE id=%s", (PEDIDO_ESTUDIO_ID,)
        ).fetchone()
        assert row["monto_total"] == 50000, "no debería haber tocado nada al rechazar"
    finally:
        conn.close()
