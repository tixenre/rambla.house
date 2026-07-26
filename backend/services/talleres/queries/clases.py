"""Validación pura (sin `conn`) de clases y modalidades de pago de una edición
de taller — move-verbatim desde `routes/talleres.py`. Reusada por
`services.talleres.commands.ediciones` (alta) y por el endpoint
`admin_update_edicion` (edición, se queda en el route)."""
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
    descuentos: `monto_total` lo carga el admin a mano; los "%" de ahorro son
    texto libre en `nota`. Lanza 400 si hay errores."""
    result = []
    seen_codigos = set()
    for m in modalidades:
        def _campo(nombre: str, default=""):
            return _row_get(m, nombre, default) if isinstance(m, dict) else getattr(m, nombre, default)

        codigo = str(_campo("codigo") or "").strip()
        label = str(_campo("label") or "").strip()
        monto = _campo("monto_total", 0)
        if not codigo:
            raise HTTPException(400, "Cada modalidad de pago necesita un código")
        if not label:
            raise HTTPException(400, f"La modalidad '{codigo}' necesita un label")
        if not isinstance(monto, int) or monto <= 0:
            raise HTTPException(400, f"La modalidad '{codigo}' necesita un monto_total > 0")
        if codigo in seen_codigos:
            raise HTTPException(400, f"Código de modalidad duplicado: '{codigo}'")
        seen_codigos.add(codigo)
        result.append({
            "id": _campo("id", None),
            "codigo": codigo,
            "label": label,
            "nota": str(_campo("nota") or "").strip(),
            "monto_total": monto,
        })
    return result
