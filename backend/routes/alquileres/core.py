"""routes/alquileres/core.py — spine del paquete de alquileres (#501; split #1254; #1312).

El `router` compartido de todo el paquete. Toda la lógica de negocio (creación
de pedido, máquina de estados, núcleo de ítems/total, lectura del detalle,
pagos) vive en `services.alquileres.{queries,commands}` (#1312) — este módulo
es puro re-export de esa superficie (más la de `modelos.py`/
`services.pedidos_enriquecimiento`/`services.pedidos_notificaciones`, issue
#1254) para no romper los ~57 call-sites existentes (`routes/alquileres/__init__.py`
y afuera del paquete). Las superficies HTTP (pedidos CRUD, cotización,
disponibilidad, pagos, documentos, descuentos) viven en submódulos que
registran sus rutas sobre este router.
"""

from fastapi import APIRouter

from database import get_db  # noqa: F401 — re-export, lo usa routes/alquileres/__init__.py
# _batch_get_alquiler_items/_enriquecer_pedido_con_cliente_fiscal/_enriquecer_pedidos_con_cliente
# viven en services.pedidos_enriquecimiento (auditoría cruzada de plata, 2026-07-02) —
# reexportados acá tal cual para no tocar los call-sites existentes (este paquete +
# routes/cliente_portal). `_enriquecer_pedido_con_cliente` la usa `detalle.py` (Corte C,
# #1254) directo de la misma fuente — acá queda como puro re-export. Código nuevo
# debería importar de services.pedidos_enriquecimiento directo.
from services.pedidos_enriquecimiento import (
    _batch_get_alquiler_items,  # noqa: F401 — re-export, ver comentario arriba
    _enriquecer_pedido_con_cliente_fiscal,  # noqa: F401 — re-export, ver comentario arriba
    _enriquecer_pedido_con_cliente,  # noqa: F401 — re-export, ver comentario arriba
    _enriquecer_pedidos_con_cliente,  # noqa: F401 — re-export, ver comentario arriba
)
# Creación del pedido: vive en `services.alquileres.commands.creacion` (#1312,
# Fase 4) — la puerta única con el advisory lock. Re-exportada acá TAL CUAL,
# `routes/alquileres/__init__.py` y `routes/cliente_portal/pedidos.py` la
# siguen importando de este paquete sin cambiar una línea.
from services.alquileres.commands.creacion import (
    create_pedido,  # noqa: F401 — re-export, ver comentario arriba
    create_pedido_retry,  # noqa: F401 — re-export, ver comentario arriba
)
# Núcleo de ítems/total: vive en `services.alquileres.commands.items` (#1312,
# Fase 3). Re-exportado acá TAL CUAL — puro re-export para `pedidos.py`/
# `clientes/`, que importan de `routes.alquileres.core`/`routes.alquileres` directo.
from services.alquileres.commands.items import (
    _apply_pedido_datos,  # noqa: F401 — re-export, ver comentario arriba
    _apply_pedido_items,  # noqa: F401 — re-export, ver comentario arriba
    _recalcular_total_pedido,  # noqa: F401 — re-export, ver comentario arriba
    propagar_descuento_a_presupuestos,  # noqa: F401 — re-export, ver comentario arriba
)

# Modelos Pydantic del pedido: viven en `modelos.py` (split de este archivo, issue
# de tracking #1254). Re-exportados acá TAL CUAL — `routes/alquileres/__init__.py`
# los sigue importando de `core` sin cambiar una línea, y varios tests importan
# `PedidoItem`/`PedidoCreate`/etc. o `_parse_precio` vía este paquete.
from routes.alquileres.modelos import (
    PedidoCreate,  # noqa: F401 — re-export, ver comentario arriba
    PedidoDatos,  # noqa: F401 — re-export, ver comentario arriba
    PedidoEstado,  # noqa: F401 — re-export, ver comentario arriba
    PedidoItem,  # noqa: F401 — re-export, ver comentario arriba
    PedidoItemUpdate,  # noqa: F401 — re-export, ver comentario arriba
    _parse_precio,  # noqa: F401 — re-export, ver comentario arriba
    _validar_fecha_iso,  # noqa: F401 — re-export, ver comentario arriba
)
# Lectura del detalle de un pedido: vive en `services.alquileres.queries.detalle`
# (#1312, Fase 1) vía `detalle.py` (puro re-export). Re-exportada acá TAL CUAL —
# puro re-export para `pagos.py`/`documentos.py`/`pedidos.py`, que importan de
# `routes.alquileres.core` directo.
from routes.alquileres.detalle import (
    _get_alquiler_detail,  # noqa: F401 — re-export, ver comentario arriba
    _get_alquiler_items,  # noqa: F401 — re-export, ver comentario arriba
    _get_alquiler_pagos,  # noqa: F401 — re-export, ver comentario arriba
    _get_historial_modificaciones,  # noqa: F401 — re-export, ver comentario arriba
    _maybe_finalizar,  # noqa: F401 — re-export, ver comentario arriba
    _next_numero_pedido,  # noqa: F401 — re-export, ver comentario arriba
    _enriquecer_pedido_con_total,  # noqa: F401 — re-export, ver comentario arriba
)
# El armado de contexto/`.ics` y el despacho de avisos al cliente viven ahora en la
# capa única de comunicación (`services/comunicacion`, 2026-07-11): el ex-módulo
# `services/pedidos_notificaciones` se eliminó y los consumidores importan directo
# de ahí, sin re-export intermedio.

# Motor de reservas: la fuente única vive en el paquete `reservas`.
# `ESTADOS_RESERVADO` se re-exporta porque es la constante canónica del
# dominio. El resto de las primitivas se importan directo de `reservas` donde
# se usan (routes.estudio, routes.cliente_portal, routes.alquileres.disponibilidad,
# services.alquileres.commands.{creacion,transiciones}). Ver issue #501, Fase 1.
from reservas import (
    ESTADOS_RESERVADO,  # noqa: F401 — re-export canónico (guard: test_reservas_sql_safety)
)

router = APIRouter()
