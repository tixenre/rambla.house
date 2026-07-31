"""Escuela v2 F4a: video hero (YouTube) del concepto + modalidades de pago por edición.

Video: `talleres.video_url` + `video_poster_media_id`/`video_poster_url`. Mismo
extractor que `estudio_trabajos` (services.media.youtube.extract_video_id),
pero acá el poster SÍ se descarga y se guarda en R2 (store_youtube_poster) —
es contenido sobre-el-pliegue (hero de la landing), no una card en un grid más
abajo: vale la mejora de LCP de no pegarle a img.youtube.com en cada visita.

Modalidades de pago: `edicion_modalidades_pago` (una fila por opción — "3
cuotas", "un pago con descuento", "ex alumnos"). Montos finales cargados a
mano por el admin — cero motor de descuentos real, los "%" de ahorro son
texto libre en `nota`. Snapshot en `taller_inscripciones.modalidad_*` al
inscribirse (mismo criterio que el precio de línea de un pedido: congelado).
Sin modalidades configuradas, el público ve un fallback sintético de 1 sola
opción ("Pago total" = precio_total) — cero ruptura para ediciones existentes
(Jime nunca las configura y sigue funcionando igual).

En paridad con `database/schema.py::init_db()`.

Revision ID: esc4v5i6d7e8o
Revises: esc3n4t5r6u7
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "esc4v5i6d7e8o"
down_revision: Union[str, Sequence[str], None] = "esc3n4t5r6u7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(text(
        "ALTER TABLE talleres ADD COLUMN IF NOT EXISTS video_url TEXT NOT NULL DEFAULT ''"
    ))
    op.execute(text(
        "ALTER TABLE talleres ADD COLUMN IF NOT EXISTS video_poster_media_id "
        "BIGINT REFERENCES media_assets(id) ON DELETE SET NULL"
    ))
    op.execute(text(
        "ALTER TABLE talleres ADD COLUMN IF NOT EXISTS video_poster_url TEXT NOT NULL DEFAULT ''"
    ))

    op.execute(text("""
        CREATE TABLE IF NOT EXISTS edicion_modalidades_pago (
            id          SERIAL PRIMARY KEY,
            edicion_id  INTEGER NOT NULL REFERENCES ediciones_taller(id) ON DELETE CASCADE,
            orden       INTEGER NOT NULL DEFAULT 0,
            codigo      TEXT NOT NULL,
            label       TEXT NOT NULL,
            nota        TEXT NOT NULL DEFAULT '',
            monto_total INTEGER NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(edicion_id, codigo)
        )
    """))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_edicion_modalidades_pago_edicion "
        "ON edicion_modalidades_pago(edicion_id, orden)"
    ))

    op.execute(text(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS modalidad_codigo TEXT"
    ))
    op.execute(text(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS modalidad_label TEXT"
    ))
    op.execute(text(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS modalidad_monto INTEGER"
    ))


def downgrade() -> None:
    op.execute(text("ALTER TABLE taller_inscripciones DROP COLUMN IF EXISTS modalidad_monto"))
    op.execute(text("ALTER TABLE taller_inscripciones DROP COLUMN IF EXISTS modalidad_label"))
    op.execute(text("ALTER TABLE taller_inscripciones DROP COLUMN IF EXISTS modalidad_codigo"))
    op.execute(text("DROP TABLE IF EXISTS edicion_modalidades_pago"))
    op.execute(text("ALTER TABLE talleres DROP COLUMN IF EXISTS video_poster_url"))
    op.execute(text("ALTER TABLE talleres DROP COLUMN IF EXISTS video_poster_media_id"))
    op.execute(text("ALTER TABLE talleres DROP COLUMN IF EXISTS video_url"))
