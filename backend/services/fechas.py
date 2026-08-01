"""Fechas y horas de alquiler — puerta única de TODA la lógica de fechas.

Cualquier cosa que sea una DECISIÓN sobre fechas/horas vive acá, para que todos
los caminos usen los mismos valores y reglas (no más copias divergentes):

  - `validar_fecha_iso(v)` → valida el FORMATO ISO en el borde (field_validator → 422)
  - `validar_rango_fechas(fd, fh, *, permitir_pasado, max_dias)` → criterio (orden /
    no-pasado / tope de días) → mensaje | None
  - `antelacion_minima_horas(conn)` → horas de lead-time configuradas (app_settings)
  - `antelacion_insuficiente(conn, inicio)` → horas si viola el lead-time | None
  - `inicio_desde_fecha_hora(fecha, hora)` → combina fecha + hora en un datetime
  - `disclaimers_retiro(conn, fecha_desde, fecha_hasta)` → avisos del picker público
    ({check, mensaje}, mismo shape que el portero del checkout) — el FRONT ya no
    decide "¿corresponde avisar? ¿qué dice?", solo pide y muestra (#1237)

Antes el criterio de rango estaba duplicado byte-por-byte en 4 lugares
(`create_pedido`, `_apply_pedido_datos`, `_validar_fechas_propuestas`, el cap de
120 días) y el formato (`validar_fecha_iso`) vivía aparte en `routes/alquileres`.
Ahora todo eso es este módulo.

Se construye sobre dos PRIMITIVAS de bajo nivel que viven en el DAL
(`database/core.py`, decisión _2026-06-27 — DAL wrapper fino_) y ya son fuente
única: `now_ar()` (reloj wall-clock de Argentina, no `date.today()` que en CI
corre en UTC y desfasa entre 00:00–03:00) y `to_datetime()` (coerción de los
date/datetime que devuelve psycopg). Este módulo es el dueño de las REGLAS;
el DAL, de esas dos primitivas.
"""

import datetime
import json

from database import now_ar, to_datetime


# ── Validación de formato (borde → 422) ─────────────────────────────────────────


def validar_fecha_iso(v):
    """Valida que una fecha sea ISO parseable (o None/''). Se usa como
    field_validator en los modelos de pedido para rechazar fechas malformadas
    en el borde (422) en vez de explotar como 500 más adentro al castear.
    Acepta 'yyyy-mm-dd' o 'yyyy-mm-ddThh:mm'. Devuelve el str original (sin
    normalizar) o None."""
    if v is None or v == "":
        return None
    try:
        datetime.datetime.fromisoformat(str(v))
    except (ValueError, TypeError):
        raise ValueError(
            f"fecha inválida: '{v}'. Formato esperado ISO (yyyy-mm-dd o yyyy-mm-ddThh:mm)"
        )
    return str(v)


# ── Validación de rango (criterio) ──────────────────────────────────────────────


def validar_rango_fechas(
    fecha_desde,
    fecha_hasta,
    *,
    permitir_pasado: bool = False,
    max_dias: int | None = None,
) -> str | None:
    """Valida el criterio de un rango de fechas. Devuelve None si es válido, o un
    mensaje en lenguaje claro listo para mostrar/levantar.

    - permitir_pasado: el admin (carga retroactiva) y los pedidos históricos
      pueden tener inicio en el pasado; el cliente no.
    - max_dias: tope de duración en días (regla solo-cliente, ej. 120). None = sin tope.

    La granularidad (día vs. día+hora) la define el VALOR que entra: si el caller
    pasa 'YYYY-MM-DD' compara por día; si pasa 'YYYY-MM-DDThh:mm' compara con hora.
    El helper no la impone — preserva el comportamiento de cada llamador.
    """
    d0 = to_datetime(fecha_desde)
    d1 = to_datetime(fecha_hasta)
    if d0 is None or d1 is None:
        # "ambas o ninguna" lo decide el caller; sin ambas no hay rango que validar.
        return None
    if d0 >= d1:
        return "La fecha de devolución debe ser posterior a la de retiro."
    if not permitir_pasado:
        hoy = now_ar().replace(hour=0, minute=0, second=0, microsecond=0)
        if d0 < hoy:
            return "La fecha de inicio no puede ser en el pasado."
    if max_dias is not None and (d1 - d0).days > max_dias:
        return f"El rango del alquiler no puede superar los {max_dias} días."
    return None


