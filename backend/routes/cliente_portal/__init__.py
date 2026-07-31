"""Paquete del router del portal del cliente (#501 — split del god-module
`routes/cliente_portal.py`).

`main` importa `router`; otros routers (estudio / didit / alquileres) y los tests
importan helpers / modelos internos → este `__init__` re-exporta la superficie
pública estable. El router es UNO solo (creado en `core`); cada submódulo registra
sus rutas sobre ese mismo router al importarse.
"""
from routes.cliente_portal.core import (
    router,
    require_cliente,
    require_cliente_verificado,
    cliente_verificado,
    IDENTIDAD_NO_VERIFICADA_MSG,
    get_session,
)
from routes.cliente_portal.pedidos import cliente_crear_pedido, CartItemIn, PedidoClienteCreate
from routes.cliente_portal.documentos import _doc_response, _DOC_PREVIEW_HEADERS
from routes.cliente_portal import favoritos as _favoritos  # registra sus rutas
from routes.cliente_portal import listas as _listas  # registra sus rutas

__all__ = [
    "router",
    "require_cliente",
    "require_cliente_verificado",
    "cliente_verificado",
    "IDENTIDAD_NO_VERIFICADA_MSG",
    "get_session",
    "cliente_crear_pedido",
    "CartItemIn",
    "PedidoClienteCreate",
    "_doc_response",
    "_DOC_PREVIEW_HEADERS",
]

# Submódulos sin símbolos re-exportados: el import (arriba) registra sus rutas
# sobre el `router` compartido; el tuple los mantiene "usados" para ruff.
from routes.cliente_portal import cuenta as _cuenta  # registra sus rutas

_SUBMODULOS = (_favoritos, _listas, _cuenta)
