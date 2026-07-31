"""talleres: nuevo modelo ediciones_taller + clases_taller + interesados_taller.

Migra del modelo "una fila por edición en talleres" al modelo en tres capas:
  - talleres        = concepto del workshop (datos estables: nombre, bio, programa)
  - ediciones_taller = una fila por edición (fechas, precios, cupos, freeze)
  - clases_taller   = clases/sesiones de cada edición (reemplaza taller_sesiones)
  - interesados_taller = captación de leads cuando no hay cupos disponibles

El modelo viejo (talleres con proxima_edicion_slug) queda intacto mientras no
se actualicen las rutas (backward-compatible). La migración de datos backfilla
ediciones_taller a partir de las filas existentes en talleres.

Espeja init_db() (esquema en dos capas, MEMORIA 2026-06-03): ADD COLUMN IF NOT
EXISTS / CREATE TABLE IF NOT EXISTS → idempotente.

Revision ID: e1d2c3i4o5n6
Revises: t4ll3rs3s01
Create Date: 2026-06-27
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "e1d2c3i4o5n6"
down_revision: Union[str, Sequence[str], None] = "t4ll3rs3s01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── slug_base en talleres (identifica la raíz del concepto) ───────────────
    op.execute(
        "ALTER TABLE talleres ADD COLUMN IF NOT EXISTS slug_base VARCHAR(120)"
    )

    # ── ediciones_taller ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS ediciones_taller (
            id                SERIAL PRIMARY KEY,
            taller_id         INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            numero_edicion    INTEGER NOT NULL DEFAULT 1,
            slug              VARCHAR(120) NOT NULL UNIQUE,
            tipo_taller       TEXT NOT NULL DEFAULT 'intensivo',
            fecha_inicio      DATE NOT NULL,
            fecha_fin         DATE NOT NULL,
            horario           TEXT NOT NULL DEFAULT '',
            cupos_total       INTEGER NOT NULL DEFAULT 12,
            cupos_confirmados INTEGER NOT NULL DEFAULT 0,
            precio_total      INTEGER NOT NULL DEFAULT 0,
            precio_sena       INTEGER NOT NULL DEFAULT 0,
            pago_alias        TEXT NOT NULL DEFAULT '',
            pago_cbu          TEXT NOT NULL DEFAULT '',
            pago_banco        TEXT NOT NULL DEFAULT '',
            direccion         TEXT NOT NULL DEFAULT '',
            activo            BOOLEAN NOT NULL DEFAULT TRUE,
            snapshot          JSONB,
            frozen_at         TIMESTAMPTZ,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(taller_id, numero_edicion)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ediciones_taller_taller "
        "ON ediciones_taller(taller_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ediciones_taller_slug "
        "ON ediciones_taller(slug)"
    )

    # ── clases_taller (reemplaza taller_sesiones para ediciones) ──────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS clases_taller (
            id          SERIAL PRIMARY KEY,
            edicion_id  INTEGER NOT NULL REFERENCES ediciones_taller(id) ON DELETE CASCADE,
            fecha       DATE    NOT NULL,
            hora_inicio INTEGER NOT NULL,
            hora_fin    INTEGER NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_clases_taller_edicion "
        "ON clases_taller(edicion_id)"
    )

    # ── interesados_taller (captación de leads sin cupos disponibles) ─────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS interesados_taller (
            id            SERIAL PRIMARY KEY,
            taller_id     INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            nombre        TEXT NOT NULL,
            email         TEXT NOT NULL,
            telefono      TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            notificado_at TIMESTAMPTZ
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_interesados_taller_taller "
        "ON interesados_taller(taller_id)"
    )

    # ── Extender taller_inscripciones ─────────────────────────────────────────
    op.execute(
        "ALTER TABLE taller_inscripciones "
        "ADD COLUMN IF NOT EXISTS edicion_id INTEGER REFERENCES ediciones_taller(id)"
    )
    op.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS estado TEXT"
    )
    op.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS comprobante_resto_url TEXT"
    )
    op.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS comprobante_resto_key TEXT"
    )
    op.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS notas_admin TEXT"
    )
    op.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS sena_verificada_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS pago_completo_at TIMESTAMPTZ"
    )

    # ── F2: backfill de datos ─────────────────────────────────────────────────
    # Guard post-Escuela-v2-F6 (esc7l8i9m0p1): en una DB fresca, init_db() ya
    # crea `talleres` en su forma FINAL — sin fecha_inicio/proxima_edicion_slug/
    # el resto de columnas de edición "plana" que este backfill lee (retiradas
    # en F6) — así que no hay ninguna fila legacy de la que migrar. Mismo
    # criterio que el guard de clases_taller un poco más abajo.
    conn = op.get_bind()
    tiene_fecha_inicio = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'talleres' AND column_name = 'fecha_inicio'"
    )).fetchone() is not None

    if tiene_fecha_inicio:
        # Marcar raíces de cadena (slug no referenciado como proxima_edicion_slug)
        op.execute("""
            UPDATE talleres
            SET slug_base = slug
            WHERE slug NOT IN (
                SELECT proxima_edicion_slug FROM talleres WHERE proxima_edicion_slug != ''
            )
            AND slug_base IS NULL
        """)

        # Crear ediciones_taller a partir de cada fila de talleres.
        # Para cadenas de profundidad 2 (root → hijo): el taller_id de la edición
        # es la raíz del concepto (el que tiene slug_base seteado).
        op.execute("""
            INSERT INTO ediciones_taller (
                taller_id, numero_edicion, slug, tipo_taller,
                fecha_inicio, fecha_fin, horario,
                cupos_total, cupos_confirmados, precio_total, precio_sena,
                pago_alias, pago_cbu, pago_banco, direccion, activo
            )
            SELECT
                (
                    SELECT r.id FROM talleres r
                    WHERE r.slug_base IS NOT NULL
                      AND (r.slug = t.slug OR r.proxima_edicion_slug = t.slug)
                    LIMIT 1
                ) AS taller_id,
                t.numero_edicion, t.slug, t.tipo_taller,
                t.fecha_inicio, t.fecha_fin, t.horario,
                t.cupos_total, t.cupos_confirmados, t.precio_total, t.precio_sena,
                t.pago_alias, t.pago_cbu, t.pago_banco, t.direccion, t.activo
            FROM talleres t
            WHERE NOT EXISTS (
                SELECT 1 FROM ediciones_taller e WHERE e.slug = t.slug
            )
        """)

    # Migrar clases desde taller_sesiones (si existen).
    # Guard post-Escuela-v2-F1 (esc1m2i3n4t5): en una DB fresca, init_db() ya
    # crea clases_taller con `hora_inicio_min`/`hora_fin_min` (minutos) — el
    # CREATE IF NOT EXISTS de arriba es no-op y este backfill debe escribir a
    # las columnas que EXISTAN (regla del bootstrap dual init_db+upgrade, ver
    # test_alembic_upgrade_db). En DBs históricas (columnas viejas en horas) el
    # INSERT original sigue tal cual; esc1m2i3n4t5 las convierte después.
    conn = op.get_bind()
    tiene_viejas = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'clases_taller' AND column_name = 'hora_inicio'"
    )).fetchone() is not None
    if tiene_viejas:
        op.execute("""
            INSERT INTO clases_taller (edicion_id, fecha, hora_inicio, hora_fin)
            SELECT e.id, s.fecha, s.hora_inicio, s.hora_fin
            FROM taller_sesiones s
            JOIN talleres t ON t.id = s.taller_id
            JOIN ediciones_taller e ON e.slug = t.slug
            WHERE NOT EXISTS (
                SELECT 1 FROM clases_taller c
                WHERE c.edicion_id = e.id AND c.fecha = s.fecha
            )
        """)
    else:
        # taller_sesiones guarda HORAS enteras → ×60 al escribir en minutos.
        op.execute("""
            INSERT INTO clases_taller (edicion_id, fecha, hora_inicio_min, hora_fin_min)
            SELECT e.id, s.fecha, s.hora_inicio * 60, s.hora_fin * 60
            FROM taller_sesiones s
            JOIN talleres t ON t.id = s.taller_id
            JOIN ediciones_taller e ON e.slug = t.slug
            WHERE NOT EXISTS (
                SELECT 1 FROM clases_taller c
                WHERE c.edicion_id = e.id AND c.fecha = s.fecha
            )
        """)

    # Linkear inscripciones existentes a su edición correspondiente
    op.execute("""
        UPDATE taller_inscripciones ti
        SET
            edicion_id = e.id,
            estado = CASE
                WHEN ti.en_lista_espera THEN 'en_espera'
                ELSE 'pendiente_sena'
            END
        FROM talleres t
        JOIN ediciones_taller e ON e.slug = t.slug
        WHERE t.id = ti.taller_id
          AND ti.edicion_id IS NULL
    """)


def downgrade() -> None:
    op.execute(
        "UPDATE taller_inscripciones SET edicion_id = NULL, estado = NULL, "
        "comprobante_resto_url = NULL, comprobante_resto_key = NULL, "
        "notas_admin = NULL, confirmed_at = NULL, "
        "sena_verificada_at = NULL, pago_completo_at = NULL"
    )
    op.execute("""
        ALTER TABLE taller_inscripciones
            DROP COLUMN IF EXISTS edicion_id,
            DROP COLUMN IF EXISTS estado,
            DROP COLUMN IF EXISTS comprobante_resto_url,
            DROP COLUMN IF EXISTS comprobante_resto_key,
            DROP COLUMN IF EXISTS notas_admin,
            DROP COLUMN IF EXISTS confirmed_at,
            DROP COLUMN IF EXISTS sena_verificada_at,
            DROP COLUMN IF EXISTS pago_completo_at
    """)
    op.execute("DROP TABLE IF EXISTS interesados_taller")
    op.execute("DROP TABLE IF EXISTS clases_taller")
    op.execute("DROP TABLE IF EXISTS ediciones_taller")
    op.execute("ALTER TABLE talleres DROP COLUMN IF EXISTS slug_base")
