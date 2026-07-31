"""Contenido por defecto de las plantillas de email (los 7 mails del sistema).

**Fuente única forward del copy de los templates.** Espeja el end-state de la
cadena de migraciones (`a4e8c2b9d710` siembra → `e7c3a9f5d1b8` → `c1e9f3a7b5d2`
branded → `f2a4c6e8b0d1` botón calendario → `a7d4f1c9e2b5` restyle Design System;
los 3 mails `modificacion_*` los sembró `b6f8d3e5a2c1` y los repintó al DS
`c5e9a3f7d1b4`). `init_db()` siembra estas filas de forma idempotente
(`ON CONFLICT DO NOTHING`) para que las plantillas **existan siempre**, aunque las
migraciones se traben — la red del esquema en dos capas (ver `docs/MEMORIA.md`
2026-06-03).

El layout branded (header con logo, colores, footer) lo pone el shell común en
`services/email/service.py` (`_wrap_email_html`); estos bodies guardan **solo el
contenido editable** (el admin los puede editar desde `/admin/email-templates`).

Los tokens visuales (colores, fuentes) y los helpers (`btn`, `H`, `LBL`, …) viven
en `services/email/branding.py` — **fuente única**, no se repiten hex acá.

Si se cambia el copy, se edita ACÁ (+ una migración si hay que repisar prod). No
duplicar el contenido en otro lado.
"""
from __future__ import annotations

from . import branding as b

