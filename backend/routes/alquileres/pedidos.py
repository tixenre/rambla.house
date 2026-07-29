"""Endpoints HTTP de pedidos (#501 — extraído del god-module `routes/alquileres.py`).

Capa de transporte del ciclo de vida del pedido: alta (admin), listado, detalle,
baja, transición de estado y edición de datos/ítems. La lógica reusable
(`create_pedido`, `_apply_pedido_*`, enriquecimiento, recálculo de total) vive en
`core` y se importa; acá quedan solo los handlers que registran sus rutas sobre el
router compartido del paquete `routes.alquileres`.

Incluye también el disparador on-demand de recordatorios de retiro (mudado de
`disponibilidad.py`, issue #1254 — no tenía relación temática con disponibilidad;
es un trigger admin sobre el ciclo de vida del pedido, calza acá).
"""
import logging
from typing import Optional

from fastapi import Request, HTTPException, Query, BackgroundTasks

from database import get_db, row_to_dict
from auth.guards import require_admin
from busqueda import construir
from pedidos_vinculados import SIN_PRINCIPAL_SQL, es_turno_vinculado
from rate_limit import limiter, ADMIN_WRITE_LIMIT
from services.email import send_email
from services.facturacion.repo import pedidos_con_factura_emitida
from services.pedidos_enriquecimiento import _batch_count_turnos_vinculados
from reservas import validar_stock as _check_stock
from routes.alquileres.core import (
    router,
    PedidoCreate,
    PedidoEstado,
    PedidoDatos,
    PedidoItemUpdate,
    create_pedido_retry,
    _get_alquiler_detail,
    _batch_get_alquiler_items,
    _enriquecer_pedidos_con_cliente,
    _pedido_email_context,
    _ics_adjunto_pedido,
    _apply_pedido_datos,
    _apply_pedido_items,
)
from routes.alquileres.transiciones import ESTADOS_QUE_RESERVAN, cambiar_estado

logger = logging.getLogger(__name__)


SORT_COLS = {
    "numero":  "p.numero_pedido",
    "cliente": "p.cliente_nombre",
    "monto":   "p.monto_total",
    "fecha":   "p.fecha_desde",
    "estado":  "p.estado",
}


