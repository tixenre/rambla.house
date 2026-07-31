"""whatsapp_log: columnas de estado de entrega REAL (webhook)

Antes de esto, `whatsapp_log.status='sent'` solo decía que Meta ACEPTÓ el envío
(la request HTTP devolvió un `wamid`) — no que el mensaje llegó al teléfono del
cliente. El webhook de Meta (`services/whatsapp/webhook.py`) recién ahora puede
completar el estado real (delivered/read/failed) que llega asincrónicamente.

`status` NO se toca: esa columna sostiene el índice único de idempotencia
(`idx_whatsapp_log_idempotente`, `WHERE status='sent'`) — pisarla con el estado
de entrega la sacaría del índice y reabriría la puerta a un duplicado. Son
columnas nuevas, siempre nullable (un envío sin webhook configurado simplemente
nunca las completa — no rompe nada).

Revision ID: w3bh00k1nb0x
Revises: r3t1r0h0y2x
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op

revision: str = "w3bh00k1nb0x"
down_revision: Union[str, Sequence[str], None] = "r3t1r0h0y2x"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE whatsapp_log ADD COLUMN IF NOT EXISTS delivery_status TEXT")
    op.execute("ALTER TABLE whatsapp_log ADD COLUMN IF NOT EXISTS delivery_error TEXT")
    op.execute("ALTER TABLE whatsapp_log ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE whatsapp_log DROP COLUMN IF EXISTS delivered_at")
    op.execute("ALTER TABLE whatsapp_log DROP COLUMN IF EXISTS delivery_error")
    op.execute("ALTER TABLE whatsapp_log DROP COLUMN IF EXISTS delivery_status")
