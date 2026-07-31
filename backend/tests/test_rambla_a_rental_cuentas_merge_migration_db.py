"""Migración `23aa6949d4df` (rambla_a_rental_rename) — el merge de `cuentas` (#1314).

Reproduce el bug encontrado en staging: `init_db()` corre ANTES que Alembic en
cada boot y, como el código ya nombra "Rental", siembra una fila
`('Fondo Rental', 'fondo', 'Rental', ...)` ON CONFLICT DO NOTHING. En una BD
que TODAVÍA tenía la fila legacy ("Fondo Rambla"/socio='Rambla', con plata real)
ese seed no choca (nombre/socio distintos todavía) y crea una fila NUEVA vacía
en paralelo. Un rename ciego (`UPDATE cuentas SET socio='Rental' WHERE
socio='Rambla'`) choca contra esa fila nueva — `UniqueViolation` sobre
`idx_cuentas_socio`, la migración entera hace rollback (incluido el rename de
`equipos.dueno`, en el mismo `upgrade()`) — exactamente el síntoma reportado
(equipos con dueño "Rambla" no migrado).

Verifica que el fix mergea la cuenta vieja en la nueva (reasigna sus
movimientos + suma su saldo_inicial + la borra) en vez de chocar, que el resto
de la migración (equipos.dueno) sí se aplica, y que correr la migración dos
veces es idempotente (no duplica ni rompe).

OPT-IN y SEGURO POR DEFECTO (mismo gating que
test_backfill_estudio_dueno_comisiones_migration_db.py):
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


def _simular_bd_legacy_con_fondo_rambla(conn) -> int:
    """`init_db()` ya sembró 'Fondo Rental' (socio='Rental', saldo 0) — acá se
    agrega la fila LEGACY en paralelo ('Fondo Rambla', socio='Rambla', con
    plata real + un movimiento real apuntándole), tal como quedaría una BD
    real que todavía no corrió el rename. Devuelve el id de la cuenta legacy."""
    vieja_id = conn.execute(
        "INSERT INTO cuentas (nombre, tipo, socio, moneda, saldo_inicial, orden) "
        "VALUES ('Fondo Rambla', 'fondo', 'Rambla', 'ARS', 50000, 5) RETURNING id"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO movimientos (tipo, monto, cuenta_origen_id) VALUES ('gasto', 12345, %s)",
        (vieja_id,),
    )
    conn.execute(
        "INSERT INTO movimientos (tipo, monto, cuenta_destino_id) VALUES ('transferencia', 6789, %s)",
        (vieja_id,),
    )
    return vieja_id


def test_merge_cuenta_legacy_en_la_nueva_sembrada_por_init_db(clean_db):
    from alembic import command
    from database import init_db, get_db

    init_db()

    conn = get_db()
    try:
        vieja_id = _simular_bd_legacy_con_fondo_rambla(conn)
        # Mismo síntoma reportado: un equipo con dueño legacy.
        conn.execute(
            "INSERT INTO equipos (nombre, cantidad, precio_jornada, dueno) "
            "VALUES ('Equipo test (rambla-rental)', 1, 1000, 'Rambla')"
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
        # La cuenta vieja se borró — quedó mergeada, no duplicada.
        assert conn.execute(
            "SELECT 1 FROM cuentas WHERE id = %s", (vieja_id,)
        ).fetchone() is None

        nueva = conn.execute(
            "SELECT id, saldo_inicial FROM cuentas WHERE socio = 'Rental' AND activa"
        ).fetchone()
        assert nueva is not None, "Debería sobrevivir UNA sola cuenta activa con socio='Rental'"
        # saldo_inicial de la nueva (0, recién sembrada) + el de la vieja (50000).
        assert nueva["saldo_inicial"] == 50000

        # Los movimientos de la vieja se reasignaron a la sobreviviente.
        origenes = conn.execute(
            "SELECT COUNT(*) AS c FROM movimientos WHERE cuenta_origen_id = %s", (nueva["id"],)
        ).fetchone()["c"]
        destinos = conn.execute(
            "SELECT COUNT(*) AS c FROM movimientos WHERE cuenta_destino_id = %s", (nueva["id"],)
        ).fetchone()["c"]
        assert origenes == 1
        assert destinos == 1
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM movimientos WHERE cuenta_origen_id = %s OR cuenta_destino_id = %s",
            (vieja_id, vieja_id),
        ).fetchone()["c"] == 0

        # El resto de la migración (equipos.dueno) SÍ se aplicó — antes del fix,
        # el rollback por el UniqueViolation de cuentas también lo revertía.
        dueno = conn.execute(
            "SELECT dueno FROM equipos WHERE nombre = 'Equipo test (rambla-rental)'"
        ).fetchone()["dueno"]
        assert dueno == "Rental"
    finally:
        conn.close()

    # Idempotencia: correr de nuevo no rompe ni duplica (el downgrade es no-op
    # a propósito — ver el módulo — así que solo re-corremos upgrade).
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")

    conn = get_db()
    try:
        cuentas_rental = conn.execute(
            "SELECT COUNT(*) AS c FROM cuentas WHERE socio = 'Rental' AND activa"
        ).fetchone()["c"]
        assert cuentas_rental == 1, "No debería duplicarse la cuenta al re-correr"
    finally:
        conn.close()


def test_sin_cuenta_rambla_previa_no_rompe_ni_duplica(clean_db):
    """Caso sin colisión real: la BD nunca tuvo una cuenta 'Fondo Rambla'
    (instalación nueva, o una que ya se migró a mano) — la migración no
    encuentra nada para mergear/renombrar y no debe duplicar ni tocar la única
    cuenta 'Rental' que ya sembró `init_db()`.

    (El caso "hay 'Fondo Rambla' pero todavía no existe ninguna cuenta
    'Rental'" no es reproducible corriendo la cadena completa de migraciones
    desde cero para este test: una migración histórica anterior
    (`x8y9z0a1b2c3_contabilidad_cuentas_movimientos.py`) YA siembra su propia
    fila `Fondo Rental` — por diseño, para cualquier BD (nueva o vieja) que
    llegue a `23aa6949d4df` siempre hay al menos una cuenta 'Rental' activa
    para esa fecha; el rename-en-el-lugar del `else` de
    `_migrar_cuenta_rambla_a_rental` cubre igual ese caso hipotético, solo que
    no es construible en este harness de test.)
    """
    from alembic import command
    from database import init_db, get_db

    init_db()
    command.upgrade(_alembic_config(), "head")

    conn = get_db()
    try:
        cuentas_rental = conn.execute(
            "SELECT id, saldo_inicial FROM cuentas WHERE socio = 'Rental' AND activa"
        ).fetchall()
        assert len(cuentas_rental) == 1
        assert cuentas_rental[0]["saldo_inicial"] == 0

        assert conn.execute(
            "SELECT 1 FROM cuentas WHERE nombre = 'Fondo Rambla' OR socio = 'Rambla'"
        ).fetchone() is None
    finally:
        conn.close()
