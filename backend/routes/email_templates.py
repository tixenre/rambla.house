"""CRUD admin de plantillas de email + endpoints de preview/test.

Endpoints (todos bajo /api/admin):
- GET  /email-templates                  → lista
- GET  /email-templates/{key}            → detalle
- PATCH /email-templates/{key}           → editar
- POST /email-templates/{key}/preview    → renderiza con context (no envía)
- POST /email-templates/{key}/test       → envía mail real al `to` que pasa el admin
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from auth.guards import require_admin
from database import get_db, row_to_dict
from services.email import branding as _eb, render_template, send_email

logger = logging.getLogger(__name__)
router = APIRouter()


# Sample context para previews — refleja los placeholders comunes que
# pueden aparecer en cualquier template. Pisable por el caller. La tabla de
# ítems se arma con el helper canónico de branding (misma fuente que el mail
# real → el preview no miente sobre el estilo).
_PREVIEW_ITEMS_HTML = _eb.items_table(
    _eb.item_row("Sony FX3", "1", "$ 9.000")
    + _eb.item_row("RØDE NTG", "2", "$ 3.500")
)

_PREVIEW_CONTEXT: dict[str, Any] = {
    "cliente_nombre": "Juan Pérez",
    "cliente_email": "juan@ejemplo.com",
    "cliente_telefono": "+54 9 223 585 2510",
    "numero_pedido": "1234",
    "fecha_desde": "20 may · 10:00",
    "fecha_hasta": "24 may · 18:00",
    "cantidad_jornadas": 4,
    "total": "$ 12.500",
    "total_pagado": "$ 6.250",
    "saldo_pendiente": "$ 6.250",
    "pago_estado": "Pagado $ 6.250 · saldo pendiente $ 6.250",
    # Sample para que el preview muestre la nota del admin y la lista de
    # adjuntos cuando el mail se manda desde el modal de envío al cliente.
    "mensaje_admin": "¡Gracias por elegirnos! Te esperamos el jueves a las 10.",
    "docs_adjuntos": ["Contrato", "Remito", "Detalle de seguro"],
    "notas": "Necesito un trípode extra.",
    "items_html": _PREVIEW_ITEMS_HTML,
    "items_text": "- Sony FX3 × 1\n- RØDE NTG × 2",
    "admin_url": "https://rambla.house/admin/pedidos/1234",
    "portal_url": "https://rambla.house/cliente/portal",
    # Sample para que el botón "Agregar al calendario" (confirmado) se vea en
    # el Preview; en el envío real lo arma `_pedido_email_context`.
    "gcal_url": "https://calendar.google.com/calendar/render?action=TEMPLATE",
    # Días de anticipación del recordatorio (configurable). =1 → el preview
    # muestra la variante "mañana"; el envío real lo inyecta el job.
    "dias_antes": 1,
    # Placeholders de los mails de modificación de pedido (modificacion_*); en el
    # envío real los arma `routes/cliente_portal._build_diff_payload` / el dispatch.
    "fecha_desde_actual": "20 may · 10:00",
    "fecha_hasta_actual": "24 may · 18:00",
    "fecha_desde_propuesta": "21 may · 10:00",
    "fecha_hasta_propuesta": "25 may · 18:00",
    "total_actual": "$ 12.500",
    "diff_html": "<ul><li>Sony FX3: 1 → 2</li><li>RØDE NTG: 2 → 1</li></ul>",
    "diff_text": "  - Sony FX3: 1 → 2\n  - RØDE NTG: 2 → 1",
    "mensaje": "¿Pueden sumar un trípode?",
    "estado_label": "aprobada",
    "respuesta": "Listo, ajustamos las fechas y el equipo.",
}


class TemplateUpdate(BaseModel):
    subject: str
    body_html: str
    body_text: str


class TemplatePreview(BaseModel):
    context: Optional[dict[str, Any]] = None


class TemplateTest(BaseModel):
    to: str
    context: Optional[dict[str, Any]] = None


class TemplateEnabled(BaseModel):
    enabled: bool


@router.get("/admin/email/status")
def email_channel_status(request: Request):
    """Estado del canal de mail: qué backend está activo y si manda de verdad.
    Para que el dueño verifique de un vistazo que el mail quedó integrado tras
    setear `RESEND_API_KEY` en prod. No expone secretos."""
    require_admin(request)
    from services.email.service import channel_status

    return channel_status()


@router.get("/admin/email-templates")
def list_templates(request: Request):
    require_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT key, subject, enabled, updated_at, updated_by "
            "FROM email_templates ORDER BY key"
        ).fetchall()
        return {"items": [row_to_dict(r) for r in rows]}


@router.get("/admin/email-templates/{key}")
def get_template(key: str, request: Request):
    require_admin(request)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT key, subject, body_html, body_text, enabled, updated_at, updated_by
            FROM email_templates WHERE key = %s
            """,
            (key,),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Template '{key}' no encontrado")
        return row_to_dict(row)


