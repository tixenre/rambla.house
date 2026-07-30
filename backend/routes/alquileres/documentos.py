"""Documentos del pedido (#501 — extraído del god-module `routes/alquileres.py`).

Transporte HTTP fino (#1312, Fase 1): delega en la fuente única de lectura +
I/O externo `services.alquileres.queries.documentos` (armado de HTML/contexto
de mail). Este módulo solo abre la conexión, renderiza el PDF (Playwright,
async) y envía el mail. Registra sus rutas sobre el router compartido del
paquete `routes.alquileres`.
"""
from typing import Optional

from fastapi import Request, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from database import get_db, row_to_dict
from services.email import send_email, send_raw_email, render_template, wrap_preview, Attachment
from pdf import _render_pdf
from auth.guards import require_admin
from routes.alquileres.core import router
from services.alquileres.queries.documentos import (
    DOCUMENTOS,
    _add_componentes,  # noqa: F401 — re-export, lo usan los tests vía este módulo
    _agrupar_items_por_categoria,  # noqa: F401 — re-export, lo usa cliente_portal/documentos.py
    _ctx_mail_pedido,
    _cuerpo_mail_simple,
    _doc_html,
    _ordenar_items_en_grupos,  # noqa: F401 — re-export, lo re-exporta routes/alquileres/__init__.py
)


# ── PDFs ─────────────────────────────────────────────────────────────────────

# Los documentos (remito/albarán/contrato) se generan al vuelo y siempre deben
# reflejar el estado actual del pedido. Sin esto, el navegador cachea la URL
# estática (es la misma siempre) y, tras editar el pedido —p. ej. cambiar el
# cliente—, vuelve a servir el PDF viejo. `no-store` lo fuerza a re-pedirlo.
_DOC_NO_CACHE = {"Cache-Control": "no-store, max-age=0"}


@router.get("/alquileres/{id}/remito")
async def pedido_remito(id: int, request: Request, format: str = "pdf"):
    """`format=html` devuelve el preview HTML sin pasar por el renderer."""
    require_admin(request)
    with get_db() as conn:
        html, filename = _doc_html(conn, id, "remito")
    if format == "html":
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html, headers=_DOC_NO_CACHE)
    pdf_bytes = await _render_pdf(html)
    return Response(
        content    = pdf_bytes,
        media_type = "application/pdf",
        headers    = {"Content-Disposition": f'attachment; filename="{filename}"', **_DOC_NO_CACHE},
    )


@router.get("/alquileres/{id}/detalle-seguro")
async def pedido_detalle_seguro(id: int, request: Request, format: str = "pdf"):
    """`format=html` devuelve el preview HTML sin pasar por el renderer."""
    require_admin(request)
    with get_db() as conn:
        html, filename = _doc_html(conn, id, "detalle-seguro")
    if format == "html":
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html, headers=_DOC_NO_CACHE)
    pdf_bytes = await _render_pdf(html)
    return Response(
        content    = pdf_bytes,
        media_type = "application/pdf",
        headers    = {"Content-Disposition": f'attachment; filename="{filename}"', **_DOC_NO_CACHE},
    )


@router.get("/alquileres/{id}/checklist-retiro")
async def pedido_checklist_retiro(id: int, request: Request, format: str = "pdf"):
    """`format=html` devuelve el preview HTML sin pasar por el renderer."""
    require_admin(request)
    with get_db() as conn:
        html_content, filename = _doc_html(conn, id, "checklist-retiro")
    if format == "html":
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html_content, headers=_DOC_NO_CACHE)
    pdf_bytes = await _render_pdf(html_content)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', **_DOC_NO_CACHE},
    )


@router.get("/alquileres/{id}/contrato")
async def pedido_contrato(id: int, request: Request, format: str = "pdf"):
    """Genera el PDF del contrato de alquiler."""
    require_admin(request)
    with get_db() as conn:
        html, filename = _doc_html(conn, id, "contrato")
    if format == "html":
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html, headers=_DOC_NO_CACHE)
    pdf_bytes = await _render_pdf(html)
    return Response(
        content    = pdf_bytes,
        media_type = "application/pdf",
        headers    = {"Content-Disposition": f'attachment; filename="{filename}"', **_DOC_NO_CACHE},
    )


# ── Enviar documentos por mail (#725) ─────────────────────────────────────────

# Plantillas de mail que se pueden elegir desde el modal de envío al cliente.
# Es un subconjunto curado de los templates al CLIENTE (nunca los de admin) →
# evita que el modal mande un "entró un pedido nuevo" al cliente por error.
# Las etiquetas (lo que ve el admin) viven en el frontend; acá solo la whitelist.
PLANTILLAS_ENVIO_CLIENTE = {
    "pedido_confirmado_cliente",
    "pedido_creado_cliente",
}


class EnviarDocsRequest(BaseModel):
    docs: list[str]                       # subconjunto de DOCUMENTOS
    to: Optional[str] = None              # override del destinatario (default: cliente)
    mensaje: Optional[str] = None         # mensaje/nota opcional del admin
    template: Optional[str] = None        # plantilla a usar (whitelist); None = mensaje simple


class MailPreviewRequest(BaseModel):
    docs: list[str] = []                  # documentos a listar como adjuntos en el cuerpo
    mensaje: Optional[str] = None         # nota del admin (se ve en el preview)
    template: Optional[str] = None        # plantilla; None = mensaje simple


