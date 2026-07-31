"""Routes admin del canal WhatsApp (Meta Cloud API).

Espeja `routes/facturacion.py` en lo que aplica: un `GET .../estado` agregador
(readiness sin secretos), la lista de templates a dar de alta en Meta, y un
`POST .../test` gateado para validar el pipeline de punta a punta cuando exista el
número (número de test de Meta → allowlist). El token NUNCA se expone ni se sube por
acá: vive en ENV (WHATSAPP_ACCESS_TOKEN), no en la BD.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from auth.guards import require_admin
from database import get_db
from rate_limit import ADMIN_WRITE_LIMIT, limiter

logger = logging.getLogger(__name__)

router = APIRouter()

_E164 = re.compile(r"^\+\d{8,15}$")


@router.get("/admin/whatsapp/estado")
def estado_whatsapp(request: Request):
    """Readiness del canal (token/número/enabled/ambiente) + los templates a dar de
    alta en Meta, con su copy sugerido — para que el back-office muestre qué falta y
    qué pedir aprobado. Sin secretos (nunca el token)."""
    require_admin(request)

    from services.whatsapp import REGISTRO, diagnosticar, estado_plantillas

    with get_db() as conn:
        estado = diagnosticar(conn)

    # Estado de aprobación REAL en Meta (una llamada al Graph). Si el canal no está
    # configurado devuelve `disponible: False` sin romper — la pantalla igual muestra
    # el copy para dar de alta a mano.
    remoto = estado_plantillas()
    por_key = {f["key"]: f for f in remoto.get("plantillas", [])}

    plantillas = [
        {
            "key": p.key,
            "meta_name": p.meta_name,
            "lang": p.lang,
            "categoria": "utility",
            "descripcion": p.descripcion,
            "copy_ejemplo": p.copy_ejemplo,
            "parametros": list(p.campos_ctx),
            # None cuando no se pudo consultar (canal sin configurar / Meta caído).
            "estado_meta": (por_key.get(p.key) or {}).get("estado"),
        }
        for p in REGISTRO.values()
    ]
    return {
        **estado,
        "plantillas": plantillas,
        "gestion_plantillas": {
            "disponible": remoto.get("disponible", False),
            "motivo": remoto.get("motivo"),
        },
    }


@router.post("/admin/whatsapp/plantillas/sincronizar")
@limiter.limit(ADMIN_WRITE_LIMIT)
def sincronizar_plantillas(request: Request):
    """Da de alta en Meta las plantillas del registro que falten (las que ya existen
    no se tocan). No saltea la revisión: nacen en PENDING y Meta las aprueba."""
    require_admin(request)

    from services.whatsapp import sincronizar

    return sincronizar()


@router.post("/admin/whatsapp/test")
@limiter.limit(ADMIN_WRITE_LIMIT)
def test_whatsapp(request: Request, body: dict):
    """Envía un template de prueba a un número (E.164). Para validar el pipeline con
    el número de test de Meta. Respeta la allowlist de no-producción (WHATSAPP_TEST_
    RECIPIENTS) y NO chequea opt-in (es un envío explícito del admin a un número que
    él controla). No persiste en whatsapp_log (es una prueba, no un evento de pedido)."""
    require_admin(request)

    from services.whatsapp.config import destinatario_permitido, resolver_creds
    from services.whatsapp.plantillas import REGISTRO
    from whatsapp_cloud import WhatsAppClient, WhatsAppError

    creds = resolver_creds()
    if creds is None:
        raise HTTPException(503, "Canal WhatsApp sin configurar (falta WHATSAPP_ACCESS_TOKEN / _PHONE_NUMBER_ID)")

    to = str(body.get("to") or "").strip().replace(" ", "").replace("-", "")
    if not _E164.match(to):
        raise HTTPException(400, "El destino debe estar en E.164 (ej. +5492235550000)")
    if not destinatario_permitido(to):
        raise HTTPException(
            400,
            "Destino no permitido fuera de producción: agregalo a WHATSAPP_TEST_RECIPIENTS "
            "(y en el WhatsApp Manager como número de test).",
        )

    plantilla_key = str(body.get("plantilla") or "pedido_confirmado")
    plantilla = REGISTRO.get(plantilla_key)
    if plantilla is None:
        raise HTTPException(400, f"Template '{plantilla_key}' no existe en el registro")

    from services.comunicacion.contacto import telefono_negocio

    # Contexto de ejemplo (los mismos nombres que arma _pedido_email_context).
    ctx_demo = {
        "cliente_nombre": "Test",
        "numero_pedido": "0000",
        "fecha_desde": "hoy",
        "fecha_hasta": "hoy",
        "whatsapp_contacto": telefono_negocio() or "+54 9 223 585-2510",
    }
    client = WhatsAppClient(
        phone_number_id=creds.phone_number_id,
        access_token=creds.access_token,
        base_url=creds.base_url,
    )
    try:
        res = client.enviar_template(
            to=to,
            template_name=plantilla.meta_name,
            lang_code=plantilla.lang,
            body_params=plantilla.params(ctx_demo),
        )
    except WhatsAppError as e:
        raise HTTPException(_status_for_wa_error(e), str(e))
    return {"ok": True, "wamid": res.message_id, "to": to, "template": plantilla.meta_name}


@router.post("/admin/whatsapp/recordatorios-devolucion/run")
@limiter.limit(ADMIN_WRITE_LIMIT)
def run_recordatorios_devolucion(request: Request, body: dict | None = None):
    """Corre el barrido de recordatorios de devolución on-demand. `dry_run` (default
    True) solo lista candidatos sin enviar — preview seguro. `ventanas` opcional
    (lista de 'd1'/'d0'/'vencido'); si falta, usa las prendidas en la config."""
    require_admin(request)

    from jobs.recordatorios_devolucion import enviar_recordatorios_devolucion
    from jobs.recordatorios_devolucion_config import resolve as resolve_dev

    body = body or {}
    dry_run = bool(body.get("dry_run", True))
    ventanas = body.get("ventanas")
    if ventanas is None:
        ventanas = resolve_dev()["ventanas"]
    return enviar_recordatorios_devolucion(ventanas=set(ventanas), dry_run=dry_run)


@router.get("/webhooks/whatsapp")
def verificar_webhook_whatsapp(request: Request):
    """Handshake GET que Meta hace UNA vez al guardar el Callback URL en
    Configuration → Webhooks. Sin sesión (lo llama Meta): exento del middleware
    de auth por el prefijo `/api/webhooks/` (mismo criterio que Didit)."""
    from services.whatsapp import WhatsAppWebhookError, verify_challenge

    q = request.query_params
    try:
        challenge = verify_challenge(
            q.get("hub.mode", ""), q.get("hub.verify_token", ""), q.get("hub.challenge", "")
        )
    except WhatsAppWebhookError as exc:
        logger.warning("whatsapp webhook: handshake rechazado — %s", exc)
        raise HTTPException(403, str(exc))
    return PlainTextResponse(challenge)


@router.post("/webhooks/whatsapp", status_code=200)
async def recibir_webhook_whatsapp(request: Request):
    """Recibe estados de entrega y mensajes entrantes. Autenticado SOLO por
    firma HMAC (`X-Hub-Signature-256`) — sin sesión, lo llama Meta server-to-
    server. Siempre devuelve 200 con firma válida (Meta reintenta si no)."""
    from services.whatsapp import WhatsAppWebhookError, procesar_evento, verify_signature

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    try:
        verify_signature(body, signature)
    except WhatsAppWebhookError as exc:
        logger.warning("whatsapp webhook: firma rechazada — %s", exc)
        raise HTTPException(401, "Firma inválida")

    try:
        payload = await request.json()
    except Exception:
        logger.error("whatsapp webhook: body no es JSON válido")
        return {"ok": True}

    with get_db() as conn:
        resultado = procesar_evento(payload, conn)
        conn.commit()
    logger.info("whatsapp webhook: %s", resultado)
    return {"ok": True}


def _status_for_wa_error(exc) -> int:
    """Mapea la taxonomía de whatsapp_cloud a un status HTTP (mismo criterio que
    `facturacion._status_for_arca_error`)."""
    from whatsapp_cloud import (
        WhatsAppAuthError,
        WhatsAppRateLimitError,
        WhatsAppRequestError,
        WhatsAppResponseError,
    )

    if isinstance(exc, WhatsAppRequestError):
        return 422  # Meta rechazó por regla propia (número/template) — no transitorio
    if isinstance(exc, WhatsAppResponseError):
        return 502  # respuesta inesperada — integración
    if isinstance(exc, WhatsAppRateLimitError):
        return 429
    if isinstance(exc, WhatsAppAuthError):
        return 503  # credencial/permiso — configuración
    return 503  # network / base
