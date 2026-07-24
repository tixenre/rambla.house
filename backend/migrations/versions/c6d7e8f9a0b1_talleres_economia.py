"""Talleres: economía visible en liquidación/reportes (pedido mensual por edición).

Cada edición de taller gana 2 pares de campos — `usa_estudio`/`valor_estudio`/
`valor_estudio_modo` y `usa_equipos`/`valor_equipos`/`valor_equipos_modo`
(`modo` = 'mensual' o 'total') — que `_regenerar_pedidos_taller` (espejo de
`_regenerar_pedidos_slot`, el mecanismo de `estudio_slots_fijos`) traduce en
ítems de un pedido `tipo='taller'` por mes activo de la edición. Atribución
100% genérica vía `equipos.dueno` (`filas_atribucion`): el Estudio y Rambla
no necesitan código especial. La matrícula/curso en sí NO tiene columna — el
admin la tipea a mano como línea personalizada dentro del pedido ya generado.

`alquileres.taller_edicion_id` vincula cada pedido mensual con su edición
(mismo patrón que `estudio_slot_id`), para regenerar futuros sin tocar
pasados/pagados.

Revision ID: c6d7e8f9a0b1
Revises: a5b6c7d8e9f0
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, Sequence[str], None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS usa_estudio BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_estudio INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_estudio_modo TEXT NOT NULL DEFAULT 'mensual'")
    op.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS usa_equipos BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_equipos INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_equipos_modo TEXT NOT NULL DEFAULT 'mensual'")
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_estudio_modo_check")
    op.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_estudio_modo_check "
        "CHECK (valor_estudio_modo IN ('mensual','total'))"
    )
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_equipos_modo_check")
    op.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_equipos_modo_check "
        "CHECK (valor_equipos_modo IN ('mensual','total'))"
    )
    op.execute("ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS taller_edicion_id INTEGER REFERENCES ediciones_taller(id) ON DELETE SET NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE alquileres DROP COLUMN IF EXISTS taller_edicion_id")
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_equipos_modo_check")
    op.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_estudio_modo_check")
    op.execute("ALTER TABLE ediciones_taller DROP COLUMN IF EXISTS valor_equipos_modo")
    op.execute("ALTER TABLE ediciones_taller DROP COLUMN IF EXISTS valor_equipos")
    op.execute("ALTER TABLE ediciones_taller DROP COLUMN IF EXISTS usa_equipos")
    op.execute("ALTER TABLE ediciones_taller DROP COLUMN IF EXISTS valor_estudio_modo")
    op.execute("ALTER TABLE ediciones_taller DROP COLUMN IF EXISTS valor_estudio")
    op.execute("ALTER TABLE ediciones_taller DROP COLUMN IF EXISTS usa_estudio")
