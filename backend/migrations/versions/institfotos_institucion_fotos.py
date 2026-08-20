"""Galería de fotos por institución (dueño, 2026-08-19).

Espejo exacto de `edicion_fotos`, scoped a `institucion_id` en vez de a una
edición puntual: pedido del dueño — "agregarle lo de las galerías, y que
sea por institución también, así no subo fotos repetidas" (una institución
como Filmar solo tiene una tanda de fotos, reusada por todos sus talleres,
en vez de cargarla suelta en cada uno). `es_principal` marca la foto
destacada que usa el hero público del hub de institución.

Revision ID: institfotos
Revises: droptllrhno
Create Date: 2026-08-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "institfotos"
down_revision: Union[str, Sequence[str], None] = "droptllrhno"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS institucion_fotos (
            id             SERIAL PRIMARY KEY,
            institucion_id INTEGER NOT NULL REFERENCES instituciones(id) ON DELETE CASCADE,
            url            TEXT NOT NULL,
            url_sm         TEXT,
            url_avif       TEXT,
            url_sm_avif    TEXT,
            path           TEXT,
            media_id       BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            orden          INTEGER NOT NULL DEFAULT 0,
            es_principal   BOOLEAN NOT NULL DEFAULT FALSE,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_institucion_fotos_institucion_orden "
        "ON institucion_fotos(institucion_id, orden)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS institucion_fotos")
