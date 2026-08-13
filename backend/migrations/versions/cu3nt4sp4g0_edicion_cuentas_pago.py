"""Cuentas de cobro por edición: lista (0+), independiente de la forma de pago.

Nueva tabla `edicion_cuentas_pago` (mismo patrón que `edicion_modalidades_pago`,
sin codigo/monto/n_cuotas — solo alias/cbu/banco). Reemplaza a
`ediciones_taller.pago_alias/pago_cbu/pago_banco` como lo que el admin edita y
el público ve; esas 3 columnas quedan sin tocar (compatibilidad con scripts/
tests existentes) pero se traspasan acá como primera fila de cada edición que
ya tuviera algún dato cargado, para no perder configuración real.

Revision ID: cu3nt4sp4g0
Revises: cu0t4sp4g0
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "cu3nt4sp4g0"
down_revision: Union[str, Sequence[str], None] = "cu0t4sp4g0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS edicion_cuentas_pago (
                id          SERIAL PRIMARY KEY,
                edicion_id  INTEGER NOT NULL REFERENCES ediciones_taller(id) ON DELETE CASCADE,
                orden       INTEGER NOT NULL DEFAULT 0,
                alias       TEXT NOT NULL DEFAULT '',
                cbu         TEXT NOT NULL DEFAULT '',
                banco       TEXT NOT NULL DEFAULT '',
                created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_edicion_cuentas_pago_edicion "
            "ON edicion_cuentas_pago(edicion_id, orden)"
        )
    )
    # Traspaso de datos: una fila por edición que ya tuviera alias/cbu/banco
    # cargado — nunca al revés, esta migración no toca las columnas viejas.
    op.execute(
        text(
            """
            INSERT INTO edicion_cuentas_pago (edicion_id, orden, alias, cbu, banco)
            SELECT id, 0, pago_alias, pago_cbu, pago_banco
            FROM ediciones_taller
            WHERE pago_alias != '' OR pago_cbu != '' OR pago_banco != ''
            """
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS edicion_cuentas_pago"))
