"""Modalidades de pago: n_cuotas — el monto por cuota se deriva, no se tipea.

Antes `edicion_modalidades_pago` solo tenía `monto_total` (cargado a mano por
el admin) y el "N cuotas de $X" vivía como texto libre en `label`/`nota`, sin
ninguna relación aritmética con `monto_total` — un admin podía escribir
"4 cuotas de $80.000" con un total de $320.000 o de $500.000, sin que nada lo
chequeara. `n_cuotas` (default 1 = pago único, no rompe nada existente) deja
que el backend derive `monto_cuota = round(monto_total / n_cuotas)` — el
público ve el monto por cuota calculado, nunca tipeado.

En paridad con `database/schema.py::init_db()`.

Revision ID: cu0t4sp4g0
Revises: e1f2d3c4b5a6
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "cu0t4sp4g0"
down_revision: Union[str, Sequence[str], None] = "e1f2d3c4b5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        text(
            "ALTER TABLE edicion_modalidades_pago "
            "ADD COLUMN IF NOT EXISTS n_cuotas INTEGER NOT NULL DEFAULT 1"
        )
    )


def downgrade() -> None:
    op.execute(text("ALTER TABLE edicion_modalidades_pago DROP COLUMN IF EXISTS n_cuotas"))
