"""Entry point del servicio de email.

`send_email()` es la única función pública para mandar mails desde el
resto del backend. Internamente:
1. Lee `app_settings` para resolver `email_from` (con fallback a env var).
2. Lee el template de `email_templates`.
3. Renderiza subject + html + text con Jinja2 (autoescape para html).
4. Llama al backend (resend/smtp/test).
5. Loggea TODO en `emails_log` — éxito o fallo.

NUNCA propaga excepciones del provider — los triggers (crear pedido,
confirmar pedido) no deben fallar si el mail no se envía.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Sequence, TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .base import Attachment

import jinja2

from config import settings
from database import get_db

from . import branding as b

logger = logging.getLogger(__name__)

_jinja_html = jinja2.Environment(autoescape=True, undefined=jinja2.Undefined)
_jinja_text = jinja2.Environment(autoescape=False, undefined=jinja2.Undefined)

# Templates que solo deben enviarse UNA vez por pedido (idempotency).
# El recordatorio_retiro tiene su propio UNIQUE INDEX en DB; estos los
# chequeamos via SELECT antes de enviar para evitar dobles envíos por
# doble-click, retries, o reentradas al endpoint de confirmación.
_IDEMPOTENT_PER_PEDIDO = {
    "pedido_creado_cliente",
    "pedido_confirmado_cliente",
    # Los avisos de devolución salen UNA vez por pedido y ventana: el barrido
    # puede correr varias veces el mismo día (scheduler + botón del back-office).
    "recordatorio_devolucion_d1",
    "recordatorio_devolucion_d0",
    "recordatorio_devolucion_vencido",
}


def _resolve_from(conn) -> str:
    """from address: env EMAIL_FROM > app_settings.email_from > fallback."""
    env_val = settings.EMAIL_FROM.strip()
    if env_val:
        return env_val
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = %s", ("email_from",),
    ).fetchone()
    if row and row["value"]:
        return row["value"]
    return f"Rambla Rental <noreply@{urlparse(settings.SITE_URL).netloc}>"


def _split_emails(raw: str) -> list[str]:
    """Parte un string crudo en direcciones — separador coma, punto y coma, o
    salto de línea (mismo criterio que ya usaba `routes/reportes.py` para la
    lista de destinatarios del reporte de liquidación; fuente única para no
    tener dos regexes ligeramente distintas)."""
    import re

    return [p.strip() for p in re.split(r"[,;\n]+", raw) if p.strip()]


def validar_email(direccion: str) -> Optional[str]:
    """Valida el FORMATO de una dirección (no la deliverability — no
    resuelve MX en el momento de guardar un setting) vía `email-validator`
    (ya es dependencia real de Pydantic). Devuelve la forma normalizada o
    `None` si es inválida."""
    from email_validator import validate_email, EmailNotValidError

    try:
        return validate_email(direccion, check_deliverability=False).normalized
    except EmailNotValidError:
        return None


def get_admin_tos() -> list[str]:
    """Direcciones para la notificación al admin: env `EMAIL_ADMIN_TO` >
    `app_settings.email_admin_to`, separadas por coma/punto y coma/salto de
    línea. Filtra entradas inválidas en vez de romper (mismo criterio que
    `services/whatsapp/config.py::destinatarios_admin`, su equivalente para
    WhatsApp) — deduplicadas sin distinguir mayúsculas."""
    crudo = settings.EMAIL_ADMIN_TO.strip()
    if not crudo:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = %s", ("email_admin_to",),
            ).fetchone()
            crudo = row["value"] if row and row["value"] else ""
        finally:
            conn.close()

    out: list[str] = []
    vistos: set[str] = set()
    for direccion in _split_emails(crudo):
        norm = validar_email(direccion)
        if norm and norm.lower() not in vistos:
            vistos.add(norm.lower())
            out.append(norm)
    return out


def channel_status() -> dict:
    """Estado del canal de mail para el back-office (indicador "¿está integrado%s").

    Devuelve el backend activo, si manda de verdad (`activo`: test=False porque
    solo loggea en memoria), el `from` resuelto y el destinatario admin.
    **No expone secretos** — nunca la API key. Reusa la fuente única
    `resolve_provider()` y los mismos helpers de resolución que el envío real.
    """
    from . import resolve_provider

    provider = resolve_provider()
    conn = get_db()
    try:
        from_addr = _resolve_from(conn)
    finally:
        conn.close()
    return {
        "provider": provider,
        "activo": provider != "test",
        "from_addr": from_addr,
        "admin_to": ", ".join(get_admin_tos()),
    }


def _setting(conn, key: str) -> str:
    """Lee un app_setting como string (vacío si no existe)."""
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = %s", (key,)
    ).fetchone()
    return (row["value"].strip() if row and row["value"] else "")


def _wrap_email_html(body_html: str, conn) -> str:
    """Envuelve el cuerpo renderizado en un layout branded común (header con
    logo + barra de acento + footer con contacto). Table-based + estilos
    inline para máxima compatibilidad con clientes de mail.

    Las plantillas editables guardan solo el CONTENIDO; el chrome vive acá,
    en un único lugar. El body ya viene renderizado y escapado por Jinja.
    """
    from config import SITE_URL

    # Header = barra amber sólida + wordmark BLANCO (mismo lenguaje que los
    # documentos PDF). La celda amber sólida resuelve el bug de dark mode: el
    # wordmark es blanco sobre transparente, así que el hueco muestra el amber
    # de la celda (no negro) en cualquier cliente. `email_logo_url` permite
    # override desde el back-office; NO se usa `logo_url` (el logo del top bar
    # puede ser de color → se perdería sobre el amber).
    logo = _setting(conn, "email_logo_url") or f"{SITE_URL}/email-wordmark-white.png"
    whatsapp = _setting(conn, "whatsapp_phone")

    wa_html = ""
    if whatsapp:
        digits = "".join(ch for ch in whatsapp if ch.isdigit())
        wa_html = (
            f' · <a href="https://wa.me/{digits}" '
            f'style="color:{b.MUTED};text-decoration:underline;">WhatsApp</a>'
        )

    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light only">
<title>Rambla Rental</title>
</head>
<body style="margin:0;padding:0;background:{b.BONE};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{b.BONE};padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:{b.CARD};border-radius:12px;overflow:hidden;border:1px solid {b.HAIRLINE};">
<tr><td bgcolor="{b.AMBER}" style="padding:20px 28px;background:{b.AMBER};text-align:left;">
<img src="{logo}" alt="Rambla Rental" height="32" style="height:32px;width:auto;display:inline-block;border:0;">
</td></tr>
<tr><td style="padding:28px;font-family:{b.FONT_SANS};font-size:15px;line-height:1.55;color:{b.INK};">
{body_html}
</td></tr>
<tr><td style="padding:20px 28px;background:{b.SURFACE};border-top:1px solid {b.HAIRLINE};font-family:{b.FONT_SANS};font-size:12px;line-height:1.5;color:{b.FAINT};text-align:center;">
<strong style="color:{b.INK};">Rambla Rental</strong> · alquiler de equipos audiovisuales<br>
<a href="{SITE_URL}" style="color:{b.MUTED};text-decoration:underline;">{SITE_URL.replace("https://", "").replace("http://", "")}</a>{wa_html}
</td></tr>
</table>
</td></tr>
</table>
</body></html>"""


