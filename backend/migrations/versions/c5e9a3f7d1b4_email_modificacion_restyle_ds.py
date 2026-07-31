"""email_modificacion_restyle_ds: repinta los 3 mails `modificacion_*` al Design System.

Los 3 mails de modificación de pedido (`modificacion_solicitada_admin`,
`modificacion_resuelta_cliente`, `modificacion_cancelada_admin`) los había
sembrado `b6f8d3e5a2c1` con copy inline crudo — quedaron FUERA del restyle al
Design System que `a7d4f1c9e2b5` aplicó a los otros 4 (porque en ese momento no
vivían en `default_templates.py`). Esta migración cierra ese drift: ahora los 3
viven en `DEFAULT_TEMPLATES` (mono labels, tabular nums, paleta de marca, botones
bulletproof) y este repaint lleva prod a ese end-state.

**Importa `DEFAULT_TEMPLATES`** (igual que `a7d4f1c9e2b5`, no inlinea copy): lo que
recibe prod == lo que siembra `init_db()` para instalaciones nuevas → seed y
repaint **no pueden divergir** (invariante del esquema en dos capas,
`docs/MEMORIA.md` 2026-06-03). Cualquier cambio futuro de copy se edita en
`default_templates.py` + su propia migración.

GUARDA (igual que c1e9f3a7b5d2 / f2a4c6e8b0d1 / a7d4f1c9e2b5): solo actualiza filas
con `updated_by = 'system:migration'` — plantillas que nunca editó un admin desde
la UI (el PATCH setea `updated_by` al email del admin). Si el dueño ya customizó un
template, no se pisa.

Revision ID: c5e9a3f7d1b4
Revises: r2s3t4u5v6w7
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op

from services.email.default_templates import DEFAULT_TEMPLATES

revision: str = "c5e9a3f7d1b4"
down_revision: Union[str, Sequence[str], None] = "r2s3t4u5v6w7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Solo las 3 plantillas que `b6f8d3e5a2c1` sembró sin estilo; las otras 4 ya las
# repintó `a7d4f1c9e2b5`. El contenido sale de DEFAULT_TEMPLATES (fuente única).
_KEYS = (
    "modificacion_solicitada_admin",
    "modificacion_resuelta_cliente",
    "modificacion_cancelada_admin",
)


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def upgrade() -> None:
    # `.get(...)` + skip: la feature se retiró después (`s0l1c1tudb4j`), que
    # también saca estas 3 keys de `DEFAULT_TEMPLATES` — un bootstrap fresco
    # nunca las tuvo, así que esto no-opea ahí en vez de romper `alembic
    # upgrade head` con un KeyError. Prod no se ve afectado (ya corrió).
    for key in _KEYS:
        tpl = DEFAULT_TEMPLATES.get(key)
        if tpl is None:
            continue
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
    # No-op: el copy anterior queda en el historial de git (b6f8d3e5a2c1). No
    # revertimos para no pisar el contenido nuevo a ciegas.
    pass
