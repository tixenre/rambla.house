"""estudio_anticipacion_pintura: anticipación propia del add-on "recién pintado" (#1300 seguimiento)

`estudio.anticipacion_pintura_horas` — pintar/secar el ciclorama necesita más
lead time que una reserva común, independiente de `anticipacion_min_horas`
(se exige ADEMÁS, no en su lugar). 0 = sin restricción extra.

Espejado en init_db() (esquema en dos capas, `database/schema.py`).

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "k6l7m8n9o0p1"
down_revision: Union[str, Sequence[str], None] = "j5k6l7m8n9o0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE estudio ADD COLUMN IF NOT EXISTS anticipacion_pintura_horas "
        "INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE estudio DROP COLUMN IF EXISTS anticipacion_pintura_horas")
