"""Turnos del Estudio EMBEBIDOS en un pedido de alquiler existente (#1308
rediseño "turno como ítem", Fase 4.2).

Transporte HTTP fino: la validación de disponibilidad/stock, el armado de
ítems y el recálculo del total viven en
`services.estudio.commands.reserva.agregar_turno_embebido`/
`editar_turno_embebido`/`eliminar_turno_embebido`. Acá solo se resuelve la
franja horaria del request (`_franja_estudio`, mismo helper que usa el turno
STANDALONE), se abre la conexión, se delega y se commitea. Registra sus rutas
sobre el router compartido del paquete `routes.alquileres` — mismo prefijo
`/alquileres/{id}/...` que documentos/pagos, porque un turno embebido SIEMPRE
cuelga de un pedido existente (a diferencia de `/admin/estudio/reservas`, que
es la puerta de un turno STANDALONE, sin pedido contenedor).
"""
from typing import Optional

from fastapi import Request, HTTPException
from pydantic import BaseModel, field_validator

from database import get_db
from auth.guards import require_admin
from rate_limit import limiter, ADMIN_WRITE_LIMIT
from routes.contabilidad import map_pg_errors
from routes.alquileres.core import router
from routes.alquileres.modelos import (
    _validar_descuento_manual_monto,
    _validar_descuento_manual_tipo,
    _validar_descuento_pct,
    _validar_espacio_monto,
)
from services.alquileres.queries.detalle import _get_alquiler_detail
from services.estudio.commands.reserva import (
    SueltoItem,
    agregar_turno_embebido,
    editar_turno_embebido,
    eliminar_turno_embebido,
)
from services.estudio.queries.disponibilidad import _franja_estudio
from services.estudio.queries.estudio import _get_estudio_row


class TurnoEstudioCreate(BaseModel):
    fecha: str
    start: str
    horas: int
    con_promo: bool = False
    pintura_reciente: bool = False
    sueltos: list[SueltoItem] = []
    espacio_monto: Optional[int] = None

    @field_validator("espacio_monto")
    @classmethod
    def _v_espacio_monto(cls, v):
        return _validar_espacio_monto(v)


class TurnoEstudioUpdate(BaseModel):
    fecha: Optional[str] = None
    start: Optional[str] = None
    horas: Optional[int] = None
    con_promo: Optional[bool] = None
    pintura_reciente: Optional[bool] = None
    sueltos: Optional[list[SueltoItem]] = None
    espacio_monto: Optional[int] = None
    # Descuento PROPIO del turno — mismo contrato que `EstudioReservaAdminUpdate`
    # (routes/estudio.py): `None` = no tocar lo persistido (≠ `espacio_monto`,
    # donde `None` vuelve a precio de lista). Mismos validadores que un pedido/
    # turno standalone — el descuento de un turno embebido no puede aceptar
    # rangos que el de cualquier otro rechaza.
    descuento_pct: Optional[float] = None
    descuento_manual_tipo: Optional[str] = None
    descuento_manual_monto: Optional[int] = None

    @field_validator("espacio_monto")
    @classmethod
    def _v_espacio_monto(cls, v):
        return _validar_espacio_monto(v)

    @field_validator("descuento_pct")
    @classmethod
    def _v_descuento_pct(cls, v):
        return _validar_descuento_pct(v)

    @field_validator("descuento_manual_tipo")
    @classmethod
    def _v_descuento_manual_tipo(cls, v):
        return _validar_descuento_manual_tipo(v)

    @field_validator("descuento_manual_monto")
    @classmethod
    def _v_descuento_manual_monto(cls, v):
        return _validar_descuento_manual_monto(v)


@router.post("/alquileres/{id}/turnos-estudio", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def agregar_turno_estudio(id: int, body: TurnoEstudioCreate, request: Request):
    """Agrega un turno del Estudio como ítem del pedido `id` (#1308 Fase 4).
    Devuelve el pedido COMPLETO actualizado (mismo shape que `GET /alquileres/
    {id}`) — el front reemplaza su cache entera con la respuesta en vez de
    reconciliar un turno aparte."""
    require_admin(request)
    with get_db() as conn:
        try:
            estudio = _get_estudio_row(conn)
            if not estudio["equipo_id"]:
                raise HTTPException(409, "El estudio todavía no tiene un recurso asociado")
            fecha_desde, fecha_hasta = _franja_estudio(estudio, body.fecha, body.start, body.horas)
            _turno_id, promo_advertencia = agregar_turno_embebido(
                conn, id, estudio=estudio, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
                con_promo=body.con_promo, sueltos=body.sueltos,
                pintura_reciente=body.pintura_reciente, espacio_monto=body.espacio_monto,
            )
            conn.commit()
            pedido = _get_alquiler_detail(conn, id)
            pedido["promo_advertencia"] = promo_advertencia
            return pedido
        except Exception:
            conn.rollback()
            raise


@router.patch("/alquileres/{id}/turnos-estudio/{turno_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def editar_turno_estudio(id: int, turno_id: int, body: TurnoEstudioUpdate, request: Request):
    """Edita el turno `turno_id` (debe pertenecer al pedido `id`) — reprograma
    fecha/hora, reemplaza promo/sueltos/pintura, y/o cambia su descuento
    propio. Devuelve el pedido completo actualizado, igual que el alta."""
    require_admin(request)
    with get_db() as conn:
        try:
            turno = conn.execute(
                "SELECT pedido_id FROM alquiler_turnos_estudio WHERE id = %s", (turno_id,)
            ).fetchone()
            if not turno:
                raise HTTPException(404, "Turno no encontrado")
            if turno["pedido_id"] != id:
                raise HTTPException(404, "Ese turno no pertenece a este pedido")

            promo_advertencia = editar_turno_embebido(
                conn, turno_id,
                fecha=body.fecha, start=body.start, horas=body.horas,
                con_promo=body.con_promo, sueltos=body.sueltos,
                pintura_reciente=body.pintura_reciente,
                espacio_monto=body.espacio_monto,
                descuento_pct=body.descuento_pct,
                descuento_manual_tipo=body.descuento_manual_tipo,
                descuento_manual_monto=body.descuento_manual_monto,
            )
            conn.commit()
            pedido = _get_alquiler_detail(conn, id)
            pedido["promo_advertencia"] = promo_advertencia
            return pedido
        except Exception:
            conn.rollback()
            raise


@router.delete("/alquileres/{id}/turnos-estudio/{turno_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def borrar_turno_estudio(id: int, turno_id: int, request: Request):
    """Saca el turno `turno_id` del pedido `id` (cascade sobre sus ítems) y
    devuelve el pedido completo actualizado."""
    require_admin(request)
    with get_db() as conn:
        try:
            turno = conn.execute(
                "SELECT pedido_id FROM alquiler_turnos_estudio WHERE id = %s", (turno_id,)
            ).fetchone()
            if not turno:
                raise HTTPException(404, "Turno no encontrado")
            if turno["pedido_id"] != id:
                raise HTTPException(404, "Ese turno no pertenece a este pedido")

            eliminar_turno_embebido(conn, turno_id)
            conn.commit()
            return _get_alquiler_detail(conn, id)
        except Exception:
            conn.rollback()
            raise
