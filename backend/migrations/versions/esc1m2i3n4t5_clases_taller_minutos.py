"""Escuela v2 F1: `clases_taller` pasa de horas enteras a MINUTOS desde medianoche.

`hora_inicio`/`hora_fin` eran INTEGER de hora entera (0..24) — imposible
representar 8:30–12:30 o 14:00–16:30 (el taller de Filmar cursa así). Pasan a
`hora_inicio_min`/`hora_fin_min` (minutos desde medianoche, 0..1440).

El RENAME de columnas es deliberado (no se reusa el nombre con otra unidad):
cualquier lector olvidado que espere horas enteras falla ruidoso en SQL en vez
de comparar horas contra minutos en silencio. Los consumidores conocidos
(`routes/talleres.py` + el chequeo de disponibilidad del estudio en
`routes/estudio.py::_taller_bloqueante`/`verificar_sesiones_disponibles`)
migran en el mismo PR. `estudio_slots_fijos.hora_desde/hasta` NO se toca
(siguen en horas enteras en SU tabla; la conversión ×60 vive en
`_sesiones_de_slot`).

En paridad con `database/schema.py::init_db()` (crea la tabla ya con `_min`).

Downgrade: vuelve a horas enteras con división entera `/60` — TRUNCA los :30
(8:30 → 8). Pérdida documentada y aceptable: el modelo viejo no puede
representar medias horas.

Revision ID: esc1m2i3n4t5
Revises: s0l1c1t4d0e5
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "esc1m2i3n4t5"
down_revision: Union[str, Sequence[str], None] = "s0l1c1t4d0e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(conn, table: str, col: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": col},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()
    # Guards IF EXISTS: una DB fresca creada por init_db() ya nace con _min.
    if _col_exists(conn, "clases_taller", "hora_inicio"):
        op.execute(text("ALTER TABLE clases_taller RENAME COLUMN hora_inicio TO hora_inicio_min"))
        op.execute(text("ALTER TABLE clases_taller RENAME COLUMN hora_fin TO hora_fin_min"))
        # Convertir horas → minutos SOLO si los datos siguen en horas (≤24).
        # Idempotencia real: un re-run tras un fallo parcial no re-multiplica.
        op.execute(
            text(
                "UPDATE clases_taller SET "
                "hora_inicio_min = hora_inicio_min * 60, "
                "hora_fin_min = hora_fin_min * 60 "
                "WHERE hora_fin_min <= 24"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _col_exists(conn, "clases_taller", "hora_inicio_min"):
        # Minutos → horas enteras (división entera: TRUNCA los :30, documentado).
        op.execute(
            text(
                "UPDATE clases_taller SET "
                "hora_inicio_min = hora_inicio_min / 60, "
                "hora_fin_min = hora_fin_min / 60 "
                "WHERE hora_fin_min > 24"
            )
        )
        op.execute(text("ALTER TABLE clases_taller RENAME COLUMN hora_inicio_min TO hora_inicio"))
        op.execute(text("ALTER TABLE clases_taller RENAME COLUMN hora_fin_min TO hora_fin"))
