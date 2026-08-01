"""solicitudes_modificacion_baja: retira la feature de solicitudes de
modificación del portal (a pedido del dueño — complejizaba el flujo del
cliente sin necesidad; en su lugar se comunica el canal de WhatsApp).

- `DROP TABLE solicitudes_modificacion` (CASCADE se lleva sus 3 índices y la
  secuencia del PK; nunca tuvo una migración de creación propia — nació en el
  baseline idempotente de `init_db()`, ya actualizado en el mismo commit).
- Borra las 3 plantillas de mail huérfanas (`modificacion_solicitada_admin`,
  `modificacion_resuelta_cliente`, `modificacion_cancelada_admin`) y el
  setting `modificacion_ventana_horas`.
- Repisa el copy de `pedido_creado_cliente`/`pedido_confirmado_cliente` con la
  mención explícita de WhatsApp para modificaciones (mismo `DEFAULT_TEMPLATES`
  que siembra `init_db()`) — mismo guard que `a7d4f1c9e2b5`: solo pisa filas
  que nunca editó un admin desde la UI (`updated_by = 'system:migration'`).

Revision ID: s0l1c1tudb4j
Revises: w1h2a3t4s5a6
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op

from services.email.default_templates import DEFAULT_TEMPLATES

revision: str = "s0l1c1tudb4j"
down_revision: Union[str, Sequence[str], None] = "w1h2a3t4s5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEMPLATES_HUERFANAS = (
    "modificacion_solicitada_admin",
    "modificacion_resuelta_cliente",
    "modificacion_cancelada_admin",
)
_TEMPLATES_REPINTADAS = ("pedido_creado_cliente", "pedido_confirmado_cliente")


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def upgrade() -> None:
    keys_sql = ", ".join(_q(k) for k in _TEMPLATES_HUERFANAS)
    op.execute(f"DELETE FROM email_templates WHERE key IN ({keys_sql})")
    op.execute("DELETE FROM app_settings WHERE key = 'modificacion_ventana_horas'")

    for key in _TEMPLATES_REPINTADAS:
        tpl = DEFAULT_TEMPLATES[key]
        op.execute(
            f"""
            UPDATE email_templates
            SET subject = {_q(tpl["subject"])},
                body_html = {_q(tpl["body_html"])},
                body_text = {_q(tpl["body_text"])},
                updated_by = 'system:migration'
            WHERE key = {_q(key)} AND updated_by = 'system:migration'
            """
        )

    op.execute("DROP TABLE IF EXISTS solicitudes_modificacion CASCADE")


def downgrade() -> None:
    # No-op: no había migración de creación para esta tabla (nació en el
    # baseline de init_db()) y el copy viejo de los 2 mails repintados queda
    # en el historial de git — no revertimos a ciegas ni recreamos una tabla
    # que el bootstrap ya no siembra (quedaría desincronizada de init_db()).
    pass
