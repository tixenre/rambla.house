"""Paquete del router de alquileres (#501 — split del god-module `routes/alquileres.py`).

Superficie externa amplia: `main` importa `router`; estudio / cliente_portal /
clientes y muchos tests importan modelos, constantes y helpers internos. Este
`__init__` re-exporta esa superficie pública estable. El router es UNO solo (creado
en `core`); cada submódulo extraído registra sus rutas sobre ese mismo router al
importarse.
"""
from routes.alquileres.core import (
    router,
    # ── Modelos / constantes ──
    PedidoCreate,
    PedidoDatos,
    PedidoItem,
    ESTADOS_RESERVADO,
    # ── Endpoints consumidos como función ──
    create_pedido,
    create_pedido_retry,
    propagar_descuento_a_presupuestos,
    # ── Helpers ──
    get_db,
    _apply_pedido_datos,
    _apply_pedido_items,
    _batch_get_alquiler_items,
    _enriquecer_pedido_con_cliente,
    _enriquecer_pedido_con_cliente_fiscal,
    _enriquecer_pedido_con_total,
    _enriquecer_pedidos_con_cliente,
    _get_alquiler_detail,
    _get_alquiler_items,
    _next_numero_pedido,
    _parse_precio,
    _recalcular_total_pedido,
    _validar_fecha_iso,
)
# Registro de pagos: constantes + validador consumidos por contabilidad y tests
# vía este paquete.
from routes.alquileres.pagos import (
    DESTINATARIOS_PAGO,
    METODOS_PAGO,
    _resolver_destino_metodo,
)
# Cotización canónica: modelos + endpoint consumidos por tests vía este paquete.
# (El módulo se llama `cotizacion` y no `cotizar` a propósito: si se llamara
# igual que la función `cotizar`, el re-export de abajo rebindearía el atributo
# del paquete `routes.alquileres.cotizar` del módulo a la función.)
from routes.alquileres.cotizacion import (
    cotizar,
    CotizarItem,
    CotizarRequest,
)
# Disponibilidad + validación de horarios: endpoint y helper consumidos por
# estudio / cliente_portal / tests vía este paquete.
from routes.alquileres.disponibilidad import (
    get_disponibilidad,
    _validar_horarios_habilitados,
)
# Helpers de documentos (PDFs + mail) consumidos por los tests vía este paquete.
from routes.alquileres.documentos import (
    _agrupar_items_por_categoria,
    _ordenar_items_en_grupos,
    _cuerpo_mail_simple,
)

__all__ = [
    "router",
    "CotizarItem", "CotizarRequest", "PedidoCreate", "PedidoDatos", "PedidoItem",
    "DESTINATARIOS_PAGO", "METODOS_PAGO", "ESTADOS_RESERVADO",
    "cotizar", "create_pedido", "create_pedido_retry", "get_disponibilidad", "propagar_descuento_a_presupuestos",
    "get_db",
    "_agrupar_items_por_categoria", "_apply_pedido_datos", "_apply_pedido_items",
    "_batch_get_alquiler_items", "_cuerpo_mail_simple",
    "_enriquecer_pedido_con_cliente", "_enriquecer_pedido_con_cliente_fiscal", "_enriquecer_pedido_con_total",
    "_enriquecer_pedidos_con_cliente", "_get_alquiler_detail", "_get_alquiler_items",
    "_next_numero_pedido", "_ordenar_items_en_grupos",
    "_parse_precio", "_recalcular_total_pedido",
    "_resolver_destino_metodo", "_validar_fecha_iso", "_validar_horarios_habilitados",
]

# Submódulos sin símbolos re-exportados: el import registra sus rutas sobre el
# `router` compartido; el tuple los mantiene "usados" para ruff. (`documentos`
# sí re-exporta helpers, arriba — su import ya registra sus rutas.) `pedidos`
# son los endpoints HTTP del CRUD del pedido (la lógica reusable queda en `core`).
from routes.alquileres import descuentos as _descuentos
from routes.alquileres import pedidos as _pedidos

_SUBMODULOS = (_descuentos, _pedidos)
