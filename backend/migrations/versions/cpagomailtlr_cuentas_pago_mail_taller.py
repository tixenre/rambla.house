"""cuentas_pago_mail_taller: el mail de inscripción a un taller lee las
cuentas de cobro nuevas, no los 3 campos viejos.

Hallazgo del supervisor (2026-08-13, revisión del lote `dev → main`): desde
`cu3nt4sp4g0_edicion_cuentas_pago.py`, el admin edita la lista de cuentas de
cobro (`edicion_cuentas_pago`) desde "Precios y forma de pago" — el público
(`WorkshopInscripcionForm`) ya la lee correcta, pero el template
`taller_inscripcion_cliente` seguía interpolando `pago_alias`/`pago_cbu`/
`pago_banco` (los 3 campos viejos, que la UI ya no edita). Resultado: apenas
se editaba una cuenta de cobro, la página web mostraba el alias correcto
mientras el mail de confirmación seguía mandando el viejo — riesgo real de
que alguien transfiera la seña a una cuenta que ya no es la vigente.

`routes/talleres.py` ahora arma `cuentas_pago_html`/`cuentas_pago_text`
(`_cuentas_pago_para_mail`, misma fuente `_get_cuentas_pago` que el público)
y el template los inyecta con `|safe` (mismo patrón `items_html`/`items_text`
de `pedido_confirmado_cliente`) — sin loop en Jinja: sin `trim_blocks`, un
`{% for %}` en el body de texto plano deja saltos de línea sueltos que sí se
ven en un mail real.

**Importa `DEFAULT_TEMPLATES`** (no inlinea el copy) — mismo criterio que
`t4u5v6w7x8y9`/`a7d4f1c9e2b5`: lo que recibe prod == lo que siembra
`init_db()` para instalaciones nuevas, seed y repaint no pueden divergir.

GUARDA (igual que las anteriores): solo actualiza la fila si
`updated_by = 'system:migration'` — si el dueño ya customizó este template
desde `/admin/comunicacion`, no se pisa.

Revision ID: cpagomailtlr
Revises: tlrvalortipo
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op

from services.email.default_templates import DEFAULT_TEMPLATES

revision: str = "cpagomailtlr"
down_revision: Union[str, Sequence[str], None] = "tlrvalortipo"
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
    # No-op: el copy anterior queda en el historial de git. No revertimos
    # para no pisar el contenido nuevo a ciegas.
    pass
