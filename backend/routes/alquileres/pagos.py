"""Registro de pagos (#501 — extraído del god-module `routes/alquileres.py`).

El ledger `alquiler_pagos` es la fuente ÚNICA de "pagado": cada cobro deja su
fila y `monto_pagado` se DERIVA con `_recalcular_monto_pagado`. Acá viven el
modelo + validación de destinatario/método, el recálculo del monto pagado, y los
endpoints del ledger (por pedido + global). Registra sus rutas sobre el router
compartido del paquete `routes.alquileres`.
"""
import logging
from typing import Optional

from fastapi import Request, HTTPException, Query
from pydantic import BaseModel, Field

from database import get_db, row_to_dict, now_ar
from auth.guards import require_admin
from rate_limit import limiter, ADMIN_WRITE_LIMIT
from routes.contabilidad import map_pg_errors
from routes.alquileres.core import (
    router,
    _maybe_finalizar,
    _get_alquiler_pagos,
    _get_alquiler_detail,
)

logger = logging.getLogger(__name__)


# Pagos: a quién se cobró (destinatario) y cómo (método). Fuente única de los
# valores admitidos — la usan la validación del endpoint y la vista de logs.
# Cualquiera de los tres puede cobrar; el default es Rambla (en transferencia).
# Cada destinatario mapea a una caja en Contabilidad (Pablo/Tincho → su caja de
# socio; Rambla → Fondo Rambla), donde la plata cobrada se atribuye sola.
from contabilidad.constants import COBRADORES as DESTINATARIOS_PAGO  # fuente única
METODOS_PAGO = ("transferencia", "efectivo")
DESTINATARIO_PAGO_DEFAULT = "Rambla"
METODO_PAGO_DEFAULT = "transferencia"


class PagoCreate(BaseModel):
    monto:        int = Field(gt=0, le=2_000_000_000)
    concepto:     Optional[str] = Field(default=None, max_length=500)
    fecha:        Optional[str] = Field(default=None, max_length=10)   # YYYY-MM-DD; si no viene usa hoy
    destinatario: Optional[str] = Field(default=None, max_length=20)   # Tincho|Pablo (default Tincho)
    metodo:       Optional[str] = Field(default=None, max_length=20)   # transferencia|efectivo (default transferencia)


class AnularPagoBody(BaseModel):
    motivo: str = Field(max_length=500)


def _resolver_destino_metodo(
    destinatario: Optional[str], metodo: Optional[str]
) -> tuple[str, str]:
    """Aplica defaults (Tincho/transferencia) y valida contra los valores admitidos.

    Pieza pura (testeable sin DB): la usa `agregar_pago`. Lanza HTTP 400 si el
    valor explícito no está en la lista permitida.
    """
    d = destinatario or DESTINATARIO_PAGO_DEFAULT
    m = metodo or METODO_PAGO_DEFAULT
    if d not in DESTINATARIOS_PAGO:
        raise HTTPException(400, f"Destinatario inválido. Usar: {', '.join(DESTINATARIOS_PAGO)}")
    if m not in METODOS_PAGO:
        raise HTTPException(400, f"Método inválido. Usar: {', '.join(METODOS_PAGO)}")
    return d, m


def _recalcular_monto_pagado(conn, pedido_id: int):
    """Recalcula monto_pagado atómicamente desde alquiler_pagos.

    Usa UPDATE con subquery (en lugar de SELECT-luego-UPDATE) para evitar
    race conditions cuando dos pagos llegan en paralelo.

    No hace commit — el caller debe commitear inmediatamente después para que
    el UPDATE no quede huérfano si falla algo posterior en la misma transacción.

    `AND NOT anulado`: un pago anulado (soft-delete, #1184) no cuenta para lo
    pagado — mismo criterio que `movimientos` con sus movimientos anulados.
    """
    conn.execute(
        """
        UPDATE alquileres
           SET monto_pagado = (
               SELECT COALESCE(SUM(monto), 0)
                 FROM alquiler_pagos
                WHERE pedido_id = %s AND NOT anulado
           )
         WHERE id = %s
        """,
        (pedido_id, pedido_id),
    )


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