# ── Settings de horas + ventana de tiempo (primitivas compartidas) ──────────────


def setting_horas(conn, key: str, default: int = 0) -> int:
    """Lee un setting de HORAS (int) de `app_settings` con fallback. Fail-open:
    valor corrupto/ausente/negativo → `default`; nunca negativo. Fuente única para
    todos los settings de horas (lead-time, ventana de modificación, …)."""
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = %s", (key,)
    ).fetchone()
    try:
        return max(0, int((row["value"] if row and row["value"] else default) or default))
    except (ValueError, TypeError):
        return default


def dentro_de_ventana_horas(inicio: datetime.datetime | None, horas: int) -> bool:
    """True si `inicio` cae DENTRO de las próximas `horas` desde ahora (wall-clock
    AR). Predicado puro reusable: el lead-time pregunta "¿el retiro es demasiado
    pronto?" (esto) y el corte de modificación pregunta lo contrario (su negación).
    `inicio` naive AR, comparable contra `now_ar()`."""
    if inicio is None:
        return False
    return inicio < now_ar() + datetime.timedelta(hours=horas)


# ── Antelación mínima (lead-time configurable, #1126) ───────────────────────────


def antelacion_minima_horas(conn) -> int:
    """Horas mínimas de antelación para que un cliente reserve online
    (`app_settings.antelacion_minima_horas`, default 0 = apagado)."""
    return setting_horas(conn, "antelacion_minima_horas", 0)


def antelacion_insuficiente(conn, inicio: datetime.datetime | None) -> int | None:
    """Si el retiro `inicio` cae dentro de la ventana de antelación mínima, devuelve
    las horas configuradas (para armar el mensaje/disclaimer); si no, None. 0 =
    apagado. Lo usa el portero (UX) y el backstop de creación (defensa en profundidad)."""
    horas = antelacion_minima_horas(conn)
    if horas <= 0:
        return None
    return horas if dentro_de_ventana_horas(inicio, horas) else None


def inicio_desde_fecha_hora(fecha, hora) -> datetime.datetime | None:
    """Combina una fecha ('YYYY-MM-DD' o date) + una hora opcional ('HH:MM' o None)
    en un datetime naive (wall-clock AR). Hora ausente/ inválida → 00:00 (el momento
    más temprano del día = el más conservador para el lead-time)."""
    d = to_datetime(fecha)
    if d is None:
        return None
    t = datetime.time(0, 0)
    if hora:
        try:
            t = datetime.time.fromisoformat(str(hora))
        except (ValueError, TypeError):
            t = datetime.time(0, 0)
    return datetime.datetime.combine(d.date(), t)


# ── Formato de horario en minutos-desde-medianoche ─────────────────────────────


def fmt_hhmm(minutos: int) -> str:
    """510 → \"08:30\", 780 → \"13:00\", 1440 → \"24:00\". Formato único de display
    para horarios guardados en minutos desde medianoche (clases de talleres,
    Escuela v2 F1). El backend resuelve el string — el front no formatea horarios
    a mano (mismo criterio que la plata)."""
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


# ── Mes actual (wall-clock AR) ──────────────────────────────────────────────────


def mes_actual_ar() -> str:
    """Mes calendario actual en formato 'YYYY-MM', en hora de Argentina. Usar esto
    en vez de `date.today()` (que en CI/servidor corre en UTC y desfasa entre
    00:00–03:00 → puede devolver el mes equivocado a fin de mes)."""
    return now_ar().strftime("%Y-%m")


def iter_meses(mes_desde: str, mes_hasta: str):
    """Itera (year, month) inclusive entre dos 'YYYY-MM' — promovido desde
    `routes/estudio.py` (usado también por la economía de talleres,
    `_regenerar_pedidos_taller`: ambos recorren el rango de meses de una
    edición/slot para decidir qué pedido mensual conservar/recrear)."""
    y0, m0 = int(mes_desde[:4]), int(mes_desde[5:7])
    y1, m1 = int(mes_hasta[:4]), int(mes_hasta[5:7])
    cur = (y0, m0)
    while cur <= (y1, m1):
        yield cur
        y, m = cur
        cur = (y + 1, 1) if m == 12 else (y, m + 1)


