"""recordatorio de retiro: copy "hoy / mañana" (el aviso ya no es "N días antes")

El recordatorio pasó a depender de la HORA del retiro (ver
`jobs/recordatorios_config.py`): sale el MISMO día a la mañana, o la víspera a la
hora de cierre si el retiro es temprano. Así que `dias_antes` en el contexto ya
solo vale 0 (hoy) o 1 (mañana) — con el copy viejo, un envío del mismo día decía
"Faltan 0 días para retirar".

Repisa subject/body de `recordatorio_retiro` con el copy nuevo. Si el admin lo
había editado a mano, esta migración lo reemplaza: el texto viejo no puede
quedar (renderiza mal en el caso más común, el aviso del mismo día).

Revision ID: r3t1r0h0y2x
Revises: wa1d3st1n4t
"""
from alembic import op

revision = "r3t1r0h0y2x"
down_revision = "wa1d3st1n4t"
branch_labels = None
depends_on = None

_KEY = "recordatorio_retiro"


def upgrade() -> None:
    from services.email.default_templates import DEFAULT_TEMPLATES

    tpl = DEFAULT_TEMPLATES[_KEY]
    op.get_bind().execute(
        _sql(),
        {
            "key": _KEY,
            "subject": tpl["subject"],
            "body_html": tpl["body_html"],
            "body_text": tpl["body_text"],
        },
    )


def downgrade() -> None:
    """No revierte el copy: el texto viejo asume "N días antes", que ya no existe."""


def _sql():
    from sqlalchemy import text

    return text(
        """
        UPDATE email_templates
           SET subject    = :subject,
               body_html  = :body_html,
               body_text  = :body_text,
               updated_at = CURRENT_TIMESTAMP,
               updated_by = 'system:migration'
         WHERE key = :key
        """
    )
