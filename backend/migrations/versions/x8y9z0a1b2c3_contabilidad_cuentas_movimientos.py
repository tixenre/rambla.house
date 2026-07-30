"""contabilidad: cuentas + gasto_categorias + movimientos (módulo contable, #809)

Fundaciones del módulo contable (`backend/contabilidad/`, espejo de `reportes/`):
el libro único de movimientos entre cuentas/cajas con saldos. El ingreso por
alquiler NO vive acá — DERIVA de `alquiler_pagos` (única fuente de verdad del
cobro, #722); el saldo de la caja de un socio se calcula sumando sus pagos. Acá
viven solo los movimientos manuales (gasto/transferencia/retiro/aporte/ajuste) y
las cuentas con su saldo inicial.

Las tres tablas están espejadas en init_db() (database.py) —esquema en dos capas,
decisión 2026-06-03: toda tabla nueva va TAMBIÉN en init_db()— así existen aunque
esta migración no llegue a correr. Idempotente (IF NOT EXISTS / ON CONFLICT DO
NOTHING) para convivir con el bootstrap.

`movimientos` referencia a `cuentas` y a `gasto_categorias`, así que las tres se
crean juntas aunque la UI de gastos/categorías llegue en una fase posterior — el
esquema del libro va completo de una para no alterarlo después.

Revision ID: x8y9z0a1b2c3
Revises: u5v6w7x8y9z0
Create Date: 2026-06-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x8y9z0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "u5v6w7x8y9z0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── cuentas (cajas/cuentas con saldo) ────────────────────────────────────
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS cuentas (
            id             SERIAL PRIMARY KEY,
            nombre         TEXT NOT NULL UNIQUE,
            tipo           TEXT NOT NULL DEFAULT 'caja',
            socio          TEXT,
            saldo_inicial  INTEGER NOT NULL DEFAULT 0,
            fecha_apertura DATE NOT NULL DEFAULT '2026-06-01',
            activa         BOOLEAN NOT NULL DEFAULT TRUE,
            orden          INTEGER NOT NULL DEFAULT 0,
            created_by     TEXT,
            created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_by     TEXT,
            updated_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    # Un socio = exactamente una caja (puente 1:1 con alquiler_pagos.destinatario).
    bind.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_cuentas_socio "
        "ON cuentas(socio) WHERE socio IS NOT NULL"
    ))
    # Seed: las cajas de arranque. Las dos de socio reciben los cobros derivados.
    # `Fondo Rental` (ex `Fondo Rambla`, 2026-07-29): mantiene paridad con el
    # seed de `init_db()` — mismo nombre, para que `ON CONFLICT (nombre)` siga
    # atrapando el choque en vez de crear una fila fantasma con el nombre viejo.
    bind.execute(sa.text("""
        INSERT INTO cuentas (nombre, tipo, socio, orden) VALUES
            ('Caja Tincho', 'socio', 'Tincho', 1),
            ('Caja Pablo',  'socio', 'Pablo',  2),
            ('Efectivo',    'caja',  NULL,      3),
            ('Banco',       'banco', NULL,      4),
            ('Fondo Rental','fondo', 'Rental',  5)
        ON CONFLICT (nombre) WHERE activa DO NOTHING
    """))

    # ── gasto_categorias (rubros de gasto, editables) ────────────────────────
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS gasto_categorias (
            id     SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL UNIQUE,
            activa BOOLEAN NOT NULL DEFAULT TRUE,
            orden  INTEGER NOT NULL DEFAULT 0
        )
    """))
    bind.execute(sa.text("""
        INSERT INTO gasto_categorias (nombre, orden) VALUES
            ('Alquiler local', 1), ('Sueldos', 2), ('Equipos', 3),
            ('Mantenimiento', 4), ('Impuestos', 5), ('Servicios', 6),
            ('Otros', 99)
        ON CONFLICT (nombre) DO NOTHING
    """))

    # ── movimientos (el libro único) ─────────────────────────────────────────
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS movimientos (
            id                SERIAL PRIMARY KEY,
            tipo              TEXT NOT NULL,
            monto             INTEGER NOT NULL CHECK (monto > 0),
            cuenta_origen_id  INTEGER REFERENCES cuentas(id),
            cuenta_destino_id INTEGER REFERENCES cuentas(id),
            categoria_id      INTEGER REFERENCES gasto_categorias(id),
            metodo            TEXT,
            fecha             DATE NOT NULL DEFAULT CURRENT_DATE,
            nota              TEXT,
            comprobante_url   TEXT,
            comprobante_key   TEXT,
            rendicion_mes     VARCHAR(7),
            es_rendicion      BOOLEAN NOT NULL DEFAULT FALSE,
            created_by        TEXT,
            created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_by        TEXT,
            updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            anulado           BOOLEAN NOT NULL DEFAULT FALSE,
            anulado_por       TEXT,
            anulado_at        TIMESTAMP,
            anulado_motivo    TEXT,
            CONSTRAINT mov_tiene_cuenta  CHECK (cuenta_origen_id IS NOT NULL OR cuenta_destino_id IS NOT NULL),
            CONSTRAINT mov_cuentas_distintas CHECK (cuenta_origen_id IS DISTINCT FROM cuenta_destino_id)
        )
    """))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_mov_fecha ON movimientos(fecha)"))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_mov_origen ON movimientos(cuenta_origen_id) WHERE NOT anulado"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_mov_destino ON movimientos(cuenta_destino_id) WHERE NOT anulado"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_mov_rendicion ON movimientos(rendicion_mes) WHERE es_rendicion"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    # Orden inverso por las FKs: movimientos referencia a cuentas y categorías.
    bind.execute(sa.text("DROP TABLE IF EXISTS movimientos"))
    bind.execute(sa.text("DROP TABLE IF EXISTS gasto_categorias"))
    bind.execute(sa.text("DROP TABLE IF EXISTS cuentas"))
