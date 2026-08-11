"""Escuela: `talleres.resumen` — teaser corto para la tarjeta del listado.

`descripcion` es el texto largo de la página propia del taller (pensado para
leerse completo, con su Programa). La tarjeta de `/escuelas` lo truncaba con
`line-clamp-2`, pero muchas descripciones arrancan dirigiéndose al lector
("Si llegaste hasta acá: gracias...") en vez de explicar de qué trata el
taller — un teaser inservible fuera de contexto (pedido del dueño, #og-share).

`resumen` es un campo corto y separado — mezcla "para quién es" + "de qué
trata" — pensado específicamente para esa tarjeta. `''` (default) → el front
cae a `descripcion` truncada, cero ruptura para talleres que nunca lo cargan.

En paridad con `database/schema.py::init_db()`.

Revision ID: r3s4u5m6e7n8
Revises: i1c2s3t4a5l6
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "r3s4u5m6e7n8"
down_revision: Union[str, Sequence[str], None] = "i1c2s3t4a5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(text("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS resumen TEXT NOT NULL DEFAULT ''"))


def downgrade() -> None:
    op.execute(text("ALTER TABLE talleres DROP COLUMN IF EXISTS resumen"))
