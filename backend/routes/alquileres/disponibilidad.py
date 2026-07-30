"""Disponibilidad (#501 — extraído del god-module `routes/alquileres.py`).

Transporte HTTP fino (#1312, Fase 1): delega en la fuente única de lectura
`services.alquileres.queries.disponibilidad`. Registra sus rutas sobre el
router compartido del paquete `routes.alquileres`.

(El disparador on-demand de recordatorios de retiro vivía acá sin ninguna
relación temática — se mudó a `pedidos.py` en la auditoría de duplicación/
superposición del módulo, issue #1254.)
"""
from fastapi import Query

from routes.alquileres.core import router
from services.alquileres.queries.disponibilidad import (
    _parse_items_draft,  # noqa: F401 — re-export, lo usan los tests vía este módulo
    _validar_horarios_habilitados,  # noqa: F401 — re-export, lo usa routes/alquileres/__init__.py
    dias_no_disponibles_de_pedido,
    disponibilidad_de_rango,
)


@router.get("/disponibilidad-dias")
def get_disponibilidad_dias(
    items: str = Query(..., description="Lista 'equipo_id:cantidad' separada por coma"),
    desde: str = Query(...),
    hasta: str = Query(...),
):
    """Días sin disponibilidad para los equipos pedidos, en [desde, hasta].
    Lo usa el calendario del cliente para bloquear días según las reservas
    reales de los equipos que tiene en el carrito."""
    return dias_no_disponibles_de_pedido(items, desde, hasta)


@router.get("/disponibilidad")
def get_disponibilidad(
    fecha_desde: str = Query(...),
    fecha_hasta: str = Query(...),
    exclude_pedido_id: int = Query(None),
    # Draft "equipo_id:cantidad,..." — resta también esa demanda (expandida por
    # kits como el gate) y devuelve valores CON SIGNO. Default plano (NO
    # `Query(None)`): esta función también se llama DIRECTO como helper
    # (`routes/cliente_portal/solicitudes.py`) y un default `Query(None)` es
    # truthy → entraría al camino draft sin querer.
    items: str = None,
):
    """Endpoint fino: delega en la fuente única de lectura
    `services.alquileres.queries.disponibilidad.disponibilidad_de_rango`
    (a su vez sobre `reservas.calcular_disponibilidad`). Lo llama también
    `routes.cliente_portal` con esta misma firma."""
    return disponibilidad_de_rango(fecha_desde, fecha_hasta, exclude_pedido_id, items)
