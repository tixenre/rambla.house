"""alquiler_turnos_estudio: el turno del Estudio pasa a ser un ítem del pedido, no una fila aparte

Un turno del Estudio embebido en un pedido de alquiler normal (`tipo='diaria'`) deja de crear su
propia fila `alquileres` vinculada por `pedido_principal_id` — pasa a ser un GRUPO de
`alquiler_items` (centinela + opcional promo/sueltos/pintura) colgando de la MISMA fila, vía la
tabla nueva `alquiler_turnos_estudio` (fecha/hora propia + su propio descuento, igual que hoy tiene
una fila `alquileres` de turno) + la FK `alquiler_items.turno_estudio_id`.

Puramente aditivo: ninguna fila existente tiene `turno_estudio_id` poblado — cero cambio de
comportamiento hasta que se empiece a insertar (Fase 4). `ON DELETE CASCADE` en ambas direcciones:
borrar el turno se lleva sus ítems; borrar el pedido se lleva su(s) turno(s).

Espejado en init_db() (esquema en dos capas, `database/schema.py`).

Revision ID: turnoestudio
Revises: 1t3mss4f3f1x
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op

revision: str = "turnoestudio"
down_revision: Union[str, Sequence[str], None] = "1t3mss4f3f1x"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS alquiler_turnos_estudio (
            id                      SERIAL PRIMARY KEY,
            pedido_id               INTEGER NOT NULL REFERENCES alquileres(id) ON DELETE CASCADE,
            fecha_desde             TIMESTAMP NOT NULL,
            fecha_hasta             TIMESTAMP NOT NULL,
            descuento_pct           NUMERIC(7,4) NOT NULL DEFAULT 0,
            descuento_manual_tipo   VARCHAR(10) NOT NULL DEFAULT 'pct',
            descuento_manual_monto  INTEGER NOT NULL DEFAULT 0,
            created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_turnos_estudio_pedido "
        "ON alquiler_turnos_estudio(pedido_id)"
    )
    op.execute(
        "ALTER TABLE alquiler_items ADD COLUMN IF NOT EXISTS turno_estudio_id "
        "INTEGER REFERENCES alquiler_turnos_estudio(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pedido_items_turno_estudio "
        "ON alquiler_items(turno_estudio_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pedido_items_turno_estudio")
    op.execute("ALTER TABLE alquiler_items DROP COLUMN IF EXISTS turno_estudio_id")
    op.execute("DROP INDEX IF EXISTS idx_turnos_estudio_pedido")
    op.execute("DROP TABLE IF EXISTS alquiler_turnos_estudio")
