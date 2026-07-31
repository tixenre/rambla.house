"""Backfill `q2r3s4t5u6v7` (Fase 2 de la economía del Estudio, ítems veraces).

Simula el camino real de prod: `init_db()` (esquema al día, incluye el
centinela seedeado) + pedidos "legacy" insertados con el shape PRE-Fase-2
(ítems del estudio a $0, o —para `estudio_fijo`— sin ítems) + `alembic
upgrade head` (aplica el backfill). Verifica que cada pedido queda con
`Σ subtotal(ítems) == monto_total` (ítems veraces) usando el criterio real
de split (espacio = `LEAST(monto_total, precio_hora × horas)`, remanente del
pack como línea personalizada) y que correr el backfill DOS VECES no duplica
ni recalcula sobre datos ya migrados (idempotencia).

OPT-IN y SEGURO POR DEFECTO (mismo gating que
test_backfill_descuento_cliente_pct_migration_db.py):
se saltea salvo ALEMBIC_DB_TEST=1 + DATABASE_URL a una base de prueba.
"""
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

_OPT_IN = os.getenv("ALEMBIC_DB_TEST") == "1"
_DB_URL = os.getenv("DATABASE_URL", "")
_DB_NAME = urlparse(_DB_URL).path.lstrip("/") if _DB_URL else ""


def _looks_like_test_db() -> bool:
    return bool(_DB_NAME) and "test" in _DB_NAME.lower()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _OPT_IN,
        reason="opt-in: setear ALEMBIC_DB_TEST=1 + DATABASE_URL a una base de prueba",
    ),
    pytest.mark.skipif(
        _OPT_IN and not _looks_like_test_db(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return cfg


def _reset_schema():
    from database import get_db

    conn = get_db()
    try:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def clean_db():
    _reset_schema()
    yield
    _reset_schema()


EQ_PACK_ID = 9_480_001
PEDIDO_SIN_PACK = 9_480_101      # estudio, sin pack, ítem centinela a $0
PEDIDO_CON_PACK = 9_480_102      # estudio, con pack, centinela + equipo a $0
PEDIDO_ESTUDIO_FIJO = 9_480_103  # estudio_fijo, SIN ningún ítem


def test_backfill_deja_items_veraces_split_espacio_y_pack(clean_db):
    """precio_hora=10000 → split limpio del pedido con pack."""
    from alembic import command
    from database import init_db, get_db
    import migration_state

    init_db()

    conn = get_db()
    try:
        centinela_id = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]
        assert centinela_id, "el seed de init_db() debería crear el centinela"
        conn.execute("UPDATE estudio SET precio_hora=10000 WHERE id=1")
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada) VALUES (%s,%s,1,0)",
            (EQ_PACK_ID, "Equipo pack test (backfill)"),
        )

        # PEDIDO_SIN_PACK: 4 horas × 10000 = 40000, sin pack. Shape PRE-Fase-2:
        # centinela a $0 (cobro_modo default 'jornada').
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, estudio_con_pack, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,'legacy estudio','confirmado','estudio',FALSE,"
            "'2026-09-01T14:00:00','2026-09-01T18:00:00',40000)",
            (PEDIDO_SIN_PACK,),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s,%s,1,0,0)",
            (PEDIDO_SIN_PACK, centinela_id),
        )

        # PEDIDO_CON_PACK: 2 horas × 10000(espacio) + 15000(pack) = 35000.
        # Shape PRE-Fase-2: centinela a $0 + 1 equipo del pack a $0.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, estudio_con_pack, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,'legacy estudio pack','confirmado','estudio',TRUE,"
            "'2026-09-02T10:00:00','2026-09-02T12:00:00',35000)",
            (PEDIDO_CON_PACK,),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s,%s,1,0,0)",
            (PEDIDO_CON_PACK, centinela_id),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s,%s,1,0,0)",
            (PEDIDO_CON_PACK, EQ_PACK_ID),
        )

        # PEDIDO_ESTUDIO_FIJO: shape PRE-Fase-2 = SIN NINGÚN ítem.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,'Filmar (slot legacy)','confirmado','estudio_fijo',"
            "'2026-09-03T08:00:00','2026-09-03T20:00:00',50000)",
            (PEDIDO_ESTUDIO_FIJO,),
        )
        conn.commit()
    finally:
        conn.close()

    cfg = _alembic_config()
    command.upgrade(cfg, "head")

    head = migration_state._head_revision(cfg)
    current = migration_state._current_revision()
    assert current == head, f"La cadena quedó en {current!r}, head es {head!r}"

    def _items(conn, pedido_id):
        return conn.execute(
            "SELECT equipo_id, cantidad, precio_jornada, subtotal, nombre_libre, cobro_modo "
            "FROM alquiler_items WHERE pedido_id=%s ORDER BY equipo_id NULLS LAST",
            (pedido_id,),
        ).fetchall()

    conn = get_db()
    try:
        # PEDIDO_SIN_PACK: el centinela pasa a llevar el monto real, cobro_modo='fijo'.
        items = _items(conn, PEDIDO_SIN_PACK)
        assert len(items) == 1
        assert items[0]["equipo_id"] == centinela_id
        assert items[0]["subtotal"] == 40000
        assert items[0]["precio_jornada"] == 40000
        assert items[0]["cobro_modo"] == "fijo"

        # PEDIDO_CON_PACK: centinela = espacio (20000), línea personalizada
        # nueva = remanente del pack (15000); el equipo del pack sigue a $0
        # (informativo — su presencia no cambia, solo aparece la línea fija).
        items = _items(conn, PEDIDO_CON_PACK)
        assert len(items) == 3
        centinela = next(it for it in items if it["equipo_id"] == centinela_id)
        assert centinela["subtotal"] == 20000
        assert centinela["cobro_modo"] == "fijo"
        pack_equipo = next(it for it in items if it["equipo_id"] == EQ_PACK_ID)
        assert pack_equipo["subtotal"] == 0  # informativo, sin cambios
        linea_pack = next(it for it in items if it["equipo_id"] is None)
        assert linea_pack["subtotal"] == 15000
        assert linea_pack["precio_jornada"] == 15000
        assert linea_pack["cobro_modo"] == "fijo"
        assert linea_pack["nombre_libre"]  # el pack_nombre seedeado, no vacío
        # Ítems veraces: la suma de TODOS los subtotales = monto_total.
        assert sum(it["subtotal"] for it in items) == 35000

        # PEDIDO_ESTUDIO_FIJO: gana su único ítem centinela con el monto real.
        items = _items(conn, PEDIDO_ESTUDIO_FIJO)
        assert len(items) == 1
        assert items[0]["equipo_id"] == centinela_id
        assert items[0]["subtotal"] == 50000
        assert items[0]["cobro_modo"] == "fijo"
    finally:
        conn.close()

    # Idempotencia: downgrade (no-op de datos, solo mueve el stamp de alembic
    # una revisión atrás) + upgrade DE NUEVO — el `upgrade()` real vuelve a
    # correr sobre datos YA MIGRADOS. No debe duplicar ítems ni recalcular.
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")

    conn = get_db()
    try:
        assert len(_items(conn, PEDIDO_SIN_PACK)) == 1
        items_pack = _items(conn, PEDIDO_CON_PACK)
        assert len(items_pack) == 3, "una segunda corrida no debería insertar OTRA línea de pack"
        assert sum(it["subtotal"] for it in items_pack) == 35000
        assert len(_items(conn, PEDIDO_ESTUDIO_FIJO)) == 1, "no debería insertar un segundo centinela"
    finally:
        conn.execute(
            "DELETE FROM alquileres WHERE id IN (%s,%s,%s)",
            (PEDIDO_SIN_PACK, PEDIDO_CON_PACK, PEDIDO_ESTUDIO_FIJO),
        )
        conn.execute("DELETE FROM equipos WHERE id=%s", (EQ_PACK_ID,))
        conn.commit()
        conn.close()


