"""Resolución de la config del recordatorio de retiro — **fuente única**.

Decide si el recordatorio está prendido y **cuándo** sale. La leen el scheduler
in-process (`jobs/scheduler.py`) y el job (`jobs/recordatorios.py`) — nadie lee
estas settings por su cuenta en dos lados.

## Cuándo sale (criterio del dueño)

No es "N días antes" fijo: **depende de la hora del retiro**, porque avisar a las
9 de la mañana llega tarde para quien retira a las 9.

- Retiro **a partir del corte** (default 12:00) → aviso **el mismo día**, a la
  hora configurada (default 9).
- Retiro **antes del corte** (temprano) → aviso **el día anterior**, a la **hora
  de cierre** de ese día, que sale de `horarios_retiro`
  (`services/fechas.ultima_hora_laboral`, fuente única de los horarios): cambiar
  el horario del galpón mueve el aviso solo.

La pasada de la mañana además **rescata** los retiros de hoy que no recibieron el
aviso de la víspera y todavía no ocurrieron (ver `jobs/recordatorios.py`).

Precedencia (alineada con `email_from`, decisión 2026-05-27 — la config se
activa por entorno): la **variable de entorno**, si está presente, MANDA
(kill-switch / override de ops); si no, el valor que el admin guardó desde
`/admin/comunicacion`; si tampoco, el **default**.

| Concepto           | Env override              | app_settings key              | Default |
| ------------------ | ------------------------- | ----------------------------- | ------- |
| encendido          | REMINDERS_ENABLED         | recordatorios_enabled         | off     |
| hora (AR)          | REMINDERS_HOUR            | recordatorios_hora            | 9       |
| corte "de mañana"  | REMINDERS_CORTE_MANANA    | recordatorios_corte_manana    | 12      |
"""
from __future__ import annotations

import logging
import os

from database import get_db, now_ar

logger = logging.getLogger(__name__)

DEFAULT_HORA = 9
DEFAULT_CORTE_MANANA = 12  # retiro antes de esta hora = "temprano" → aviso la víspera

_TRUTHY = ("1", "true", "yes")


def _env(name: str) -> str | None:
    """Valor de la env var si está presente y no vacía; si no, None."""
    v = os.getenv(name)
    v = v.strip() if v else ""
    return v or None


def _setting(conn, key: str) -> str:
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = %s", (key,)
    ).fetchone()
    return (row["value"].strip() if row and row["value"] else "")


def _clamp_int(raw: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(raw), hi))
    except (ValueError, TypeError):
        return default


def resolve(conn=None, *, dia=None) -> dict:
    """Devuelve `{enabled, hora, corte_manana, hora_vispera}` aplicando
    env > settings > default. `hora_vispera` es la hora de cierre de `dia` (hoy
    por defecto): a esa hora sale el aviso de los retiros tempranos de mañana.

    `conn=None` abre y cierra su propia conexión (uso del scheduler); si se le
    pasa una, no la cierra."""
    from services.fechas import ultima_hora_laboral

    propia = conn is None
    if propia:
        conn = get_db()
    try:
        ev = _env("REMINDERS_ENABLED")
        enabled = (
            ev.lower() in _TRUTHY if ev is not None
            else _setting(conn, "recordatorios_enabled").lower() in _TRUTHY
        )
        hora = _clamp_int(
            _env("REMINDERS_HOUR") or _setting(conn, "recordatorios_hora"),
            DEFAULT_HORA, 0, 23,
        )
        corte_manana = _clamp_int(
            _env("REMINDERS_CORTE_MANANA") or _setting(conn, "recordatorios_corte_manana"),
            DEFAULT_CORTE_MANANA, 1, 23,
        )
        return {
            "enabled": enabled,
            "hora": hora,
            "corte_manana": corte_manana,
            "hora_vispera": ultima_hora_laboral(conn, dia or now_ar().date()),
        }
    finally:
        if propia:
            conn.close()
