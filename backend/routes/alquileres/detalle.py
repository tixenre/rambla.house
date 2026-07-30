"""routes/alquileres/detalle.py — lectura del detalle de un pedido (split de `core.py`).

Puro re-export (#1312): las lecturas (`_get_alquiler_detail` + sus piezas)
viven en `services.alquileres.queries.detalle` (Fase 1); `_maybe_finalizar`/
`_next_numero_pedido` (parecen lectura por su forma pero mutan) viven en
`services.alquileres.commands.pedido` (Fase 2). Re-exportados acá TAL CUAL
para no romper `core.py`/`transiciones.py`/tests, que importan de este módulo
directo.
"""
from services.alquileres.commands.pedido import (
    _maybe_finalizar,  # noqa: F401 — re-export, ver docstring arriba
    _next_numero_pedido,  # noqa: F401 — re-export, ver docstring arriba
)
from services.alquileres.queries.detalle import (
    _clases_del_taller,  # noqa: F401 — re-export, ver docstring arriba
    _enriquecer_pedido_con_total,  # noqa: F401 — re-export, ver docstring arriba
    _es_historico,  # noqa: F401 — re-export, ver docstring arriba
    _get_alquiler_detail,  # noqa: F401 — re-export, ver docstring arriba
    _get_alquiler_items,  # noqa: F401 — re-export, ver docstring arriba
    _get_alquiler_pagos,  # noqa: F401 — re-export, ver docstring arriba
    _get_historial_modificaciones,  # noqa: F401 — re-export, ver docstring arriba
    _pedido_principal_liviano,  # noqa: F401 — re-export, ver docstring arriba
    _turnos_vinculados,  # noqa: F401 — re-export, ver docstring arriba
)
