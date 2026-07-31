"""modificacion_pedidos_portal: extender solicitudes_modificacion + setting + 2 plantillas

Permite que el cliente edite pedidos desde su portal:
- `solicitudes_modificacion` gana `cambios_json` (snapshot del pedido propuesto),
  `tipo` ('directo' | 'aprobacion'), `resolved_at`, `resolved_by` (auditoría).
- `app_settings`: seed `modificacion_ventana_horas=24` (configurable).
- 2 plantillas de email: `modificacion_solicitada_admin` y `modificacion_resuelta_cliente`.

Revision ID: b6f8d3e5a2c1
Revises: a4e8c2b9d710
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b6f8d3e5a2c1"
down_revision: Union[str, Sequence[str], None] = "a4e8c2b9d710"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TEMPLATE_ADMIN = (
    "modificacion_solicitada_admin",
    "Modificación pedida — pedido #{{ numero_pedido }} ({{ cliente_nombre }})",
    """<p>El cliente <strong>{{ cliente_nombre }}</strong> ({{ cliente_email }}) pidió modificar el pedido <strong>#{{ numero_pedido }}</strong>.</p>
<p><strong>Pedido actual</strong><br>
Fechas: {{ fecha_desde_actual }} → {{ fecha_hasta_actual }}<br>
Total: {{ total_actual }}</p>
<p><strong>Cambios propuestos</strong><br>
Fechas: {{ fecha_desde_propuesta }} → {{ fecha_hasta_propuesta }}<br>
{{ diff_html }}</p>
{% if mensaje %}<p><strong>Comentario del cliente:</strong> {{ mensaje }}</p>{% endif %}
<p><a href="{{ admin_url }}">Revisar en back-office</a></p>""",
    """El cliente {{ cliente_nombre }} ({{ cliente_email }}) pidió modificar el pedido #{{ numero_pedido }}.

Pedido actual:
  Fechas: {{ fecha_desde_actual }} → {{ fecha_hasta_actual }}
  Total: {{ total_actual }}

Cambios propuestos:
  Fechas: {{ fecha_desde_propuesta }} → {{ fecha_hasta_propuesta }}
{{ diff_text }}

{% if mensaje %}Comentario del cliente: {{ mensaje }}{% endif %}

Revisar en back-office: {{ admin_url }}""",
)

_TEMPLATE_CLIENTE = (
    "modificacion_resuelta_cliente",
    "Tu solicitud de modificación del pedido #{{ numero_pedido }} fue {{ estado_label }}",
    """<p>Hola {{ cliente_nombre }},</p>
<p>Tu solicitud de modificación del pedido <strong>#{{ numero_pedido }}</strong> fue <strong>{{ estado_label }}</strong>.</p>
{% if respuesta %}<p><strong>Nota:</strong> {{ respuesta }}</p>{% endif %}
<p>Podés ver el detalle en tu portal.</p>
<p>— El equipo de Rambla</p>""",
    """Hola {{ cliente_nombre }},

Tu solicitud de modificación del pedido #{{ numero_pedido }} fue {{ estado_label }}.

{% if respuesta %}Nota: {{ respuesta }}{% endif %}

Podés ver el detalle en tu portal.

— El equipo de Rambla""",
)

_TEMPLATE_CANCELACION_ADMIN = (
    "modificacion_cancelada_admin",
    "El cliente canceló su solicitud — pedido #{{ numero_pedido }}",
    """<p>El cliente <strong>{{ cliente_nombre }}</strong> ({{ cliente_email }}) canceló su solicitud de modificación del pedido <strong>#{{ numero_pedido }}</strong>.</p>
<p><a href="{{ admin_url }}">Ver pedido</a></p>""",
    """El cliente {{ cliente_nombre }} ({{ cliente_email }}) canceló su solicitud de modificación del pedido #{{ numero_pedido }}.

Ver pedido: {{ admin_url }}""",
)


def upgrade() -> None:
    # `IF EXISTS` en la tabla (sumado a `IF NOT EXISTS` en la columna): la
    # feature se retiró después (`s0l1c1tudb4j`) — un bootstrap fresco ya no
    # crea `solicitudes_modificacion` en `init_db()`, así que estas 5 líneas
    # tienen que no-opear ahí en vez de romper `alembic upgrade head`. Prod
    # (donde la tabla existió y ya corrió esta migración) no se ve afectado.
    op.execute("ALTER TABLE IF EXISTS solicitudes_modificacion ADD COLUMN IF NOT EXISTS cambios_json JSONB")
    op.execute("ALTER TABLE IF EXISTS solicitudes_modificacion ADD COLUMN IF NOT EXISTS tipo TEXT NOT NULL DEFAULT 'aprobacion'")
    op.execute("ALTER TABLE IF EXISTS solicitudes_modificacion ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ")
    op.execute("ALTER TABLE IF EXISTS solicitudes_modificacion ADD COLUMN IF NOT EXISTS resolved_by TEXT")

    # `mensaje` pasa a ser opcional: la nueva UI estructurada manda cambios_json,
    # el texto libre queda como comentario opcional del cliente.
    op.execute("ALTER TABLE IF EXISTS solicitudes_modificacion ALTER COLUMN mensaje DROP NOT NULL")

    # Setting: horas de antelación mínima antes del retiro para permitir modificar.
    op.execute("""
        INSERT INTO app_settings (key, value, updated_by)
        VALUES ('modificacion_ventana_horas', '24', 'system-seed')
        ON CONFLICT (key) DO NOTHING
    """)

    # Plantillas de email.
    for key, subject, body_html, body_text in (
        _TEMPLATE_ADMIN, _TEMPLATE_CLIENTE, _TEMPLATE_CANCELACION_ADMIN,
    ):
        op.execute(
            f"""
            INSERT INTO email_templates (key, subject, body_html, body_text, updated_by)
            VALUES ({_q(key)}, {_q(subject)}, {_q(body_html)}, {_q(body_text)}, 'system:migration')
            ON CONFLICT (key) DO NOTHING
            """
        )


def downgrade() -> None:
    op.execute("DELETE FROM email_templates WHERE key IN ('modificacion_solicitada_admin', 'modificacion_resuelta_cliente', 'modificacion_cancelada_admin')")
    op.execute("DELETE FROM app_settings WHERE key = 'modificacion_ventana_horas'")
    op.execute("ALTER TABLE IF EXISTS solicitudes_modificacion DROP COLUMN IF EXISTS resolved_by")
    op.execute("ALTER TABLE IF EXISTS solicitudes_modificacion DROP COLUMN IF EXISTS resolved_at")
    op.execute("ALTER TABLE IF EXISTS solicitudes_modificacion DROP COLUMN IF EXISTS tipo")
    op.execute("ALTER TABLE IF EXISTS solicitudes_modificacion DROP COLUMN IF EXISTS cambios_json")


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"
