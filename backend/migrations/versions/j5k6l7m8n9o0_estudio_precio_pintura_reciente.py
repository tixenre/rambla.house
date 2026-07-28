"""estudio_precio_pintura_reciente: precio del add-on "recién pintado" (#1300 seguimiento)

`estudio.precio_pintura_reciente` es un cargo fijo opcional, independiente de la
promo/sueltos — el cliente lo tilda aparte en el checkout público, no reemplaza
ninguna de las dos opciones de "¿Qué reservás?". 0 = todavía no lo cargó el
dueño (el checkbox sigue mostrándose, sin costo).

Espejado en init_db() (esquema en dos capas, `database/schema.py`).

Revision ID: j5k6l7m8n9o0
Revises: c6d7e8f9a0b1
Create Date: 2026-07-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "j5k6l7m8n9o0"
down_revision: Union[str, Sequence[str], None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE estudio ADD COLUMN IF NOT EXISTS precio_pintura_reciente "
        "INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE estudio DROP COLUMN IF EXISTS precio_pintura_reciente")
