"""Validación pura (sin `conn`) de clases y modalidades de pago de una edición
de taller — move-verbatim desde `routes/talleres.py`. Reusada por
`services.talleres.commands.ediciones` (alta) y por el endpoint
`admin_update_edicion` (edición, se queda en el route).

`clases_de_edicion` (con `conn`, 2026-07-28) es la excepción a "queries/ es
puro": vive acá para que `routes/alquileres/detalle.py` pueda leer las clases
reales de un taller sin crear un ciclo de import (`routes/talleres.py` ya
importa `_next_numero_pedido` de `routes.alquileres` — el sentido inverso
rompería). Mismo motivo que puso `tipos_pedido.py` "en el nivel más bajo del
árbol de imports"."""
from datetime import date as _dt_date

from fastapi import HTTPException

from services.fechas import fmt_hhmm as _fmt_hhmm


def _row_get(c, key, default=None):
    """Lectura tolerante: row de DB o dict normalizado pueden no traer el campo."""
    try:
        v = c[key]
        return default if v is None else v
    except (KeyError, IndexError):
        return default


def _clase_dict(c) -> dict:
    """Serialización única de una clase (row de DB o dict normalizado de
    _validar_clases): minutos crudos + strings "HH:MM" resueltos acá +
    el contenido rico (F2: titulo/descripcion/nota/portada). Move-verbatim
    desde `routes/talleres.py` (2026-07-28, junto con `clases_de_edicion`)."""
    return {
        "id": _row_get(c, "id"),
        "fecha": str(c["fecha"]),
        "hora_inicio_min": c["hora_inicio_min"],
        "hora_fin_min": c["hora_fin_min"],
        "hora_inicio_str": _fmt_hhmm(c["hora_inicio_min"]),
        "hora_fin_str": _fmt_hhmm(c["hora_fin_min"]),
        "titulo": _row_get(c, "titulo", ""),
        "descripcion": _row_get(c, "descripcion", ""),
        "nota": _row_get(c, "nota", ""),
        "portada_media_id": _row_get(c, "portada_media_id"),
        "portada_url": _row_get(c, "portada_url", ""),
    }


def clases_de_edicion(conn, edicion_id: int) -> list[dict]:
    """Clases reales (fecha + franja horaria) de una edición de taller,
    ordenadas por `orden` (manual, independiente de fecha — el admin puede
    reordenar sin que la fecha las reordene sola). Fuente única: la usan
    `routes/talleres.py` (`_get_clases`, alias de esta función) y el detalle
    de un pedido de taller (`routes/alquileres/detalle.py`, vía
    `taller_edicion_id`) para mostrar la verdad temporal real en vez del
    rango contable del pedido (bug real #445: "7 jornadas" en vez de las
    clases puntuales)."""
    rows = conn.execute(
        "SELECT id, fecha, hora_inicio_min, hora_fin_min, titulo, descripcion, "
        "nota, portada_media_id, portada_url FROM clases_taller "
        "WHERE edicion_id = %s ORDER BY orden, id",
        (edicion_id,),
    ).fetchall()
    return [_clase_dict(r) for r in rows]


def _validar_clases(clases: list) -> list[dict]:
    """Valida y normaliza una lista de clases (horas en MINUTOS desde medianoche,
    múltiplo de 15 — la UI ofrece pasos de 30, 15 da margen sin granularidad
    arbitraria). Devuelve lista de dicts. Lanza 400 si hay errores."""
    if not clases:
        raise HTTPException(400, "Debe tener al menos una clase")
    result = []
    seen = set()
    for s in clases:
        fecha_str = s.fecha if hasattr(s, "fecha") else s["fecha"]
        h_ini = s.hora_inicio_min if hasattr(s, "hora_inicio_min") else s["hora_inicio_min"]
        h_fin = s.hora_fin_min if hasattr(s, "hora_fin_min") else s["hora_fin_min"]
        try:
            fecha = _dt_date.fromisoformat(fecha_str)
        except (ValueError, TypeError):
            raise HTTPException(400, f"Fecha inválida: {fecha_str}")
        if not (0 <= h_ini < h_fin <= 1440):
            raise HTTPException(
                400, f"Horario inválido en {fecha_str}: {_fmt_hhmm(h_ini)}-{_fmt_hhmm(h_fin)}"
            )
        if h_ini % 15 or h_fin % 15:
            raise HTTPException(
                400, f"El horario debe ser múltiplo de 15 minutos ({fecha_str})"
            )
        titulo = str(_row_get(s, "titulo", "") if isinstance(s, dict) else getattr(s, "titulo", "")).strip()
        # La key de duplicado incluye el título: "Clase 11 y 12 se dictan juntas"
        # (caso Filmar) = 2 clases con la misma fecha/franja y títulos distintos.
        key = (fecha, h_ini, h_fin, titulo)
        if key in seen:
            raise HTTPException(
                400, f"Clase duplicada: {fecha_str} {_fmt_hhmm(h_ini)}-{_fmt_hhmm(h_fin)}"
            )
        seen.add(key)

        def _campo(nombre: str, default=""):
            return _row_get(s, nombre, default) if isinstance(s, dict) else getattr(s, nombre, default)

        result.append({
            "id": _campo("id", None),
            "fecha": fecha,
            "hora_inicio_min": h_ini,
            "hora_fin_min": h_fin,
            "titulo": titulo,
            "descripcion": str(_campo("descripcion") or "").strip(),
            "nota": str(_campo("nota") or "").strip(),
            "portada_media_id": _campo("portada_media_id", None),
            "portada_url": str(_campo("portada_url") or ""),
        })
    return result


def _validar_modalidades(modalidades: list) -> list[dict]:
    """Valida y normaliza una lista de modalidades de pago. Sin motor de
    descuentos: `monto_total` (costo total del plan) lo carga el admin a
    mano; los "%" de ahorro son texto libre en `nota`. `n_cuotas` (default 1
    = pago único) también lo carga el admin — el monto POR cuota se DERIVA
    en `_modalidad_dict` (routes/talleres.py), nunca se tipea a mano, para
    que no pueda desincronizarse del total. Lanza 400 si hay errores."""
    result = []
    seen_codigos = set()
    for m in modalidades:
        def _campo(nombre: str, default=""):
            return _row_get(m, nombre, default) if isinstance(m, dict) else getattr(m, nombre, default)

        codigo = str(_campo("codigo") or "").strip()
        label = str(_campo("label") or "").strip()
        monto = _campo("monto_total", 0)
        n_cuotas = _campo("n_cuotas", 1)
        if n_cuotas is None:
            n_cuotas = 1
        if not codigo:
            raise HTTPException(400, "Cada modalidad de pago necesita un código")
        if not label:
            raise HTTPException(400, f"La modalidad '{codigo}' necesita un label")
        if not isinstance(monto, int) or monto <= 0:
            raise HTTPException(400, f"La modalidad '{codigo}' necesita un monto_total > 0")
        if not isinstance(n_cuotas, int) or n_cuotas < 1:
            raise HTTPException(400, f"La modalidad '{codigo}' necesita n_cuotas >= 1")
        if codigo in seen_codigos:
            raise HTTPException(400, f"Código de modalidad duplicado: '{codigo}'")
        seen_codigos.add(codigo)
        result.append({
            "id": _campo("id", None),
            "codigo": codigo,
            "label": label,
            "nota": str(_campo("nota") or "").strip(),
            "monto_total": monto,
            "n_cuotas": n_cuotas,
        })
    return result
