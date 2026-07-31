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
from services.facturacion.repo import pedidos_con_factura_emitida
from services.pedidos_enriquecimiento import (
    _batch_count_turnos_vinculados,
    _batch_plata_turnos_vinculados,
)
from services.alquileres.queries.detalle import _pedido_tiene_contenido, _tiene_saldo_pendiente
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
    _apply_pedido_datos,
    _apply_pedido_items,
)
from routes.alquileres.transiciones import ESTADOS_QUE_RESERVAN, cambiar_estado
from services.alquileres.commands.pedido import _delete_pedido
from services.comunicacion import notificar_pedido

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
        # Tres grupos, en este orden:
        #   0. BORRADORES — son lo que se está armando ahora mismo, y desde que
        #      nacen sin número (2026-07-29) caían en el mismo saco que los
        #      registros manuales viejos: al fondo de todo, después de ~200
        #      pedidos, o sea fuera de la primera página. El dueño no los
        #      encontraba ("este borrador no me aparece en el listado").
        #   1. Los pedidos con número — la lista de siempre.
        #   2. "Registro manual" sin número — histórico, al final, como estaba.
        grupo = (
            "(CASE WHEN p.estado = 'borrador' THEN 0"
            "      WHEN p.numero_pedido IS NOT NULL THEN 1 ELSE 2 END)"
        )
        # Dentro de los borradores, el más nuevo primero (no tienen número con
        # el cual desempatar). El CASE deja NULL para todo lo demás → con NULLS
        # LAST empatan entre sí y caen al criterio de siempre, así el orden del
        # resto de la lista queda EXACTAMENTE como estaba.
        recientes_borrador = "(CASE WHEN p.estado = 'borrador' THEN p.created_at END)"
        order = (
            f"{grupo} ASC, {recientes_borrador} DESC NULLS LAST, {col} {direction} NULLS LAST"
        )
        # secundario: número descendente para desempate
        if col != "p.numero_pedido":
            order += ", p.numero_pedido DESC NULLS LAST"

        total = conn.execute(f"SELECT COUNT(*) FROM alquileres p {where}", params).fetchone()[0]
        # Los borradores se cuentan APARTE: son presupuestos rápidos, no ventas
        # (decisión del dueño) — siguen listándose junto al resto, pero el
        # "N pedidos" del header no los suma. `total` NO cambia: es la verdad de
        # la paginación (cuántas filas hay para recorrer), no un número de negocio.
        borradores = conn.execute(
            f"SELECT COUNT(*) FROM alquileres p {where} AND p.estado = 'borrador'", params
        ).fetchone()[0]
        rows  = conn.execute(
            f"SELECT p.* FROM alquileres p {where} ORDER BY {order} LIMIT %s OFFSET %s",
            params + [per_page, offset]
        ).fetchall()

        pedidos    = [row_to_dict(r) for r in rows]
        _enriquecer_pedidos_con_cliente(conn, pedidos)
        items_map  = _batch_get_alquiler_items(conn, [p["id"] for p in pedidos])

        pedido_ids = [p["id"] for p in pedidos]
        # Turnos del Estudio vinculados por pedido — para el badge de la
        # lista (el turno en sí ya no aparece como fila propia, ver `where`).
        turnos_count_map = _batch_count_turnos_vinculados(conn, pedido_ids)
        # `facturado` = tiene factura PRINCIPAL emitida. La puerta única
        # `pedidos_con_factura_emitida` excluye las notas de crédito (una NC
        # también es una fila 'emitida' → un EXISTS crudo marcaría "facturado" un
        # pedido ya anulado). Batch, sin N+1.
        facturados = pedidos_con_factura_emitida(pedido_ids, conn)

        turnos_plata_map = _batch_plata_turnos_vinculados(conn, pedido_ids)

        for p in pedidos:
            p["items"] = items_map.get(p["id"], [])
            p["facturado"] = p["id"] in facturados
            p["turnos_vinculados_count"] = turnos_count_map.get(p["id"], 0)
            # Mismo campo que expone el detalle (`_get_alquiler_detail`) — sin
            # query extra, reusa `items`/`turnos_count_map` ya batcheados.
            p["tiene_contenido"] = _pedido_tiene_contenido(p["items"], p["turnos_vinculados_count"])
            # Con los montos DE LA FILA (antes de combinar con el turno abajo)
            # — mismos que ve `cambiar_estado` (SELECT * FOR UPDATE de la fila
            # individual, sin combinar), así que el botón "Finalizar" del
            # front bloquea EXACTAMENTE lo mismo que el backend rechazaría.
            p["saldo_pendiente"] = _tiene_saldo_pendiente(p["monto_total"], p["monto_pagado"])
            # La plata del turno se SUMA a la del pedido (#1308: una sola venta).
            # `monto_total`/`monto_pagado` de la fila quedan pisados con el
            # combinado — es lo que la lista tiene que leer para no contradecir
            # al detalle, a la factura y a Cuentas por cobrar, que ya combinan.
            t_total, t_pagado = turnos_plata_map.get(p["id"], (0, 0))
            if t_total or t_pagado:
                p["monto_total"] = (p["monto_total"] or 0) + t_total
                p["monto_pagado"] = (p["monto_pagado"] or 0) + t_pagado

        return {
            "total": total,
            "borradores": borradores,
            "page": page,
            "per_page": per_page,
            "items": pedidos,
        }


