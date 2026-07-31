"""Escuela v2 F4c: cierre de inscripciones por fecha + trabajos pasados
(YouTube, sin testimonios) + FAQ editable del taller.

`ediciones_taller.fecha_cierre_inscripcion` (NULL = sin cierre, siempre
abierto). `taller_trabajos` (mismo patrón de poster que el video hero de F4a:
se descarga y guarda en R2). `talleres.faqs JSONB` — lista editable de
{pregunta, respuesta}, ninguna obligatoria.

En paridad con `database/schema.py::init_db()`.

Revision ID: esc6f7a8q9
Revises: esc5c6u7p8o
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "esc6f7a8q9"
down_revision: Union[str, Sequence[str], None] = "esc5c6u7p8o"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(text(
        "ALTER TABLE talleres ADD COLUMN IF NOT EXISTS faqs JSONB NOT NULL DEFAULT '[]'"
    ))
    op.execute(text(
        "ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS fecha_cierre_inscripcion DATE"
    ))
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS taller_trabajos (
            id                SERIAL PRIMARY KEY,
            taller_id         INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            titulo            TEXT NOT NULL DEFAULT '',
            youtube_url       TEXT NOT NULL,
            poster_media_id   BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            poster_url        TEXT NOT NULL DEFAULT '',
            orden             INTEGER NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_taller_trabajos_taller "
        "ON taller_trabajos(taller_id, orden)"
    ))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS taller_trabajos"))
    op.execute(text("ALTER TABLE ediciones_taller DROP COLUMN IF EXISTS fecha_cierre_inscripcion"))
    op.execute(text("ALTER TABLE talleres DROP COLUMN IF EXISTS faqs"))
