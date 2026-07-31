"""email_periodo_label_estudio: "Duración: 4 horas" en vez de "Jornadas: 1"
para un turno del Estudio.

Repinta `pedido_creado_cliente`/`pedido_confirmado_cliente` para usar la
variable nueva `periodo_label` (`services/pedidos_notificaciones.py`, Fase 2
de la economía del Estudio) en vez de `cantidad_jornadas` — un turno de 4hs
mostraba "Jornadas: 1" en el mail (mismo bug de display que ya se arregló
en el presupuesto/contrato/packing list, `pdf_templates.py`). Para un
alquiler normal el label sigue siendo "N jornada(s)" — cero cambio visual.

**Importa `DEFAULT_TEMPLATES`** (no inlinea el copy) a propósito, mismo
criterio que `t4u5v6w7x8y9_email_saludo_nombre_pila.py`: lo que recibe prod
== lo que siembra `init_db()` para instalaciones nuevas.

GUARDA (igual que las demás repinturas de email): solo actualiza filas con
`updated_by = 'system:migration'` — plantillas que nunca editó un admin
desde la UI. Si el dueño ya customizó un template, no se pisa.

Revision ID: r8s9t0u1v2w3
Revises: q2r3s4t5u6v7
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op

from services.email.default_templates import DEFAULT_TEMPLATES

revision: str = "r8s9t0u1v2w3"
down_revision: Union[str, Sequence[str], None] = "q2r3s4t5u6v7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEYS = ("pedido_creado_cliente", "pedido_confirmado_cliente")


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def upgrade() -> None:
    for key in _KEYS:
        tpl = DEFAULT_TEMPLATES[key]
        op.execute(
            f"""
            UPDATE email_templates
            SET subject = {_q(tpl["subject"])},
                body_html = {_q(tpl["body_html"])},
                body_text = {_q(tpl["body_text"])},
                updated_by = 'system:migration'
            WHERE key = {_q(key)} AND updated_by = 'system:migration'
            """
        )


def downgrade() -> None:
    # No-op: el copy anterior queda en el historial de git. No revertimos para
    # no pisar el contenido nuevo a ciegas (mismo criterio que las demás
    # repinturas de email de este repo).
    pass
