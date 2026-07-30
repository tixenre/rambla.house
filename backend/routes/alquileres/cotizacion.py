"""Cotización canónica del carrito (#501 — extraído del god-module `routes/alquileres.py`).

Contrato HTTP (#1312, Fase 1): los modelos Pydantic + el rate limit viven acá;
el CUERPO de la cotización (fuente única del total del carrito) vive en
`services.alquileres.queries.cotizacion.cotizar_carrito`. Registra su ruta
sobre el router compartido del paquete `routes.alquileres`.
"""
from typing import Optional

from fastapi import Request
from pydantic import BaseModel, field_validator

from rate_limit import limiter
from routes.alquileres.core import router
from services.alquileres.queries.cotizacion import cotizar_carrito
# Validadores de descuento: fuente única compartida con `PedidoDatos`
# (routes/alquileres/modelos.py) — antes estaban duplicados byte a byte acá.
from routes.alquileres.modelos import (
    _validar_descuento_manual_monto,
    _validar_descuento_manual_tipo,
    _validar_descuento_pct,
)


class CotizarItem(BaseModel):
    # equipo_id None = línea personalizada (#805): su precio y modo de cobro
    # vienen del front (el admin la edita libre); no se busca en `equipos`.
    equipo_id: Optional[int] = None
    cantidad: int
    precio_jornada: Optional[int] = None
    cobro_modo: Optional[str] = None


class CotizarRequest(BaseModel):
    items: list[CotizarItem] = []
    fecha_desde: Optional[str] = None
    fecha_hasta: Optional[str] = None
    # Los dos siguientes SOLO los honra una sesión admin (el builder de pedidos
    # arma para OTRO cliente, no para la sesión):
    #  - cliente_id: de qué cliente tomar el perfil tributario.
    #  - descuento_pct: override del descuento del cliente (el admin lo edita
    #    en vivo en el builder; gana sobre el `clientes.descuento` guardado).
    cliente_id: Optional[int] = None
    descuento_pct: Optional[float] = None
    # Override manual en % o en $ fijo (Fase C-2, #1219): mismo par que
    # `PedidoDatos` (routes/alquileres/core.py) — el builder los edita en vivo
    # para que el preview coincida con lo que se va a persistir.
    descuento_manual_tipo: Optional[str] = None
    descuento_manual_monto: Optional[float] = None
    # Solo lo honra una sesión admin: respeta el `precio_jornada` que manda cada
    # ítem de catálogo (el snapshot congelado del pedido que se está editando)
    # en vez de re-buscarlo en `equipos`. Sin esto, el editor de pedidos admin
    # mostraba un total "en vivo" con el precio de HOY del catálogo — distinto
    # al que persiste `_recalcular_total_pedido` al guardar (que sí respeta el
    # precio de línea) → dos totales del mismo pedido que podían no coincidir.
    # Ver MEMORIA 2026-06-06 "Datos del pedido: plata congelada".
    respetar_precio_item: Optional[bool] = False
    # Solo lo honra una sesión admin: id del pedido que se está editando. Cuando
    # el pedido ya NO está en `presupuesto` (plata congelada), el descuento de
    # cliente/jornadas del preview sale del MISMO snapshot que la persistencia
    # (`_resolver_descuentos_snapshot_o_vivo`), no en vivo — así el total del
    # editor coincide con `monto_total` (y con la lista de pedidos). El editor
    # solo lo manda para pedidos no-presupuesto; en presupuesto el descuento
    # sigue al cliente en vivo. Ver MEMORIA 2026-06-06 "plata congelada".
    pedido_id: Optional[int] = None
    # #1240: a nombre de quién se está cotizando (perfil personal alternativo o
    # productora) — solo lo honra una sesión cliente (mismo criterio que el resto
    # de este bloque: el admin cotiza para el cliente del pedido, no para sí
    # mismo). Mutuamente excluyentes; NULL/NULL = perfil default de la cuenta.
    perfil_fiscal_id: Optional[int] = None
    productora_id: Optional[int] = None

    # Mismo validador que `PedidoDatos.descuento_pct` (routes/alquileres/modelos.py)
    # — este override vivía sin cota de rango (hallazgo de la Fase A del split
    # de descuentos/, #1184): un admin podía mandar un negativo al preview en
    # vivo sin que nada lo rechazara. Ahora es la MISMA función (no una copia):
    # preview y guardado no pueden divergir en qué rechazan.
    @field_validator("descuento_pct")
    @classmethod
    def validate_descuento(cls, v):
        return _validar_descuento_pct(v)

    @field_validator("descuento_manual_tipo")
    @classmethod
    def validate_descuento_manual_tipo(cls, v):
        return _validar_descuento_manual_tipo(v)

    @field_validator("descuento_manual_monto")
    @classmethod
    def validate_descuento_manual_monto(cls, v):
        return _validar_descuento_manual_monto(v)


@router.post("/cotizar")
@limiter.limit("30/minute")
def cotizar(data: CotizarRequest, request: Request):
    """Cotización canónica del carrito — fuente única, calculada en el backend.
    Delega en `services.alquileres.queries.cotizacion.cotizar_carrito`."""
    return cotizar_carrito(data, request)
