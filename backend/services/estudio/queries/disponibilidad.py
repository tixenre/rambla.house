"""Motor de lectura de disponibilidad de El Estudio — orden: slot → taller → centinela.

Move-verbatim desde `routes/estudio.py` (extracción a `services/estudio/`, CQRS-lite).
Cero cambio de SQL/lógica — ver `services/estudio/CLAUDE.md` para las reglas que no se
rompen (buffer propio del espacio vs. buffer global de equipos, garantía dura del
re-chequeo bajo lock en `commands/reserva.py`).

REGLA SAGRADA: el motor de reservas (`reservas.validar_stock_hipotetico` /
`reservas.calcular_disponibilidad`) NO se modifica ni se reusa para el espacio. La
reserva del estudio es un pedido normal (`tipo='estudio'`) con UN ítem: el equipo
centinela (`estudio.equipo_id`, cantidad=1, recurso único).

El solapamiento del centinela se chequea con una query DEDICADA (`_centinela_libre`,
no vía el motor), para que el espacio use SOLO su buffer propio (`estudio.buffer_horas`)
y nunca el buffer global de equipos. Al ser stock=1, un overlap directo alcanza.
"""
from collections import namedtuple
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException

from database import now_ar, to_datetime
from reservas import ESTADOS_RESERVADO, validar_stock_hipotetico
from services.fechas import fmt_hhmm

from services.estudio.queries.estudio import _get_estudio_row


def _franja_estudio(estudio, fecha: str, start: str, horas: int) -> tuple[datetime, datetime]:
    """Valida y arma la franja [fecha_desde, fecha_hasta] de una reserva.

    - `horas` debe ser >= min_horas del estudio.
    - La franja [start, start+horas] debe caer dentro de [open_hour, close_hour].

    Devuelve (fecha_desde, fecha_hasta) como datetimes. Lanza HTTPException 400
    si algo no valida.
    """
    min_horas = estudio["min_horas"]
    if horas < min_horas:
        raise HTTPException(400, f"El mínimo de reserva es de {min_horas} horas")
    try:
        hh, mm = (int(x) for x in start.split(":"))
        dia = datetime.strptime(fecha, "%Y-%m-%d")
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(400, "Fecha u hora inválida (esperado fecha=YYYY-MM-DD, start=HH:MM)")

    inicio_min = hh * 60 + mm
    fin_min = inicio_min + horas * 60
    open_h, close_h = estudio["open_hour"], estudio["close_hour"]
    if inicio_min < open_h * 60 or fin_min > close_h * 60:
        raise HTTPException(
            400,
            f"La franja debe estar entre las {open_h:02d}:00 y las {close_h:02d}:00",
        )

    fecha_desde = dia.replace(hour=hh, minute=mm, second=0, microsecond=0)
    fecha_hasta = fecha_desde + timedelta(hours=horas)
    return fecha_desde, fecha_hasta


def _viola_anticipacion_horas(fecha_desde, horas: int) -> bool:
    """Núcleo puro: ¿`fecha_desde` no deja `horas` de anticipación desde ahora?
    `horas <= 0` → sin tope (apagado)."""
    horas = horas or 0
    if horas <= 0:
        return False
    return fecha_desde < now_ar() + timedelta(hours=horas)


def _viola_anticipacion(estudio, fecha_desde) -> bool:
    """¿La franja arranca antes de la anticipación mínima exigida por el estudio?
    Solo aplica al estudio (no a equipos). anticipacion_min_horas <= 0 → sin tope."""
    return _viola_anticipacion_horas(fecha_desde, estudio["anticipacion_min_horas"])


def _viola_anticipacion_pintura(estudio, fecha_desde) -> bool:
    """¿La franja arranca antes de la anticipación PROPIA del add-on "recién
    pintado" (pintar/secar el ciclorama necesita más lead time que una reserva
    común)? Se exige ADEMÁS de `_viola_anticipacion`, no en su lugar — el caller
    solo la chequea cuando el cliente tildó el add-on.
    `anticipacion_pintura_horas` <= 0 → sin tope extra."""
    return _viola_anticipacion_horas(fecha_desde, estudio["anticipacion_pintura_horas"])


