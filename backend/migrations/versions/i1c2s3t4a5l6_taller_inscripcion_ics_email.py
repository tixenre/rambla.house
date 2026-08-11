"""taller_inscripcion_ics_email: adjunto .ics + wording de fechas por tipo_taller.

Dos cambios al copy de `taller_inscripcion_cliente` (`services/email/default_templates.py`):
1. Nota "Te adjuntamos un calendario…" cuando `send_email` manda el `.ics` de
   las clases (nuevo: reemplaza el botón "Agregar a mi calendario" que vivía
   en la landing pública — ahora solo tiene sentido en el mail, una vez
   inscripto).
2. La sección "Fechas" mostraba SIEMPRE "Clase teórica: {fecha_inicio} / Clase
   práctica: {fecha_fin}" — correcto para un taller `intensivo` (2 sesiones)
   pero sin sentido para uno `semanal` (ej. 16 clases semanales): mostraba
   "Clase práctica" en la fecha de la última clase, no de una práctica real.
   Ahora es condicional por `tipo_taller` — `semanal` muestra "Primera
   clase"/"Última clase"/"Horario"; `intensivo` no cambia.

**Importa `DEFAULT_TEMPLATES`** (no inlinea el copy), mismo criterio que las
demás repinturas de email (`r8s9t0u1v2w3`, `t4u5v6w7x8y9`, ...): lo que
recibe prod == lo que siembra `init_db()` para instalaciones nuevas.

GUARDA (igual que las demás repinturas): solo actualiza filas con
`updated_by = 'system:migration'` — si el dueño ya customizó el template
desde la UI, no se pisa.

Revision ID: i1c2s3t4a5l6
Revises: unifestlgcy2
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op

from services.email.default_templates import DEFAULT_TEMPLATES

revision: str = "i1c2s3t4a5l6"
down_revision: Union[str, Sequence[str], None] = "unifestlgcy2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "taller_inscripcion_cliente"


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def upgrade() -> None:
    tpl = DEFAULT_TEMPLATES[_KEY]
    op.execute(
        f"""
        UPDATE email_templates
        SET subject = {_q(tpl["subject"])},
            body_html = {_q(tpl["body_html"])},
            body_text = {_q(tpl["body_text"])},
            updated_by = 'system:migration'
        WHERE key = {_q(_KEY)} AND updated_by = 'system:migration'
        """
    )


def downgrade() -> None:
    # No-op: el copy anterior queda en el historial de git. No revertimos para
    # no pisar el contenido nuevo a ciegas (mismo criterio que las demás
    # repinturas de email de este repo).
    pass
