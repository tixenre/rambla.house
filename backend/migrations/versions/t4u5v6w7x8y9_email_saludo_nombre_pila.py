"""email_saludo_nombre_pila: los mails al cliente saludan por nombre de pila.

Repinta los templates al cliente que saludan por nombre ("Hola Santiago" en vez
de "Hola Santiago Granone López"). El saludo usa la variable nueva
`cliente_nombre_pila` (solo el nombre de pila), que el renderer deriva de
`cliente_nombre` en runtime — el resto del mail y los documentos PDF siguen
usando el nombre completo.

**Importa `DEFAULT_TEMPLATES`** (no inlinea el copy) a propósito: lo que recibe
prod == lo que siembra `init_db()` para instalaciones nuevas → seed y repaint no
pueden divergir (invariante del esquema en dos capas, `docs/MEMORIA.md`
2026-06-03). El copy se edita en `services/email/default_templates.py`.

GUARDA (igual que d8b2f4a6c0e1 / a7d4f1c9e2b5): solo actualiza filas con
`updated_by = 'system:migration'` — plantillas que nunca editó un admin desde la
UI. Si el dueño ya customizó un template, no se pisa.

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op

from services.email.default_templates import DEFAULT_TEMPLATES

revision: str = "t4u5v6w7x8y9"
down_revision: Union[str, Sequence[str], None] = "s3t4u5v6w7x8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Solo los mails al cliente que saludan por nombre.
_KEYS = (
    "pedido_creado_cliente",
    "pedido_confirmado_cliente",
    "recordatorio_retiro",
    "modificacion_resuelta_cliente",
)


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def upgrade() -> None:
    # `.get(...)` + skip: `modificacion_resuelta_cliente` se retiró después
    # (`s0l1c1tudb4j`), que también la saca de `DEFAULT_TEMPLATES` — un
    # bootstrap fresco nunca la tuvo, así que esto no-opea para esa key en vez
    # de romper `alembic upgrade head` con un KeyError. Prod no se ve afectado
    # (esta migración ya corrió cuando la key existía).
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
    # No-op: el copy anterior queda en el historial de git. No revertimos para
    # no pisar el contenido nuevo a ciegas.
    pass