def _centinela_libre(conn, equipo_id: int, fecha_desde, fecha_hasta,
                     buffer_horas: int, exclude_pedido_id: int | None = None,
                     exclude_slot_id: int | None = None) -> bool:
    """True si el centinela del estudio está libre en [fecha_desde, fecha_hasta],
    aplicando SOLO el buffer propio del estudio (expande el rango por
    `buffer_horas` a cada lado). Query dedicada — NO usa el motor sagrado, así
    el buffer global de equipos no interviene.

    El centinela es un recurso único (stock=1): cualquier reserva activa que se
    pise con la franja expandida (half-open: fecha_desde < hi AND fecha_hasta > lo)
    significa ocupado. `exclude_pedido_id` excluye el propio pedido en el POST.

    `exclude_slot_id`: los pedidos `estudio_fijo` llevan su propio ítem
    centinela (Fase 2, ítems veraces) — sin esto, revalidar la disponibilidad
    de un slot fijo (`actualizar_slot`, ANTES de regenerar sus pedidos)
    chocaría contra los pedidos YA EXISTENTES del propio slot para ese mismo
    día/hora, bloqueándose a sí mismo.
    """
    lo = fecha_desde - timedelta(hours=max(0, buffer_horas or 0))
    hi = fecha_hasta + timedelta(hours=max(0, buffer_horas or 0))
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS cnt
        FROM alquiler_items pi
        JOIN alquileres p ON p.id = pi.pedido_id
        WHERE pi.equipo_id = %s
          AND p.estado IN {ESTADOS_RESERVADO}
          AND (%s IS NULL OR p.id != %s)
          AND (%s IS NULL OR p.estudio_slot_id IS DISTINCT FROM %s)
          AND p.fecha_desde < %s
          AND p.fecha_hasta > %s
        """,
        (equipo_id, exclude_pedido_id, exclude_pedido_id,
         exclude_slot_id, exclude_slot_id, hi, lo),
    ).fetchone()
    return (row["cnt"] or 0) == 0


def _slot_bloqueante(conn, fecha_desde, fecha_hasta,
                     exclude_slot_id: Optional[int] = None) -> Optional[str]:
    """Si la franja cae en un slot fijo activo (mismo día de semana, dentro del
    rango de meses y con solape horario), devuelve el `cliente` del slot. Regla
    del slot — NO usa el motor de reservas."""
    dia = fecha_desde.weekday()
    mes = f"{fecha_desde.year:04d}-{fecha_desde.month:02d}"
    # Minutos relativos al día de inicio (no `.hour`): una franja que cierra a
    # medianoche tiene fecha_hasta = 00:00 del día siguiente, y `.hour` daría 0,
    # rompiendo el solape. La resta sí da 1440.
    dia_base = fecha_desde.replace(hour=0, minute=0, second=0, microsecond=0)
    ini = int((fecha_desde - dia_base).total_seconds() // 60)
    fin = int((fecha_hasta - dia_base).total_seconds() // 60)
    rows = conn.execute(
        """
        SELECT id, cliente, hora_desde, hora_hasta
        FROM estudio_slots_fijos
        WHERE activo = TRUE AND dia_semana = %s
          AND mes_desde <= %s AND mes_hasta >= %s
          AND (%s IS NULL OR id != %s)
        """,
        (dia, mes, mes, exclude_slot_id, exclude_slot_id),
    ).fetchall()
    for r in rows:
        if ini < r["hora_hasta"] * 60 and fin > r["hora_desde"] * 60:
            return r["cliente"]
    return None


def _primer_dia_semana(year: int, month: int, dia_semana: int) -> datetime:
    """Primera fecha del mes cuyo weekday() == dia_semana (0=Lun..6=Dom).
    Move-verbatim desde `routes/estudio.py` — helper puro de `_sesiones_de_slot`."""
    base = datetime(year, month, 1)
    offset = (dia_semana - base.weekday()) % 7
    return base + timedelta(days=offset)


def _sesiones_de_slot(slot: dict) -> list:
    """Genera todas las fechas con `dia_semana` en el rango de meses del slot,
    como lista de dicts {fecha, hora_inicio_min, hora_fin_min}. Usada para validar
    disponibilidad antes de crear o editar un slot, y para listar la ocupación de
    slots fijos en un rango (agenda/ocupación admin, ocupación pública).

    OJO unidades: `estudio_slots_fijos.hora_desde/hasta` siguen en HORAS enteras
    (su tabla no cambió); las sesiones se emiten en MINUTOS (contrato de
    `verificar_sesiones_disponibles` desde Escuela v2 F1) → conversión ×60 acá.

    Move-verbatim desde `routes/estudio.py` — vivía ahí desde antes de que
    existiera este paquete; se mueve para que `services/estudio/queries/` pueda
    consumirla sin importar de `routes.*` (regla dura del paquete)."""
    y0, m0 = int(slot["mes_desde"][:4]), int(slot["mes_desde"][5:7])
    y1, m1 = int(slot["mes_hasta"][:4]), int(slot["mes_hasta"][5:7])
    import calendar as _cal
    sesiones = []
    cur = (y0, m0)
    while cur <= (y1, m1):
        y, m = cur
        _, last_day = _cal.monthrange(y, m)
        d = _primer_dia_semana(y, m, slot["dia_semana"]).date()
        while d.month == m:
            sesiones.append({
                "fecha": d,
                "hora_inicio_min": slot["hora_desde"] * 60,
                "hora_fin_min": slot["hora_hasta"] * 60,
            })
            d = d + timedelta(weeks=1)
        cur = (y + 1, 1) if m == 12 else (y, m + 1)
    return sesiones


def _taller_bloqueante(conn, fecha_desde, fecha_hasta,
                       exclude_taller_id: Optional[int] = None) -> Optional[str]:
    """Si la franja solapa una clase de un taller PUBLICADO (concepto Y edición
    activos), devuelve el nombre del taller. Compara contra la fecha literal — no
    deriva weekday ni rango. `hora_*_min` ya está en minutos desde medianoche
    (Escuela v2 F1) — misma unidad que `ini`/`fin`, sin conversión.
    Consulta clases_taller (modelo vigente; taller_sesiones era el modelo anterior).

    `AND e.activo`: fix del bloqueo fantasma (Escuela v2 F1, decisión del dueño) —
    una edición desactivada/borrador NO bloquea el estudio; antes solo se miraba
    `t.activo` (concepto) y una edición dada de baja seguía reservando la franja."""
    dia = fecha_desde.date()
    dia_base = fecha_desde.replace(hour=0, minute=0, second=0, microsecond=0)
    ini = int((fecha_desde - dia_base).total_seconds() // 60)
    fin = int((fecha_hasta - dia_base).total_seconds() // 60)
    rows = conn.execute(
        """
        SELECT t.nombre, c.hora_inicio_min, c.hora_fin_min
        FROM clases_taller c
        JOIN ediciones_taller e ON e.id = c.edicion_id
        JOIN talleres t ON t.id = e.taller_id
        WHERE t.activo = TRUE
          AND e.activo = TRUE
          AND c.fecha = %s
          AND (%s IS NULL OR t.id != %s)
        """,
        (dia, exclude_taller_id, exclude_taller_id),
    ).fetchall()
    for r in rows:
        if ini < r["hora_fin_min"] and fin > r["hora_inicio_min"]:
            return r["nombre"]
    return None


def _estudio_disponible(conn, estudio, fecha_desde, fecha_hasta,
                        exclude_pedido_id: Optional[int] = None,
                        exclude_taller_id: Optional[int] = None,
                        exclude_slot_id: Optional[int] = None) -> tuple:
    """Engine de lectura unificada. Orden: slot → taller → centinela.
    Devuelve (True, None) si libre; (False, motivo) si ocupado."""
    s = _slot_bloqueante(conn, fecha_desde, fecha_hasta, exclude_slot_id=exclude_slot_id)
    if s:
        return False, f"slot fijo «{s}»"
    t = _taller_bloqueante(conn, fecha_desde, fecha_hasta, exclude_taller_id=exclude_taller_id)
    if t:
        return False, f"taller «{t}»"
    if not _centinela_libre(conn, estudio["equipo_id"], fecha_desde, fecha_hasta,
                            estudio["buffer_horas"], exclude_pedido_id=exclude_pedido_id,
                            exclude_slot_id=exclude_slot_id):
        return False, "ya reservado en esa franja"
    return True, None


def revalidar_disponibilidad_estudio(conn, pedido) -> list[str]:
    """Re-valida un pedido del Estudio YA EXISTENTE (turno o slot fijo) al
    transicionar de estado — la usa `transiciones.cambiar_estado` EN VEZ DEL
    `_check_stock` genérico (bug encontrado auditando la economía del
    Estudio: ese gate leería el ítem centinela como un equipo más y lo
    validaría con el buffer GLOBAL, no con el buffer propio del espacio).

    ESPACIO (centinela): por `_estudio_disponible` (buffer propio), excluyendo
    el propio pedido y —si es un `estudio_fijo`— su propio slot (para no
    chocar contra sí mismo). EQUIPOS reales (pack/sueltos, si los hay): por el
    motor sagrado `validar_stock_hipotetico`, excluyendo el centinela (que no
    es un equipo real).

    `pedido` es la fila de `alquileres` (dict o `PGRow`) ya leída `FOR UPDATE`
    por el caller — esta función no relockea nada."""
    estudio = _get_estudio_row(conn)
    errores: list[str] = []

    fd, fh = to_datetime(pedido["fecha_desde"]), to_datetime(pedido["fecha_hasta"])
    libre, motivo = _estudio_disponible(
        conn, estudio, fd, fh,
        exclude_pedido_id=pedido["id"],
        exclude_slot_id=pedido["estudio_slot_id"],
    )
    if not libre:
        errores.append(f"El espacio no está disponible: {motivo}")

    items = conn.execute(
        "SELECT equipo_id, cantidad FROM alquiler_items "
        "WHERE pedido_id=%s AND equipo_id IS NOT NULL AND equipo_id != %s",
        (pedido["id"], estudio["equipo_id"]),
    ).fetchall()
    if items:
        _Item = namedtuple("_Item", ["equipo_id", "cantidad"])
        sin_stock = validar_stock_hipotetico(
            conn, pedido["id"], pedido["fecha_desde"], pedido["fecha_hasta"],
            [_Item(it["equipo_id"], it["cantidad"]) for it in items],
        )
        errores.extend(f"Sin stock suficiente: {s}" for s in sin_stock)

    return errores


def verificar_sesiones_disponibles(conn, estudio, sesiones: list,
                                   exclude_pedido_id: Optional[int] = None,
                                   exclude_taller_id: Optional[int] = None,
                                   exclude_slot_id: Optional[int] = None) -> None:
    """Valida cada sesión futura contra _estudio_disponible. Lanza 409 al primer
    conflicto. Usada por talleres (clases explícitas) y slots (sesiones generadas).
    Contrato: sesiones = [{fecha, hora_inicio_min, hora_fin_min}] en MINUTOS desde
    medianoche (Escuela v2 F1) — timedelta(minutes) representa 1440 = medianoche
    sin el caso especial que `datetime.time` no banca (`replace(hour=24)` rompe)."""
    hoy = now_ar().date()
    for s in sesiones:
        if s["fecha"] < hoy:
            continue
        base = datetime(s["fecha"].year, s["fecha"].month, s["fecha"].day)
        desde = base + timedelta(minutes=s["hora_inicio_min"])
        hasta = base + timedelta(minutes=s["hora_fin_min"])
        libre, motivo = _estudio_disponible(
            conn, estudio, desde, hasta,
            exclude_pedido_id=exclude_pedido_id,
            exclude_taller_id=exclude_taller_id,
            exclude_slot_id=exclude_slot_id,
        )
        if not libre:
            raise HTTPException(
                409,
                f"El estudio no está libre el "
                f"{s['fecha'].strftime('%d/%m/%Y')} de {fmt_hhmm(s['hora_inicio_min'])} "
                f"a {fmt_hhmm(s['hora_fin_min'])} hs: {motivo}",
            )
