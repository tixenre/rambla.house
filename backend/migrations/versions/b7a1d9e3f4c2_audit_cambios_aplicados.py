"""audit_cambios_aplicados: registra qué se aplicó realmente al aprobar una solicitud

Cuando el admin aprueba con contrapropuesta (`cambios_override`), hoy se pierde
el rastro de qué terminó aplicándose — `cambios_json` sigue siendo la propuesta
original del cliente. Esta columna persiste el snapshot real aplicado, para
soporte y debugging.

Revision ID: b7a1d9e3f4c2
Revises: b6f8d3e5a2c1
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b7a1d9e3f4c2"
down_revision: Union[str, Sequence[str], None] = "b6f8d3e5a2c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `IF EXISTS`: la feature se retiró después (`s0l1c1tudb4j`) — un bootstrap
    # fresco ya no crea esta tabla en `init_db()`, así que esto no-opea ahí en
    # vez de romper `alembic upgrade head`. Prod no se ve afectado (ya corrió).
    op.execute(
        "ALTER TABLE IF EXISTS solicitudes_modificacion "
        "ADD COLUMN IF NOT EXISTS cambios_aplicados JSONB"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE IF EXISTS solicitudes_modificacion DROP COLUMN IF EXISTS cambios_aplicados"
    )
