"""Lecturas de disponibilidad — Fase 1 del split CQRS-lite de `routes/alquileres/` (#1312).

Move-verbatim desde `routes/alquileres/disponibilidad.py`: delegan en la fuente única
`reservas.calcular_disponibilidad`/`dias_no_disponibles` y la validación de horarios
habilitados. `routes/alquileres/disponibilidad.py` queda como transporte HTTP fino
(los `@router.get`) y delega acá.
"""
from fastapi import HTTPException

from database import get_db
from reservas import (
    calcular_disponibilidad as _calcular_disponibilidad,
    calcular_disponibilidad_draft as _calcular_disponibilidad_draft,
    dias_no_disponibles as _dias_no_disponibles,
)
from services.fechas import validar_horarios_habilitados


def _validar_horarios_habilitados(conn, fecha_desde, fecha_hasta) -> None:
    """Adapter HTTP de `services.fechas.validar_horarios_habilitados`: la lógica de
    horarios vive en la puerta única de fechas; acá solo levantamos el 400. Se
    mantiene el nombre (re-exportado por `routes/alquileres`) para los callsites y
    el monkeypatch de tests."""
    msg = validar_horarios_habilitados(conn, fecha_desde, fecha_hasta)
    if msg:
        raise HTTPException(400, msg)


def _parse_items_dias(items: str) -> dict[int, int]:
    """Parsea 'equipo_id:cantidad,...' tomando el MAX por equipo repetido —
    semántica de bloqueo de calendario (`dias_no_disponibles_de_pedido`), distinta
    a propósito de `_parse_items_draft` (que suma, semántica de demanda)."""
    parsed: dict[int, int] = {}
    for tok in (items or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        eid_str, _, qty_str = tok.partition(":")
        try:
            eid = int(eid_str)
            qty = int(qty_str) if qty_str else 1
        except ValueError:
            raise HTTPException(400, f"Item inválido: '{tok}' (se espera 'id' o 'id:cantidad')")
        parsed[eid] = max(parsed.get(eid, 0), max(1, qty))
    return parsed


def dias_no_disponibles_de_pedido(items: str, desde: str, hasta: str) -> dict:
    """Días sin disponibilidad para los equipos pedidos, en [desde, hasta].
    Lo usa el calendario del cliente para bloquear días según las reservas
    reales de los equipos que tiene en el carrito."""
    parsed = _parse_items_dias(items)
    if not parsed:
        return {"dias_bloqueados": []}
    with get_db() as conn:
        return {"dias_bloqueados": _dias_no_disponibles(conn, parsed, desde, hasta)}


def _parse_items_draft(items: str) -> dict[int, int]:
    """Parsea el draft 'equipo_id:cantidad,...' a `{equipo_id: cantidad}`.

    Los duplicados del mismo equipo se SUMAN — espeja la consolidación del gate
    (issue #102). Distinto a propósito del parser de `/disponibilidad-dias`, que
    toma el MAX (semántica de bloqueo de calendario, no de demanda de un draft).
    """
    parsed: dict[int, int] = {}
    for tok in (items or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        eid_str, _, qty_str = tok.partition(":")
        try:
            eid = int(eid_str)
            qty = int(qty_str) if qty_str else 1
        except ValueError:
            raise HTTPException(400, f"Item inválido: '{tok}' (se espera 'id' o 'id:cantidad')")
        if qty > 0:
            parsed[eid] = parsed.get(eid, 0) + qty
    return parsed


def disponibilidad_de_rango(
    fecha_desde: str,
    fecha_hasta: str,
    exclude_pedido_id: int = None,
    items: str = None,
) -> dict:
    """Delega en la fuente única de lectura `reservas.calcular_disponibilidad`.
    Lo llama también `routes.cliente_portal` con esta misma firma.
    `services/estudio/queries/promo.py` tiene su PROPIO wrapper local sobre
    `reservas.calcular_disponibilidad` (no llama a esto — evita que un service
    importe de un route).

    Con `items` (el draft del editor de pedidos), delega en
    `calcular_disponibilidad_draft`: descuenta además la demanda del draft con
    la MISMA expansión de kits del gate, y los valores vuelven con signo (un
    negativo = cuántas unidades faltan)."""
    with get_db() as conn:
        if items:
            return _calcular_disponibilidad_draft(
                conn, fecha_desde, fecha_hasta, _parse_items_draft(items), exclude_pedido_id
            )
        return _calcular_disponibilidad(conn, fecha_desde, fecha_hasta, exclude_pedido_id)
