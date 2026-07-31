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
                else "Falta WHATSAPP_ACCESS_TOKEN en las variables de entorno del ambiente"
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
                else "Falta WHATSAPP_PHONE_NUMBER_ID en las variables de entorno del ambiente"
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
                else "Canal apagado — prendé 'whatsapp_enabled' en /admin/settings (o WHATSAPP_ENABLED)"
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

    return {
        "chequeos": chequeos,
        "listo": _listo(chequeos),
        "ambiente": "produccion" if prod else "no_produccion",
        "graph_version": GRAPH_VERSION,
    }


def _listo(chequeos: list[dict]) -> bool:
    return all(c["ok"] or not c["bloqueante"] for c in chequeos)