# ── Nombres de días/meses en español (display) ──────────────────────────────

DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def fmt_fecha_es(d) -> str:
    """datetime.date → 'sábado 11 de julio' — promovido desde `routes/talleres.py`
    (lo necesita también `services.talleres.commands.economia`, que evitaba así
    importar de `routes.*`)."""
    if isinstance(d, str):
        d = datetime.date.fromisoformat(d)
    return f"{DIAS_ES[d.weekday()]} {d.day} de {MESES_ES[d.month - 1]}"


# ── Horarios habilitados de retiro/devolución (setting `horarios_retiro`) ────────

_DIAS_HORARIO = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]


def horarios_habilitados(conn) -> dict | None:
    """Parsea `app_settings.horarios_retiro` (JSON `{"lun": {"desde","hasta"}
    | null, ...}`, 3 letras por día). `None` = sin config → no restringe.
    Fuente única del parseo — antes vivía inline solo en
    `validar_horarios_habilitados`; `disclaimers_retiro` también lo necesita."""
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = %s", ("horarios_retiro",)
    ).fetchone()
    if not row or not row["value"]:
        return None
    try:
        horarios = json.loads(row["value"])
    except (ValueError, TypeError):
        return None
    if not isinstance(horarios, dict) or not horarios:
        return None
    return horarios


def validar_horarios_habilitados(conn, fecha_desde, fecha_hasta) -> str | None:
    """Valida que retiro/devolución caigan en días/horas habilitados (setting
    `horarios_retiro`). Sin config → no restringe. Pensado para el flujo del
    cliente, que manda hora real (el admin carga date-only y no se restringe).
    Devuelve un mensaje de error (retiro primero) o None; el route levanta el HTTP."""
    horarios = horarios_habilitados(conn)
    if not horarios:
        return None

    def _check(dt_raw, etiqueta: str) -> str | None:
        if not dt_raw:
            return None
        dt = to_datetime(dt_raw)
        franja = horarios.get(_DIAS_HORARIO[dt.weekday()])
        if not franja:
            return f"El {etiqueta} cae en un día no habilitado"
        hhmm = dt.strftime("%H:%M")
        if hhmm < franja["desde"] or hhmm > franja["hasta"]:
            return (
                f"El horario de {etiqueta} ({hhmm}) está fuera del rango "
                f"habilitado ({franja['desde']}–{franja['hasta']})"
            )
        return None

    return _check(fecha_desde, "retiro") or _check(fecha_hasta, "devolución")


DEFAULT_ULTIMA_HORA_LABORAL = 18


def ultima_hora_laboral(conn, fecha) -> int:
    """Hora (0-23) a la que cierra el galpón ese día, según `horarios_retiro`.

    Día cerrado o sin config → `DEFAULT_ULTIMA_HORA_LABORAL`. La usa el
    recordatorio de retiro para mandar "a última hora" la víspera: si el cliente
    retira temprano, avisarle a la mañana del mismo día llega tarde."""
    horarios = horarios_habilitados(conn)
    franja = (horarios or {}).get(_DIAS_HORARIO[fecha.weekday()])
    if not franja:
        return DEFAULT_ULTIMA_HORA_LABORAL
    try:
        return max(0, min(23, int(str(franja["hasta"]).split(":")[0])))
    except (KeyError, ValueError, AttributeError, TypeError):
        return DEFAULT_ULTIMA_HORA_LABORAL


def _franja_minutos(franja: dict | None) -> int:
    """Duración en minutos de una franja `{desde,hasta}` HH:MM. 0 si cerrada/ausente."""
    if not franja:
        return 0
    try:
        dh, mh = franja["hasta"].split(":")
        dd, md = franja["desde"].split(":")
        return max(0, (int(dh) * 60 + int(mh)) - (int(dd) * 60 + int(md)))
    except (KeyError, ValueError, AttributeError):
        return 0