# key → {subject, body_html, body_text}
DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "pedido_creado_cliente": {
        "subject": "Recibimos tu pedido #{{ numero_pedido }} — Rambla Rental",
        "body_html": f"""<p {b.H}>¡Recibimos tu pedido!</p>
<p style="margin:0 0 8px;">Hola {{{{ cliente_nombre_pila }}}}, gracias por tu pedido <strong>#{{{{ numero_pedido }}}}</strong>. Lo estamos revisando y te confirmamos la disponibilidad a la brevedad.</p>
{{% if mensaje_admin %}}{b.callout("mensaje_admin")}{{% endif %}}
<p {b.LBL}>Tu pedido</p>
<p style="margin:0 0 4px;"><strong>Retiro:</strong> {{{{ fecha_desde }}}}<br><strong>Devolución:</strong> {{{{ fecha_hasta }}}}{{% if periodo_label %}}<br><strong>Duración:</strong> {{{{ periodo_label }}}}{{% endif %}}</p>
{{{{ items_html|safe }}}}
<p {b.TOTAL}><strong>Total estimado: {{{{ total }}}}</strong></p>
{{% if docs_adjuntos %}}<p style="margin:6px 0 4px;">Te adjuntamos en este mail: <strong>{{{{ docs_adjuntos|join(', ') }}}}</strong>.</p>{{% endif %}}
{b.btn("portal_url", "Ver mi pedido")}
<p {b.MUTED_P}>Cuando confirmemos el pedido vas a poder descargar el <strong>remito</strong> y el <strong>contrato</strong> desde tu portal. ¿Tenés alguna duda? Respondé este mail.</p>
<p style="margin:18px 0 0;">— El equipo de Rambla</p>""",
        "body_text": """Hola {{ cliente_nombre_pila }},

Recibimos tu pedido #{{ numero_pedido }}. Lo estamos revisando y te confirmamos la disponibilidad a la brevedad.
{% if mensaje_admin %}
{{ mensaje_admin }}
{% endif %}
Retiro: {{ fecha_desde }}
Devolución: {{ fecha_hasta }}{% if periodo_label %}
Duración: {{ periodo_label }}{% endif %}

{{ items_text }}

Total estimado: {{ total }}
{% if docs_adjuntos %}
Te adjuntamos en este mail: {{ docs_adjuntos|join(', ') }}.
{% endif %}
Seguí tu pedido en el portal: {{ portal_url }}
Cuando lo confirmemos vas a poder descargar el remito y el contrato desde ahí.

¿Dudas? Respondé este mail.
— El equipo de Rambla""",
    },
    "pedido_confirmado_cliente": {
        "subject": "Tu pedido #{{ numero_pedido }} está confirmado — Rambla Rental",
        "body_html": f"""<p {b.H}>¡Tu pedido está confirmado!</p>
<p style="margin:0 0 8px;">Hola {{{{ cliente_nombre_pila }}}}, confirmamos tu pedido <strong>#{{{{ numero_pedido }}}}</strong>. Acá tenés todos los datos de tu reserva.</p>
{{% if mensaje_admin %}}{b.callout("mensaje_admin")}{{% endif %}}
<p {b.LBL}>Reserva</p>
<p style="margin:0 0 4px;"><strong>Retiro:</strong> {{{{ fecha_desde }}}}<br><strong>Devolución:</strong> {{{{ fecha_hasta }}}}{{% if periodo_label %}}<br><strong>Duración:</strong> {{{{ periodo_label }}}}{{% endif %}}</p>
<p {b.LBL}>Equipos</p>
{{{{ items_html|safe }}}}
<p {b.LBL}>Pago</p>
<p {b.TOTAL}><strong>Total: {{{{ total }}}}</strong></p>
{{% if pago_estado %}}<p style="margin:0 0 4px;color:{b.MUTED};font-size:14px;">{{{{ pago_estado }}}}</p>{{% endif %}}
{{% if docs_adjuntos %}}<p {b.LBL}>Documentos</p>
<p style="margin:0 0 4px;">Te adjuntamos en este mail: <strong>{{{{ docs_adjuntos|join(', ') }}}}</strong>.</p>{{% else %}}<p {b.MUTED_P}>Ya podés descargar el <strong>remito</strong> y el <strong>contrato</strong> desde tu portal.</p>{{% endif %}}
{b.btn("portal_url", "Ver mi pedido")}
{{% if gcal_url %}}{b.btn_secondary("gcal_url", "📅 Agregar al calendario")}{{% endif %}}
<p {b.MUTED_P}>Te esperamos en el galpón el día del retiro. ¿Dudas? Respondé este mail.</p>
<p style="margin:18px 0 0;">— El equipo de Rambla</p>""",
        "body_text": """Hola {{ cliente_nombre_pila }},

Tu pedido #{{ numero_pedido }} está confirmado. Acá tenés todos los datos de tu reserva.
{% if mensaje_admin %}
{{ mensaje_admin }}
{% endif %}
RESERVA
Retiro: {{ fecha_desde }}
Devolución: {{ fecha_hasta }}{% if periodo_label %}
Duración: {{ periodo_label }}{% endif %}

EQUIPOS
{{ items_text }}

PAGO
Total: {{ total }}{% if pago_estado %}
{{ pago_estado }}{% endif %}
{% if docs_adjuntos %}
Te adjuntamos en este mail: {{ docs_adjuntos|join(', ') }}.
{% else %}
Ya podés descargar el remito y el contrato desde tu portal: {{ portal_url }}
{% endif %}{% if gcal_url %}
Agregá la reserva a tu calendario: {{ gcal_url }}
{% endif %}
Te esperamos en el galpón el día del retiro. ¿Dudas? Respondé este mail.

— El equipo de Rambla""",
    },
    "pedido_creado_admin": {
        "subject": "Nuevo pedido #{{ numero_pedido }} — {{ cliente_nombre }}",
        "body_html": f"""<p {b.H}>Entró un pedido nuevo</p>
<p style="margin:0 0 4px;"><strong>#{{{{ numero_pedido }}}}</strong> de <strong>{{{{ cliente_nombre }}}}</strong></p>
<p style="margin:0 0 4px;color:{b.MUTED};font-size:14px;">{{{{ cliente_email }}}}{{% if cliente_telefono %}} · {{{{ cliente_telefono }}}}{{% endif %}}</p>
<p {b.LBL}>Pedido</p>
<p style="margin:0 0 4px;"><strong>Retiro:</strong> {{{{ fecha_desde }}}}<br><strong>Devolución:</strong> {{{{ fecha_hasta }}}}</p>
{{{{ items_html|safe }}}}
<p {b.TOTAL}><strong>Total: {{{{ total }}}}</strong></p>
{{% if notas %}}<p style="margin:8px 0 0;"><strong>Notas:</strong> {{{{ notas }}}}</p>{{% endif %}}
{b.btn("admin_url", "Ver en el back-office")}""",
        "body_text": """Entró un pedido nuevo.

#{{ numero_pedido }} de {{ cliente_nombre }}
Contacto: {{ cliente_email }}{% if cliente_telefono %} · {{ cliente_telefono }}{% endif %}

Retiro: {{ fecha_desde }}
Devolución: {{ fecha_hasta }}

{{ items_text }}

Total: {{ total }}
{% if notas %}Notas: {{ notas }}{% endif %}

Ver en el back-office: {{ admin_url }}""",
    },
    "recordatorio_retiro": {
        # El copy se adapta a `dias_antes` (configurable desde /admin/settings):
        # con 1 día dice "mañana"; con N>1 dice "en N días". `dias_antes` lo
        # inyecta el job (jobs/recordatorios.py) y el preview del admin (=1).
        "subject": "{% if dias_antes == 1 %}Mañana retirás{% else %}Faltan {{ dias_antes }} días para retirar{% endif %} tu pedido #{{ numero_pedido }} — Rambla Rental",
        "body_html": f"""<p {b.H}>{{% if dias_antes == 1 %}}¡Mañana es el día!{{% else %}}¡Falta poco!{{% endif %}}</p>
<p style="margin:0 0 8px;">Hola {{{{ cliente_nombre_pila }}}}, te recordamos que <strong>{{% if dias_antes == 1 %}}mañana{{% else %}}en {{{{ dias_antes }}}} días{{% endif %}} ({{{{ fecha_desde }}}})</strong> retirás tu pedido <strong>#{{{{ numero_pedido }}}}</strong>.</p>
{{{{ items_html|safe }}}}
{b.btn("portal_url", "Ver mi pedido")}
<p {b.MUTED_P}>Te esperamos en el galpón. Si necesitás reagendar, escribinos cuanto antes.</p>
<p style="margin:18px 0 0;">— El equipo de Rambla</p>""",
        "body_text": """Hola {{ cliente_nombre_pila }},

{% if dias_antes == 1 %}Mañana{% else %}En {{ dias_antes }} días{% endif %} ({{ fecha_desde }}) retirás tu pedido #{{ numero_pedido }}.

{{ items_text }}

Te esperamos en el galpón. Si necesitás reagendar, escribinos cuanto antes.
Tu portal: {{ portal_url }}

— El equipo de Rambla""",
    },
    "modificacion_solicitada_admin": {
        "subject": "Modificación pedida — pedido #{{ numero_pedido }} ({{ cliente_nombre }})",
        "body_html": f"""<p {b.H}>El cliente pidió modificar un pedido</p>
<p style="margin:0 0 4px;"><strong>#{{{{ numero_pedido }}}}</strong> de <strong>{{{{ cliente_nombre }}}}</strong></p>
<p style="margin:0 0 4px;color:{b.MUTED};font-size:14px;">{{{{ cliente_email }}}}</p>
<p {b.LBL}>Pedido actual</p>
<p style="margin:0 0 4px;"><strong>Fechas:</strong> {{{{ fecha_desde_actual }}}} → {{{{ fecha_hasta_actual }}}}</p>
<p {b.TOTAL}><strong>Total: {{{{ total_actual }}}}</strong></p>
<p {b.LBL}>Cambios propuestos</p>
<p style="margin:0 0 4px;"><strong>Fechas:</strong> {{{{ fecha_desde_propuesta }}}} → {{{{ fecha_hasta_propuesta }}}}</p>
{{{{ diff_html|safe }}}}
{{% if mensaje %}}<p {b.MUTED_P}><strong>Comentario del cliente:</strong> {{{{ mensaje }}}}</p>{{% endif %}}
{b.btn("admin_url", "Revisar en el back-office")}""",
        "body_text": """El cliente {{ cliente_nombre }} ({{ cliente_email }}) pidió modificar el pedido #{{ numero_pedido }}.

Pedido actual:
  Fechas: {{ fecha_desde_actual }} → {{ fecha_hasta_actual }}
  Total: {{ total_actual }}

Cambios propuestos:
  Fechas: {{ fecha_desde_propuesta }} → {{ fecha_hasta_propuesta }}
{{ diff_text }}
{% if mensaje %}
Comentario del cliente: {{ mensaje }}{% endif %}

Revisar en el back-office: {{ admin_url }}""",
    },
    "modificacion_resuelta_cliente": {
        "subject": "Tu solicitud de modificación del pedido #{{ numero_pedido }} fue {{ estado_label }}",
        "body_html": f"""<p {b.H}>Tu solicitud fue {{{{ estado_label }}}}</p>
<p style="margin:0 0 8px;">Hola {{{{ cliente_nombre_pila }}}}, tu solicitud de modificación del pedido <strong>#{{{{ numero_pedido }}}}</strong> fue <strong>{{{{ estado_label }}}}</strong>.</p>
{{% if respuesta %}}<p {b.LBL}>Nota</p>
<p style="margin:0 0 4px;">{{{{ respuesta }}}}</p>{{% endif %}}
{b.btn("portal_url", "Ver mi pedido")}
<p {b.MUTED_P}>Podés ver el detalle del pedido actualizado en tu portal.</p>
<p style="margin:18px 0 0;">— El equipo de Rambla</p>""",
        "body_text": """Hola {{ cliente_nombre_pila }},

Tu solicitud de modificación del pedido #{{ numero_pedido }} fue {{ estado_label }}.
{% if respuesta %}
Nota: {{ respuesta }}{% endif %}

Podés ver el detalle del pedido actualizado en tu portal: {{ portal_url }}

— El equipo de Rambla""",
    },
    "modificacion_cancelada_admin": {
        "subject": "El cliente canceló su solicitud — pedido #{{ numero_pedido }}",
        "body_html": f"""<p {b.H}>El cliente canceló su solicitud</p>
<p style="margin:0 0 4px;"><strong>{{{{ cliente_nombre }}}}</strong> canceló su solicitud de modificación del pedido <strong>#{{{{ numero_pedido }}}}</strong>.</p>
<p style="margin:0 0 4px;color:{b.MUTED};font-size:14px;">{{{{ cliente_email }}}}</p>
{b.btn("admin_url", "Ver pedido")}""",
        "body_text": """El cliente {{ cliente_nombre }} ({{ cliente_email }}) canceló su solicitud de modificación del pedido #{{ numero_pedido }}.

Ver pedido: {{ admin_url }}""",
    },

    # ── Talleres ──────────────────────────────────────────────────────────────
    "taller_inscripcion_admin": {
        "subject": "Nueva inscripción{% if en_lista_espera %} (lista de espera){% endif %} — {{ taller_nombre }} ({{ nombre }})",
        "body_html": f"""<p {b.H}>{{% if en_lista_espera %}}Nueva inscripción — lista de espera{{% else %}}Nueva inscripción{{% endif %}}</p>
<p style="margin:0 0 8px;"><strong>{{{{ nombre }}}}</strong> se inscribió al taller <strong>{{{{ taller_nombre }}}}</strong>.</p>
{{% if en_lista_espera %}}<p style="margin:0 0 8px;color:#b45309;"><strong>Lista de espera</strong> — los cupos del taller están completos.</p>{{% endif %}}
<p {b.LBL}>Contacto</p>
<p style="margin:0 0 4px;"><strong>Email:</strong> {{{{ email }}}}<br><strong>Teléfono:</strong> {{{{ telefono }}}}</p>
{{% if experiencia %}}<p {b.LBL}>Experiencia</p><p style="margin:0 0 4px;">{{{{ experiencia }}}}</p>{{% endif %}}
{{% if comprobante_url %}}<p {b.LBL}>Comprobante de pago</p><p style="margin:0 0 4px;"><a href="{{{{ comprobante_url }}}}" style="color:{b.INK};">Ver comprobante</a></p>{{% endif %}}
<p {b.MUTED_P}>Inscripción recibida el {{{{ fecha }}}}.</p>""",
        "body_text": """{%- if en_lista_espera %}[LISTA DE ESPERA] {% endif -%}
Nueva inscripción — {{ taller_nombre }}

Nombre: {{ nombre }}
Email: {{ email }}
Teléfono: {{ telefono }}
{% if experiencia %}Experiencia: {{ experiencia }}{% endif %}
{% if comprobante_url %}Comprobante: {{ comprobante_url }}{% endif %}

Fecha: {{ fecha }}""",
    },
    "taller_cambio_datos": {
        "subject": "Actualización sobre {{ taller_nombre }}",
        "body_html": f"""<p {b.H}>Actualización: {{{{ taller_nombre }}}}</p>
<p style="margin:0 0 8px;">Hola <strong>{{{{ nombre_pila }}}}</strong>, hay una novedad sobre el workshop al que te inscribiste:</p>
{{% if mensaje %}}<p style="margin:12px 0;padding:12px 16px;background:#f5f3f0;border-left:3px solid #c8a96e;border-radius:4px;">{{{{ mensaje }}}}</p>{{% endif %}}
<p {b.MUTED_P}>¿Preguntas? Respondé este mail o escribínos por WhatsApp.</p>
<p style="margin:18px 0 0;">— El equipo de Rambla</p>""",
        "body_text": """Hola {{ nombre_pila }}, hay una novedad sobre {{ taller_nombre }}.

{% if mensaje %}{{ mensaje }}

{% endif %}¿Preguntas? Respondé este mail.

— El equipo de Rambla""",
    },
    "taller_inscripcion_cliente": {
        "subject": "{% if en_lista_espera %}Quedaste en lista de espera{% else %}¡Tu lugar está reservado!{% endif %} — {{ taller_nombre }}",
        "body_html": f"""<p {b.H}>{{% if en_lista_espera %}}Quedaste en lista de espera{{% else %}}¡Tu lugar está reservado!{{% endif %}}</p>
<p style="margin:0 0 8px;">Hola <strong>{{{{ nombre_pila }}}}</strong>, {{% if en_lista_espera %}}te anotamos en la lista de espera de <strong>{{{{ taller_nombre }}}}</strong>. Te avisamos si se libera un cupo.{{% else %}}recibimos tu inscripción a <strong>{{{{ taller_nombre }}}}</strong>. Tu seña queda confirmada cuando verifiquemos el pago.{{% endif %}}</p>
{{% if not en_lista_espera %}}
<p {b.LBL}>Fechas</p>
<p style="margin:0 0 4px;"><strong>Clase teórica:</strong> {{{{ fecha_inicio_str }}}}, {{{{ horario }}}}<br><strong>Clase práctica:</strong> {{{{ fecha_fin_str }}}}, {{{{ horario }}}}<br><strong>Lugar:</strong> {{{{ direccion }}}}</p>
<p {b.LBL}>Datos de pago (seña)</p>
<p style="margin:0 0 4px;"><strong>Alias:</strong> {{{{ pago_alias }}}}<br><strong>CBU:</strong> {{{{ pago_cbu }}}}<br><strong>Banco:</strong> {{{{ pago_banco }}}}<br><strong>Monto:</strong> {{{{ precio_sena_str }}}}</p>
{{% endif %}}
<p {b.MUTED_P}>¿Preguntas? Respondé este mail o escribínos por WhatsApp.</p>
<p style="margin:18px 0 0;">— El equipo de Rambla</p>""",
        "body_text": """{%- if en_lista_espera -%}
Hola {{ nombre_pila }}, te anotamos en la lista de espera de {{ taller_nombre }}.

Te avisamos si se libera un cupo. ¿Preguntas? Respondé este mail.
{%- else -%}
Hola {{ nombre_pila }}, recibimos tu inscripción a {{ taller_nombre }}.

Clase teórica: {{ fecha_inicio_str }}, {{ horario }}
Clase práctica: {{ fecha_fin_str }}, {{ horario }}
Lugar: {{ direccion }}

Datos de pago (seña):
  Alias: {{ pago_alias }}
  CBU: {{ pago_cbu }}
  Banco: {{ pago_banco }}
  Monto: {{ precio_sena_str }}

¿Preguntas? Respondé este mail.
{%- endif %}

— El equipo de Rambla""",
    },
    # F4b: verificar seña (pendiente_sena → confirmada).
    "taller_sena_confirmada": {
        "subject": "¡Tu lugar está confirmado! — {{ taller_nombre }}",
        "body_html": f"""<p {b.H}>¡Tu lugar está confirmado!</p>
<p style="margin:0 0 8px;">Hola <strong>{{{{ nombre_pila }}}}</strong>, verificamos tu seña — tu lugar en <strong>{{{{ taller_nombre }}}}</strong> queda reservado.</p>
<p {b.LBL}>Fechas</p>
<p style="margin:0 0 4px;"><strong>Desde:</strong> {{{{ fecha_inicio_str }}}}<br><strong>Hasta:</strong> {{{{ fecha_fin_str }}}}<br><strong>Horario:</strong> {{{{ horario }}}}<br><strong>Lugar:</strong> {{{{ direccion }}}}</p>
<p {b.MUTED_P}>¿Preguntas? Respondé este mail o escribínos por WhatsApp.</p>
<p style="margin:18px 0 0;">— El equipo de Rambla</p>""",
        "body_text": """Hola {{ nombre_pila }}, verificamos tu seña — tu lugar en {{ taller_nombre }} queda reservado.

Desde: {{ fecha_inicio_str }}
Hasta: {{ fecha_fin_str }}
Horario: {{ horario }}
Lugar: {{ direccion }}

¿Preguntas? Respondé este mail.

— El equipo de Rambla""",
    },
    # F4b: se liberó un cupo — se le ofrece a el/la primero/a de la lista de
    # espera, con link tokenizado para completar la seña.
    "taller_cupo_ofrecido": {
        "subject": "¡Se liberó un cupo! — {{ taller_nombre }}",
        "body_html": f"""<p {b.H}>¡Se liberó un cupo!</p>
<p style="margin:0 0 8px;">Hola <strong>{{{{ nombre_pila }}}}</strong>, se liberó un cupo en <strong>{{{{ taller_nombre }}}}</strong> y sos la/el primera/o en la lista de espera.</p>
<p style="margin:0 0 8px;">Completá tu seña ({{{{ precio_sena_str }}}}) para confirmar tu lugar — es por orden de llegada, así que te recomendamos hacerlo pronto.</p>
{b.btn("link_sena", "Completar mi seña")}
<p {b.MUTED_P}>¿Preguntas? Respondé este mail o escribínos por WhatsApp.</p>
<p style="margin:18px 0 0;">— El equipo de Rambla</p>""",
        "body_text": """Hola {{ nombre_pila }}, se liberó un cupo en {{ taller_nombre }} y sos la/el primera/o en la lista de espera.

Completá tu seña ({{ precio_sena_str }}) para confirmar tu lugar (por orden de llegada): {{ link_sena }}

¿Preguntas? Respondé este mail.

— El equipo de Rambla""",
    },
    # F4b: aviso a un interesado (lead sin cupo disponible en su momento) de
    # que hay una nueva edición abierta.
    "taller_interesado_nueva_edicion": {
        "subject": "Nueva edición abierta — {{ taller_nombre }}",
        "body_html": f"""<p {b.H}>Nueva edición abierta</p>
<p style="margin:0 0 8px;">Hola <strong>{{{{ nombre_pila }}}}</strong>, te contactamos porque te habías anotado como interesado/a en <strong>{{{{ taller_nombre }}}}</strong> — ¡ya está abierta una nueva edición!</p>
{b.btn("taller_url", "Ver el taller")}
<p {b.MUTED_P}>¿Preguntas? Respondé este mail o escribínos por WhatsApp.</p>
<p style="margin:18px 0 0;">— El equipo de Rambla</p>""",
        "body_text": """Hola {{ nombre_pila }}, te contactamos porque te habías anotado como interesado/a en {{ taller_nombre }} — ¡ya está abierta una nueva edición!

{{ taller_url }}

¿Preguntas? Respondé este mail.

— El equipo de Rambla""",
    },
}