@router.post("/alquileres/{id}/enviar-documentos")
async def enviar_documentos(id: int, data: EnviarDocsRequest, request: Request):
    """Manda al cliente los documentos elegidos (cotización/remito/contrato/
    packing-list) adjuntos en PDF.

    Dos modos, mismo adjunto:
    - **Con `template`** (ej. `pedido_confirmado_cliente`): renderiza el mail
      rico editable con TODO el contexto de la reserva (fechas, jornadas, ítems,
      total, estado de pago, botón calendario) vía el mailer único `send_email`.
      `force=True` permite reenviarlo a mano aunque ya se haya mandado el auto.
    - **Sin `template`** (mensaje simple): cuerpo genérico vía `send_raw_email`.

    Reusa el renderer único de documentos (`_doc_html`) en ambos."""
    require_admin(request)

    docs = [d for d in (data.docs or []) if d in DOCUMENTOS]
    if not docs:
        raise HTTPException(400, "Elegí al menos un documento válido.")

    template = (data.template or "").strip() or None
    if template and template not in PLANTILLAS_ENVIO_CLIENTE:
        raise HTTPException(400, f"Plantilla inválida: {template}")

    # Resolver destinatario + metadatos del pedido (dentro de la conexión).
    with get_db() as conn:
        row = conn.execute("SELECT * FROM alquileres WHERE id=%s", (id,)).fetchone()
        if not row:
            raise HTTPException(404, "Pedido no encontrado")
        ped = row_to_dict(row)
        if ped["estado"] == "borrador":
            raise HTTPException(400, "No se puede enviar mail de un pedido en borrador")
        destinatario = (data.to or ped.get("cliente_email") or "").strip()
        if not destinatario and ped.get("cliente_id"):
            c = conn.execute(
                "SELECT email FROM clientes WHERE id=%s", (ped["cliente_id"],)
            ).fetchone()
            if c and c["email"]:
                destinatario = c["email"].strip()
        if not destinatario or "@" not in destinatario:
            raise HTTPException(400, "El pedido no tiene un email de cliente válido.")

        # Renderizar el HTML de cada documento (con la conexión abierta).
        docs_html = [(kind, *_doc_html(conn, id, kind)) for kind in docs]

        # Si hay plantilla, armamos el contexto del mail con la conexión abierta
        # (helper único, compartido con el preview).
        ctx = None
        if template:
            _, ctx = _ctx_mail_pedido(conn, id, docs, data.mensaje, ped=ped)

    # Renderizar los PDFs fuera de la conexión (Playwright, async).
    adjuntos: list[Attachment] = []
    for _kind, html, filename in docs_html:
        pdf_bytes = await _render_pdf(html)
        adjuntos.append(Attachment(filename=filename, content=pdf_bytes))

    numero = ped.get("numero_pedido") or id

    # ── Modo plantilla: mail rico editable + PDFs adjuntos ────────────────────
    if template and ctx is not None:
        res = send_email(
            template, destinatario, ctx, alquiler_id=id,
            attachments=adjuntos, respect_enabled=False, force=True,
        )
        if not res.get("ok"):
            raise HTTPException(
                502, f"No se pudo enviar el mail: {res.get('error', 'error desconocido')}"
            )
        return {
            "ok": True, "to": destinatario, "docs": docs,
            "template": template, "provider": res.get("provider"),
        }

    # ── Modo mensaje simple: cuerpo genérico + PDFs adjuntos ──────────────────
    nombre = (ped.get("cliente_nombre") or "").strip()
    subject, body_html, text = _cuerpo_mail_simple(numero, nombre, docs, data.mensaje)

    res = send_raw_email(
        to=destinatario,
        subject=subject,
        body_html=body_html,
        text=text,
        attachments=adjuntos,
        alquiler_id=id,
        log_key="documentos_cliente",
    )
    if not res.get("ok"):
        raise HTTPException(502, f"No se pudo enviar el mail: {res.get('error', 'error desconocido')}")
    return {"ok": True, "to": destinatario, "docs": docs, "provider": res.get("provider")}


@router.post("/alquileres/{id}/mail-preview")
def mail_preview(id: int, data: MailPreviewRequest, request: Request):
    """Renderiza el mail que mandaría el modal (plantilla + nota + adjuntos
    elegidos) con los datos REALES de este pedido, **sin enviar**. Devuelve
    {subject, html, text}. Reusa los mismos helpers que el envío
    (`_ctx_mail_pedido` / `_cuerpo_mail_simple`) → el preview no puede divergir
    de lo que se manda."""
    require_admin(request)

    docs = [d for d in (data.docs or []) if d in DOCUMENTOS]
    template = (data.template or "").strip() or None
    if template and template not in PLANTILLAS_ENVIO_CLIENTE:
        raise HTTPException(400, f"Plantilla inválida: {template}")

    with get_db() as conn:
        row = conn.execute(
            "SELECT numero_pedido, cliente_nombre FROM alquileres WHERE id=%s", (id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Pedido no encontrado")
        ped = row_to_dict(row)
        if template:
            _, ctx = _ctx_mail_pedido(conn, id, docs, data.mensaje)
        else:
            numero = ped.get("numero_pedido") or id
            nombre = (ped.get("cliente_nombre") or "").strip()
            subject, body_html, text = _cuerpo_mail_simple(numero, nombre, docs, data.mensaje)

    # Renderizado fuera de la conexión (cada uno abre la suya: render_template /
    # wrap_preview) — mismo patrón que el envío.
    if template:
        return render_template(template, ctx)
    return {"subject": subject, "html": wrap_preview(body_html), "text": text}
