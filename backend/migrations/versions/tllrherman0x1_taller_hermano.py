"""taller_hermano: pareja de marketing entre dos talleres (dueño, 2026-08-17).

Dos talleres lanzados juntos ("van de la mano en el marketing") comparten un
solo link en redes — cada uno sigue siendo un concepto independiente, con su
propia página/formulario. El Hero de cualquiera de los dos muestra un
mini-selector hacia el otro. `taller_hermano_id` se resuelve SIMÉTRICO desde
el lado que lo tenga seteado (ver `_resolver_hermano` en routes/talleres.py)
— no hace falta setearlo en los 2 lados. `taller_hermano_titulo` es un copy
corto opcional de esa campaña; '' → el header muestra solo los 2 nombres.

Revision ID: tllrherman0x1
Revises: bkupcodes2fa
Create Date: 2026-08-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "tllrherman0x1"
down_revision: Union[str, Sequence[str], None] = "bkupcodes2fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE talleres ADD COLUMN IF NOT EXISTS taller_hermano_id INTEGER "
        "REFERENCES talleres(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE talleres ADD COLUMN IF NOT EXISTS taller_hermano_titulo TEXT "
        "NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE talleres DROP COLUMN IF EXISTS taller_hermano_titulo")
    op.execute("ALTER TABLE talleres DROP COLUMN IF EXISTS taller_hermano_id")
