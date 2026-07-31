"""services.whatsapp.sincronizacion — dar de alta en Meta los templates del registro.

Evita el copiar-pegar de cada plantilla en el WhatsApp Manager: compara lo que
declara `plantillas.REGISTRO` (fuente única) contra lo que existe hoy en la cuenta y
**crea solo lo que falta**.

Se lista ANTES de crear a propósito: así el "ya existe" no depende de adivinar el
mensaje de error de Meta, y de paso se obtiene el estado de aprobación real de cada
uno para mostrarlo en el back-office.

Dar de alta por API **no saltea la revisión**: el template nace `PENDING` y Meta lo
aprueba o lo rechaza. Lo que se gana es no tipear seis veces y ver el estado en vivo.
"""
from __future__ import annotations

import logging
from typing import Optional

from services.whatsapp.config import resolver_creds
from services.whatsapp.plantillas import REGISTRO

logger = logging.getLogger(__name__)

# Valores de ejemplo que Meta pide para revisar el template. Uno por campo del
# contexto, en el MISMO orden que `campos_ctx` (= el orden de los `{{n}}`).
_EJEMPLOS = {
    "cliente_nombre": "Santiago",
    "numero_pedido": "1042",
    "fecha_desde": "15 jun · 10:00",
    "fecha_hasta": "18 jun · 18:00",
    "whatsapp_contacto": "+54 9 223 585-2510",
}


def _waba_id() -> str:
    from config import settings

    return (settings.WHATSAPP_BUSINESS_ACCOUNT_ID or "").strip()


def _ejemplos_de(campos: tuple[str, ...]) -> list[str]:
    return [_EJEMPLOS.get(c, "ejemplo") for c in campos]


def _cliente():
    """Cliente de templates, o None si falta credencial o WABA id."""
    creds = resolver_creds()
    waba = _waba_id()
    if creds is None or not waba:
        return None
    from whatsapp_cloud import WhatsAppTemplatesClient

    return WhatsAppTemplatesClient(
        waba_id=waba, access_token=creds.access_token, base_url=creds.base_url
    )


def estado_plantillas() -> dict:
    """Estado de cada plantilla del registro según Meta, sin crear nada.

    Devuelve `{disponible, motivo?, plantillas:[{key, meta_name, lang, estado, ...}]}`.
    `estado` es el de Meta (APPROVED/PENDING/REJECTED/…) o `NO_CREADA` si no existe.
    Nunca propaga: si Meta falla, se informa el motivo y `disponible=False`."""
    cli = _cliente()
    if cli is None:
        return {
            "disponible": False,
            "motivo": (
                "Falta el token o el ID de la cuenta de WhatsApp "
                "(WHATSAPP_ACCESS_TOKEN / WHATSAPP_BUSINESS_ACCOUNT_ID)."
            ),
            "plantillas": [],
        }

    from whatsapp_cloud import WhatsAppError

    try:
        remotos = cli.listar()
    except WhatsAppError as e:
        logger.warning("whatsapp: no se pudieron listar los templates: %s", e)
        return {"disponible": False, "motivo": str(e), "plantillas": []}

    # Meta identifica un template por (nombre, idioma).
    por_clave = {(t.name, t.language): t for t in remotos}
    filas = []
    for p in REGISTRO.values():
        remoto = por_clave.get((p.meta_name, p.lang))
        filas.append(
            {
                "key": p.key,
                "meta_name": p.meta_name,
                "lang": p.lang,
                "estado": remoto.status if remoto else "NO_CREADA",
                "existe": remoto is not None,
            }
        )
    return {"disponible": True, "plantillas": filas}


def sincronizar(*, solo_faltantes: bool = True) -> dict:
    """Crea en Meta las plantillas del registro que todavía no existen.

    Devuelve `{ok, creadas, ya_existian, fallidas, resultados:[...]}`. Nunca propaga:
    una plantilla que falla no frena a las demás (se informa su error)."""
    cli = _cliente()
    if cli is None:
        return {
            "ok": False,
            "motivo": (
                "Falta el token o el ID de la cuenta de WhatsApp "
                "(WHATSAPP_ACCESS_TOKEN / WHATSAPP_BUSINESS_ACCOUNT_ID)."
            ),
            "creadas": 0,
            "ya_existian": 0,
            "fallidas": 0,
            "resultados": [],
        }

    from whatsapp_cloud import WhatsAppError

    try:
        existentes = {(t.name, t.language) for t in cli.listar()}
    except WhatsAppError as e:
        logger.warning("whatsapp: no se pudo listar antes de sincronizar: %s", e)
        return {
            "ok": False,
            "motivo": str(e),
            "creadas": 0,
            "ya_existian": 0,
            "fallidas": 0,
            "resultados": [],
        }

    resultados: list[dict] = []
    creadas = ya = fallidas = 0
    for p in REGISTRO.values():
        if solo_faltantes and (p.meta_name, p.lang) in existentes:
            ya += 1
            resultados.append(
                {"key": p.key, "meta_name": p.meta_name, "resultado": "ya_existia", "estado": None}
            )
            continue
        try:
            creado = cli.crear_body(
                name=p.meta_name,
                language=p.lang,
                body_text=p.copy_ejemplo,
                ejemplos=_ejemplos_de(p.campos_ctx),
                category="UTILITY",
            )
        except WhatsAppError as e:
            fallidas += 1
            logger.warning("whatsapp: falló crear el template %s: %s", p.meta_name, e)
            resultados.append(
                {"key": p.key, "meta_name": p.meta_name, "resultado": "error", "error": str(e)}
            )
            continue
        creadas += 1
        resultados.append(
            {
                "key": p.key,
                "meta_name": p.meta_name,
                "resultado": "creada",
                "estado": creado.status,
            }
        )

    return {
        "ok": fallidas == 0,
        "creadas": creadas,
        "ya_existian": ya,
        "fallidas": fallidas,
        "resultados": resultados,
    }


def motivo_no_disponible() -> Optional[str]:
    """Por qué no se puede administrar templates hoy, o None si sí se puede."""
    return None if _cliente() is not None else "Falta credencial o WHATSAPP_BUSINESS_ACCOUNT_ID"
