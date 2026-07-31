"""Config del recordatorio de DEVOLUCIÓN — **fuente única**.

Tres ventanas independientes, cada una encendible/apagable desde el back-office
(pedido del dueño): D-1 (la víspera), D-0 (el día de la devolución) y "vencido"
(D+1, si el equipo figura sin devolver). Todas comparten una hora de barrido.

Precedencia (igual que `recordatorios_config`): env var (kill-switch/override de
ops) > app_settings (toggle del admin) > default. Todas las ventanas arrancan
APAGADAS (el canal WhatsApp además está inerte hasta configurar credencial + opt-in).

| Ventana | Env override                 | app_settings key                        | Default |
| ------- | ---------------------------- | --------------------------------------- | ------- |
| D-1     | REMINDERS_DEVOLUCION_D1      | recordatorios_devolucion_d1_enabled     | off     |
| D-0     | REMINDERS_DEVOLUCION_D0      | recordatorios_devolucion_d0_enabled     | off     |
| vencido | REMINDERS_DEVOLUCION_VENCIDO | recordatorios_devolucion_vencido_enabled| off     |
| hora    | REMINDERS_DEVOLUCION_HOUR    | recordatorios_devolucion_hora           | 9       |
"""
from __future__ import annotations

import logging
import os

from database import get_db

logger = logging.getLogger(__name__)

DEFAULT_HORA = 9
_TRUTHY = ("1", "true", "yes", "on")

# Clave de ventana → (env var, app_settings key). El orden es el de envío.
VENTANAS = {
    "d1": ("REMINDERS_DEVOLUCION_D1", "recordatorios_devolucion_d1_enabled"),
    "d0": ("REMINDERS_DEVOLUCION_D0", "recordatorios_devolucion_d0_enabled"),
    "vencido": ("REMINDERS_DEVOLUCION_VENCIDO", "recordatorios_devolucion_vencido_enabled"),
}


def _env(name: str) -> str | None:
    v = os.getenv(name)
    v = v.strip() if v else ""
    return v or None


def _setting(conn, key: str) -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = %s", (key,)).fetchone()
    return (row["value"].strip() if row and row["value"] else "")


def _bool(conn, env_name: str, setting_key: str) -> bool:
    ev = _env(env_name)
    if ev is not None:
        return ev.lower() in _TRUTHY
    return _setting(conn, setting_key).lower() in _TRUTHY


def _clamp_int(raw: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(raw), hi))
    except (ValueError, TypeError):
        return default


def resolve(conn=None) -> dict:
    """Devuelve `{ventanas: set[str], alguna: bool, hora: int(0-23), <clave>: bool}`.
    `ventanas` son las ventanas prendidas (subconjunto de VENTANAS). `conn=None`
    abre y cierra su propia conexión (uso del scheduler)."""
    propia = conn is None
    if propia:
        conn = get_db()
    try:
        estado = {clave: _bool(conn, env, key) for clave, (env, key) in VENTANAS.items()}
        hora = _clamp_int(
            _env("REMINDERS_DEVOLUCION_HOUR") or _setting(conn, "recordatorios_devolucion_hora"),
            DEFAULT_HORA, 0, 23,
        )
        ventanas = {clave for clave, on in estado.items() if on}
        return {"ventanas": ventanas, "alguna": bool(ventanas), "hora": hora, **estado}
    finally:
        if propia:
            conn.close()
