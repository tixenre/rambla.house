"""taller_inscripciones: soft-delete (eliminado_at/eliminado_por) en vez de DELETE.

Hallazgo del dueño (2026-08-13): `admin_delete_inscripcion` hacía un
`DELETE FROM taller_inscripciones` real — un borrado accidental (o cualquier
baja normal) perdía para siempre los datos de contacto de esa persona. El
dueño pidió soft-delete explícitamente: toda persona que se inscribe sirve
como dataset de interesados, incluso si después se da de baja su inscripción
puntual.

`eliminado_at IS NULL` = activo (el estado de siempre); un valor no-NULL
saca la fila de las vistas/listas/exports/conteos normales (mismo criterio
que `eliminado_at` en equipos) sin perder la fila. `eliminado_por` guarda el
mail del admin que borró — accountability, mismo patrón que `updated_by` en
email_templates.

Revision ID: tlrinscsoft
Revises: cpagomailtlr
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "tlrinscsoft"
down_revision: Union[str, Sequence[str], None] = "cpagomailtlr"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS eliminado_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS eliminado_por TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE taller_inscripciones DROP COLUMN IF EXISTS eliminado_por")
    op.execute("ALTER TABLE taller_inscripciones DROP COLUMN IF EXISTS eliminado_at")
