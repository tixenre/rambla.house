"""services.comunicacion.contacto — el WhatsApp REAL del negocio.

Fuente única para "a dónde redirigir al cliente para que le contesten de
verdad" — nunca para iniciar contacto por ese canal. Dos consumidores:

  - La plantilla de WhatsApp de avisos (`services/whatsapp/plantillas.py`): ese
    número no tiene bandeja ni coexistencia, así que no puede invitar a
    responder ahí — el copy apunta acá.
  - El auto-reply del webhook (`services/whatsapp/webhook.py`) cuando alguien
    igual le escribe al número de avisos.

`business_phone_display` (formato lindo, "+54 9 223 585 2510") gana sobre
`whatsapp_phone` (crudo, el que arma el link wa.me del footer de mail) — mismas
dos settings que ya existen en `/admin/settings`, no se agrega ninguna nueva.
Nunca rompe: sin ninguna de las dos cargadas, devuelve "" y el copy queda sin
el número antes que reventar.
"""
from __future__ import annotations

from typing import Optional


def _setting(conn, key: str) -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = %s", (key,)).fetchone()
    return (row["value"].strip() if row and row["value"] else "")


def telefono_negocio(conn=None) -> Optional[str]:
    """El WhatsApp real del negocio, o "" si no está configurado. `conn=None`
    abre y cierra su propia conexión (uso fuera de un request con conn abierta)."""
    if conn is not None:
        return _setting(conn, "business_phone_display") or _setting(conn, "whatsapp_phone")

    from database import get_db

    with get_db() as c:
        return _setting(c, "business_phone_display") or _setting(c, "whatsapp_phone")
