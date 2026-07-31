"""Escuela v2 F6: limpieza legacy — taller_sesiones, columnas de edición duplicadas,
programa_teorica/practica, instructor_* de `talleres`.

Cierra la migración en fases de Escuela v2: `ediciones_taller` es la fuente única de
fechas/precio/cupos/pago/dirección/tipo desde F1, `instructores`+`taller_instructores`
la de instructor(es) desde F3, `clases_taller` la de contenido de clase desde F2 — las
columnas legacy de `talleres` quedaban servidas EN PARALELO a propósito mientras el
front/admin migraban. Esta migración las retira, en 3 pasos, EN ORDEN:

1. `instructores.proyectos` (nuevo) + re-correr el backfill de F3 (esc3n4t5r6u7):
   cualquier concepto creado DESPUÉS de esa migración (2026-07-23) seguía escribiendo
   `talleres.instructor_nombre` sin disparar el backfill — esto cierra ese gap antes
   de dropear la columna fuente. Idempotente (mismo WHERE NOT EXISTS del original).

2. Backfill de `clases_taller` para ediciones con clases VACÍAS que todavía tienen
   contenido en `programa_teorica`/`programa_practica`. El backfill de F2
   (esc2r3i4c5a6) exigía EXACTAMENTE 2 clases pre-existentes sin título como
   precondición — pero NINGUNA migración anterior insertó esas 2 filas vacías para
   talleres pre-existentes (t4ll3rs3s01 solo crea la tabla `taller_sesiones`, nunca
   la llena retroactivamente), así que esa guarda nunca pudo matchear y el backfill
   quedó muerto desde el día uno. Talleres reales (Jime, ambas ediciones) llegan a
   esta migración con `clases_taller` vacío y el programa vivo solo en
   `programa_teorica`/`practica` — sin este paso, dropear esas columnas below borraría
   contenido real sin dejar rastro en ningún lado. El horario de cada clase sintética
   se resuelve con un parser best-effort de `ediciones_taller.horario` (texto libre
   tipo "9 a 13 hs" / "8:30 a 12:30"); sin match, cae a (0, 0) — mismo placeholder que
   ya usaba el fallback del front `clasesDesdeLegacy` (se borra en este mismo PR).

3. DROP de `taller_sesiones` (cero lectores vivos — confirmado: solo el CREATE TABLE
   propio + el backfill histórico YA EJECUTADO de e1d2c3i4o5n6) y de las columnas
   legacy de `talleres` (instructor_*, programa_*, y las 13 columnas de edición
   duplicadas: fechas/horario/cupos/precios/pago/dirección/tipo/numero_edicion/
   proxima_edicion_slug — todas con su fuente única viva en `ediciones_taller` desde
   F1). `talleres.activo`/`slug_base` NO se tocan (semántica propia, ver
   docs/MEMORIA.md 2026-07-23 — Escuela v2 F6).

En paridad con `database/schema.py::init_db()` (el seed de Jime + las columnas legacy
se retiran ahí en el mismo commit).

Revision ID: esc7l8i9m0p1
Revises: esc6f7a8q9
Create Date: 2026-07-23
"""
import re
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "esc7l8i9m0p1"
down_revision: Union[str, Sequence[str], None] = "esc6f7a8q9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HORARIO_RE = re.compile(r"(\d{1,2})(?:[:.](\d{2}))?\s*(?:a|hasta|-)\s*(\d{1,2})(?:[:.](\d{2}))?")


def _parse_horario(horario: str) -> tuple[int, int]:
    """Best-effort 'HH[:MM] a HH[:MM]' → minutos desde medianoche. Sin match o
    rango inválido → (0, 0), el mismo placeholder que usaba el fallback legacy
    del front (`clasesDesdeLegacy`, retirado en este PR)."""
    m = _HORARIO_RE.search(horario or "")
    if not m:
        return (0, 0)
    h1, m1, h2, m2 = m.groups()
    ini = int(h1) * 60 + int(m1 or 0)
    fin = int(h2) * 60 + int(m2 or 0)
    if not (0 <= ini < fin <= 1440):
        return (0, 0)
    return (ini, fin)


