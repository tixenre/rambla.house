"""Backfill `t8u9v0w1x2y3` (Fase 4 de la economía del Estudio, #1283).

Simula una BD que YA tenía el centinela creado con `dueno='Rambla'` (el valor
viejo, de antes de esta fase) — `init_db()` siembra el estado ACTUAL
(`dueno='Estudio'`) para instalaciones nuevas, así que para probar el backfill
hay que revertir manualmente ese único campo después de `init_db()`, tal como
quedaría una base real ya desplegada antes de este cambio de código.

Verifica los dos pasos del backfill: (1) el centinela pasa a `dueno='Estudio'`,
(2) un `comisiones_modelo` YA CUSTOMIZADO por el dueño (con reglas propias para
Pablo/Tincho, sin tocar) se le suma la entrada "Estudio" si todavía no la
tiene — sin pisar lo que el dueño ya configuró. Más idempotencia (correr el
backfill dos veces no duplica ni rompe el modelo custom).

OPT-IN y SEGURO POR DEFECTO (mismo gating que
test_backfill_descuento_cliente_pct_migration_db.py):
se saltea salvo ALEMBIC_DB_TEST=1 + DATABASE_URL a una base de prueba.
"""
import json
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

_MODELO_CUSTOM = {
    "Rambla": {"Rambla": 100},
    "Pablo": {"Pablo": 60, "Rambla": 40},
    "Tincho": {"Tincho": 50, "Rambla": 45, "Pablo": 5},
}


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


def test_backfill_dueno_estudio_y_comisiones_respeta_modelo_custom(clean_db):
    from alembic import command
    from database import init_db, get_db

    init_db()

    conn = get_db()
    try:
        # Simula el estado LEGACY (pre-Fase-4): el centinela ya existía con
        # dueno='Rambla' (init_db() ya lo siembra como 'Estudio' hoy).
        conn.execute("UPDATE equipos SET dueno = 'Rambla' "
                     "WHERE id = (SELECT equipo_id FROM estudio WHERE id = 1)")
        # El dueño ya había customizado el reparto (sin Estudio, que no existía).
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_by) VALUES (%s,%s,%s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            ("comisiones_modelo", json.dumps(_MODELO_CUSTOM), "dueño"),
        )
        conn.commit()
    finally:
        conn.close()

    cfg = _alembic_config()
    command.upgrade(cfg, "head")

    import migration_state
    head = migration_state._head_revision(cfg)
    current = migration_state._current_revision()
    assert current == head, f"La cadena quedó en {current!r}, head es {head!r}"

    conn = get_db()
    try:
        dueno = conn.execute(
            "SELECT dueno FROM equipos WHERE id = (SELECT equipo_id FROM estudio WHERE id = 1)"
        ).fetchone()["dueno"]
        assert dueno == "Estudio"

        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'comisiones_modelo'"
        ).fetchone()
        modelo = json.loads(row["value"])
        # Se agregó Estudio...
        assert modelo["Estudio"] == {"Estudio": 100}
        # ...sin tocar las reglas custom del dueño para Pablo/Tincho/Rambla.
        assert modelo["Pablo"] == {"Pablo": 60, "Rambla": 40}
        assert modelo["Tincho"] == {"Tincho": 50, "Rambla": 45, "Pablo": 5}
        assert modelo["Rambla"] == {"Rambla": 100}
    finally:
        conn.close()

    # Idempotencia: correr el backfill de nuevo no duplica ni rompe nada. `conn`
    # tiene que estar CERRADO antes de esto — downgrade/upgrade corren en su
    # propia conexión y el ALTER/UPDATE necesita un lock que una transacción
    # abierta en `conn` (aunque sea de solo lectura) bloquearía indefinidamente.
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")

    conn = get_db()
    try:
        dueno2 = conn.execute(
            "SELECT dueno FROM equipos WHERE id = (SELECT equipo_id FROM estudio WHERE id = 1)"
        ).fetchone()["dueno"]
        assert dueno2 == "Estudio"
        modelo2 = json.loads(conn.execute(
            "SELECT value FROM app_settings WHERE key = 'comisiones_modelo'"
        ).fetchone()["value"])
        assert modelo2 == modelo  # sin cambios en la segunda corrida
    finally:
        conn.close()


def test_backfill_sin_modelo_customizado_no_crea_setting(clean_db):
    """Si el dueño nunca tocó el reparto (no hay fila en app_settings), el
    backfill NO crea una — `cargar_modelo` cae al DEFAULT_MODELO en código,
    que esta misma iniciativa ya actualizó con la entrada de Estudio."""
    from alembic import command
    from database import init_db, get_db

    init_db()
    conn = get_db()
    try:
        conn.execute("UPDATE equipos SET dueno = 'Rambla' "
                     "WHERE id = (SELECT equipo_id FROM estudio WHERE id = 1)")
        conn.execute("DELETE FROM app_settings WHERE key = 'comisiones_modelo'")
        conn.commit()
    finally:
        conn.close()

    command.upgrade(_alembic_config(), "head")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'comisiones_modelo'"
        ).fetchone()
        assert row is None

        dueno = conn.execute(
            "SELECT dueno FROM equipos WHERE id = (SELECT equipo_id FROM estudio WHERE id = 1)"
        ).fetchone()["dueno"]
        assert dueno == "Estudio"
    finally:
        conn.close()
