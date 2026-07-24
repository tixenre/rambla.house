"""estudio_promo_combo_id: columna para la promo combo del Estudio (Fase 5, #1283)

`estudio.promo_combo_id` apunta al equipo tipo='combo' que reemplaza al pack
curado (`estudio_pack_equipos`/`pack_*`) — creado a demanda desde el
back-office (`POST /admin/estudio/promo/crear-desde-pack`), no acá. NULL
hasta entonces: el pack sigue siendo el mecanismo vigente (⏰ LEGACY hasta
que la Fase 8 lo retire).

Espejado en init_db() (esquema en dos capas, `database/schema.py`).

Revision ID: u9v0w1x2y3z4
Revises: t8u9v0w1x2y3
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "u9v0w1x2y3z4"
down_revision: Union[str, Sequence[str], None] = "t8u9v0w1x2y3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE estudio ADD COLUMN IF NOT EXISTS promo_combo_id "
        "INTEGER REFERENCES equipos(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE estudio DROP COLUMN IF EXISTS promo_combo_id")
