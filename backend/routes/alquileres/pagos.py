"""Registro de pagos (#501 — extraído del god-module `routes/alquileres.py`).

Transporte HTTP fino (#1312, Fase 2): la validación de destinatario/método, el
recálculo del monto pagado y las mutaciones (agregar/agregar combinado/anular)
viven en `services.alquileres.commands.pagos`. Acá quedan los modelos de
request que son puro contrato HTTP (`PagoCombinadoCreate`/`AnularPagoBody`) y
los endpoints del ledger (por pedido + global), que abren la conexión,
delegan y commitean. Registra sus rutas sobre el router compartido del
paquete `routes.alquileres`.
"""
import logging
from typing import Optional

from fastapi import Request, HTTPException, Query
from pydantic import BaseModel, Field

from database import get_db, row_to_dict
from auth.guards import require_admin
from rate_limit import limiter, ADMIN_WRITE_LIMIT
from routes.contabilidad import map_pg_errors
from routes.alquileres.core import router
from services.alquileres.queries.detalle import _get_alquiler_pagos
from services.pedidos_enriquecimiento import _enriquecer_pedidos_con_cliente
from services.alquileres.commands.pagos import (
    DESTINATARIOS_PAGO,  # noqa: F401 — re-export, lo usa routes/alquileres/__init__.py
    METODOS_PAGO,  # noqa: F401 — re-export, lo usa routes/alquileres/__init__.py
    PagoCreate,
    _agregar_pago,
    _agregar_pago_combinado,
    _anular_pago,
    _resolver_destino_metodo,  # noqa: F401 — re-export, lo usa routes/alquileres/__init__.py
)

logger = logging.getLogger(__name__)


class AnularPagoBody(BaseModel):
    # Opcional (2026-08): mismo criterio que `anular_movimiento` — ver el
    # docstring de `anular_pago` más abajo.
    motivo: str | None = Field(default=None, max_length=500)


# ── Registro de pagos ────────────────────────────────────────────────────────
#
# `alquiler_pagos` (el ledger) es la ÚNICA fuente de verdad de "pagado": cada
# cobro deja su fila y `monto_pagado` se DERIVA con `_recalcular_monto_pagado`.
# Se retiró el endpoint legacy `PATCH /alquileres/{id}/pago` que seteaba
# `monto_pagado` a pelo sin registrar el pago (rompía el reporte de liquidación
# y desincronizaba dashboard vs reporte). Ver #722.

