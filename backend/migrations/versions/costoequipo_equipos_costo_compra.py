"""equipos.costo_compra: costo de compra del equipo, para rentabilidad neta en Estadísticas

Columna nueva, nullable, puramente aditiva. Distinta de `valor_reposicion` (estimación para
seguros, ya existente) — esta es lo que costó COMPRAR el equipo, cargada a mano por el dueño.
NULL = todavía no cargado; el ranking de rentabilidad neta (ingreso − costo) de Estadísticas
solo cuenta los equipos que ya la tengan.

Espejado en init_db() (esquema en dos capas, `database/schema.py`).

Revision ID: costoequipo
Revises: turnoestudio
Create Date: 2026-08-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "costoequipo"
down_revision: Union[str, Sequence[str], None] = "turnoestudio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS costo_compra INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE equipos DROP COLUMN IF EXISTS costo_compra")
