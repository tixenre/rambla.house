"""ipc_series: serie mensual de IPC (INDEC) para ajustar Estadísticas por inflación

Tabla nueva, cache local de la API pública de series de tiempo de INDEC
(apis.datos.gob.ar, serie "148.3_INIVELNAL_DICI_M_26" — IPC Nacional, base
diciembre 2016). Se refresca 1×/día desde el scheduler in-process
(backend/jobs/ipc.py). El factor de ajuste ("pesos de hoy") vive en
services/ipc.py::IPC_FACTOR_CTE, no en esta migración.

Espejado en init_db() (esquema en dos capas, `database/schema.py`).

Revision ID: ipcseries
Revises: costoequipo
Create Date: 2026-08-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "ipcseries"
down_revision: Union[str, Sequence[str], None] = "costoequipo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ipc_series (
            mes           VARCHAR(7) PRIMARY KEY,
            indice        NUMERIC(14,4) NOT NULL,
            actualizado_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ipc_series")
