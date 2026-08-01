"""pedido_creado_cliente: rescata la fila que ninguna repintura anterior tocó

Hallazgo en vivo (staging, back-office): el mail "Pedido creado — cliente"
mostraba la tabla de ítems como texto crudo (`<table role="presentation" ...>`
visible) en vez de una tabla real. Causa: esta fila quedó congelada en el
copy PREHISTÓRICO — de antes de `c1e9f3a7b5d2`/`a7d4f1c9e2b5`/`r8s9t0u1v2w3`
(las tres repinturas de marca) — con `{{ items_html }}` SIN `|safe`, así que
`_jinja_html` (autoescape=True) escapaba el HTML de la tabla entero a texto
visible. Evidencia de que es prehistórico, no una customización real: el
subject no tenía `#{{ numero_pedido }}`, el saludo usaba `cliente_nombre` en
vez de `cliente_nombre_pila`, y no tenía nada del branding/botones/
`docs_adjuntos` que sí tienen las demás filas.

Por qué las tres migraciones anteriores no la alcanzaron: todas guardan con
`WHERE updated_by = 'system:migration'` (no pisar una customización real del
dueño) — en algún momento alguien abrió el editor y tocó "Guardar" sobre esta
fila puntual (sin necesariamente cambiar nada), y eso alcanza para que el
PATCH le ponga su email en `updated_by` y quede afuera de la guarda para
siempre. Acá se hace la excepción, a propósito y una sola vez, porque el
contenido congelado no es una decisión de copy — es simplemente viejo.

**Importa `DEFAULT_TEMPLATES`** (mismo criterio que las tres anteriores): lo
que recibe esta fila es EXACTAMENTE lo que siembra `init_db()` para una
instalación nueva — no puede volver a divergir por escribirlo a mano acá.

Revision ID: p3d1d0cr34d0
Revises: w3bh00k1nb0x
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op

from services.email.default_templates import DEFAULT_TEMPLATES

revision: str = "p3d1d0cr34d0"
down_revision: Union[str, Sequence[str], None] = "w3bh00k1nb0x"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "pedido_creado_cliente"


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def upgrade() -> None:
    tpl = DEFAULT_TEMPLATES[_KEY]
    op.execute(
        f"""
        UPDATE email_templates
           SET subject    = {_q(tpl["subject"])},
               body_html  = {_q(tpl["body_html"])},
               body_text  = {_q(tpl["body_text"])},
               updated_by = 'system:migration'
         WHERE key = {_q(_KEY)}
        """
    )


def downgrade() -> None:
    # No-op: el copy viejo (roto) queda en el historial de git. No lo
    # restauramos a ciegas (mismo criterio que las tres repinturas anteriores).
    pass
