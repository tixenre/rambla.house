"""Escuela v2: instituciones como entidad propia (N↔N con talleres).

Mismo patrón que `instructores`/`taller_instructores` (esc3n4t5r6u7): un
taller puede tener varias instituciones co-presentadoras (ej. "Rambla" +
"Filmar"), y una institución puede co-presentar varios talleres. A
diferencia de instructores, sin `rol`/`proyectos` (no aplican a una
organización) y sin `activo` (quedó vestigial en instructores — no se
copia un campo que no rinde).

Revision ID: a5b6c7d8e9f0
Revises: y3z4a5b6c7d8
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, Sequence[str], None] = "y3z4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS instituciones (
            id            SERIAL PRIMARY KEY,
            nombre        TEXT NOT NULL,
            descripcion   TEXT NOT NULL DEFAULT '',
            instagram     TEXT NOT NULL DEFAULT '',
            web           TEXT NOT NULL DEFAULT '',
            logo_media_id BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            logo_url      TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS taller_instituciones (
            taller_id      INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            institucion_id INTEGER NOT NULL REFERENCES instituciones(id) ON DELETE CASCADE,
            orden          INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (taller_id, institucion_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_instituciones_taller "
        "ON taller_instituciones(taller_id, orden)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_instituciones_institucion "
        "ON taller_instituciones(institucion_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS taller_instituciones")
    op.execute("DROP TABLE IF EXISTS instituciones")