@router.patch("/admin/email-templates/{key}")
def update_template(key: str, data: TemplateUpdate, request: Request):
    session = require_admin(request)
    if not data.subject.strip():
        raise HTTPException(400, "subject no puede estar vacío")
    if not data.body_html.strip() and not data.body_text.strip():
        raise HTTPException(400, "body_html y body_text no pueden estar ambos vacíos")
    with get_db() as conn:
        cur = conn.execute(
            """
            UPDATE email_templates
            SET subject = %s, body_html = %s, body_text = %s,
                updated_at = CURRENT_TIMESTAMP, updated_by = %s
            WHERE key = %s
            RETURNING key, subject, body_html, body_text, updated_at, updated_by
            """,
            (data.subject, data.body_html, data.body_text,
             session.get("email", "unknown"), key),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"Template '{key}' no encontrado")
        conn.commit()
        return row_to_dict(row)


@router.patch("/admin/email-templates/{key}/enabled")
def set_template_enabled(key: str, data: TemplateEnabled, request: Request):
    """Prende/apaga el envío automático de una plantilla. No toca el contenido
    ni `updated_by` (no es una edición de copy del admin) → el repintado por
    migración sigue aplicando si la plantilla nunca se editó a mano."""
    require_admin(request)
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE email_templates SET enabled = %s WHERE key = %s RETURNING key, enabled",
            (data.enabled, key),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"Template '{key}' no encontrado")
        conn.commit()
        return row_to_dict(row)


@router.get("/admin/emails-log")
def list_emails_log(
    request: Request,
    status: Optional[str] = None,
    template_key: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """Visor read-only del log de envíos (`emails_log`): qué salió, a quién,
    cuáles fallaron y el error. Lo más valioso para diagnosticar entregabilidad.
    Paginado (limit/offset) y con filtros opcionales por estado, plantilla y
    destinatario (`q`, substring case-insensitive sobre `to_addr`)."""
    require_admin(request)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    where = []
    params: list[Any] = []
    if status:
        where.append("status = %s")
        params.append(status)
    if template_key:
        where.append("template_key = %s")
        params.append(template_key)
    if q:
        where.append("to_addr ILIKE %s")
        params.append(f"%{q}%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM emails_log{clause}", tuple(params)
        ).fetchone()["n"]
        rows = conn.execute(
            f"""
            SELECT id, to_addr, subject, template_key, alquiler_id,
                   status, provider, provider_id, error, sent_at
            FROM emails_log{clause}
            ORDER BY sent_at DESC, id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        ).fetchall()
        items = []
        for r in rows:
            d = row_to_dict(r)
            if d.get("sent_at") is not None and hasattr(d["sent_at"], "isoformat"):
                d["sent_at"] = d["sent_at"].isoformat()
            items.append(d)
        return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/admin/email-templates/{key}/preview")
def preview_template(key: str, data: TemplatePreview = Body(default=TemplatePreview()),
                     request: Request = None):
    require_admin(request)
    ctx = {**_PREVIEW_CONTEXT, **(data.context or {})}
    try:
        return render_template(key, ctx)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        # Errores de Jinja (sintaxis, variable indefinida con strict) caen acá.
        logger.warning("preview falló para %s: %s", key, e)
        raise HTTPException(400, f"Error renderizando template: {e}")


@router.post("/admin/email-templates/{key}/test")
def test_template(key: str, data: TemplateTest, request: Request):
    require_admin(request)
    if not data.to or "@" not in data.to:
        raise HTTPException(400, "Dirección 'to' inválida")
    ctx = {**_PREVIEW_CONTEXT, **(data.context or {})}
    # El test del admin ignora el on/off: tiene que poder probar un template
    # aunque esté apagado para envíos automáticos.
    result = send_email(
        template_key=key, to=data.to, context=ctx, alquiler_id=None,
        respect_enabled=False,
    )
    return result