def test_backfill_fallback_sin_precio_hora_confiable(clean_db):
    """precio_hora=0 (o nulo) al momento del backfill: no hay tarifa confiable
    para reconstruir el split → el `monto_total` completo queda en el
    espacio (centinela), SIN inventar una línea de pack."""
    from alembic import command
    from database import init_db, get_db

    init_db()

    conn = get_db()
    try:
        centinela_id = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]
        conn.execute("UPDATE estudio SET precio_hora=0 WHERE id=1")
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, estudio_con_pack, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,'legacy sin tarifa','confirmado','estudio',TRUE,"
            "'2026-09-04T10:00:00','2026-09-04T12:00:00',35000)",
            (PEDIDO_CON_PACK,),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s,%s,1,0,0)",
            (PEDIDO_CON_PACK, centinela_id),
        )
        conn.commit()
    finally:
        conn.close()

    command.upgrade(_alembic_config(), "head")

    conn = get_db()
    try:
        items = conn.execute(
            "SELECT equipo_id, subtotal, cobro_modo FROM alquiler_items WHERE pedido_id=%s",
            (PEDIDO_CON_PACK,),
        ).fetchall()
        assert len(items) == 1, "sin precio_hora confiable no debería inventarse una línea de pack"
        assert items[0]["equipo_id"] == centinela_id
        assert items[0]["subtotal"] == 35000  # monto_total completo, fallback
        assert items[0]["cobro_modo"] == "fijo"
    finally:
        conn.execute("DELETE FROM alquileres WHERE id=%s", (PEDIDO_CON_PACK,))
        conn.commit()
        conn.close()
