"""whatsapp: tabla whatsapp_log + opt-in por cliente.

Canal WhatsApp Business (Meta Cloud API). Espeja el esquema de dos capas: esto
también vive en `database/schema.py::init_db()` (idempotente). El índice único
parcial de `whatsapp_log` da idempotencia por pedido (un envío 'sent' por
(alquiler_id, template_key)); `clientes.whatsapp_opt_in` es el consentimiento
demostrable que exige Meta (default FALSE).

Revision ID: w1h2a3t4s5a6
Revises: 23aa6949d4df
Create Date: 2026-07-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "w1h2a3t4s5a6"
# Se re-encadena sobre la punta de `dev` en cada merge (antes `t3l3f0n0bkfl`, luego
# `s0l1c1t4d0e5`, hoy `23aa6949d4df`): la rama de WhatsApp vive fuera de `dev` y su
# migración tiene que quedar ÚLTIMA, si no quedan cabezas divergentes. El upgrade es
# idempotente (`IF NOT EXISTS`) e independiente de lo que traiga dev → correr al
# final es seguro.
down_revision: Union[str, Sequence[str], None] = "23aa6949d4df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_log (
            id           BIGSERIAL PRIMARY KEY,
            to_phone     TEXT NOT NULL,
            template_key TEXT NOT NULL,
            alquiler_id  INTEGER REFERENCES alquileres(id) ON DELETE SET NULL,
            status       TEXT NOT NULL,
            wamid        TEXT,
            error        TEXT,
            sent_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_whatsapp_log_alquiler ON whatsapp_log(alquiler_id)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_log_idempotente
        ON whatsapp_log(alquiler_id, template_key)
        WHERE status = 'sent'
    """)
    op.execute(
        "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS whatsapp_opt_in BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS whatsapp_opt_in_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE clientes DROP COLUMN IF EXISTS whatsapp_opt_in_at")
    op.execute("ALTER TABLE clientes DROP COLUMN IF EXISTS whatsapp_opt_in")
    op.execute("DROP TABLE IF EXISTS whatsapp_log")
