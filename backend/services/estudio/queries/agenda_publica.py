"""Ocupación del estudio por rango — vista PÚBLICA y ANÓNIMA (grilla semanal de
`/estudio`). Combina slot fijo + taller publicado + centinela (reservas
reales), igual criterio que `_ocupacion_estudio_rango` (`routes/estudio.py`,
admin) pero SIN `cliente`/`nombre`/`numero_pedido` — el consumidor público
solo necesita saber "ocupado sí/no" por franja, nunca quién la ocupa.

No es parte del motor de gate (`disponibilidad.py`): es una vista agregada de
*display* para un rango, mismo rol que `_ocupacion_estudio_rango` pero
pensada para exponerse sin auth. No muta nada — solo SELECTs de lectura.
"""
from datetime import date, datetime, timedelta

from reservas import ESTADOS_RESERVADO

from services.estudio.queries.disponibilidad import _sesiones_de_slot


def _centinela_ocupado_en_rango(
    conn, equipo_id: int, desde: date, hasta: date, buffer_horas: int
) -> list[tuple[datetime, datetime]]:
    """Reservas reales del centinela que ocupan (o rozan por buffer) el rango
    [desde, hasta] (fechas inclusive), ya expandidas por `buffer_horas` a cada
    lado. Hermana de lectura-por-rango de `_centinela_libre`
    (`disponibilidad.py`): misma tabla/estado, pero trae los BLOQUES en vez de
    un booleano de una franja puntual. La ventana de búsqueda se amplía por el
    buffer para no perderse reservas que bloquean el rango visible solo por
    el buffer (mismo cálculo que `_centinela_libre` aplica a la franja
    consultada, acá aplicado al bloque que se devuelve)."""
    buf = max(0, buffer_horas or 0)
    ventana_desde = datetime(desde.year, desde.month, desde.day) - timedelta(hours=buf)
    ventana_hasta = (
        datetime(hasta.year, hasta.month, hasta.day) + timedelta(days=1) + timedelta(hours=buf)
    )
    rows = conn.execute(
        f"""
        SELECT p.fecha_desde, p.fecha_hasta
        FROM alquiler_items pi
        JOIN alquileres p ON p.id = pi.pedido_id
        WHERE pi.equipo_id = %s
          AND p.estado IN {ESTADOS_RESERVADO}
          AND p.fecha_desde < %s
          AND p.fecha_hasta > %s
        """,
        (equipo_id, ventana_hasta, ventana_desde),
    ).fetchall()
    out: list[tuple[datetime, datetime]] = []
    for r in rows:
        fd, fh = r["fecha_desde"], r["fecha_hasta"]
        out.append((fd - timedelta(hours=buf), fh + timedelta(hours=buf)))
    return out


def bloques_ocupados_estudio(conn, estudio, desde: date, hasta: date) -> list[dict]:
    """Bloques ocupados del estudio en [desde, hasta] (fechas inclusive),
    combinando slot fijo + taller publicado + centinela (reservas reales,
    expandidas por `estudio.buffer_horas`). Vista PÚBLICA y ANÓNIMA — a
    diferencia de `_ocupacion_estudio_rango` (admin), NUNCA incluye
    cliente/nombre/número de pedido. Cada bloque: {"fecha_desde": datetime,
    "fecha_hasta": datetime}. Solapamientos entre tipos NO se fusionan — el
    consumidor solo necesita "ocupado sí/no" por franja, un array con
    solapes es igual de válido y más simple que mergear intervalos acá."""
    mes_desde = f"{desde.year:04d}-{desde.month:02d}"
    mes_hasta = f"{hasta.year:04d}-{hasta.month:02d}"
    out: list[dict] = []

    slots = conn.execute(
        """
        SELECT dia_semana, hora_desde, hora_hasta, mes_desde, mes_hasta
        FROM estudio_slots_fijos
        WHERE activo = TRUE AND mes_desde <= %s AND mes_hasta >= %s
        """,
        (mes_hasta, mes_desde),
    ).fetchall()
    for slot in slots:
        for s in _sesiones_de_slot(slot):
            if not (desde <= s["fecha"] <= hasta):
                continue
            base = datetime(s["fecha"].year, s["fecha"].month, s["fecha"].day)
            out.append({
                "fecha_desde": base + timedelta(minutes=s["hora_inicio_min"]),
                "fecha_hasta": base + timedelta(minutes=s["hora_fin_min"]),
            })

    clases = conn.execute(
        """
        SELECT c.fecha, c.hora_inicio_min, c.hora_fin_min
        FROM clases_taller c
        JOIN ediciones_taller e ON e.id = c.edicion_id
        JOIN talleres t ON t.id = e.taller_id
        WHERE t.activo = TRUE AND e.activo = TRUE
          AND c.fecha BETWEEN %s AND %s
        """,
        (desde, hasta),
    ).fetchall()
    for c in clases:
        base = datetime(c["fecha"].year, c["fecha"].month, c["fecha"].day)
        out.append({
            "fecha_desde": base + timedelta(minutes=c["hora_inicio_min"]),
            "fecha_hasta": base + timedelta(minutes=c["hora_fin_min"]),
        })

    if estudio["equipo_id"]:
        for (fd, fh) in _centinela_ocupado_en_rango(
            conn, estudio["equipo_id"], desde, hasta, estudio["buffer_horas"]
        ):
            out.append({"fecha_desde": fd, "fecha_hasta": fh})

    return out
