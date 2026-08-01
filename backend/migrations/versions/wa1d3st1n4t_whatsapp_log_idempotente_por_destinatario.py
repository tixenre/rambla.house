"""whatsapp: la idempotencia del log pasa a ser por DESTINATARIO.

El índice único era `(alquiler_id, template_key)`: un solo envío 'sent' por pedido
y plantilla. Servía mientras cada aviso tenía un único destinatario (el cliente).

Con el aviso al equipo (Pablo y Tincho reciben el MISMO template para el MISMO
pedido, cada uno a su número) esa clave es incorrecta: el segundo INSERT chocaba
contra el índice y `envio.py` lo interpretaba como "duplicado" → el segundo
integrante se quedaba sin el mensaje, en silencio.

La clave correcta incluye el número: `(alquiler_id, template_key, to_phone)`. Para
un aviso de un solo destinatario el comportamiento no cambia.

Revision ID: wa1d3st1n4t
Revises: s0l1c1tudb4j
Create Date: 2026-07-31
"""

from typing import Sequence, Union

from alembic import op

revision: str = "wa1d3st1n4t"
down_revision: Union[str, Sequence[str], None] = "s0l1c1tudb4j"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_whatsapp_log_idempotente")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_log_idempotente
        ON whatsapp_log(alquiler_id, template_key, to_phone)
        WHERE status = 'sent'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_whatsapp_log_idempotente")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_log_idempotente
        ON whatsapp_log(alquiler_id, template_key)
        WHERE status = 'sent'
    """)