def dia_fin_de_semana_reducido(horarios: dict | None, fecha: datetime.date) -> bool:
    """¿`fecha` cae sábado o domingo Y ese día tiene menos minutos habilitados
    (o está cerrado) que un lunes de referencia? Compara contra lunes en vez
    de declarar "el finde es más corto" a mano — si el admin iguala los
    horarios, esto se apaga solo. Espejo semántico de
    `frontend/src/lib/rental-dates.ts::finDeSemanaReducido`, pero evaluado
    para una fecha puntual (la elegida en el picker) en vez de en abstracto."""
    if not horarios:
        return False
    dia = _DIAS_HORARIO[fecha.weekday()]
    if dia not in ("sab", "dom"):
        return False
    referencia = horarios.get("lun")
    if not referencia:
        return False
    return _franja_minutos(horarios.get(dia)) < _franja_minutos(referencia)


# ── Disclaimers del picker público (#1237) ───────────────────────────────────
# El front (DateRangePickerModal) antes decidía "¿corresponde avisar? ¿qué
# dice?" en TS, reimplementando estas mismas reglas. Ahora solo pide acá y
# muestra `mensaje` — mismo shape `{check, mensaje}` que el portero del
# checkout (`services/checkout/validar.py::_falta`, sin el campo `accion`
# porque acá no hay una ruta a la que mandar al usuario, solo información).
#
# El TEXTO también es editable desde el back-office (`app_settings`, no solo
# la REGLA) — antes era un string hardcodeado acá, así que ajustar la
# redacción (una coma, una palabra) exigía un cambio de código. Default =
# lo que se mostraba antes; `{horas}` en el texto de antelación se reemplaza
# por el valor configurado (placeholder literal, no `.format()` — un texto
# libre con `{`/`}` sueltos no debe poder romper el render).

DEFAULT_MSG_ANTELACION = (
    "Reservás online con al menos {horas} h de anticipación, "
    "por eso no ves horas más cercanas a ahora."
)
DEFAULT_MSG_HORARIOS_FINDE = "Sábados y domingos tenemos horarios reducidos."


def _texto_setting(conn, key: str, default: str) -> str:
    """Lee un setting de TEXTO libre de `app_settings` con fallback. Fail-open:
    ausente/vacío → `default`. Fuente única para los textos editables de los
    disclaimers del picker (antes duplicado ad-hoc)."""
    row = conn.execute("SELECT value FROM app_settings WHERE key = %s", (key,)).fetchone()
    value = row["value"] if row else None
    return value.strip() if value and value.strip() else default


def disclaimers_retiro(conn, fecha_desde: str | None, fecha_hasta: str | None) -> list[dict]:
    """Avisos del picker público. No todos son contextuales de la misma
    forma — cada uno tiene su propio criterio de "¿corresponde?":

    - `antelacion`: regla PERMANENTE del catálogo (aplica a cualquier
      reserva online, no solo a la fecha puntual que estés mirando ahora
      mismo) — se muestra siempre que esté configurada, elijas la fecha que
      elijas. No depende de `fecha_desde`.
    - `horarios_finde`: sí es contextual a la selección — solo aplica si la
      fecha elegida realmente cae en un día reducido.

    Pueden coexistir los dos a la vez (lista, no un solo mensaje) — no es
    "el más relevante gana", el front los muestra todos."""
    avisos: list[dict] = []

    horas = antelacion_minima_horas(conn)
    if horas > 0:
        texto = _texto_setting(conn, "disclaimer_antelacion_texto", DEFAULT_MSG_ANTELACION)
        avisos.append({
            "check": "antelacion",
            "mensaje": texto.replace("{horas}", str(horas)),
        })

    horarios = horarios_habilitados(conn)
    if horarios:
        fechas = [d for d in (to_datetime(fecha_desde), to_datetime(fecha_hasta)) if d]
        if any(dia_fin_de_semana_reducido(horarios, d.date()) for d in fechas):
            avisos.append({
                "check": "horarios_finde",
                "mensaje": _texto_setting(
                    conn, "disclaimer_horarios_finde_texto", DEFAULT_MSG_HORARIOS_FINDE
                ),
            })

    return avisos