def upgrade() -> None:
    # ── 1) instructores.proyectos + re-correr backfill de F3 ─────────────────
    op.execute(text(
        "ALTER TABLE instructores ADD COLUMN IF NOT EXISTS proyectos TEXT NOT NULL DEFAULT ''"
    ))

    conn = op.get_bind()

    # Guard: en una DB fresca (init_db()-first), `talleres.instructor_nombre`
    # nunca llegó a existir (el seed de t1a2l3l4e5r6 y el backfill original de
    # esc3n4t5r6u7 ya se saltean solos por el mismo motivo) — no hay nada de
    # qué re-correr el backfill.
    tiene_instructor_nombre = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'talleres' AND column_name = 'instructor_nombre'"
    )).fetchone() is not None

    if tiene_instructor_nombre:
        op.execute(text("""
            INSERT INTO instructores (nombre, descripcion, proyectos, foto_media_id, foto_url)
            SELECT DISTINCT ON (t.instructor_nombre)
                   t.instructor_nombre, t.instructor_bio, t.instructor_proyectos,
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
        # proyectos de instructores ya creados por la corrida ORIGINAL de F3
        # (antes de que esta columna existiera) — 1 fuente no vacía por nombre.
        op.execute(text("""
            UPDATE instructores i
            SET proyectos = src.proyectos
            FROM (
                SELECT DISTINCT ON (t.instructor_nombre)
                       t.instructor_nombre, t.instructor_proyectos AS proyectos
                FROM talleres t
                WHERE t.instructor_proyectos != ''
                ORDER BY t.instructor_nombre, t.id
            ) src
            WHERE i.nombre = src.instructor_nombre AND i.proyectos = ''
        """))

    # ── 2) Backfill de clases_taller para ediciones vacías con programa legacy ──
    # Guard: en una DB fresca, `talleres.programa_teorica/practica` nunca
    # llegaron a existir (mismo motivo que arriba) — no hay nada de qué leer.
    tiene_programa = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'talleres' AND column_name = 'programa_teorica'"
    )).fetchone() is not None

    if tiene_programa:
        candidatas = conn.execute(text("""
            SELECT e.id AS edicion_id, e.fecha_inicio, e.fecha_fin, e.horario, t.id AS taller_id,
                   jsonb_array_length(t.programa_teorica) AS n_teorica,
                   jsonb_array_length(t.programa_practica) AS n_practica
            FROM ediciones_taller e
            JOIN talleres t ON t.id = e.taller_id
            WHERE (jsonb_array_length(t.programa_teorica) > 0
                   OR jsonb_array_length(t.programa_practica) > 0)
              AND NOT EXISTS (SELECT 1 FROM clases_taller c WHERE c.edicion_id = e.id)
        """)).fetchall()

        for row in candidatas:
            h_ini, h_fin = _parse_horario(row.horario)
            if row.n_teorica > 0:
                conn.execute(text("""
                    INSERT INTO clases_taller (edicion_id, fecha, hora_inicio_min, hora_fin_min, titulo, descripcion)
                    SELECT :eid, :fecha, :hini, :hfin, 'Teórica', COALESCE(string_agg(x.v, E'\n'), '')
                    FROM talleres t, LATERAL jsonb_array_elements_text(t.programa_teorica) AS x(v)
                    WHERE t.id = :tid
                """), {
                    "eid": row.edicion_id, "fecha": row.fecha_inicio,
                    "hini": h_ini, "hfin": h_fin, "tid": row.taller_id,
                })
            if row.n_practica > 0:
                conn.execute(text("""
                    INSERT INTO clases_taller (edicion_id, fecha, hora_inicio_min, hora_fin_min, titulo, descripcion)
                    SELECT :eid, :fecha, :hini, :hfin, 'Práctica', COALESCE(string_agg(x.v, E'\n'), '')
                    FROM talleres t, LATERAL jsonb_array_elements_text(t.programa_practica) AS x(v)
                    WHERE t.id = :tid
                """), {
                    "eid": row.edicion_id, "fecha": row.fecha_fin,
                    "hini": h_ini, "hfin": h_fin, "tid": row.taller_id,
                })

    # ── 3) DROP de lo legacy ──────────────────────────────────────────────────
    op.execute(text("DROP TABLE IF EXISTS taller_sesiones"))
    op.execute(text("""
        ALTER TABLE talleres
            DROP COLUMN IF EXISTS instructor_nombre,
            DROP COLUMN IF EXISTS instructor_bio,
            DROP COLUMN IF EXISTS instructor_proyectos,
            DROP COLUMN IF EXISTS programa_teorica,
            DROP COLUMN IF EXISTS programa_practica,
            DROP COLUMN IF EXISTS fecha_inicio,
            DROP COLUMN IF EXISTS fecha_fin,
            DROP COLUMN IF EXISTS horario,
            DROP COLUMN IF EXISTS cupos_total,
            DROP COLUMN IF EXISTS cupos_confirmados,
            DROP COLUMN IF EXISTS precio_total,
            DROP COLUMN IF EXISTS precio_sena,
            DROP COLUMN IF EXISTS pago_alias,
            DROP COLUMN IF EXISTS pago_cbu,
            DROP COLUMN IF EXISTS pago_banco,
            DROP COLUMN IF EXISTS direccion,
            DROP COLUMN IF EXISTS instructor_foto_url,
            DROP COLUMN IF EXISTS instructor_media_id,
            DROP COLUMN IF EXISTS numero_edicion,
            DROP COLUMN IF EXISTS proxima_edicion_slug,
            DROP COLUMN IF EXISTS tipo_taller
    """))


def downgrade() -> None:
    # Re-agregar columnas legacy (constraints relajadas donde la fuente viva
    # -ediciones_taller/instructores- no garantiza 1:1 hoy: un concepto puede
    # tener 0 instructores linkeados vía el mini-CRUD de F3, o -en teoría- 0
    # ediciones si se borró la #1). Se re-pueblan desde esas fuentes, que
    # siguen intactas — NO es un downgrade con pérdida de datos salvo el
    # contenido específico de `taller_sesiones` (nunca tuvo lectores) y los
    # renglones sintéticos "Teórica"/"Práctica" que este mismo upgrade insertó
    # en `clases_taller` (se dejan tal cual: son datos reales del taller, no
    # basura a limpiar).
    op.execute(text("""
        ALTER TABLE talleres
            ADD COLUMN IF NOT EXISTS instructor_nombre TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS instructor_bio TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS instructor_proyectos TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS programa_teorica JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS programa_practica JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS fecha_inicio DATE,
            ADD COLUMN IF NOT EXISTS fecha_fin DATE,
            ADD COLUMN IF NOT EXISTS horario TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS cupos_total INTEGER NOT NULL DEFAULT 12,
            ADD COLUMN IF NOT EXISTS cupos_confirmados INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS precio_total INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS precio_sena INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS pago_alias TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS pago_cbu TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS pago_banco TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS direccion TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS instructor_foto_url TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS instructor_media_id BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS numero_edicion INTEGER NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS proxima_edicion_slug TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS tipo_taller TEXT NOT NULL DEFAULT 'intensivo'
    """))
    op.execute(text("""
        UPDATE talleres t SET
            fecha_inicio = e.fecha_inicio, fecha_fin = e.fecha_fin, horario = e.horario,
            cupos_total = e.cupos_total, cupos_confirmados = e.cupos_confirmados,
            precio_total = e.precio_total, precio_sena = e.precio_sena,
            pago_alias = e.pago_alias, pago_cbu = e.pago_cbu, pago_banco = e.pago_banco,
            direccion = e.direccion, numero_edicion = e.numero_edicion, tipo_taller = e.tipo_taller
        FROM ediciones_taller e
        WHERE e.taller_id = t.id AND e.numero_edicion = 1
    """))
    op.execute(text("""
        UPDATE talleres t SET
            instructor_nombre = i.nombre, instructor_bio = i.descripcion,
            instructor_proyectos = i.proyectos, instructor_foto_url = i.foto_url,
            instructor_media_id = i.foto_media_id
        FROM taller_instructores ti
        JOIN instructores i ON i.id = ti.instructor_id
        WHERE ti.taller_id = t.id AND ti.orden = (
            SELECT MIN(ti2.orden) FROM taller_instructores ti2 WHERE ti2.taller_id = t.id
        )
    """))

    op.execute(text("""
        CREATE TABLE IF NOT EXISTS taller_sesiones (
            id          SERIAL PRIMARY KEY,
            taller_id   INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            fecha       DATE    NOT NULL,
            hora_inicio INTEGER NOT NULL,
            hora_fin    INTEGER NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_taller_sesiones_taller ON taller_sesiones(taller_id)"
    ))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_taller_sesiones_fecha ON taller_sesiones(fecha)"
    ))

    op.execute(text("ALTER TABLE instructores DROP COLUMN IF EXISTS proyectos"))
