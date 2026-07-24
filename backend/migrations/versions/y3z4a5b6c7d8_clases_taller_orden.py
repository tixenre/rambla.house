"""clases_taller.orden: orden manual de las clases, independiente de la fecha

El admin necesita reordenar clases sin que la fecha las re-ordene sola (un
taller real puede querer que "Clase 5" sea pedagógicamente la 5ta aunque su
fecha no sea la 5ta cronológica — caso "clase 11 y 12 se dictan juntas").
`_get_clases` pasa de `ORDER BY fecha, hora_inicio_min` a `ORDER BY orden, id`;
`_insert_clases`/`_upsert_clases` escriben `orden` = posición en el array que
manda el front (nunca lo decide el front explícitamente, ya viene implícito en
el orden de la lista). Backfill: `orden` inicial = el orden por fecha/hora de
HOY, para que ninguna edición existente cambie de aspecto hasta que el admin
reordene a mano.

Espejado en init_db() (esquema en dos capas, `database/schema.py`) — SOLO la
columna, el backfill es un evento único de esta migración (repetirlo en cada
arranque de la app pisaría cualquier reorden manual ya guardado).

Revision ID: y3z4a5b6c7d8
Revises: mrgestbrescu
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op

revision: str = "y3z4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "mrgestbrescu"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS orden INTEGER NOT NULL DEFAULT 0")
    op.execute("""
        UPDATE clases_taller c
        SET orden = sub.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY edicion_id ORDER BY fecha, hora_inicio_min, id
            ) - 1 AS rn
            FROM clases_taller
        ) sub
        WHERE c.id = sub.id
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE clases_taller DROP COLUMN IF EXISTS orden")
