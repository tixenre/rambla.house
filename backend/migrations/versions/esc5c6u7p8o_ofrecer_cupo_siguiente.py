"""Escuela v2 F4b: "ofrecer cupo al siguiente" — cuando se libera un cupo
(baja de un confirmado), el admin le manda al primero de la lista de espera
un link tokenizado para completar la seña. `cupo_ofrecido_at` NO toca
`cupos_confirmados` ni `en_lista_espera` hasta que la persona efectivamente
reclama el cupo (POST /talleres/sena/{token}) — así el admin puede
re-ofrecer a otro si no responde, sin tener que "devolver" nada.

En paridad con `database/schema.py::init_db()`.

Revision ID: esc5c6u7p8o
Revises: esc4v5i6d7e8o
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "esc5c6u7p8o"
down_revision: Union[str, Sequence[str], None] = "esc4v5i6d7e8o"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(text(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS cupo_ofrecido_at TIMESTAMPTZ"
    ))


def downgrade() -> None:
    op.execute(text("ALTER TABLE taller_inscripciones DROP COLUMN IF EXISTS cupo_ofrecido_at"))
