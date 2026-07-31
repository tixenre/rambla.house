"""services.whatsapp.config — credenciales + gating del canal WhatsApp.

A diferencia de ARCA (credencial cifrada en DB, multi-emisor), WhatsApp es UNA sola
cuenta de plataforma (la marca Rambla es única — decisión "una sola cuenta Rambla"):
el token y el `phone_number_id` viven en variables de entorno (mismo patrón que
`RESEND_API_KEY`/`DIDIT_API_KEY` en `config.py`), NO cifrados en la BD. Razón de
peso: WhatsApp no tiene un host de "homologación" como ARCA — es el mismo Graph y
envíos reales. Si el token viviera en `app_settings`, staging (que corre con una BD
CLONADA de prod) heredaría el token de prod y podría mensajear a clientes reales. En
ENV, cada ambiente de Railway tiene el suyo (o ninguno) → staging es seguro por
construcción.

Gating (defensa en profundidad):
  1. credencial presente (token + phone_number_id) — si falta, el canal es inerte.
  2. `whatsapp_enabled` prendido (env override > app_settings > default OFF).
  3. destinatario permitido: en prod cualquiera con opt-in; fuera de prod SOLO la
     allowlist `WHATSAPP_TEST_RECIPIENTS` (red anti-spam, espeja el número de test
     de Meta).
El opt-in del cliente y el teléfono E.164 los chequea `envio.py`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# Versión del Graph API. Un solo host (no hay homologación como en ARCA); el
# "test vs real" lo da qué número (phone_number_id) y la allowlist, no el host.
GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

_TRUTHY = ("1", "true", "yes", "on")


@dataclass(frozen=True)
class WhatsAppCreds:
    """Credenciales resueltas del canal (una sola cuenta de plataforma)."""

    phone_number_id: str
    access_token: str
    base_url: str = GRAPH_BASE


def resolver_creds() -> Optional[WhatsAppCreds]:
    """Credenciales desde ENV, o None si el canal no está configurado en este
    ambiente (falta el token o el phone_number_id → canal inerte)."""
    from config import settings

    token = (settings.WHATSAPP_ACCESS_TOKEN or "").strip()
    pnid = (settings.WHATSAPP_PHONE_NUMBER_ID or "").strip()
    if not token or not pnid:
        return None
    return WhatsAppCreds(phone_number_id=pnid, access_token=token)


def _setting(conn, key: str) -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = %s", (key,)).fetchone()
    return (row["value"].strip() if row and row["value"] else "")


def canal_habilitado(conn) -> bool:
    """El canal manda de verdad solo si está EXPLÍCITAMENTE prendido (default OFF):
    env `WHATSAPP_ENABLED` (kill-switch/override de ops) > app_settings
    `whatsapp_enabled` (toggle del back-office). Mismo criterio env>settings>default
    que `jobs/recordatorios_config`."""
    env = os.getenv("WHATSAPP_ENABLED")
    if env is not None and env.strip() != "":
        return env.strip().lower() in _TRUTHY
    return _setting(conn, "whatsapp_enabled").lower() in _TRUTHY


def destinatario_permitido(to_e164: str) -> bool:
    """En producción se le puede enviar a cualquier destino (el opt-in lo filtra
    `envio.py`). FUERA de producción (staging/local) SOLO a la allowlist
    `WHATSAPP_TEST_RECIPIENTS` (E.164 coma-separados) — red anti-spam para que un
    token mal configurado en staging nunca mensajee a clientes reales."""
    from config import settings

    if settings.is_production:
        return True
    permitidos = {
        x.strip() for x in (settings.WHATSAPP_TEST_RECIPIENTS or "").split(",") if x.strip()
    }
    return to_e164 in permitidos
