"""services.whatsapp.envio — boca única de envío de WhatsApp para eventos de pedido.

Mismo contrato que `services.email.send_email`: **NUNCA propaga** excepciones,
**loguea SIEMPRE** en `whatsapp_log`, e **idempotente por pedido** (índice único
`idx_whatsapp_log_idempotente`). El adapter referencia las piezas del repo — no las
reimplementa:
  - teléfono → `identity.contacts.telefono_contacto` (verificado E.164 > crudo).
  - creación/gating → `services.whatsapp.config`.
  - envío HTTP + errores tipados → `whatsapp_cloud` (librería portable).

El teléfono pasa por el embudo único `services/telefono.normalizar_e164` (libphonenumber,
región AR): valida y normaliza a E.164 el mejor teléfono del cliente (verificado por
Didit > base). Si no es un número válido, se saltea (no se manda basura a Meta).
"""
from __future__ import annotations

import logging
from typing import Optional

from database import get_db
from services.telefono import normalizar_e164
from services.whatsapp.config import (
    canal_habilitado,
    destinatario_permitido,
    resolver_creds,
)
from services.whatsapp.plantillas import REGISTRO

logger = logging.getLogger(__name__)


def enviar_evento_pedido(plantilla_key: str, pedido: dict, ctx: dict, *, force: bool = False) -> dict:
    """Manda el WhatsApp del evento `plantilla_key` para `pedido`, usando `ctx`
    (el mismo contexto que arman los mails, `comunicacion.pedido_email_context`) para los
    parámetros del template. Devuelve `{ok, skipped?, reason?, wamid?, log_id?, error?}`.

    NUNCA propaga: cada rama que no envía devuelve `{ok: True, skipped: True, reason}`
    (canal inerte / cliente sin opt-in / sin E.164 / duplicado), y un fallo del
    provider se loguea con `status='failed'` sin tumbar al caller."""
    plantilla = REGISTRO.get(plantilla_key)
    if plantilla is None:
        logger.warning("whatsapp: plantilla desconocida %r", plantilla_key)
        return {"ok": False, "skipped": True, "reason": "plantilla_desconocida"}

    alquiler_id = pedido.get("id")
    cliente_id = pedido.get("cliente_id")

    # Corte barato ANTES de abrir conexión: si no hay credencial en este ambiente,
    # el canal es inerte (no configurado).
    creds = resolver_creds()
    if creds is None:
        return {"ok": True, "skipped": True, "reason": "sin_credenciales"}

    conn = get_db()
    try:
        if not canal_habilitado(conn):
            return {"ok": True, "skipped": True, "reason": "canal_apagado"}
        if not _opt_in(conn, cliente_id):
            return {"ok": True, "skipped": True, "reason": "sin_opt_in"}
        to = _resolver_telefono(conn, pedido)
        if not to:
            return {"ok": True, "skipped": True, "reason": "sin_telefono_e164"}
        if not destinatario_permitido(to):
            return {"ok": True, "skipped": True, "reason": "destinatario_no_permitido"}

        # Idempotencia por pedido Y DESTINATARIO: primera línea (el índice único es
        # la red final). Incluye `to_phone` porque un mismo aviso puede tener varios
        # destinatarios (el equipo) — sin eso, el segundo se descartaría como duplicado.
        if not force and plantilla.idempotente_por_pedido and alquiler_id:
            existing = conn.execute(
                "SELECT id FROM whatsapp_log WHERE alquiler_id = %s AND template_key = %s "
                "AND to_phone = %s AND status = 'sent' LIMIT 1",
                (alquiler_id, plantilla.key, to),
            ).fetchone()
            if existing:
                return {"ok": True, "skipped": True, "reason": "duplicado", "log_id": existing["id"]}

        from whatsapp_cloud import WhatsAppClient, WhatsAppError

        # `whatsapp_contacto` (el WhatsApp real, para templates que invitan a
        # escribir) no vive en `pedido_email_context` — esa función es pura
        # a propósito (unit-testeada sin Postgres). Se agrega ACÁ, sobre una
        # copia, con la conexión que este envío ya tiene abierta — y solo si
        # el template puntual lo necesita (no gastar una query de más).
        if "whatsapp_contacto" in plantilla.campos_ctx and "whatsapp_contacto" not in ctx:
            from services.comunicacion.contacto import telefono_negocio

            ctx = {**ctx, "whatsapp_contacto": telefono_negocio(conn)}

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
                body_params=plantilla.params(ctx),
            )
        except WhatsAppError as e:
            log_id = _insert_log(
                conn, to=to, template_key=plantilla.key, alquiler_id=alquiler_id,
                status="failed", wamid=None, error=str(e),
            )
            conn.commit()
            logger.warning("whatsapp envío falló tpl=%s pedido=%s: %s", plantilla.key, alquiler_id, e)
            return {"ok": False, "error": str(e), "log_id": log_id}

        try:
            log_id = _insert_log(
                conn, to=to, template_key=plantilla.key, alquiler_id=alquiler_id,
                status="sent", wamid=res.message_id, error=None,
            )
            conn.commit()
        except Exception:
            # El índice único puede rechazar un duplicado en carrera — no es fallo
            # real (el mensaje ya salió una vez). Se registra como skip.
            conn.rollback()
            logger.info(
                "whatsapp: envío duplicado bloqueado por índice único tpl=%s pedido=%s",
                plantilla.key, alquiler_id,
            )
            return {"ok": True, "skipped": True, "reason": "duplicado"}

        logger.info("whatsapp enviado tpl=%s pedido=%s wamid=%s", plantilla.key, alquiler_id, res.message_id)
        return {"ok": True, "wamid": res.message_id, "log_id": log_id}
    except Exception as e:  # red final: jamás propagar
        logger.exception("whatsapp: error inesperado en enviar_evento_pedido: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"error interno: {e}"}
    finally:
        conn.close()


def _resolver_telefono(conn, pedido: dict) -> Optional[str]:
    """Mejor teléfono del cliente en E.164, o None. Prefiere el resolvedor canónico
    `identity.contacts.telefono_contacto` (verificado E.164 > crudo); cae al snapshot
    `cliente_telefono` del pedido. Lo pasa por el embudo `services/telefono` que valida
    y normaliza a E.164 (un número inválido → None)."""
    cid = pedido.get("cliente_id")
    tel = None
    if cid:
        try:
            from identity.contacts import telefono_contacto

            tel = telefono_contacto(conn, cid)
        except Exception:
            logger.debug("whatsapp: telefono_contacto falló para cliente %s", cid, exc_info=True)
            tel = None
    if not tel:
        tel = pedido.get("cliente_telefono")
    # El embudo único (services/telefono) valida y normaliza a E.164; si no es un
    # número válido, devuelve None y el envío se saltea (no se le manda basura a Meta).
    return normalizar_e164(tel)


def _opt_in(conn, cliente_id) -> bool:
    """True solo si el cliente aceptó explícitamente recibir WhatsApp. Sin cliente_id
    conocido → False (Meta exige opt-in demostrable; ante la duda, no se manda)."""
    if not cliente_id:
        return False
    row = conn.execute(
        "SELECT whatsapp_opt_in FROM clientes WHERE id = %s", (cliente_id,)
    ).fetchone()
    return bool(row and row["whatsapp_opt_in"])


def _insert_log(conn, *, to, template_key, alquiler_id, status, wamid, error):
    return conn.insert_returning(
        "INSERT INTO whatsapp_log "
        "(to_phone, template_key, alquiler_id, status, wamid, error) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (to, template_key, alquiler_id, status, wamid, error),
    )


def enviar_evento_admin(plantilla_key: str, pedido: dict, ctx: dict) -> dict:
    """Manda el aviso INTERNO del evento a cada número del equipo (Pablo, Tincho…).

    Diferencias con el aviso al cliente:
      - **sin opt-in**: el equipo configuró sus propios números, ese es el consentimiento;
      - el teléfono sale de la config (`destinatarios_admin`), no del pedido;
      - se manda uno por número (la API de grupos exige Official Business Account).

    Mismo contrato que el resto del canal: NUNCA propaga, loguea cada envío en
    `whatsapp_log` e idempotente por (pedido, plantilla, número). Devuelve
    `{ok, enviados, resultados:[...]}`."""
    plantilla = REGISTRO.get(plantilla_key)
    if plantilla is None:
        logger.warning("whatsapp admin: plantilla desconocida %r", plantilla_key)
        return {"ok": False, "skipped": True, "reason": "plantilla_desconocida", "enviados": 0}

    creds = resolver_creds()
    if creds is None:
        return {"ok": True, "skipped": True, "reason": "sin_credenciales", "enviados": 0}

    alquiler_id = pedido.get("id")
    conn = get_db()
    try:
        if not canal_habilitado(conn):
            return {"ok": True, "skipped": True, "reason": "canal_apagado", "enviados": 0}

        from services.whatsapp.config import destinatarios_admin

        numeros = destinatarios_admin(conn)
        if not numeros:
            return {"ok": True, "skipped": True, "reason": "sin_destinatarios", "enviados": 0}

        from whatsapp_cloud import WhatsAppClient, WhatsAppError

        client = WhatsAppClient(
            phone_number_id=creds.phone_number_id,
            access_token=creds.access_token,
            base_url=creds.base_url,
        )
        resultados: list[dict] = []
        enviados = 0
        for to in numeros:
            if not destinatario_permitido(to):
                resultados.append({"to": to, "ok": True, "skipped": True, "reason": "destinatario_no_permitido"})
                continue
            # Idempotencia por (pedido, plantilla, número): que uno ya lo haya
            # recibido no puede dejar sin mensaje al otro.
            if plantilla.idempotente_por_pedido and alquiler_id:
                ya = conn.execute(
                    "SELECT id FROM whatsapp_log WHERE alquiler_id = %s AND template_key = %s "
                    "AND to_phone = %s AND status = 'sent' LIMIT 1",
                    (alquiler_id, plantilla.key, to),
                ).fetchone()
                if ya:
                    resultados.append({"to": to, "ok": True, "skipped": True, "reason": "duplicado"})
                    continue
            try:
                res = client.enviar_template(
                    to=to,
                    template_name=plantilla.meta_name,
                    lang_code=plantilla.lang,
                    body_params=plantilla.params(ctx),
                )
            except WhatsAppError as e:
                _insert_log(
                    conn, to=to, template_key=plantilla.key, alquiler_id=alquiler_id,
                    status="failed", wamid=None, error=str(e),
                )
                conn.commit()
                logger.warning("whatsapp admin falló tpl=%s pedido=%s to=%s: %s",
                               plantilla.key, alquiler_id, to, e)
                resultados.append({"to": to, "ok": False, "error": str(e)})
                continue
            try:
                _insert_log(
                    conn, to=to, template_key=plantilla.key, alquiler_id=alquiler_id,
                    status="sent", wamid=res.message_id, error=None,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                resultados.append({"to": to, "ok": True, "skipped": True, "reason": "duplicado"})
                continue
            enviados += 1
            resultados.append({"to": to, "ok": True, "wamid": res.message_id})

        return {"ok": all(r.get("ok") for r in resultados), "enviados": enviados, "resultados": resultados}
    except Exception as e:  # red final: jamás propagar
        logger.exception("whatsapp admin: error inesperado: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"error interno: {e}", "enviados": 0}
    finally:
        conn.close()
