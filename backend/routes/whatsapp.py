"""Routes admin del canal WhatsApp (Meta Cloud API).

Espeja `routes/facturacion.py` en lo que aplica: un `GET .../estado` agregador
(readiness sin secretos), la lista de templates a dar de alta en Meta, y un
`POST .../test` gateado para validar el pipeline de punta a punta cuando exista el
número (número de test de Meta → allowlist). El token NUNCA se expone ni se sube por
acá: vive en ENV (WHATSAPP_ACCESS_TOKEN), no en la BD.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

from auth.guards import require_admin
from database import get_db
from rate_limit import ADMIN_WRITE_LIMIT, limiter

router = APIRouter()

_E164 = re.compile(r"^\+\d{8,15}$")


@router.get("/admin/whatsapp/estado")
def estado_whatsapp(request: Request):
    """Readiness del canal (token/número/enabled/ambiente) + los templates a dar de
    alta en Meta, con su copy sugerido — para que el back-office muestre qué falta y
    qué pedir aprobado. Sin secretos (nunca el token)."""
    require_admin(request)

    from services.whatsapp import REGISTRO, diagnosticar

    with get_db() as conn:
        estado = diagnosticar(conn)

    plantillas = [
        {
            "key": p.key,
            "meta_name": p.meta_name,
            "lang": p.lang,
            "categoria": "utility",
            "descripcion": p.descripcion,
            "copy_ejemplo": p.copy_ejemplo,
            "parametros": list(p.campos_ctx),
        }
        for p in REGISTRO.values()
    ]
    return {**estado, "plantillas": plantillas}


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

    # Contexto de ejemplo (los mismos nombres que arma _pedido_email_context).
    ctx_demo = {
        "cliente_nombre": "Test",
        "numero_pedido": "0000",
        "fecha_desde": "hoy",
        "fecha_hasta": "hoy",
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
