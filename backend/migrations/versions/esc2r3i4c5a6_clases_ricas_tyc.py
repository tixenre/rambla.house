"""Escuela v2 F2: clases ricas (titulo/descripcion/nota/portada) + T&C + textos del taller.

La clase deja de ser solo {fecha, horario}: gana el CONTENIDO de marketing que
muestra la landing (título, descripción/temario, nota, portada). El taller gana
`terminos` (T&C propios; '' → linkea /terminos general), `beneficios`,
`pregunta_experiencia` (label configurable del form; '' → default actual) y
`mensaje_confirmacion` (post-inscripción; mata el copy hardcodeado de WhatsApp).
La inscripción gana `tyc_aceptado_at` (checkbox del form v2; la exigencia se
activa con el form nuevo en F5 — cableado-apagado hasta entonces).

Backfill: para cada edición de un taller con `programa_teorica`/`programa_practica`
y EXACTAMENTE 2 clases sin título (el caso real: Jime), la primera clase toma
"Clase teórica" + los bullets de teórica y la segunda "Clase práctica" + los de
práctica (un bullet por línea). Idempotente (WHERE titulo = ''). Los talleres
que no matcheen quedan sin contenido por clase — el front tiene fallback legacy
hasta F6.

Los borradores (ediciones nacen activo=FALSE) no necesitan schema — reusan el
flag `activo` existente; el cambio de default es de código.

En paridad con `database/schema.py::init_db()`.

Revision ID: esc2r3i4c5a6
Revises: esc1m2i3n4t5
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "esc2r3i4c5a6"
down_revision: Union[str, Sequence[str], None] = "esc1m2i3n4t5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Clases ricas
    op.execute(text("ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS titulo TEXT NOT NULL DEFAULT ''"))
    op.execute(text("ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS descripcion TEXT NOT NULL DEFAULT ''"))
    op.execute(text("ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS nota TEXT NOT NULL DEFAULT ''"))
    op.execute(text(
        "ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS portada_media_id BIGINT "
        "REFERENCES media_assets(id) ON DELETE SET NULL"
    ))
    op.execute(text("ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS portada_url TEXT NOT NULL DEFAULT ''"))

    # Textos del taller + T&C
    op.execute(text("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS terminos TEXT NOT NULL DEFAULT ''"))
    op.execute(text("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS beneficios TEXT NOT NULL DEFAULT ''"))
    op.execute(text("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS pregunta_experiencia TEXT NOT NULL DEFAULT ''"))
    op.execute(text("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS mensaje_confirmacion TEXT NOT NULL DEFAULT ''"))

    # T&C aceptados en la inscripción
    op.execute(text("ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS tyc_aceptado_at TIMESTAMPTZ"))

    # Backfill Jime: ediciones con exactamente 2 clases sin título + programas legacy.
    # array_to_string sobre el JSONB → un bullet por línea (el formato que el
    # admin edita en textarea y la landing splitea).
    #
    # Guard post-Escuela-v2-F6 (esc7l8i9m0p1): en una DB fresca, init_db() ya
    # crea `talleres` sin `programa_teorica`/`programa_practica` (retiradas en
    # F6) — no hay nada de qué leer. (De cualquier forma esta guarda de arriba
    # -COUNT(*) = 2- nunca matcheó en la práctica contra datos reales: ninguna
    # migración anterior insertó esas 2 filas vacías; el backfill real de F6
    # las inserta directo, ver esc7l8i9m0p1.)
    conn = op.get_bind()
    tiene_programa = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'talleres' AND column_name = 'programa_teorica'"
    )).fetchone() is not None

    if tiene_programa:
        op.execute(text(
            """
            WITH candidatas AS (
                SELECT e.id AS edicion_id, t.programa_teorica, t.programa_practica
                FROM ediciones_taller e
                JOIN talleres t ON t.id = e.taller_id
                WHERE jsonb_array_length(t.programa_teorica) > 0
                  AND (SELECT COUNT(*) FROM clases_taller c WHERE c.edicion_id = e.id) = 2
                  AND NOT EXISTS (
                      SELECT 1 FROM clases_taller c
                      WHERE c.edicion_id = e.id AND c.titulo != ''
                  )
            ),
            ordenadas AS (
                SELECT c.id, c.edicion_id,
                       ROW_NUMBER() OVER (PARTITION BY c.edicion_id ORDER BY c.fecha, c.hora_inicio_min) AS pos
                FROM clases_taller c
                JOIN candidatas ca ON ca.edicion_id = c.edicion_id
            )
            UPDATE clases_taller c
            SET titulo = CASE o.pos WHEN 1 THEN 'Clase teórica' ELSE 'Clase práctica' END,
                descripcion = CASE o.pos
                    WHEN 1 THEN (
                        SELECT COALESCE(string_agg(x.v, E'\n'), '')
                        FROM candidatas ca2,
                             LATERAL jsonb_array_elements_text(ca2.programa_teorica) AS x(v)
                        WHERE ca2.edicion_id = o.edicion_id
                    )
                    ELSE (
                        SELECT COALESCE(string_agg(x.v, E'\n'), '')
                        FROM candidatas ca2,
                             LATERAL jsonb_array_elements_text(ca2.programa_practica) AS x(v)
                        WHERE ca2.edicion_id = o.edicion_id
                    )
                END
            FROM ordenadas o
            WHERE c.id = o.id
            """
        ))


def downgrade() -> None:
    op.execute(text("ALTER TABLE taller_inscripciones DROP COLUMN IF EXISTS tyc_aceptado_at"))
    op.execute(text("ALTER TABLE talleres DROP COLUMN IF EXISTS mensaje_confirmacion"))
    op.execute(text("ALTER TABLE talleres DROP COLUMN IF EXISTS pregunta_experiencia"))
    op.execute(text("ALTER TABLE talleres DROP COLUMN IF EXISTS beneficios"))
    op.execute(text("ALTER TABLE talleres DROP COLUMN IF EXISTS terminos"))
    op.execute(text("ALTER TABLE clases_taller DROP COLUMN IF EXISTS portada_url"))
    op.execute(text("ALTER TABLE clases_taller DROP COLUMN IF EXISTS portada_media_id"))
    op.execute(text("ALTER TABLE clases_taller DROP COLUMN IF EXISTS nota"))
    op.execute(text("ALTER TABLE clases_taller DROP COLUMN IF EXISTS descripcion"))
    op.execute(text("ALTER TABLE clases_taller DROP COLUMN IF EXISTS titulo"))
    # (Los datos backfilleados se pierden con las columnas; la fuente
    # programa_teorica/practica sigue intacta hasta F6 → reversible de verdad.)
