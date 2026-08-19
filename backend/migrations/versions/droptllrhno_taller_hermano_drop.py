"""Remueve taller_hermano_id/taller_hermano_titulo (dueño, 2026-08-19).

El mecanismo de "pareja" de exactamente 2 talleres se reemplaza por el hub
de institución (`/escuelas/instituciones/$slug`, ya existente): 2+ talleres
en la MISMA institución arman el hero compartido con selector, N-way — no
solo pares — y sin necesitar un segundo vínculo aparte. Pedido explícito
del dueño: "sacaría lo de talleres hermanos... esa página compartida lo
haría cuando seleccionás la institución". Ver `_resolver_hermano`/
`TituloPareja`/`MitadPareja` retirados en el mismo commit (routes/talleres.py,
TallerHero.tsx) — reemplazados por `InstitucionHeroMultiple`.

No downgrade con datos: los vínculos existentes (`taller_hermano_id`) no
tienen a dónde volver una vez que se borró el código que los leía.

Revision ID: droptllrhno
Revises: institucslug
Create Date: 2026-08-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "droptllrhno"
down_revision: Union[str, Sequence[str], None] = "institucslug"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE talleres DROP COLUMN IF EXISTS taller_hermano_id")
    op.execute("ALTER TABLE talleres DROP COLUMN IF EXISTS taller_hermano_titulo")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE talleres ADD COLUMN IF NOT EXISTS taller_hermano_id INTEGER "
        "REFERENCES talleres(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE talleres ADD COLUMN IF NOT EXISTS taller_hermano_titulo TEXT "
        "NOT NULL DEFAULT ''"
    )