@router.get("/alquileres/{id}/pagos")
def list_pagos(id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        if not conn.execute("SELECT id FROM alquileres WHERE id=%s", (id,)).fetchone():
            raise HTTPException(404, "Pedido no encontrado")
        pagos = _get_alquiler_pagos(conn, id)
        return pagos


@router.post("/alquileres/{id}/pagos", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def agregar_pago(id: int, data: PagoCreate, request: Request):
    """Agrega una entrada de pago y recalcula monto_pagado. Ver `_agregar_pago`."""
    admin = require_admin(request)
    with get_db() as conn:
        try:
            pedido = _agregar_pago(conn, id, data, admin.get("email"))
            conn.commit()
            return pedido
        except Exception:
            logger.error("Error agregando pago al pedido %s", id, exc_info=True)
            conn.rollback()
            raise


class PagoCombinadoCreate(BaseModel):
    monto:        int = Field(gt=0, le=2_000_000_000)
    concepto:     Optional[str] = Field(default=None, max_length=500)
    fecha:        Optional[str] = Field(default=None, max_length=10)
    destinatario: Optional[str] = Field(default=None, max_length=20)
    metodo:       Optional[str] = Field(default=None, max_length=20)


@router.post("/alquileres/{id}/pagos-combinado", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def agregar_pago_combinado(id: int, data: PagoCombinadoCreate, request: Request):
    """Registra un pago que se reparte entre `id` y sus turnos del Estudio
    vinculados (#1308) — "un pago, reparte solo": el admin ve un solo total
    combinado y una sola acción de cobro. Ver `_agregar_pago_combinado`."""
    admin = require_admin(request)
    with get_db() as conn:
        try:
            pedido = _agregar_pago_combinado(conn, id, data, admin.get("email"))
            conn.commit()
            return pedido
        except Exception:
            logger.error("Error agregando pago combinado al pedido %s", id, exc_info=True)
            conn.rollback()
            raise


@router.post("/alquileres/{id}/pagos/{pago_id}/anular", status_code=200)
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def anular_pago(id: int, pago_id: int, data: AnularPagoBody, request: Request):
    """Anula una entrada de pago (soft-delete) y recalcula monto_pagado.

    Reemplaza el viejo `DELETE` (hard-delete, sin actor) — auditoría 2026-07-02
    (#1184): esta tabla alimenta todo el motor contable y no respetaba "la plata
    no se borra" que `movimientos` sí respeta.

    **El motivo es OPCIONAL desde 2026-08**, igual que en `anular_movimiento`
    (mismo pedido del dueño, extendido acá porque anular un pago es el mismo
    acto: deshacer una carga propia). Lo que importa se conserva igual — sigue
    siendo soft-delete, y `anulado_por`/`anulado_at` siguen registrando quién y
    cuándo: lo único que se saca es la obligación de escribir prosa para
    corregir un tipeo. Ver `_anular_pago`."""
    admin = require_admin(request)
    motivo = (data.motivo or "").strip() or None
    with get_db() as conn:
        try:
            pedido = _anular_pago(conn, id, pago_id, motivo, admin.get("email"))
            conn.commit()
            return pedido
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            logger.error("Error anulando pago en pedido %s", id, exc_info=True)
            conn.rollback()
            raise


@router.get("/admin/pagos")
def list_all_pagos(
    request: Request,
    destinatario: Optional[str] = Query(None),
    metodo: Optional[str] = Query(None),
    desde: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    hasta: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    incluir_anulados: bool = Query(False),
    limit: int = Query(500, le=2000),
):
    """Ledger global de pagos — vista de logs del back-office.

    Lista las filas de `alquiler_pagos` (la fuente ÚNICA de "pagado") con su
    pedido y cliente, ordenadas por fecha desc. Filtros opcionales por
    destinatario, método y rango de fechas (inclusive). Por defecto excluye
    los anulados (mismo patrón que `listar_movimientos`). Devuelve también el
    total del subconjunto filtrado.

    El nombre del cliente se resuelve EN VIVO (`_enriquecer_pedidos_con_cliente`,
    decisión 2026-06-06) — el `al.cliente_nombre` del SELECT es solo la foto
    congelada al crear el pedido, punto de partida que la enriquecida
    sobrescribe. Bug real (mismo patrón que pedido #466, ya arreglado en
    calendario/dashboard pero no acá): un cliente sin nombre cargado al
    vincularse que lo completó después quedaba "sin cliente" para siempre en
    este ledger, aunque el pedido y el resto de las pantallas ya mostraban
    el nombre correcto.
    """
    require_admin(request)
    where = ["1=1"]
    params: list = []
    if not incluir_anulados:
        where.append("NOT ap.anulado")
    if destinatario:
        where.append("ap.destinatario = %s")
        params.append(destinatario)
    if metodo:
        where.append("ap.metodo = %s")
        params.append(metodo)
    if desde:
        where.append("ap.fecha::date >= %s")
        params.append(desde)
    if hasta:
        where.append("ap.fecha::date <= %s")
        params.append(hasta)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT ap.id, ap.pedido_id, ap.monto, ap.concepto,
                   ap.destinatario, ap.metodo, ap.fecha, ap.created_by,
                   ap.anulado, ap.anulado_por, ap.anulado_at, ap.anulado_motivo,
                   al.numero_pedido, al.cliente_nombre, al.cliente_id, al.pedido_principal_id
              FROM alquiler_pagos ap
              JOIN alquileres al ON al.id = ap.pedido_id
             WHERE {" AND ".join(where)}
             ORDER BY ap.fecha DESC, ap.id DESC
             LIMIT %s
            """,
            (*params, limit),
        ).fetchall()
        pagos = [row_to_dict(r) for r in rows]
        _enriquecer_pedidos_con_cliente(conn, pagos)
        total = sum((p["monto"] or 0) for p in pagos)
        return {"pagos": pagos, "total": total, "count": len(pagos)}
