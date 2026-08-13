"""Economía del taller: eje `_tipo` ('fijo'|'porcentaje'), ortogonal a `_modo`.

`valor_estudio_tipo`/`valor_equipos_tipo` deciden CÓMO se determina el valor
que un taller le "paga" al Estudio/a los equipos: 'fijo' (comportamiento de
siempre, el admin tipea el monto en `valor_estudio`/`valor_equipos`) o
'porcentaje' (el admin tipea un % en `valor_estudio_pct`/`valor_equipos_pct`,
0-100, y `_regenerar_pedidos_taller` lo aplica sobre la suma de
`modalidad_monto` de los inscriptos no en lista de espera). `_modo` (mensual/
total) sigue siendo un eje aparte — "cómo se reparte entre los meses" — y no
se toca. Pedido explícito del dueño: "si se anotan 6 vamos al 50%".

Revision ID: tlrvalortipo
Revises: cu3nt4sp4g0
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op

revision: str = "tlrvalortipo"
down_revision: Union[str, Sequence[str], None] = "cu3nt4sp4g0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_estudio_tipo TEXT NOT NULL DEFAULT 'fijo'")
    op.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_estudio_pct INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_equipos_tipo TEXT NOT NULL DEFAULT 'fijo'")
    op.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_equipos_pct INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_estudio_tipo_check")
    op.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_estudio_tipo_check "
        "CHECK (valor_estudio_tipo IN ('fijo','porcentaje'))"
    )
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_equipos_tipo_check")
    op.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_equipos_tipo_check "
        "CHECK (valor_equipos_tipo IN ('fijo','porcentaje'))"
    )
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_estudio_pct_check")
    op.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_estudio_pct_check "
        "CHECK (valor_estudio_pct BETWEEN 0 AND 100)"
    )
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_equipos_pct_check")
    op.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_equipos_pct_check "
        "CHECK (valor_equipos_pct BETWEEN 0 AND 100)"
    )
    # Sirve `_revenue_inscriptos` (WHERE edicion_id = ... AND en_lista_espera
    # = FALSE) — antes solo había índice por `taller_id`.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_inscripciones_edicion_lista "
        "ON taller_inscripciones(edicion_id, en_lista_espera)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_taller_inscripciones_edicion_lista")
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_equipos_pct_check")
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_estudio_pct_check")
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_equipos_tipo_check")
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_estudio_tipo_check")
    op.execute("ALTER TABLE ediciones_taller DROP COLUMN IF EXISTS valor_equipos_pct")
    op.execute("ALTER TABLE ediciones_taller DROP COLUMN IF EXISTS valor_equipos_tipo")
    op.execute("ALTER TABLE ediciones_taller DROP COLUMN IF EXISTS valor_estudio_pct")
    op.execute("ALTER TABLE ediciones_taller DROP COLUMN IF EXISTS valor_estudio_tipo")
