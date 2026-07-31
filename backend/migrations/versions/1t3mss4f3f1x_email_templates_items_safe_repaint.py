"""email_templates: repinta cualquier fila que aún NO tenga items_html|safe

Hallazgo en vivo (back-office, screenshot del dueño): "Pedido confirmado —
cliente" tenía el MISMO defecto que `pedido_creado_cliente` (rescatado por
`p3d1d0cr34d0`) — copy prehistórico congelado, `{{ items_html }}` SIN
`|safe`, así que Jinja (autoescape=True) escapaba la tabla de ítems entera a
texto crudo visible. Evidencia de que es prehistórico y no una
customización real: subject sin `— Rambla Rental`, saludo con
`cliente_nombre` (no `cliente_nombre_pila`), sin ninguno de los helpers de
branding (`b.H`/`b.LBL`/botones) que sí tienen el resto de las filas.

`p3d1d0cr34d0` arregló SOLO esa fila puntual porque en ese momento no
sabíamos que el mismo defecto podía repetirse en otra — encontrarlo dos
veces vía screenshot confirma que es una CLASE de bug, no un caso aislado.
Las tres repinturas anteriores (`c1e9f3a7b5d2`/`a7d4f1c9e2b5`/
`r8s9t0u1v2w3`) nunca alcanzan una fila así porque guardan con
`WHERE updated_by = 'system:migration'` — en algún momento alguien tocó
"Guardar" sobre esta fila puntual (sin necesariamente cambiar nada) y
quedó afuera de esa guarda para siempre.

Esta migración generaliza el rescate a **cualquier** fila, de cualquier key
con `items_html` en su plantilla canónica, cuyo `body_html` en la BD NO
contenga el literal `{{ items_html|safe }}` — es la firma exacta y
precisa del bug (no un overwrite ciego de todo lo que no sea
'system:migration': una fila que YA tiene `|safe` se deja intacta, sea o
no una customización real del dueño). Cubre de una sola vez:
pedido_creado_cliente (ya resuelta por p3d1d0cr34d0 — sigue teniendo
`|safe`, este UPDATE es no-op ahí), pedido_confirmado_cliente,
pedido_creado_admin, recordatorio_retiro, recordatorio_devolucion_d1,
recordatorio_devolucion_d0, recordatorio_devolucion_vencido.

**Importa `DEFAULT_TEMPLATES`** (mismo criterio que las repinturas
anteriores): lo que recibe una fila rescatada es EXACTAMENTE lo que
siembra `init_db()` para una instalación nueva.

Revision ID: 1t3mss4f3f1x
Revises: p3d1d0cr34d0
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op

from services.email.default_templates import DEFAULT_TEMPLATES

revision: str = "1t3mss4f3f1x"
down_revision: Union[str, Sequence[str], None] = "p3d1d0cr34d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SAFE_MARKER = "{{ items_html|safe }}"


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def upgrade() -> None:
    for key, tpl in DEFAULT_TEMPLATES.items():
        if _SAFE_MARKER not in tpl["body_html"]:
            continue  # esta plantilla no usa items_html — no aplica
        op.execute(
            f"""
            UPDATE email_templates
               SET subject    = {_q(tpl["subject"])},
                   body_html  = {_q(tpl["body_html"])},
                   body_text  = {_q(tpl["body_text"])},
                   updated_by = 'system:migration'
             WHERE key = {_q(key)}
               AND body_html NOT LIKE '%' || {_q(_SAFE_MARKER)} || '%'
            """
        )


def downgrade() -> None:
    # No-op: el copy viejo (roto) queda en el historial de git. No lo
    # restauramos a ciegas (mismo criterio que las repinturas anteriores).
    pass
