"""services.whatsapp.webhook — eventos ENTRANTES de Meta: estado de entrega real
y mensajes que el cliente le manda al número de avisos.

Autenticado por HMAC-SHA256 (`X-Hub-Signature-256`), firmado con el **App
Secret** de Meta — `WHATSAPP_APP_SECRET`, DISTINTO del access token (ese
autoriza a ENVIAR; este verifica que un evento entrante lo mandó Meta de
verdad). Espeja `services/didit/webhook.py` en criterio (fail-closed sin
secret, comparación en tiempo constante) adaptado al esquema de Meta: un único
header `sha256=<hex>` sobre el body crudo, sin timestamp separado (Meta no lo
manda, así que no hay chequeo de freshness posible del lado del payload).

Dos cosas que resuelve:

  1. **Estado de entrega real** (`statuses[]`): hasta ahora `whatsapp_log.
     status='sent'` solo decía que Meta ACEPTÓ el envío, no que llegó. Acá se
     guarda el estado real (delivered/read/failed) en columnas NUEVAS —
     `status` no se toca (sostiene el índice único de idempotencia).
  2. **Mensajes entrantes** (`messages[]`): sin coexistencia ni bandeja, una
     respuesta del cliente se perdía en el aire — ni un error, directamente
     nadie la veía. Ahora se le contesta automático con un texto libre (válido
     dentro de la ventana de servicio de 24h que el propio mensaje abre)
     redirigiendo al WhatsApp real del negocio (`comunicacion.contacto`).
"""
from __future__ import annotations

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)

_ESTADOS_ENTREGA = {"delivered", "read", "failed"}


class WhatsAppWebhookError(Exception):
    """Firma inválida, challenge de verificación rechazado, o secret no configurado."""


def _hmac_hex(body: bytes) -> str:
    from config import settings

    return hmac.new(
        settings.WHATSAPP_APP_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


def verify_signature(body: bytes, signature_header: str) -> None:
    """Verifica `X-Hub-Signature-256: sha256=<hex>` sobre el body crudo.

    Fail-closed: sin `WHATSAPP_APP_SECRET` configurado, siempre rechaza (mismo
    criterio que `DIDIT_WEBHOOK_SECRET`)."""
    from config import settings

    if not settings.WHATSAPP_APP_SECRET:
        raise WhatsAppWebhookError("WHATSAPP_APP_SECRET no configurado (webhook inactivo)")
    prefijo = "sha256="
    firma = (signature_header or "").strip()
    if not firma.startswith(prefijo):
        raise WhatsAppWebhookError("Falta X-Hub-Signature-256")
    esperada = _hmac_hex(body)
    if not hmac.compare_digest(firma[len(prefijo):], esperada):
        raise WhatsAppWebhookError("Firma inválida")


def verify_challenge(mode: str, token: str, challenge: str) -> str:
    """El handshake GET de Meta al configurar el webhook (`hub.mode=subscribe`,
    `hub.verify_token`, `hub.challenge`): si el token coincide con el que vos
    elegiste (`WHATSAPP_WEBHOOK_VERIFY_TOKEN`, el mismo valor que pegás en el
    WhatsApp Manager), devuelve `hub.challenge` tal cual — eso es lo que Meta
    espera para confirmar la URL."""
    from config import settings

    if not settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        raise WhatsAppWebhookError("WHATSAPP_WEBHOOK_VERIFY_TOKEN no configurado")
    if mode != "subscribe" or token != settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        raise WhatsAppWebhookError("Verify token no coincide")
    return challenge


# ── procesamiento del payload (firma ya verificada) ──────────────────────────

def _iter_values(payload: dict):
    """Cada `value` de `entry[].changes[]`. Meta a veces separa `messages` y
    `statuses` en `changes` distintos, a veces los junta en el mismo — iterar
    todos cubre ambos casos sin asumir la forma exacta."""
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value")
            if isinstance(value, dict):
                yield value


def _aplicar_estados(value: dict, conn) -> int:
    """Guarda el estado de entrega real de cada `statuses[]` en las columnas
    dedicadas (nunca en `status`, que sostiene la idempotencia). `wamid` es la
    clave para cruzar el evento con la fila que ya insertó `envio.py`."""
    aplicados = 0
    for st in value.get("statuses") or []:
        wamid = st.get("id")
        estado = st.get("status")
        if not wamid or estado not in _ESTADOS_ENTREGA:
            continue
        error = None
        if estado == "failed":
            errores = st.get("errors") or []
            if errores:
                detalle = errores[0].get("title") or errores[0].get("message") or ""
                error = str(detalle)[:500]
        conn.execute(
            """
            UPDATE whatsapp_log
               SET delivery_status = %s, delivery_error = %s, delivered_at = CURRENT_TIMESTAMP
             WHERE wamid = %s
            """,
            (estado, error, wamid),
        )
        aplicados += 1
    return aplicados


def _responder_entrantes(value: dict, conn) -> int:
    """A cada mensaje entrante le contesta un texto libre (ventana de servicio de
    24h que el propio mensaje abre) redirigiendo al WhatsApp real del negocio —
    nunca se pierde en el aire, ni silenciosamente ni con un error. Best-effort:
    un fallo de envío queda logueado, nunca rompe el webhook."""
    from services.comunicacion.contacto import telefono_negocio
    from services.whatsapp.config import resolver_creds
    from whatsapp_cloud import WhatsAppClient, WhatsAppError

    mensajes = value.get("messages") or []
    if not mensajes:
        return 0
    creds = resolver_creds()
    if creds is None:
        return 0

    contacto = telefono_negocio(conn) or "nuestro WhatsApp habitual"
    texto = (
        "Este número es solo para avisos automáticos de Rambla — no llegan "
        f"mensajes acá. Para consultas, escribinos a tu WhatsApp de siempre: {contacto}."
    )
    client = WhatsAppClient(
        phone_number_id=creds.phone_number_id,
        access_token=creds.access_token,
        base_url=creds.base_url,
    )
    respondidos = 0
    for m in mensajes:
        de = m.get("from")
        if not de:
            continue
        logger.warning(
            "whatsapp webhook: mensaje entrante de %s (wamid=%s) — auto-respondido",
            de, m.get("id"),
        )
        try:
            client.enviar_texto(to=de, body=texto)
            respondidos += 1
        except WhatsAppError as exc:
            logger.warning("whatsapp webhook: no se pudo auto-responder a %s — %s", de, exc)
    return respondidos


def procesar_evento(payload: dict, conn) -> dict:
    """Procesa un payload de webhook YA con firma verificada. Nunca propaga: un
    payload con forma inesperada queda logueado y el caller igual devuelve 200
    a Meta (evita reintentos infinitos de algo que nunca va a poder procesarse).
    Devuelve `{entregas_actualizadas, mensajes_respondidos}` (para logging/tests)."""
    entregas = 0
    respondidos = 0
    try:
        for value in _iter_values(payload):
            entregas += _aplicar_estados(value, conn)
            respondidos += _responder_entrantes(value, conn)
    except Exception:
        logger.exception("whatsapp webhook: error procesando el payload")
    return {"entregas_actualizadas": entregas, "mensajes_respondidos": respondidos}