@router.get("/alquileres/{id}")
def get_pedido(id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        pedido = _get_alquiler_detail(conn, id)
    return pedido


@router.delete("/alquileres/{id}", status_code=204)
@limiter.limit(ADMIN_WRITE_LIMIT)
def delete_pedido(id: int, request: Request):
    """Elimina un pedido (o un turno del Estudio vinculado). Ver `_delete_pedido`."""
    require_admin(request)
    with get_db() as conn:
        try:
            _delete_pedido(conn, id)
            conn.commit()
        except Exception:
            logger.error("Error eliminando pedido %s", id, exc_info=True)
            conn.rollback()
            raise


@router.patch("/alquileres/{id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def update_pedido(id: int, data: PedidoEstado, request: Request, background: BackgroundTasks):
    """Transición de estado admin. La legalidad de la transición, las
    validaciones de fecha/stock y la asignación de `numero_pedido` viven todas en
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
    # otro estado — no re-mandamos si ya estaba confirmado). El evento sale por la
    # capa única de comunicación: WhatsApp + el mail que lleva el `.ics` (estrategia
    # AMBOS del registro).
    # Un turno del Estudio vinculado NO manda aviso propio (#1308): es la misma
    # venta que su principal, que ya mandó el suyo — el cliente no conoce esa
    # fila. (La cascada nunca llegaba acá: llama `cambiar_estado` directo, sin
    # pasar por el endpoint; este guard cubre el PATCH manual al turno, que el
    # gate de FLOW permite cuando iguala al principal.)
    # NO se gatea por `cliente_email`: con el plan A/B el canal lo decide el
    # despachador — un cliente con WhatsApp y sin mail igual tiene que enterarse
    # (`_mail_cliente` ya se saltea solo si no hay dirección).
    if (
        pedido
        and resultado["estado_nuevo"] == "confirmado"
        and resultado["estado_anterior"] != "confirmado"
        and not es_turno_vinculado(pedido)
    ):
        notificar_pedido("pedido_confirmado", pedido, background=background)
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
    staging sin esperar al scheduler diario. Corre **las dos pasadas** (la de la
    mañana y la de la víspera), que es lo que pasa a lo largo de un día real.
    `dry_run=true` (default) NO manda nada: solo devuelve a quién le llegaría.
    Pasar `dry_run=false` manda de verdad (gateado igual por el canal activo).

    Import perezoso de `jobs.recordatorios` para no crear ciclo (ese módulo
    importa helpers de este paquete).
    """
    require_admin(request)
    from jobs.recordatorios import PASADAS, enviar_recordatorios_retiro

    with get_db() as conn:
        return {
            "dry_run": dry_run,
            "pasadas": {
                p: enviar_recordatorios_retiro(conn, pasada=p, dry_run=dry_run)
                for p in PASADAS
            },
        }