def primer_nombre(nombre: str) -> str:
    """Devuelve solo el nombre de pila (primera palabra) de un nombre completo.
    Fuente ÚNICA del saludo por nombre de pila en los mails ("Hola Santiago" a
    partir de "Santiago Granone López"). Cadena vacía si no hay nombre."""
    partes = (nombre or "").strip().split()
    return partes[0] if partes else ""


def _con_nombre_pila(context: dict[str, Any]) -> dict[str, Any]:
    """Agrega `cliente_nombre_pila` (solo el nombre de pila) derivado de
    `cliente_nombre`, sin mutar el dict original. Los saludos de los mails al
    cliente ("Hola Santiago") usan el nombre de pila; el resto del mail y los
    documentos PDF siguen usando el nombre completo (`cliente_nombre`)."""
    if "cliente_nombre_pila" in context:
        return context
    ctx = dict(context)
    ctx["cliente_nombre_pila"] = primer_nombre(ctx.get("cliente_nombre") or "")
    return ctx


def render_template(
    template_key: str,
    context: dict[str, Any],
) -> dict[str, str]:
    """Renderiza una plantilla del catálogo con el contexto dado.
    Devuelve {subject, html, text}. Útil para preview sin enviar.

    El html se envuelve en el layout branded común (`_wrap_email_html`) — las
    plantillas guardan solo el contenido."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT subject, body_html, body_text FROM email_templates WHERE key = %s",
            (template_key,),
        ).fetchone()
        if not row:
            raise ValueError(f"Template '{template_key}' no existe")
        context = _con_nombre_pila(context)
        # subject + text: sin autoescape (texto plano).
        subject = _jinja_text.from_string(row["subject"]).render(**context)
        text = _jinja_text.from_string(row["body_text"]).render(**context)
        # html: con autoescape — variables de usuario quedan escapadas, pero
        # las que vienen con .html() o {{ x|safe }} pasan literales.
        body_html = _jinja_html.from_string(row["body_html"]).render(**context)
        html = _wrap_email_html(body_html, conn)
        return {"subject": subject, "html": html, "text": text}
    finally:
        conn.close()


def wrap_preview(body_html: str) -> str:
    """Envuelve un body ya armado en el layout branded común, para
    **previsualizar** (no envía ni loggea). Es la misma envoltura que usa
    `send_raw_email`, expuesta para que el preview del back-office muestre el
    mail tal cual sale (chrome incluido) sin duplicar el wrapper."""
    conn = get_db()
    try:
        return _wrap_email_html(body_html, conn)
    finally:
        conn.close()


def send_raw_email(
    to: str,
    subject: str,
    body_html: str,
    text: str,
    *,
    attachments: Optional[list] = None,
    alquiler_id: Optional[int] = None,
    log_key: str = "(raw)",
) -> dict[str, Any]:
    """Envía un mail transaccional one-off (sin plantilla de DB), con adjuntos
    opcionales. El `body_html` se envuelve en el layout branded común. Loggea
    SIEMPRE en `emails_log` y NUNCA propaga excepciones del provider — mismo
    contrato que `send_email`."""
    from . import get_backend
    from .base import EmailBackendError

    if not to or "@" not in to:
        logger.warning("send_raw_email: 'to' inválido (%r), abortando", to)
        return {"ok": False, "error": "destinatario inválido"}

    conn = get_db()
    try:
        from_addr = _resolve_from(conn)
        html = _wrap_email_html(body_html, conn)
        backend = get_backend()
        try:
            result = backend.send(
                to=to, subject=subject, html=html, text=text,
                from_addr=from_addr, attachments=attachments,
            )
        except EmailBackendError as e:
            logger.error("Envío raw falló (%s → %s): %s", log_key, to, e)
            log_id = _insert_log(
                conn, to=to, subject=subject, template_key=log_key,
                alquiler_id=alquiler_id, status="failed", provider=backend.name,
                provider_id=None, error=str(e),
            )
            conn.commit()
            return {"ok": False, "error": str(e), "provider": backend.name, "log_id": log_id}
        log_id = _insert_log(
            conn, to=to, subject=subject, template_key=log_key,
            alquiler_id=alquiler_id, status="sent", provider=result.provider,
            provider_id=result.provider_id, error=None,
        )
        conn.commit()
        logger.info(
            "send_raw_email ok: to=%s provider=%s id=%s", to, result.provider, result.provider_id
        )
        return {
            "ok": True,
            "provider": result.provider,
            "provider_id": result.provider_id,
            "log_id": log_id,
        }
    except Exception as e:
        logger.exception("send_raw_email: error inesperado: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"error interno: {e}"}
    finally:
        conn.close()


def send_email(
    template_key: str,
    to: str,
    context: dict[str, Any],
    alquiler_id: Optional[int] = None,
    attachments: Optional[Sequence["Attachment"]] = None,
    *,
    respect_enabled: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Envía un mail renderizando una plantilla. Loggea SIEMPRE en
    `emails_log`. NUNCA propaga excepciones del provider.

    `attachments` (opcional): lista de `Attachment` que el backend adjunta
    al mail (ej. el `.ics` de la reserva en la confirmación). Es la única boca
    de envío — no se crea un segundo camino para adjuntar.

    `respect_enabled` (default True): si la plantilla está apagada
    (`email_templates.enabled = false`), no se envía y se devuelve
    `{ok, skipped, reason:'disabled'}` sin loggear. Los envíos automáticos lo
    dejan en True; el envío de prueba del admin lo pasa en False para poder
    testear un template apagado.

    `force` (default False): saltea la idempotencia por-pedido
    (`_IDEMPOTENT_PER_PEDIDO`). Los disparos automáticos (crear/confirmar) la
    dejan en False para no mandar dos veces por doble-click/retry; un **envío
    manual desde el back-office** (el admin aprieta "Enviar" en el modal) la
    pasa en True para poder reenviar la confirmación a pedido.

    Devuelve un dict {ok, provider, provider_id?, error?, log_id} útil para
    el endpoint de test del admin.
    """
    from . import get_backend
    from .base import EmailBackendError

    if not to or "@" not in to:
        logger.warning("send_email: 'to' inválido (%r), abortando", to)
        return {"ok": False, "error": "destinatario inválido"}

    conn = get_db()
    try:
        # On/off por plantilla (Fase B): si está apagada, no se manda. El envío
        # de prueba del admin pasa respect_enabled=False para saltarse el gate.
        if respect_enabled:
            erow = conn.execute(
                "SELECT enabled FROM email_templates WHERE key = %s", (template_key,)
            ).fetchone()
            if erow is not None and not erow["enabled"]:
                logger.info(
                    "send_email: template '%s' apagado (enabled=false) → skip", template_key
                )
                return {"ok": True, "skipped": True, "reason": "disabled"}

        # Idempotency: si este template ya se envió OK para este pedido,
        # no lo mandamos de nuevo (doble-click en confirmar, retries, etc).
        # `force=True` (envío manual desde el back-office) la saltea.
        if not force and template_key in _IDEMPOTENT_PER_PEDIDO and alquiler_id:
            existing = conn.execute(
                """
                SELECT id FROM emails_log
                 WHERE template_key = %s AND alquiler_id = %s AND status = 'sent'
                 LIMIT 1
                """,
                (template_key, alquiler_id),
            ).fetchone()
            if existing:
                logger.info(
                    "send_email: skip duplicado tpl=%s alquiler=%s log_id=%s",
                    template_key, alquiler_id, existing["id"],
                )
                return {"ok": True, "skipped": True, "log_id": existing["id"]}

        try:
            rendered = render_template(template_key, context)
        except Exception as e:
            logger.error("Render falló para %s: %s", template_key, e, exc_info=True)
            log_id = _insert_log(
                conn, to=to, subject=f"[render error] {template_key}",
                template_key=template_key, alquiler_id=alquiler_id,
                status="failed", provider="(none)", provider_id=None,
                error=f"render error: {e}",
            )
            conn.commit()
            return {"ok": False, "error": str(e), "log_id": log_id}

        from_addr = _resolve_from(conn)
        backend = get_backend()

        try:
            result = backend.send(
                to=to,
                subject=rendered["subject"],
                html=rendered["html"],
                text=rendered["text"],
                from_addr=from_addr,
                attachments=attachments,
            )
        except EmailBackendError as e:
            logger.error("Envío falló (%s → %s): %s", template_key, to, e)
            log_id = _insert_log(
                conn, to=to, subject=rendered["subject"],
                template_key=template_key, alquiler_id=alquiler_id,
                status="failed", provider=backend.name, provider_id=None,
                error=str(e),
            )
            conn.commit()
            return {"ok": False, "error": str(e), "provider": backend.name, "log_id": log_id}

        log_id = _insert_log(
            conn, to=to, subject=rendered["subject"],
            template_key=template_key, alquiler_id=alquiler_id,
            status="sent", provider=result.provider, provider_id=result.provider_id,
            error=None,
        )
        conn.commit()
        logger.info(
            "send_email ok: tpl=%s to=%s provider=%s id=%s",
            template_key, to, result.provider, result.provider_id,
        )
        return {
            "ok": True,
            "provider": result.provider,
            "provider_id": result.provider_id,
            "log_id": log_id,
        }
    except Exception as e:
        # Captura amplia para garantizar el contrato "nunca propaga".
        logger.exception("send_email: error inesperado: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"error interno: {e}"}
    finally:
        conn.close()


def _insert_log(
    conn,
    *,
    to: str,
    subject: str,
    template_key: str,
    alquiler_id: Optional[int],
    status: str,
    provider: str,
    provider_id: Optional[str],
    error: Optional[str],
) -> Optional[int]:
    """INSERT en emails_log; devuelve el id generado. Devuelve None si el
    INSERT falla por race condition con el UNIQUE INDEX (recordatorio_retiro
    duplicado) — en ese caso es OK que se ignore, ya hay otro envío exitoso.
    """
    try:
        cur = conn.execute(
            """
            INSERT INTO emails_log
                (to_addr, subject, template_key, alquiler_id,
                 status, provider, provider_id, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (to, subject, template_key, alquiler_id,
             status, provider, provider_id, error),
        )
        row = cur.fetchone()
        return row["id"] if row else None
    except Exception as e:
        # El UNIQUE INDEX parcial del recordatorio puede tirar IntegrityError
        # si el job corre 2 veces — es comportamiento deseado (idempotencia).
        logger.warning("emails_log INSERT falló (idempotencia%s): %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return None
