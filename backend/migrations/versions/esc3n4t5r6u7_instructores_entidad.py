"""Escuela v2 F3: instructores como entidad propia (N↔N con talleres).

Antes un "instructor" era solo texto suelto en `talleres.instructor_nombre/
bio/proyectos` + una foto — un taller, un instructor. El taller de Filmar
tiene el mismo instructor dando 2 niveles (Principiante y Avanzado), y en
general un taller puede tener varios instructores. Se modela como entidad:
`instructores` (nombre/rol/descripcion/instagram/web/foto) + `taller_instructores`
(N↔N con orden).

Backfill: por cada `talleres` con `instructor_nombre` no vacío, crea o reusa
(dedup EXACTO por nombre) una fila en `instructores` con bio→descripcion y
foto_media_id/foto_url copiados, y la linkea (orden 0). Las columnas
`instructor_*` de `talleres` NO se tocan — quedan servidas como legacy hasta
la limpieza de F6 (doble lectura deliberada mientras el front migra).

Deviación del plan original: NO se re-apunta el kind de media "instructor"
(entity_id=taller_id, usado por la foto legacy) — la entidad nueva usa un kind
propio "instructor-perfil" (entity_id=instructor.id). Reusar el mismo kind con
semántica de entity_id distinta arriesgaba romper el flujo legacy en
producción sin necesidad; separar es más seguro y el costo es solo un kind más
en `_KIND_HANDLERS`, que de todos modos muere en F6 junto al resto.

En paridad con `database/schema.py::init_db()`.

Revision ID: esc3n4t5r6u7
Revises: esc2r3i4c5a6
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "esc3n4t5r6u7"
down_revision: Union[str, Sequence[str], None] = "esc2r3i4c5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS instructores (
            id            SERIAL PRIMARY KEY,
            nombre        TEXT NOT NULL,
            rol           TEXT NOT NULL DEFAULT '',
            descripcion   TEXT NOT NULL DEFAULT '',
            instagram     TEXT NOT NULL DEFAULT '',
            web           TEXT NOT NULL DEFAULT '',
            foto_media_id BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            foto_url      TEXT NOT NULL DEFAULT '',
            activo        BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS taller_instructores (
            taller_id     INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            instructor_id INTEGER NOT NULL REFERENCES instructores(id) ON DELETE CASCADE,
            orden         INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (taller_id, instructor_id)
        )
    """))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_taller_instructores_taller "
        "ON taller_instructores(taller_id, orden)"
    ))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_taller_instructores_instructor "
        "ON taller_instructores(instructor_id)"
    ))

    # Backfill: crear/reusar instructor por nombre EXACTO + linkear. Idempotente
    # (WHERE NOT EXISTS en el link; el INSERT de instructor está gateado por
    # "no existe ya uno con ese nombre EXACTO" para no duplicar en un re-run).
    #
    # DISTINCT ON (no DISTINCT plano) por `instructor_nombre`: dos talleres con
    # el MISMO instructor pero bio/foto que difieren aunque sea un carácter
    # (ej. un typo corregido en uno y no en el otro) generaban 2 filas — DISTINCT
    # dedupea por la combinación de las 4 columnas, no por el nombre. Desempate
    # determinístico por `t.id` ASC (el taller más viejo con ese nombre gana).
    #
    # Guard post-Escuela-v2-F6 (esc7l8i9m0p1): en una DB fresca, init_db() ya
    # crea `talleres` sin `instructor_nombre` (retirada en F6) — no hay nada de
    # qué leer (esc7l8i9m0p1 re-corre esta misma lógica sobre datos reales).
    conn = op.get_bind()
    tiene_instructor_nombre = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'talleres' AND column_name = 'instructor_nombre'"
    )).fetchone() is not None

    if tiene_instructor_nombre:
        op.execute(text("""
            INSERT INTO instructores (nombre, descripcion, foto_media_id, foto_url)
            SELECT DISTINCT ON (t.instructor_nombre)
                   t.instructor_nombre, t.instructor_bio,
                   t.instructor_media_id, t.instructor_foto_url
            FROM talleres t
            WHERE t.instructor_nombre != ''
              AND NOT EXISTS (
                  SELECT 1 FROM instructores i WHERE i.nombre = t.instructor_nombre
              )
            ORDER BY t.instructor_nombre, t.id
        """))
        op.execute(text("""
            INSERT INTO taller_instructores (taller_id, instructor_id, orden)
            SELECT t.id, i.id, 0
            FROM talleres t
            JOIN instructores i ON i.nombre = t.instructor_nombre
            WHERE t.instructor_nombre != ''
              AND NOT EXISTS (
                  SELECT 1 FROM taller_instructores ti
                  WHERE ti.taller_id = t.id AND ti.instructor_id = i.id
              )
        """))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS taller_instructores"))
    op.execute(text("DROP TABLE IF EXISTS instructores"))
    # Los datos backfilleados se pierden con las tablas; la fuente
    # talleres.instructor_* sigue intacta → reversible de verdad.
