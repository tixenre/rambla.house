"""Documentos del pedido (#501 — extraído del god-module `routes/alquileres.py`).

Generación al vuelo de los PDFs del pedido (cotización / albarán / packing-list /
contrato) y el envío de esos documentos por mail al cliente (+ preview). Reusa el
renderer único `_doc_html` en descarga y envío. Registra sus rutas sobre el router
compartido del paquete `routes.alquileres`.
"""
from typing import Optional

from fastapi import Request, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from database import get_db, row_to_dict, MARCA_SUBQUERY
from services.contenido import contenido_de_batch
from services.categorias import root_of_categoria, categorias_por_ids
from pdf import _pedido_html, _albaran_html, _contrato_html, _packing_list_html, _render_pdf, _pedido_filename
from auth.guards import require_admin
from services.email import send_email, send_raw_email, render_template, wrap_preview, Attachment
from services.email.service import primer_nombre
from routes.alquileres.core import (
    router,
    _get_alquiler_items,
    _get_alquiler_detail,
    _enriquecer_pedido_con_cliente,
    _enriquecer_pedido_con_cliente_fiscal,
    _enriquecer_pedido_con_total,
    _pedido_email_context,
)


# ── PDFs ─────────────────────────────────────────────────────────────────────

# Los documentos (remito/albarán/contrato) se generan al vuelo y siempre deben
# reflejar el estado actual del pedido. Sin esto, el navegador cachea la URL
# estática (es la misma siempre) y, tras editar el pedido —p. ej. cambiar el
# cliente—, vuelve a servir el PDF viejo. `no-store` lo fuerza a re-pedirlo.
_DOC_NO_CACHE = {"Cache-Control": "no-store, max-age=0"}

# Documentos del pedido y su etiqueta legible (para la UI de envío por mail).
DOCUMENTOS = {
    "pdf": "Remito",
    "albaran": "Detalle de seguro",
    "contrato": "Contrato",
    "packing-list": "Checklist de retiro",
}


def _add_componentes(conn, items: list[dict]) -> None:
    """Agrega `componentes` a cada item (kits) vía la puerta única
    (services.contenido). Compartido por albarán y contrato. `solo_activos=False`:
    un documento de un pedido existente muestra TODOS los componentes que lleva,
    incluso una pieza dada de baja después (no filtra soft-deleted). Una query
    batcheada para todos los items en vez de N (una por item)."""
    eq_ids = [it["equipo_id"] for it in items if it.get("equipo_id") is not None]
    por_equipo = contenido_de_batch(conn, eq_ids, solo_activos=False)
    for item in items:
        item["componentes"] = [{
            "nombre":               c["nombre"],
            "marca":                c["marca"],
            "modelo":               c["modelo"],
            "serie":                c["serie"],
            "valor_reposicion":     c["valor_reposicion"],
            "foto_url":             c["foto_url"],
            "foto_url_sm":          c["foto_url_sm"],
            "foto_url_thumb":       c["foto_url_thumb"],
            "nombre_publico":       c["nombre_publico"],
            "nombre_publico_largo": c["nombre_publico_largo"],
            "cantidad":             c["cantidad"],
        } for c in por_equipo.get(item.get("equipo_id"), [])]


def _ordenar_items_en_grupos(items: list[dict], cat_de_equipo: dict) -> list[dict]:
    """Parte PURA (testeable sin DB) de la agrupación por categoría (#814).

    Dada la primera categoría por equipo (`cat_de_equipo: {equipo_id: (prioridad,
    nombre)}`), arma la lista de grupos ordenada por `prioridad` asc (luego nombre),
    preservando el orden de `items` dentro de cada grupo (el orden manual #806).
    Equipos sin categoría y líneas personalizadas (#805, equipo_id None) caen en
    'Otros', que va siempre al final.
    """
    OTROS = "Otros"
    grupos: dict[str, list] = {}
    prioridad: dict[str, float] = {}
    for it in items:
        cat = cat_de_equipo.get(it.get("equipo_id"))
        nombre, p = (cat[1], cat[0]) if cat else (OTROS, float("inf"))
        if nombre not in grupos:
            grupos[nombre] = []
            prioridad[nombre] = p
        grupos[nombre].append(it)
    nombres = sorted(grupos, key=lambda nm: (prioridad[nm], nm.lower()))
    return [{"categoria": nm, "items": grupos[nm]} for nm in nombres]


