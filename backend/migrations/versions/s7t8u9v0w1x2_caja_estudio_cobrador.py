"""contabilidad: Caja Estudio representa al cobrador 'Estudio' (Fase 3, #1283)

Suma la caja del Estudio (economía separada de Rambla rental, iniciativa
#1283): un fondo (caja real, no cuenta corriente de socio) vinculado al
cobrador 'Estudio' vía `cuentas.socio` — mismo puente que Fondo Rambla con
'Rambla'. Inerte hasta que un pago se registre con `destinatario='Estudio'`
(fases siguientes de la iniciativa).

Espejado en init_db() (esquema en dos capas, `database/schema.py`).
Idempotente: `ON CONFLICT DO NOTHING` (mismo criterio que el seed original de
cuentas) — no pisa una "Caja Estudio" que el admin ya haya creado a mano con
otro `socio`/config.

Revision ID: s7t8u9v0w1x2
Revises: r8s9t0u1v2w3
Create Date: 2026-07-23
"""
from typing import Sequence, Union
from alembic import op

revision: str = "s7t8u9v0w1x2"
down_revision: Union[str, Sequence[str], None] = "r8s9t0u1v2w3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO cuentas (nombre, tipo, socio, moneda, orden)
        VALUES ('Caja Estudio', 'fondo', 'Estudio', 'ARS', 6)
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    # No-op: si ya hay movimientos/saldo contra esta caja, borrarla rompería
    # el historial. El admin la puede desactivar (baja lógica) a mano si hace
    # falta — mismo criterio que otros seeds de cuentas de este repo.
    pass
