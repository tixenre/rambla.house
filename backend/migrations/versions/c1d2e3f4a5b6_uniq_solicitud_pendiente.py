"""uniq_solicitud_pendiente: garantizar una sola solicitud pendiente por pedido

Sin este index, dos pestañas del mismo cliente pueden pasar el check
`_check_solicitud_pendiente` en paralelo y ambas insertar una solicitud
con estado='pendiente'. El partial unique index sobre `(pedido_id)
WHERE estado='pendiente'` lo previene atómicamente a nivel DB.

Revision ID: c1d2e3f4a5b6
Revises: b7a1d9e3f4c2
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b7a1d9e3f4c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `CREATE INDEX` no admite `IF EXISTS` sobre la tabla (a diferencia de
    # `ALTER TABLE`) — se chequea en Python. La feature se retiró después
    # (`s0l1c1tudb4j`); un bootstrap fresco ya no crea esta tabla en
    # `init_db()`, así que esto no-opea ahí en vez de romper `alembic upgrade
    # head`. Prod no se ve afectado (ya corrió cuando la tabla existía).
    conn = op.get_bind()
    existe = conn.execute(text("SELECT to_regclass('solicitudes_modificacion')")).scalar()
    if existe:
        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_solicitud_pendiente_por_pedido
            ON solicitudes_modificacion (pedido_id)
            WHERE estado = 'pendiente'
            """
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uniq_solicitud_pendiente_por_pedido")
