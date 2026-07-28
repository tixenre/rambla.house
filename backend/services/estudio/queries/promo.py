"""Lectura de la promo (combo) del Estudio (#1283 Fase 5 — reemplaza al pack).

El pack era una lista CURADA de equipos elegidos a mano (`estudio_pack_equipos`).
La promo es UN equipo real `tipo='combo'` a precio fijo — `_pack_equipo_ids`
sobrevive solo como semilla de componentes al crear la promo
(`commands/promo.py::crear_promo`), no hay más "curar el pack" en sí.
"""
from database import get_db
from reservas import calcular_disponibilidad as _calcular_disponibilidad
from services.contenido import contenido_de
from services.precios import precio_jornada_efectivo


def get_disponibilidad(fecha_desde: str, fecha_hasta: str, exclude_pedido_id: int | None = None):
    """Wrapper local sobre `reservas.calcular_disponibilidad`, con conexión PROPIA
    (deliberado — devuelve un snapshot committed-only, igual que el helper de
    `routes/alquileres/disponibilidad.py::get_disponibilidad` que `_promo_info`
    usaba antes del split, mismo camino que con `items=None`). NO pasarle la conn
    del caller: cambiaría qué reservas concurrentes ve el combo."""
    with get_db() as conn:
        return _calcular_disponibilidad(conn, fecha_desde, fecha_hasta, exclude_pedido_id)


def _pack_equipo_ids(conn) -> list[int]:
    """IDs de los equipos curados del pack (tabla `estudio_pack_equipos`), en su
    orden. Excluye el centinela y los eliminados (por si quedó alguno colgado).
    ⏰ Sobrevive al retiro del pack (Fase 8, #1283) solo como semilla de
    componentes para `commands/promo.py::crear_promo`."""
    rows = conn.execute(
        """
        SELECT e.id
        FROM estudio_pack_equipos pe
        JOIN equipos e ON e.id = pe.equipo_id
        WHERE pe.estudio_id = 1
          AND e.es_recurso_interno = FALSE
          AND e.eliminado_at IS NULL
        ORDER BY pe.orden, pe.id
        """,
    ).fetchall()
    return [r["id"] for r in rows]


def _promo_info(conn, estudio_row, fecha_desde=None, fecha_hasta=None,
                exclude_pedido_id: int | None = None) -> dict | None:
    """Info de la promo (combo) del Estudio: nombre/foto/precio/componentes —
    `None` si todavía no se creó (#1283 Fase 5). El precio sale de
    `precio_jornada_efectivo` (fuente única, sigue en vivo el precio de los
    componentes). `descripcion` reusa `pack_descripcion` (texto libre ya
    editable desde el back-office, no se agrega un campo nuevo). `componentes`
    (listado público "qué incluye") sale de la puerta única
    `services.contenido.contenido_de` — MISMA fuente que el catálogo
    (`attach_kit`), nunca puede desincronizarse de lo que la promo realmente
    reserva. Si se pasa una franja (`fecha_desde`/`fecha_hasta`, ambos
    `datetime`), suma `disponible` (deriva de `get_disponibilidad`, que expande
    los componentes del combo igual que cualquier compuesto — sin lógica nueva)."""
    combo_id = estudio_row["promo_combo_id"]
    if not combo_id:
        return None
    combo = conn.execute(
        "SELECT nombre, foto_url FROM equipos WHERE id = %s AND eliminado_at IS NULL",
        (combo_id,),
    ).fetchone()
    if not combo:
        return None
    out = {
        "equipo_id": combo_id,
        "nombre": combo["nombre"],
        "descripcion": estudio_row["pack_descripcion"],
        "foto_url": combo["foto_url"],
        "precio": precio_jornada_efectivo(conn, combo_id) or 0,
        "componentes": [
            {"nombre": c["nombre"], "cantidad": c["cantidad"], "foto_url": c["foto_url"]}
            for c in contenido_de(conn, combo_id, solo_activos=True)
        ],
    }
    if fecha_desde is not None:
        disp = get_disponibilidad(fecha_desde.isoformat(), fecha_hasta.isoformat(), exclude_pedido_id)
        out["disponible"] = disp.get(str(combo_id), 0) >= 1
    return out