@router.post("/alquileres", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
def create_pedido_endpoint(data: PedidoCreate, request: Request, background: BackgroundTasks):
    """Endpoint admin para crear pedido. La lógica está en `create_pedido`,
    así el portal cliente (cliente_portal.py) la reutiliza sin pasar por admin guard."""
    require_admin(request)
    return create_pedido_retry(data, background=background, es_admin=True)


@router.get("/alquileres")
def list_pedidos(
    request: Request,
    estado:   Optional[str] = Query(None),
    fuente:   Optional[str] = Query(None),
    q:        Optional[str] = Query(None),
    con_saldo: Optional[bool] = Query(None, description="Si true, solo pedidos con saldo pendiente (monto_pagado < monto_total)"),
    page:     int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    sort_by:  Optional[str] = Query(None),
    sort_dir: Optional[str] = Query("desc"),
):
    require_admin(request)
    offset = (page - 1) * per_page
    params: list = []
    # Un turno del Estudio vinculado (`pedido_principal_id`) no es una venta
    # propia — se administra desde "Turnos del Estudio" en la página de su
    # principal (#1308). Sin este filtro aparecía como fila propia acá,
    # duplicando la venta a la vista del admin.
    where  = f"WHERE {SIN_PRINCIPAL_SQL}"

    with get_db() as conn:
        if estado:
            where += " AND p.estado = %s"
            params.append(estado)
        if fuente:
            where += " AND p.fuente = %s"
            params.append(fuente)
        if q:
            # Búsqueda por NOMBRE vía el motor único (backend/busqueda): sin
            # importar mayúsculas/minúsculas, sin tildes ("jose"→"José"),
            # multi-palabra y tolerante a typos. Antes era un `LIKE` crudo —
            # case-SENSITIVE en Postgres — que no encontraba "Tincho" buscando
            # "tinc". Se buscan dos campos de nombre: la foto congelada del
            # pedido (`p.cliente_nombre`) y el nombre ACTUAL del cliente (en
            # vivo → un dato corregido también tiene que encontrar el pedido).
            # El número de pedido es un id, no texto: se matchea aparte por
            # substring exacto (OR), no por el motor fuzzy.
            # El nombre en vivo prefiere RENAPER (nombre_legal → nombre_validado):
            # lo que se VE en la lista puede ser el nombre legal, no el ingresado.
            # Buscamos la UNIÓN (base + renaper) para matchear tanto lo mostrado
            # como lo que el admin recuerde haber cargado; el motor hace OR entre
            # campos, así que sobra-match antes que falte-match.
            pred = construir(
                [
                    "p.cliente_nombre",
                    "(SELECT COALESCE(c.nombre, '') || ' ' || COALESCE(c.apellido, '')"
                    "        || ' ' || COALESCE(c.nombre_renaper, '')"
                    "        || ' ' || COALESCE(c.apellido_renaper, '')"
                    " FROM clientes c WHERE c.id = p.cliente_id)",
                ],
                q,
            )
            like_num = f"%{q}%"
            if pred.activo:
                where += f" AND (({pred.where}) OR CAST(p.numero_pedido AS TEXT) LIKE %s)"
                params += pred.where_params + [like_num]
            else:
                where += " AND CAST(p.numero_pedido AS TEXT) LIKE %s"
                params.append(like_num)
        if con_saldo:
            # Pedidos con saldo > 0 y no cancelados. Borrador y presupuesto no
            # aplican porque todavía no se cobra; cancelado tampoco.
            where += " AND (COALESCE(p.monto_pagado, 0) < COALESCE(p.monto_total, 0))"
            where += " AND p.estado IN ('confirmado','retirado','devuelto','finalizado')"

        col = SORT_COLS.get(sort_by, "p.numero_pedido")
        direction = "ASC" if sort_dir == "asc" else "DESC"
        # Poner "Registro manual" (sin número de pedido) al final.
        has_numero = "(p.numero_pedido IS NOT NULL)"
        order = f"{has_numero} DESC, {col} {direction} NULLS LAST"
        # secundario: número descendente para desempate
        if col != "p.numero_pedido":
            order += ", p.numero_pedido DESC NULLS LAST"

        total = conn.execute(f"SELECT COUNT(*) FROM alquileres p {where}", params).fetchone()[0]
        rows  = conn.execute(
            f"SELECT p.* FROM alquileres p {where} ORDER BY {order} LIMIT %s OFFSET %s",
            params + [per_page, offset]
        ).fetchall()

        pedidos    = [row_to_dict(r) for r in rows]
        _enriquecer_pedidos_con_cliente(conn, pedidos)
        items_map  = _batch_get_alquiler_items(conn, [p["id"] for p in pedidos])

        # Pedidos con solicitud de modificación pendiente — para badge en UI.
        pedido_ids = [p["id"] for p in pedidos]
        # Turnos del Estudio vinculados por pedido — para el badge de la
        # lista (el turno en sí ya no aparece como fila propia, ver `where`).
        turnos_count_map = _batch_count_turnos_vinculados(conn, pedido_ids)
        # `facturado` = tiene factura PRINCIPAL emitida. La puerta única
        # `pedidos_con_factura_emitida` excluye las notas de crédito (una NC
        # también es una fila 'emitida' → un EXISTS crudo marcaría "facturado" un
        # pedido ya anulado). Batch, sin N+1.
        facturados = pedidos_con_factura_emitida(pedido_ids, conn)
        pendientes: set[int] = set()
        if pedido_ids:
            ph = ",".join(["%s"] * len(pedido_ids))
            for r in conn.execute(
                f"""SELECT DISTINCT pedido_id FROM solicitudes_modificacion
                    WHERE estado = 'pendiente' AND pedido_id IN ({ph})""",
                pedido_ids,
            ).fetchall():
                pendientes.add(r["pedido_id"])

        for p in pedidos:
            p["items"] = items_map.get(p["id"], [])
            p["tiene_solicitud_pendiente"] = p["id"] in pendientes
            p["facturado"] = p["id"] in facturados
            p["turnos_vinculados_count"] = turnos_count_map.get(p["id"], 0)

        return {"total": total, "page": page, "per_page": per_page, "items": pedidos}


@router.get("/alquileres/{id}")
def get_pedido(id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        pedido = _get_alquiler_detail(conn, id)
    return pedido


@router.delete("/alquileres/{id}", status_code=204)
@limiter.limit(ADMIN_WRITE_LIMIT)
def delete_pedido(id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        try:
            if not conn.execute("SELECT id FROM alquileres WHERE id=%s", (id,)).fetchone():
                raise HTTPException(404, "Pedido no encontrado")
            # Borrar ítems, pagos e historicos asociados (FK cascade si está activada, pero por las dudas)
            conn.execute("DELETE FROM alquiler_items  WHERE pedido_id=%s", (id,))
            conn.execute("DELETE FROM alquiler_pagos  WHERE pedido_id=%s", (id,))
            conn.execute("DELETE FROM alquileres       WHERE id=%s",        (id,))
            conn.commit()
        except Exception:
            logger.error("Error eliminando pedido %s", id, exc_info=True)
            conn.rollback()
            raise


@router.patch("/alquileres/{id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def update_pedido(id: int, data: PedidoEstado, request: Request, background: BackgroundTasks):
    """Transición de estado admin. La legalidad de la transición, las
    validaciones de fecha/stock, la asignación de `numero_pedido` y el
    auto-cancelado de solicitudes pendientes viven todas en
    `transiciones.cambiar_estado` — ver ese módulo para el grafo completo.
    Acá solo queda el transporte HTTP + el mail de confirmación."""
    require_admin(request)

    with get_db() as conn:
        try:
            resultado = cambiar_estado(conn, id, data.estado, es_admin=True, actor="system")
            conn.commit()
            pedido = _get_alquiler_detail(conn, id)
            # Bolt-on, mismo patrón que `promo_advertencia`: si `id` es un
            # pedido principal, la cascada a sus turnos vinculados (#1308) ya
            # corrió dentro de `cambiar_estado` — acá solo se propaga el
            # resultado para que el admin vea cuál turno no pudo avanzar.
            pedido["turnos_vinculados_sin_avanzar"] = resultado.get("turnos_vinculados_sin_avanzar", [])
        except Exception:
            logger.error("Error actualizando estado del pedido %s", id, exc_info=True)
            conn.rollback()
            raise

    # Notif al cliente cuando pasamos a 'confirmado' (solo si veníamos de
    # otro estado — no re-mandamos si ya estaba confirmado).
    # Un turno del Estudio vinculado NO manda mail propio (#1308): es la misma
    # venta que su principal, que ya mandó el suyo — el cliente no conoce esa
    # fila. (La cascada nunca llegaba acá: llama `cambiar_estado` directo, sin
    # pasar por el endpoint; este guard cubre el PATCH manual al turno, que el
    # gate de FLOW permite cuando iguala al principal.)
    if (
        pedido
        and resultado["estado_nuevo"] == "confirmado"
        and resultado["estado_anterior"] != "confirmado"
        and pedido.get("cliente_email")
        and not es_turno_vinculado(pedido)
    ):
        ctx = _pedido_email_context(pedido)
        background.add_task(
            send_email, "pedido_confirmado_cliente",
            pedido["cliente_email"], ctx, pedido.get("id"),
            attachments=_ics_adjunto_pedido(pedido),
        )
    return pedido


@router.patch("/alquileres/{id}/datos")
@limiter.limit(ADMIN_WRITE_LIMIT)
def update_pedido_datos(id: int, data: PedidoDatos, request: Request):
    require_admin(request)
    with get_db() as conn:
        try:
            pedido = _apply_pedido_datos(conn, id, data, es_admin=True)
            conn.commit()
            return pedido
        except Exception:
            logger.error("Error actualizando datos del pedido %s", id, exc_info=True)
            conn.rollback()
            raise


@router.put("/alquileres/{id}/items")
@limiter.limit(ADMIN_WRITE_LIMIT)
def update_alquiler_items(id: int, data: PedidoItemUpdate, request: Request):
    require_admin(request)
    with get_db() as conn:
        try:
            pedido = _apply_pedido_items(conn, id, data.items)

            # Si el pedido está en estado que reserva stock, validar después de
            # aplicar los nuevos items. Sin esto el admin podía sumar cantidades
            # que excedieran el stock disponible y crear doble booking silencioso.
            # `ESTADOS_QUE_RESERVAN` es el mismo set que usa el grafo de
            # transiciones (`transiciones.py`) — una sola fuente.
            p = conn.execute(
                "SELECT estado, fecha_desde, fecha_hasta FROM alquileres WHERE id=%s", (id,)
            ).fetchone()
            if (
                p["estado"] in ESTADOS_QUE_RESERVAN
                and p["fecha_desde"] and p["fecha_hasta"]
            ):
                problemas = _check_stock(conn, id, p["fecha_desde"], p["fecha_hasta"])
                if problemas:
                    raise HTTPException(409, "Sin stock: " + "; ".join(problemas))

            conn.commit()
            return pedido
        except Exception:
            logger.error("Error actualizando items del pedido %s", id, exc_info=True)
            conn.rollback()
            raise


@router.post("/admin/recordatorios/retiro/run")
@limiter.limit(ADMIN_WRITE_LIMIT)
def run_recordatorios_retiro(request: Request, dry_run: bool = Query(True)):
    """Dispara on-demand el barrido de recordatorios de retiro — para probar en
    staging sin esperar al scheduler diario. `dry_run=true` (default) NO manda
    nada: solo devuelve qué pedidos recibirían el recordatorio mañana. Pasar
    `dry_run=false` manda de verdad (gateado igual por el canal de mail activo).

    Import perezoso de `jobs.recordatorios` para no crear ciclo (ese módulo
    importa helpers de este paquete).
    """
    require_admin(request)
    from jobs.recordatorios import enviar_recordatorios_retiro

    with get_db() as conn:
        return enviar_recordatorios_retiro(conn, dry_run=dry_run)
