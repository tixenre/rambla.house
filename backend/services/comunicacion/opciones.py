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
        OpcionEvento(
            setting="email_admin_to",
            label="Avisarle por mail al equipo",
            tipo="texto",
            ayuda=(
                "Las direcciones que reciben el mail interno cuando entra una solicitud, "
                "separadas por coma. Vacío = usa el default del ambiente, si hay."
            ),
            env="EMAIL_ADMIN_TO",
            placeholder="equipo@rambla.house, otra@rambla.house",
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
            setting="recordatorios_hora",
            label="Hora del aviso, el mismo día",
            ayuda=(
                "Hora de Argentina a la que sale el aviso el día del retiro. Solo "
                "para los retiros del mediodía en adelante."
            ),
            default=str(retiro_cfg.DEFAULT_HORA),
            env="REMINDERS_HOUR",
            minimo=0,
            maximo=23,
        ),
        OpcionEvento(
            setting="recordatorios_corte_manana",
            label="Los retiros antes de esta hora se avisan el día anterior",
            ayuda=(
                "Al que retira temprano, avisarle a la mañana del mismo día le llega "
                "tarde: su aviso sale la víspera, a la hora de cierre del galpón "
                "(sale de Horarios de retiro — hoy sería a las {cierre})."
            ),
            default=str(retiro_cfg.DEFAULT_CORTE_MANANA),
            env="REMINDERS_CORTE_MANANA",
            minimo=1,
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


# Perillas de un CANAL (no de un evento puntual): viven en la tarjeta del canal.
OPCIONES_CANAL: dict[str, tuple[OpcionEvento, ...]] = {
    "whatsapp": (
        OpcionEvento(
            setting="whatsapp_enabled",
            label="Canal prendido",
            tipo="switch",
            ayuda=(
                "Con el canal apagado no sale ningún WhatsApp (los avisos caen al mail "
                "cuando su estrategia lo permite). Se prende recién cuando la credencial "
                "del ambiente está cargada."
            ),
            default="0",
            env="WHATSAPP_ENABLED",
        ),
    ),
    # El canal mail no tiene perillas propias: se activa con la credencial del
    # proveedor (RESEND_API_KEY) en el ambiente, no desde la UI.
    "mail": (),
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


def _hora_de_cierre_hoy(conn) -> str:
    """Para explicar en criollo cuándo saldría el aviso de la víspera. Nunca rompe
    la pantalla: si no se puede resolver, el texto queda sin el dato concreto."""
    try:
        from database import now_ar
        from services.fechas import ultima_hora_laboral

        return f"{ultima_hora_laboral(conn, now_ar().date()):02d}:00"
    except Exception:  # noqa: BLE001
        return "la hora de cierre"


def _estado_de(conn, mapa: dict[str, tuple[OpcionEvento, ...]]) -> dict[str, list[dict]]:
    """`{key: [opción con su valor efectivo]}` — una sola query para todas."""
    keys = sorted({op.setting for ops in mapa.values() for op in ops})
    guardadas: dict[str, str] = {}
    if keys:
        ph = ",".join(["%s"] * len(keys))
        for r in conn.execute(
            f"SELECT key, value FROM app_settings WHERE key IN ({ph})", keys
        ).fetchall():
            guardadas[r["key"]] = (r["value"] or "").strip()
    cierre = _hora_de_cierre_hoy(conn)
    out: dict[str, list[dict]] = {}
    for clave, ops in mapa.items():
        serializadas = []
        for op in ops:
            d = _serializar(op, guardadas)
            # Placeholder literal (no `.format()`): el texto es nuestro, pero no
            # queremos que una llave suelta pueda romper el render.
            d["ayuda"] = d["ayuda"].replace("{cierre}", cierre)
            serializadas.append(d)
        out[clave] = serializadas
    return out


def estado(conn) -> dict[str, list[dict]]:
    """Las perillas de cada EVENTO, con su valor efectivo."""
    return _estado_de(conn, OPCIONES)


def estado_canales(conn) -> dict[str, list[dict]]:
    """Las perillas de cada CANAL (hoy: el on/off de WhatsApp)."""
    return _estado_de(conn, OPCIONES_CANAL)