def _agregar_pago(conn, id: int, data: PagoCreate, admin_email: str) -> dict:
    """Lógica de `agregar_pago`, sin FastAPI/decorators — testable directo
    (sin necesitar un `Request` real) y reusable si algún día hace falta desde
    otro lado que no sea el endpoint HTTP.

    `FOR UPDATE`: lockea la fila del pedido para toda la transacción — sin
    esto, un `agregar_pago` y un `anular_pago` concurrentes sobre el MISMO
    pedido pueden pisarse un lost-update en `monto_pagado` (el `UPDATE ...
    SET monto_pagado = (subquery sobre alquiler_pagos)` de
    `_recalcular_monto_pagado` no re-evalúa esa subquery si el segundo
    escritor ya la había planeado antes de que el primero commiteara). Con el
    lock, el segundo espera al primero — su subquery ve el estado ya
    commiteado de `alquiler_pagos`. El caller (el endpoint) hace commit.
    """
    destinatario, metodo = _resolver_destino_metodo(data.destinatario, data.metodo)
    p = conn.execute("SELECT estado FROM alquileres WHERE id=%s FOR UPDATE", (id,)).fetchone()
    if not p:
        raise HTTPException(404, "Pedido no encontrado")
    if p["estado"] in ("cancelado",):
        raise HTTPException(400, "No se pueden agregar pagos a un pedido cancelado")

    fecha = data.fecha or now_ar().date().isoformat()
    conn.execute("""
        INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (id, data.monto, data.concepto, destinatario, metodo, fecha, admin_email))

    _recalcular_monto_pagado(conn, id)
    _maybe_finalizar(conn, id)
    return _get_alquiler_detail(conn, id)


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


def _agregar_pago_combinado(conn, id: int, data: PagoCombinadoCreate, admin_email: str) -> dict:
    """Reparte `data.monto` entre `id` (el pedido principal) y sus turnos del
    Estudio vinculados (#1308, "un pago, reparte solo"): primero satura el
    resta del PRINCIPAL, después cada turno por `fecha_desde` ascendente (se
    paga primero lo que vence antes — mismo orden que ya usa
    `_turnos_vinculados` para listarlos en pantalla). Un turno `cancelado`
    queda EXCLUIDO del reparto (nunca participa, nunca bloquea el resto —
    sin este filtro, un solo turno cancelado tumbaría el pago combinado
    completo con el 400 que `_agregar_pago` ya lanza para pedidos
    cancelados). El sobrante, si lo hay tras recorrer todas las filas, se
    acredita SIEMPRE en el PRINCIPAL (nunca en el último turno tocado) — es
    la pantalla donde el admin apretó "Registrar pago" y donde lo espera ver
    (mismo criterio "no esconder el excedente" que MEMORIA 2026-07-02).

    Cada parte del reparto pasa por el `_agregar_pago` YA EXISTENTE, sin
    modificar — nunca se inventa una tabla/concepto de "pago compartido"; el
    `pedido_id` de cada fila de `alquiler_pagos` sigue siendo el real. Todo
    esto es una transacción (el caller hace commit/rollback): funciona sobre
    CUALQUIER pedido — sin turnos vinculados, `turnos` da vacío y el
    comportamiento es idéntico a `_agregar_pago` de siempre (superset
    seguro, no un camino paralelo)."""
    p = conn.execute(
        "SELECT id, monto_total, monto_pagado, estado FROM alquileres WHERE id=%s FOR UPDATE",
        (id,),
    ).fetchone()
    if not p:
        raise HTTPException(404, "Pedido no encontrado")
    if p["estado"] == "cancelado":
        raise HTTPException(400, "No se pueden agregar pagos a un pedido cancelado")

    turnos = conn.execute(
        "SELECT id, monto_total, monto_pagado FROM alquileres "
        "WHERE pedido_principal_id = %s AND estado <> 'cancelado' "
        "ORDER BY fecha_desde, id",
        (id,),
    ).fetchall()

    filas = [p, *turnos]
    restante = data.monto
    reparto: list[dict] = []
    for fila in filas:
        resta_fila = max(0, (fila["monto_total"] or 0) - (fila["monto_pagado"] or 0))
        aporte = min(restante, resta_fila)
        if aporte <= 0:
            continue
        _agregar_pago(
            conn, fila["id"],
            PagoCreate(
                monto=aporte, concepto=data.concepto, fecha=data.fecha,
                destinatario=data.destinatario, metodo=data.metodo,
            ),
            admin_email,
        )
        reparto.append({"pedido_id": fila["id"], "monto": aporte})
        restante -= aporte

    if restante > 0:
        concepto_excedente = f"{data.concepto} (excedente)" if data.concepto else "(excedente)"
        _agregar_pago(
            conn, id,
            PagoCreate(
                monto=restante, concepto=concepto_excedente, fecha=data.fecha,
                destinatario=data.destinatario, metodo=data.metodo,
            ),
            admin_email,
        )
        reparto.append({"pedido_id": id, "monto": restante, "excedente": True})

    resp = _get_alquiler_detail(conn, id)
    resp["reparto"] = reparto
    return resp


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


def _anular_pago(conn, id: int, pago_id: int, motivo: str, admin_email: str) -> dict:
    """Lógica de `anular_pago`, sin FastAPI/decorators — ver `_agregar_pago`.

    `FOR UPDATE`: mismo motivo que `_agregar_pago` — serializa contra
    cualquier otro escritor de `monto_pagado` del mismo pedido (agregar/anular
    concurrentes). El caller (el endpoint) hace commit/rollback.
    """
    if not conn.execute("SELECT id FROM alquileres WHERE id=%s FOR UPDATE", (id,)).fetchone():
        raise HTTPException(404, "Pedido no encontrado")
    actualizado = conn.execute(
        """UPDATE alquiler_pagos
           SET anulado = TRUE, anulado_por = %s, anulado_at = CURRENT_TIMESTAMP,
               anulado_motivo = %s
           WHERE id = %s AND pedido_id = %s AND NOT anulado
           RETURNING id""",
        (admin_email, motivo, pago_id, id),
    ).fetchone()
    if not actualizado:
        raise HTTPException(404, "Pago no encontrado (o ya estaba anulado)")

    _recalcular_monto_pagado(conn, id)

    # Si se anuló el pago, puede que ya no esté finalizado → revertir si aplica
    p = conn.execute("SELECT estado, monto_total, monto_pagado FROM alquileres WHERE id=%s", (id,)).fetchone()
    if p and p["estado"] == "finalizado" and (p["monto_pagado"] or 0) < (p["monto_total"] or 0):
        conn.execute("UPDATE alquileres SET estado='devuelto' WHERE id=%s", (id,))

    return _get_alquiler_detail(conn, id)


@router.post("/alquileres/{id}/pagos/{pago_id}/anular", status_code=200)
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def anular_pago(id: int, pago_id: int, data: AnularPagoBody, request: Request):
    """Anula una entrada de pago (soft-delete con motivo) y recalcula monto_pagado.

    Reemplaza el viejo `DELETE` (hard-delete, sin motivo, sin actor) — auditoría
    2026-07-02 (#1184): esta tabla alimenta todo el motor contable y no
    respetaba "la plata no se borra" que `movimientos` sí respeta. Mismo patrón
    que `anular_movimiento`. Ver `_anular_pago`."""
    admin = require_admin(request)
    motivo = (data.motivo or "").strip()
    if not motivo:
        raise HTTPException(400, "Para anular un pago hay que indicar un motivo.")
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
                   al.numero_pedido, al.cliente_nombre
              FROM alquiler_pagos ap
              JOIN alquileres al ON al.id = ap.pedido_id
             WHERE {" AND ".join(where)}
             ORDER BY ap.fecha DESC, ap.id DESC
             LIMIT %s
            """,
            (*params, limit),
        ).fetchall()
        pagos = [row_to_dict(r) for r in rows]
        total = sum((p["monto"] or 0) for p in pagos)
        return {"pagos": pagos, "total": total, "count": len(pagos)}
