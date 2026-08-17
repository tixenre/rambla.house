"""taller_inscripciones_borrador: mirror de carritos_activos para el funnel
de talleres (pedido del dueño, 2026-08-13).

Heartbeat mientras alguien tipea en WorkshopInscripcionForm (nombre/email/
teléfono, lo que haya cargado hasta ahora) — el admin ve una lista real de
quién estuvo por inscribirse y no llegó, con datos de contacto para hacer
seguimiento (mismo valor que carritos_activos le da a rental). Se cierra
(`confirmado = TRUE`) cuando la inscripción real se crea.

Revision ID: tlrborrador
Revises: tlrinscsoft
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "tlrborrador"
down_revision: Union[str, Sequence[str], None] = "tlrinscsoft"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS taller_inscripciones_borrador (
            id              SERIAL PRIMARY KEY,
            session_id      TEXT NOT NULL UNIQUE,
            edicion_id      INTEGER NOT NULL REFERENCES ediciones_taller(id) ON DELETE CASCADE,
            nombre          TEXT,
            email           TEXT,
            telefono        TEXT,
            confirmado      BOOLEAN NOT NULL DEFAULT FALSE,
            abandonado_en   TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_insc_borrador_edicion "
        "ON taller_inscripciones_borrador(edicion_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS taller_inscripciones_borrador")
