"""services.comunicacion.estrategia — por dónde sale HOY cada evento.

El `REGISTRO` (`eventos.py`) declara el **default** de cada evento; el dueño puede
cambiarlo desde `/admin/comunicacion` (WhatsApp / mail / los dos) sin tocar código.
La elección se guarda en `app_settings` bajo `comunicacion_estrategia_<evento>` —
misma puerta de escritura de siempre (`PUT /api/admin/settings/{key}`).

Dos reglas que hacen que esto no pueda romper un aviso:

1. **Solo se puede elegir lo que el evento tiene cableado** (`posibles`): un evento
   sin plantilla de mail no puede quedar en "solo mail". Lo valida el endpoint al
   guardar Y esta resolución al leer (una fila vieja/corrupta cae al default).
2. **Fail-open al default del registro**: si la BD no contesta o el valor no sirve,
   se despacha como declara el código. Un problema de configuración nunca deja al
   cliente sin aviso.

Cache de proceso con TTL corto: el despacho ocurre en el camino de un request y no
queremos una query extra por notificación. Al guardar la setting el endpoint
invalida el cache; con varios workers, los demás convergen en `_TTL` segundos.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from services.comunicacion.eventos import (
    AMBOS,
    ESTRATEGIAS,
    FALLBACK,
    SOLO_MAIL,
    SOLO_WHATSAPP,
    EventoComunicacion,
)

logger = logging.getLogger(__name__)

PREFIJO_SETTING = "comunicacion_estrategia_"
_TTL = 30.0  # segundos
_cache: dict[str, tuple[float, str]] = {}


def setting_de(evento_key: str) -> str:
    """La key de `app_settings` donde vive la elección de ese evento."""
    return f"{PREFIJO_SETTING}{evento_key}"


def evento_de_setting(key: str) -> Optional[str]:
    """La key del evento a partir de la setting, o None si no es una de estas."""
    return key[len(PREFIJO_SETTING) :] if key.startswith(PREFIJO_SETTING) else None


def posibles(ev: EventoComunicacion) -> list[str]:
    """Las estrategias que ESE evento puede tener, según los canales que tiene
    cableados. Un evento sin plantilla de WhatsApp no puede salir por WhatsApp."""
    tiene_wa = bool(ev.whatsapp)
    tiene_mail = bool(ev.mail and ev.mail.template_cliente)
    out = []
    for est in ESTRATEGIAS:
        if est in (FALLBACK, AMBOS) and not (tiene_wa and tiene_mail):
            continue
        if est == SOLO_MAIL and not tiene_mail:
            continue
        if est == SOLO_WHATSAPP and not tiene_wa:
            continue
        out.append(est)
    return out


def invalidar_cache() -> None:
    """Se llama al guardar la setting para que el cambio aplique al toque."""
    _cache.clear()


def _leer_setting(key: str, conn) -> str:
    """El valor guardado, o "" si no hay fila / no se pudo leer (fail-open)."""
    try:
        if conn is not None:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = %s", (key,)
            ).fetchone()
        else:
            from database import get_db

            with get_db() as c:
                row = c.execute(
                    "SELECT value FROM app_settings WHERE key = %s", (key,)
                ).fetchone()
        return row["value"].strip() if row and row["value"] else ""
    except Exception as e:  # noqa: BLE001 — nunca romper un aviso por leer config
        logger.warning("comunicacion: no se pudo leer %s (%s) → default del registro", key, e)
        return ""


def efectiva(ev: EventoComunicacion, conn=None) -> str:
    """La estrategia con la que se despacha este evento ahora.

    `conn` explícita → lectura fresca (la usa el back-office para mostrar la verdad);
    sin conexión → cache de proceso con TTL (el camino del despacho)."""
    opciones = posibles(ev)
    if len(opciones) <= 1:
        # No hay nada que elegir: no gastamos una lectura.
        return ev.estrategia
    key = setting_de(ev.key)
    if conn is None:
        hit = _cache.get(key)
        if hit and (time.monotonic() - hit[0]) < _TTL:
            guardada = hit[1]
        else:
            guardada = _leer_setting(key, None)
            _cache[key] = (time.monotonic(), guardada)
    else:
        guardada = _leer_setting(key, conn)
    return guardada if guardada in opciones else ev.estrategia
