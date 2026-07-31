"""services.comunicacion.opciones — qué se puede CONFIGURAR de cada evento.

Fuente única de las opciones que el back-office muestra **dentro** de cada evento
(criterio del dueño: la configuración vive en el mensaje que corresponde, no en
una pantalla aparte — antes el recordatorio de retiro tenía su propia tarjeta,
suelta de la comunicación que gobierna).

Cada opción es una key de `app_settings` **ya permitida** en
`routes/settings.py::ALLOWED_SETTINGS_KEYS`: se guarda por el
`PUT /api/admin/settings/{key}` de siempre — no hay superficie de escritura nueva.

Las keys / env / defaults **no se redeclaran** acá: se importan de los módulos de
config de cada job, que siguen siendo la fuente única de la resolución
`env > app_settings > default` en runtime. Este módulo solo pone el **vocabulario
humano** (qué significa cada perilla) y el estado actual para mostrarlo.

Si una env var está seteada, manda sobre la BD (override de ops) → la opción se
devuelve con `bloqueada_por_env` y la UI la muestra en solo-lectura: si dejáramos
editarla, el admin guardaría un valor que el ambiente ignora.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from jobs import recordatorios_config as retiro_cfg
from jobs import recordatorios_devolucion_config as devolucion_cfg

_TRUTHY = ("1", "true", "yes", "on")


@dataclass(frozen=True)
class OpcionEvento:
    """Una perilla configurable de un evento.

    `tipo` decide cómo se edita: `switch` ("1"/"0"), `numero` (con `minimo`/`maximo`)
    o `texto`. `env` es la variable de entorno que la pisa, si existe.
    """

    setting: str
    label: str
    tipo: str = "numero"  # switch | numero | texto
    ayuda: str = ""
    default: str = ""
    env: Optional[str] = None
    minimo: Optional[int] = None
    maximo: Optional[int] = None
    placeholder: str = ""


_HORA_DEVOLUCION = OpcionEvento(
    setting="recordatorios_devolucion_hora",
    label="Hora del envío",
    ayuda=(
        "Hora de Argentina en que sale el aviso. Es la misma para los tres avisos "
        "de devolución (se manda todo en el mismo barrido diario)."
    ),
    default=str(devolucion_cfg.DEFAULT_HORA),
    env="REMINDERS_DEVOLUCION_HOUR",
    minimo=0,
    maximo=23,
)


OPCIONES: dict[str, tuple[OpcionEvento, ...]] = {
    "pedido_creado": (
        OpcionEvento(
            setting="whatsapp_admin_numeros",
            label="Avisarle por WhatsApp al equipo",
            tipo="texto",
            ayuda=(
                "Los números que reciben el aviso interno cuando entra una solicitud, "
                "separados por coma. Vacío = no se avisa por WhatsApp (el mail al admin "
                "sale igual)."
            ),
            env="WHATSAPP_ADMIN_NUMEROS",
            placeholder="+5492235550000, +5492236660000",
        ),
    ),
    "recordatorio_retiro": (
        OpcionEvento(
            setting="recordatorios_enabled",
            label="Mandar este recordatorio",
            tipo="switch",
            ayuda="Si está apagado, el barrido diario no manda nada de este evento.",
            default="0",
            env="REMINDERS_ENABLED",
        ),
        OpcionEvento(
            setting="recordatorios_dias_antes",
            label="Días antes",
            ayuda="Con cuánta anticipación al retiro se manda (1 = el día anterior).",
            default=str(retiro_cfg.DEFAULT_DIAS_ANTES),
            env="REMINDERS_DIAS_ANTES",
            minimo=1,
            maximo=retiro_cfg.MAX_DIAS_ANTES,
        ),
        OpcionEvento(
            setting="recordatorios_hora",
            label="Hora del envío",
            ayuda="Hora de Argentina en que corre el barrido diario.",
            default=str(retiro_cfg.DEFAULT_HORA),
            env="REMINDERS_HOUR",
            minimo=0,
            maximo=23,
        ),
    ),
    "recordatorio_devolucion_d1": (
        OpcionEvento(
            setting=devolucion_cfg.VENTANAS["d1"][1],
            label="Mandar este aviso",
            tipo="switch",
            ayuda="El aviso de la víspera. Si está apagado, no se manda.",
            default="0",
            env=devolucion_cfg.VENTANAS["d1"][0],
        ),
        OpcionEvento(
            setting="recordatorios_devolucion_dias_antes",
            label="Días antes",
            ayuda="Con cuánta anticipación a la devolución se manda (1 = el día anterior).",
            default=str(devolucion_cfg.DEFAULT_DIAS_ANTES),
            env="REMINDERS_DEVOLUCION_DIAS",
            minimo=1,
            maximo=devolucion_cfg.MAX_DIAS_ANTES,
        ),
        _HORA_DEVOLUCION,
    ),
    "recordatorio_devolucion_d0": (
        OpcionEvento(
            setting=devolucion_cfg.VENTANAS["d0"][1],
            label="Mandar este aviso",
            tipo="switch",
            ayuda="El aviso del día de la devolución. Si está apagado, no se manda.",
            default="0",
            env=devolucion_cfg.VENTANAS["d0"][0],
        ),
        _HORA_DEVOLUCION,
    ),
    "recordatorio_devolucion_vencido": (
        OpcionEvento(
            setting=devolucion_cfg.VENTANAS["vencido"][1],
            label="Mandar este aviso",
            tipo="switch",
            ayuda="El aviso del día siguiente si el equipo figura sin devolver.",
            default="0",
            env=devolucion_cfg.VENTANAS["vencido"][0],
        ),
        _HORA_DEVOLUCION,
    ),
}


def _serializar(op: OpcionEvento, guardadas: dict[str, str]) -> dict:
    env_val = (os.getenv(op.env) or "").strip() if op.env else ""
    valor = env_val or guardadas.get(op.setting, "") or op.default
    if op.tipo == "switch":
        valor = "1" if valor.lower() in _TRUTHY else "0"
    return {
        "setting": op.setting,
        "label": op.label,
        "tipo": op.tipo,
        "ayuda": op.ayuda,
        "valor": valor,
        "default": op.default,
        "minimo": op.minimo,
        "maximo": op.maximo,
        "placeholder": op.placeholder,
        # Nombre de la env var que la está pisando (o None si manda la BD).
        "bloqueada_por_env": op.env if env_val else None,
    }


def estado(conn) -> dict[str, list[dict]]:
    """`{evento_key: [opción con su valor efectivo]}` — una sola query para todas."""
    keys = sorted({op.setting for ops in OPCIONES.values() for op in ops})
    guardadas: dict[str, str] = {}
    if keys:
        ph = ",".join(["%s"] * len(keys))
        for r in conn.execute(
            f"SELECT key, value FROM app_settings WHERE key IN ({ph})", keys
        ).fetchall():
            guardadas[r["key"]] = (r["value"] or "").strip()
    return {
        ev_key: [_serializar(op, guardadas) for op in ops] for ev_key, ops in OPCIONES.items()
    }
