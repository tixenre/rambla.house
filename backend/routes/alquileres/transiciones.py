"""routes/alquileres/transiciones.py — puro re-export (#1312, Fase 4).

El motor de transición de estado (`cambiar_estado` + su grafo/helpers) vive
en `services.alquileres.commands.transiciones`. Re-exportado acá TAL CUAL
para no romper `pedidos.py` ni los tests, que importan de este módulo directo.
"""
from services.alquileres.commands.transiciones import (
    ESTADOS_QUE_RESERVAN,  # noqa: F401 — re-export, ver docstring arriba
    _revalidar_stock,  # noqa: F401 — re-export, ver docstring arriba
    cambiar_estado,  # noqa: F401 — re-export, ver docstring arriba
)
