"""pedido_principal_id: vincula un turno del Estudio a su pedido de alquiler (#1308)

`alquileres.pedido_principal_id` (self-FK, nullable) deja que un turno del
Estudio (tipo='estudio') creado desde la página de un pedido de alquiler
normal (tipo='diaria') quede vinculado a ese pedido — dos registros (fechas
con significado incompatible: rango vs. franja horaria) administrados en una
sola pantalla. ON DELETE SET NULL: borrar el pedido principal no borra el
turno, solo lo desvincula.

Espejado en init_db() (esquema en dos capas, `database/schema.py`).

Revision ID: pv1nc2l3a4d5
Revises: k6l7m8n9o0p1
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "pv1nc2l3a4d5"
down_revision: Union[str, Sequence[str], None] = "k6l7m8n9o0p1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS pedido_principal_id "
        "INTEGER REFERENCES alquileres(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pedidos_principal ON alquileres(pedido_principal_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pedidos_principal")
    op.execute("ALTER TABLE alquileres DROP COLUMN IF EXISTS pedido_principal_id")