def _agrupar_items_por_categoria(conn, items: list[dict]) -> list[dict]:
    """Agrupa los ítems del pedido por la categoría RAÍZ (sector) de su primera
    categoría — para los documentos de check físico (packing list + albarán, #814).

    Cada equipo cae bajo su primera categoría (menor `equipo_categorias.orden`,
    misma convención que `attach_categorias`) y de ahí se SUBE por `parent_id`
    hasta la raíz: el agrupado es por sector (Cámaras, Lentes, Iluminación, …),
    no por la hoja/hija/nieta. Los grupos se ordenan por la `prioridad` de la
    raíz (igual que el catálogo público). La parte pura (`_ordenar_items_en_grupos`)
    hace el armado; acá solo se resuelve la raíz de cada equipo con una query única.
    """
    eq_ids = list({it["equipo_id"] for it in items if it.get("equipo_id") is not None})
    cat_de_equipo: dict[int, tuple] = {}
    if eq_ids:
        ph = ",".join("%s" for _ in eq_ids)
        first_cats = conn.execute(f"""
            SELECT t.equipo_id, t.categoria_id FROM (
                SELECT ec.equipo_id, ec.categoria_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY ec.equipo_id
                           ORDER BY ec.orden, c.prioridad, c.id
                       ) AS rn
                FROM equipo_categorias ec
                JOIN categorias c ON c.id = ec.categoria_id
                WHERE ec.equipo_id IN ({ph})
            ) t WHERE rn = 1
        """, tuple(eq_ids)).fetchall()

        root_ids: dict[int, int] = {}
        for r in first_cats:
            root = root_of_categoria(conn, r["categoria_id"])
            if root is not None:
                root_ids[r["equipo_id"]] = root

        if root_ids:
            distinct_roots = list(set(root_ids.values()))
            if distinct_roots:
                root_rows = categorias_por_ids(conn, distinct_roots)
                root_info = {r["id"]: (r["prioridad"], r["nombre"]) for r in root_rows}
            else:
                root_info = {}
            for eq_id, rid in root_ids.items():
                if rid in root_info:
                    cat_de_equipo[eq_id] = root_info[rid]
    return _ordenar_items_en_grupos(items, cat_de_equipo)


def _doc_html(conn, id: int, kind: str) -> tuple[str, str]:
    """Construye el HTML + filename de un documento del pedido. Fuente ÚNICA
    usada por los GET de descarga y por el envío por mail."""
    if kind == "pdf":
        row = conn.execute("SELECT * FROM alquileres WHERE id=%s", (id,)).fetchone()
        if not row:
            raise HTTPException(404, "Pedido no encontrado")
        pedido = row_to_dict(row)
        pedido["items"] = _get_alquiler_items(conn, id)
        _enriquecer_pedido_con_cliente(conn, pedido)
        _enriquecer_pedido_con_cliente_fiscal(conn, pedido)
        _enriquecer_pedido_con_total(conn, pedido)
        return _pedido_html(pedido), _pedido_filename(pedido)

    if kind == "albaran":
        row = conn.execute("SELECT * FROM alquileres WHERE id=%s", (id,)).fetchone()
        if not row:
            raise HTTPException(404, "Pedido no encontrado")
        pedido = row_to_dict(row)
        items = conn.execute(f"""
            SELECT pi.cantidad, COALESCE(e.nombre, pi.nombre_libre) AS nombre,
                   {MARCA_SUBQUERY}, e.modelo, e.serie, e.valor_reposicion, e.foto_url,
                   e.foto_url_sm, e.foto_url_thumb,
                   e.nombre_publico, e.nombre_publico_largo, pi.equipo_id
            FROM alquiler_items pi
            LEFT JOIN equipos e ON e.id = pi.equipo_id
            WHERE pi.pedido_id = %s
            ORDER BY pi.orden, pi.id
        """, (id,)).fetchall()
        pedido["items"] = [row_to_dict(i) for i in items]
        _add_componentes(conn, pedido["items"])
        _enriquecer_pedido_con_cliente(conn, pedido)
        # Dato fiscal (CUIT): "Detalle de seguro" era el único de los 4
        # documentos que no lo traía, pese a que su propia plantilla
        # (`_cliente_block`, compartida con Remito/Checklist/Contrato) ya sabe
        # mostrarlo si está presente. Hallazgo de auditoría, #1254.
        _enriquecer_pedido_con_cliente_fiscal(conn, pedido)
        # Check físico → agrupar por categoría (#814).
        pedido["grupos"] = _agrupar_items_por_categoria(conn, pedido["items"])
        return _albaran_html(pedido), _pedido_filename(pedido, doc="albaran")

    if kind == "packing-list":
        row = conn.execute("SELECT * FROM alquileres WHERE id=%s", (id,)).fetchone()
        if not row:
            raise HTTPException(404, "Pedido no encontrado")
        pedido = row_to_dict(row)
        _enriquecer_pedido_con_cliente(conn, pedido)
        _enriquecer_pedido_con_cliente_fiscal(conn, pedido)
        # `_get_alquiler_items` ya ordena por el orden manual (orden, id, #806).
        pedido["items"] = _get_alquiler_items(conn, id)
        # Check físico → agrupar por categoría (#814).
        pedido["grupos"] = _agrupar_items_por_categoria(conn, pedido["items"])
        return _packing_list_html(pedido), _pedido_filename(pedido, doc="packing-list")

    if kind == "contrato":
        pedido = _get_alquiler_detail(conn, id)
        _enriquecer_pedido_con_cliente_fiscal(conn, pedido)
        _add_componentes(conn, pedido["items"])
        return _contrato_html(pedido), _pedido_filename(pedido, doc="contrato")

    raise HTTPException(400, f"Documento inválido: {kind}")


