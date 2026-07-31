"""services.whatsapp.estado — readiness del canal WhatsApp.

Molde `services.facturacion.diagnostico.diagnosticar_emisor`: devuelve
`{"chequeos": [{check, ok, bloqueante, mensaje}], "listo": bool}` — mismo shape que
usa el front para el diagnóstico de facturación, así el back-office reusa el renderer.

Hoy es solo Capa 1 (local, sin red): credencial presente, phone_number_id, canal
prendido, ambiente. Un probe en vivo contra Meta (Capa 2, ej. GET del número) se
puede sumar cuando exista el token real — no se agrega a ciegas (no tiene sentido
gastar una llamada que sin token fallaría con certeza).
"""
from __future__ import annotations

from services.whatsapp.config import GRAPH_VERSION, canal_habilitado, resolver_creds


def diagnosticar(conn) -> dict:
    """Estado de configuración del canal WhatsApp. No propaga."""
    from config import settings

    creds = resolver_creds()
    chequeos: list[dict] = []

    token_ok = creds is not None and bool(creds.access_token)
    chequeos.append(
        {
            "check": "token_cargado",
            "ok": token_ok,
            "bloqueante": True,
            "mensaje": (
                "Token de acceso configurado (WHATSAPP_ACCESS_TOKEN)"
                if token_ok
                else (
                    "Falta WHATSAPP_ACCESS_TOKEN en las variables de entorno del ambiente "
                    "(Meta → tu app → WhatsApp → API Setup). El token NO se carga por acá: "
                    "va en el ambiente, así staging nunca hereda el de producción."
                )
            ),
        }
    )

    pnid_ok = creds is not None and bool(creds.phone_number_id)
    chequeos.append(
        {
            "check": "phone_number_id",
            "ok": pnid_ok,
            "bloqueante": True,
            "mensaje": (
                "phone_number_id configurado (WHATSAPP_PHONE_NUMBER_ID)"
                if pnid_ok
                else (
                    "Falta WHATSAPP_PHONE_NUMBER_ID en las variables de entorno del ambiente "
                    "(Meta → tu app → WhatsApp → API Setup, debajo del número)"
                )
            ),
        }
    )

    enabled = canal_habilitado(conn)
    chequeos.append(
        {
            "check": "canal_habilitado",
            "ok": enabled,
            "bloqueante": True,
            "mensaje": (
                "Canal prendido"
                if enabled
                else "Canal apagado — prendelo con el interruptor de esta tarjeta (o la env WHATSAPP_ENABLED)"
            ),
        }
    )

    prod = bool(settings.is_production)
    chequeos.append(
        {
            "check": "ambiente",
            "ok": True,
            "bloqueante": False,
            "mensaje": (
                "Producción: envía a cualquier destino con opt-in"
                if prod
                else "No-producción: solo envía a la allowlist WHATSAPP_TEST_RECIPIENTS"
            ),
        }
    )

    # NO bloqueante: sin esto se sigue pudiendo ENVIAR (lo de arriba alcanza).
    # Falta para RECIBIR — saber si un WhatsApp llegó de verdad (no solo que
    # Meta lo aceptó) y que una respuesta del cliente no se pierda en el aire.
    webhook_ok = bool(settings.WHATSAPP_APP_SECRET and settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN)
    chequeos.append(
        {
            "check": "webhook_configurado",
            "ok": webhook_ok,
            "bloqueante": False,
            "mensaje": (
                "Webhook configurado: sabemos si un WhatsApp llegó de verdad y una "
                "respuesta del cliente no se pierde."
                if webhook_ok
                else (
                    "Sin webhook: se puede mandar igual, pero no sabemos si llegó y una "
                    "respuesta del cliente se perdería. Configuralo en Meta → tu app → "
                    "WhatsApp → Configuration: Callback URL "
                    f"{settings.SITE_URL}/api/webhooks/whatsapp, Verify token = el valor "
                    "que cargues en WHATSAPP_WEBHOOK_VERIFY_TOKEN (además falta "
                    "WHATSAPP_APP_SECRET, el 'App Secret' de Settings → Basic — "
                    "DISTINTO del access token)."
                )
            ),
        }
    )

    return {
        "chequeos": chequeos,
        "listo": _listo(chequeos),
        "ambiente": "produccion" if prod else "no_produccion",
        "graph_version": GRAPH_VERSION,
    }


def _listo(chequeos: list[dict]) -> bool:
    return all(c["ok"] or not c["bloqueante"] for c in chequeos)
