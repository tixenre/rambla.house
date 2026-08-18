"""admin_backup_codes: recovery del 2º factor admin cuando se pierde el
dispositivo con la passkey (Pablo, dueño, 2026-08-15).

Una vez que una cuenta admin tiene una passkey, Google solo ya no alcanza
para entrar (2º factor obligatorio) — hasta ahora, perder ese dispositivo
dejaba a la cuenta sin salida salvo un DELETE manual en la base. Códigos
de un solo uso, generados 10 a la vez (regenerar invalida el set viejo),
hasheados (nunca en claro en la base).

Revision ID: bkupcodes2fa
Revises: tlrborrador
Create Date: 2026-08-15
"""

from typing import Sequence, Union

from alembic import op

revision: str = "bkupcodes2fa"
down_revision: Union[str, Sequence[str], None] = "tlrborrador"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS admin_backup_codes (
            id           SERIAL PRIMARY KEY,
            owner_email  TEXT NOT NULL,
            code_hash    TEXT NOT NULL,
            used_at      TIMESTAMP,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_backup_codes_email "
        "ON admin_backup_codes(LOWER(owner_email))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_backup_codes")