@router.get("/alquileres/{id}/pdf")
async def pedido_pdf(id: int, request: Request, format: str = "pdf"):
    """`format=html` devuelve el preview HTML sin pasar por el renderer."""
    require_admin(request)
    with get_db() as conn:
        html, filename = _doc_html(conn, id, "pdf")
    if format == "html":
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html, headers=_DOC_NO_CACHE)
    pdf_bytes = await _render_pdf(html)
    return Response(
        content    = pdf_bytes,
        media_type = "application/pdf",
        headers    = {"Content-Disposition": f'attachment; filename="{filename}"', **_DOC_NO_CACHE},
    )


@router.get("/alquileres/{id}/albaran")
async def pedido_albaran(id: int, request: Request, format: str = "pdf"):
    """`format=html` devuelve el preview HTML sin pasar por el renderer."""
    require_admin(request)
    with get_db() as conn:
        html, filename = _doc_html(conn, id, "albaran")
    if format == "html":
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html, headers=_DOC_NO_CACHE)
    pdf_bytes = await _render_pdf(html)
    return Response(
        content    = pdf_bytes,
        media_type = "application/pdf",
        headers    = {"Content-Disposition": f'attachment; filename="{filename}"', **_DOC_NO_CACHE},
    )


@router.get("/alquileres/{id}/packing-list")
async def pedido_packing_list(id: int, request: Request, format: str = "pdf"):
    """`format=html` devuelve el preview HTML sin pasar por el renderer."""
    require_admin(request)
    with get_db() as conn:
        html_content, filename = _doc_html(conn, id, "packing-list")
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


def _ctx_mail_pedido(conn, id: int, docs: list[str], mensaje: Optional[str],
                     ped: Optional[dict] = None) -> tuple[dict, dict]:
    """Arma el contexto del mail rico (modo plantilla) de un pedido: contacto en
    vivo + desglose de total/jornadas (decisión 2026-06-06) + la lista de
    documentos adjuntos y la nota del admin. Fuente ÚNICA usada por el envío y
    por el preview → el preview no puede divergir de lo que se manda."""
    if ped is None:
        row = conn.execute("SELECT * FROM alquileres WHERE id=%s", (id,)).fetchone()
        if not row:
            raise HTTPException(404, "Pedido no encontrado")
        ped = row_to_dict(row)
    ped["items"] = _get_alquiler_items(conn, id)
    _enriquecer_pedido_con_cliente(conn, ped)
    _enriquecer_pedido_con_total(conn, ped)
    ctx = _pedido_email_context(ped)
    ctx["docs_adjuntos"] = [DOCUMENTOS[k] for k in docs]
    if mensaje and mensaje.strip():
        ctx["mensaje_admin"] = mensaje.strip()
    return ped, ctx


def _cuerpo_mail_simple(numero, nombre: str, docs: list[str],
                        mensaje: Optional[str]) -> tuple[str, str, str]:
    """Arma (subject, body_html, text) del mail genérico "mensaje simple". El
    body_html es el CONTENIDO (sin chrome) — se envuelve afuera. Fuente ÚNICA
    usada por el envío (`send_raw_email`) y por el preview (`wrap_preview`)."""
    nombres_docs = [DOCUMENTOS[k] for k in docs]
    subject = f"Documentos de tu pedido #{numero}"
    pila = primer_nombre(nombre)
    saludo = f"Hola {pila}," if pila else "Hola,"
    mensaje_html = ""
    if mensaje and mensaje.strip():
        # Escapado básico: el mensaje lo escribe el admin, pero por las dudas.
        import html as _html_mod
        mensaje_html = f"<p>{_html_mod.escape(mensaje.strip())}</p>"
    lista_docs = "".join(f"<li>{d}</li>" for d in nombres_docs)
    body_html = (
        f"<p>{saludo}</p>"
        f"<p>Te adjuntamos los siguientes documentos de tu pedido <strong>#{numero}</strong>:</p>"
        f"<ul>{lista_docs}</ul>"
        f"{mensaje_html}"
        f"<p>Cualquier duda, respondé este mail. ¡Gracias!</p>"
    )
    text = (
        f"{saludo}\n\nTe adjuntamos los documentos de tu pedido #{numero}: "
        f"{', '.join(nombres_docs)}.\n\n"
        f"{(mensaje.strip() + chr(10) + chr(10)) if (mensaje and mensaje.strip()) else ''}"
        f"Cualquier duda, respondé este mail. ¡Gracias!"
    )
    return subject, body_html, text


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
