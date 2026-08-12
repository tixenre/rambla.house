"""Galería de fotos por EDICIÓN de taller — portada + galería pública.

Espejo exacto de `estudio_fotos` (2026-05-E1) pero scoped a `edicion_id` en
vez de al singleton Estudio. Confirmado con el dueño: portada+galería son
por EDICIÓN, no por taller (a diferencia de `video_url`/`video_poster_url`,
que sí viven a nivel `talleres`) — cada edición (fechas/instructor/grupo
distintos) amerita su propia tanda de fotos. `es_principal` marca la
portada del hero público.

En paridad con `database/schema.py::init_db()`.

Revision ID: e1f2d3c4b5a6
Revises: r3s4u5m6e7n8
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "e1f2d3c4b5a6"
down_revision: Union[str, Sequence[str], None] = "r3s4u5m6e7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        text("""
            CREATE TABLE IF NOT EXISTS edicion_fotos (
                id           SERIAL PRIMARY KEY,
                edicion_id   INTEGER NOT NULL REFERENCES ediciones_taller(id) ON DELETE CASCADE,
                url          TEXT NOT NULL,
                url_sm       TEXT,
                url_avif     TEXT,
                url_sm_avif  TEXT,
                path         TEXT,
                media_id     BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
                orden        INTEGER NOT NULL DEFAULT 0,
                es_principal BOOLEAN NOT NULL DEFAULT FALSE,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_edicion_fotos_edicion_orden "
            "ON edicion_fotos(edicion_id, orden)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS edicion_fotos"))
