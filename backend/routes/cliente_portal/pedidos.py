"""Ciclo del pedido del cliente (#501 — extraído del god-module `routes/cliente_portal.py`).

Crear / cancelar pedido + listar / ver detalle de los pedidos del cliente logueado.
Registra sus rutas en el router compartido del paquete `routes.cliente_portal`. Los
helpers compartidos (`require_cliente`, `_proyectar`, `_documentos_disponibles`) viven
en `core`; cancelar el pedido delega en
`services.alquileres.commands.transiciones.cambiar_estado` (única puerta de
transición de estado, admin y cliente).
"""
from typing import Optional

from fastapi import Request, HTTPException, BackgroundTasks
from pydantic import BaseModel, field_validator

from database import get_db, row_to_dict, to_datetime
from pedidos_vinculados import SIN_PRINCIPAL_SQL
from rate_limit import limiter, CLIENTE_WRITE_LIMIT
from routes.cliente_portal.core import (
    router,
    require_cliente,
    require_cliente_verificado,
    _proyectar,
    _documentos_disponibles,
    _ITEM_CAMPOS_PORTAL,
)
from services.checkout import faltan_firma_tyc, FIRMA_CHECKOUT_OBLIGATORIA
from services.finanzas_flujo.pedido import combinar_turnos_vinculados
from services.fechas import validar_rango_fechas, antelacion_insuficiente, validar_fecha_iso
from auth.stepup import has_recent_stepup


# ── Crear / cancelar pedido ───────────────────────────────────────────────────

class CartItemIn(BaseModel):
    equipo_id:      int
    cantidad:       int
    # `precio_jornada` se acepta por compatibilidad con clientes ya
    # cacheados, pero el server lo IGNORA y resuelve el precio desde
    # `equipos.precio_jornada`. El cliente nunca decide el precio
    # (ver `cliente_crear_pedido`).
    precio_jornada: int = 0

    @field_validator("cantidad")
    @classmethod
    def _v_cantidad(cls, v: int) -> int:
        # Espejo de `PedidoItem.validate_cantidad` (routes/alquileres/core.py).
        # Acá la validación vive en el PARSE → 422 limpio; sin esto, una cantidad
        # inválida explotaba recién al construir `PedidoItem` adentro del handler → 500.
        if v is None or v < 1:
            raise ValueError("cantidad debe ser >= 1")
        if v > 999:
            raise ValueError("cantidad demasiado alta (máx 999)")
        return v


class PedidoClienteCreate(BaseModel):
    fecha_desde: Optional[str] = None
    fecha_hasta: Optional[str] = None
    notas:       Optional[str] = None
    items:       list[CartItemIn] = []
    # session_id del carrito (#280 Fase 1): si viene, marcamos el carrito como
    # confirmado en carritos_activos para cerrar el funnel de conversión.
    session_id:  Optional[str] = None
    # Firma del checkout (Fase 5 #1098): fallback "Confirmo" por sesión para el cliente
    # sin passkey. La firma fuerte es la cookie `stepup` (passkey / on-the-fly), que el
    # server lee aparte (no viaja en el body). Ver el gate más abajo.
    session_confirmed: bool = False
    # #1240: a nombre de quién se factura ESTE pedido — mutuamente excluyentes,
    # NULL/NULL = perfil default de la cuenta (comportamiento de siempre).
    perfil_fiscal_id: Optional[int] = None
    productora_id: Optional[int] = None

    @field_validator("fecha_desde", "fecha_hasta")
    @classmethod
    def _v_fechas(cls, v):
        return validar_fecha_iso(v)


@router.post("/api/cliente/pedidos", status_code=201)
@limiter.limit(CLIENTE_WRITE_LIMIT)
def cliente_crear_pedido(
    data: PedidoClienteCreate, request: Request, background: BackgroundTasks,
):
    """Crea un pedido (estado 'solicitado') ligado al cliente autenticado."""
    session = require_cliente_verificado(request)
    cliente_id = session["cliente_id"]

    if not data.items:
        raise HTTPException(400, "El pedido debe tener al menos un ítem")
    if not data.fecha_desde or not data.fecha_hasta:
        raise HTTPException(400, "Elegí la fecha de retiro y de devolución")

    # Caps espejo de la UI (el cliente las tiene en el front; la API no las
    # validaba → defensa en profundidad). El rango de 120 días es límite del
    # cliente, NO del admin, por eso vive acá y no en `create_pedido`. Criterio
    # (orden + no-pasado + tope) por la fuente única `validar_rango_fechas`.
    if data.notas and len(data.notas) > 500:
        raise HTTPException(400, "Las notas no pueden superar los 500 caracteres")
    msg = validar_rango_fechas(
        data.fecha_desde, data.fecha_hasta, permitir_pasado=False, max_dias=120
    )
    if msg:
        raise HTTPException(400, msg)

    # Lead-time mínimo (#1126): backstop server-side. El portero ya lo avisa en la
    # UI antes de submitear; esto bloquea por si un cliente saltea el pre-flight.
    # Límite solo-cliente (el admin carga urgencias a mano), por eso vive acá.
    with get_db() as _conn:
        horas = antelacion_insuficiente(_conn, to_datetime(data.fecha_desde))
    if horas:
        raise HTTPException(
            422,
            f"Tu retiro es en menos de {horas} h. Por la antelación mínima no podemos "
            "confirmar el pedido online — escribinos para coordinar una urgencia.",
        )

    # Horas habilitadas de retiro/devolución (setting `horarios_retiro`).
    from routes.alquileres import _validar_horarios_habilitados
    with get_db() as _conn:
        _validar_horarios_habilitados(_conn, data.fecha_desde, data.fecha_hasta)

    # Gate de firma + T&C (Fase 5 #1098): reusa los checks cliente-scoped del portero del
    # checkout (`services/checkout`), sin re-implementarlos. `has_recent_stepup` lee la
    # cookie `stepup` (passkey / firma on-the-fly); el fallback es "Confirmo" por sesión.
    # Cableado-apagado (FIRMA_CHECKOUT_OBLIGATORIA) hasta que la UI del checkout mande la
    # señal → no rompe el flujo actual; se activa en el PR que enchufa el paso de firma.
    if FIRMA_CHECKOUT_OBLIGATORIA:
        firma_ok = has_recent_stepup(request, cliente_id) or data.session_confirmed
        with get_db() as _conn:
            faltan = faltan_firma_tyc(_conn, cliente_id, firma_ok)
        if faltan:
            raise HTTPException(422, detail={"faltan": faltan})

    # #1240: a nombre de quién se factura este pedido — mutuamente excluyentes,
    # y cada uno se valida como propio del cliente autenticado (nunca el de otro).
    if data.perfil_fiscal_id and data.productora_id:
        raise HTTPException(400, "Elegí un perfil personal O una productora, no los dos")
    with get_db() as _conn:
        if data.perfil_fiscal_id:
            propio = _conn.execute(
                "SELECT 1 FROM cliente_perfiles_fiscales WHERE id = %s AND cliente_id = %s",
                (data.perfil_fiscal_id, cliente_id),
            ).fetchone()
            if not propio:
                raise HTTPException(404, "Perfil fiscal no encontrado")
        if data.productora_id:
            vinculado = _conn.execute(
                "SELECT 1 FROM productora_miembros WHERE productora_id = %s AND cliente_id = %s",
                (data.productora_id, cliente_id),
            ).fetchone()
            if not vinculado:
                raise HTTPException(404, "Productora no encontrada")

    # Reusamos la lógica de creación del back-office para mantener una sola fuente.
    from routes.alquileres import create_pedido_retry, PedidoCreate, PedidoItem
    from services.carrito import precios_catalogo_para_reserva

    # SEGURIDAD: el cliente nunca decide el precio. La puerta del carrito
    # `precios_catalogo_para_reserva` resuelve cada precio desde el catálogo
    # (gate `visible_catalogo` + fuente única `precio_jornada_efectivo`,
    # combo-aware) y descarta lo que vino en el body; 404 si un equipo no está
    # en el catálogo público. Acá solo hacemos el handoff a `create_pedido_retry`.
    with get_db() as conn:
        precios = precios_catalogo_para_reserva(conn, data.items)

    payload = PedidoCreate(
        cliente_id=cliente_id,
        fecha_desde=data.fecha_desde,
        fecha_hasta=data.fecha_hasta,
        notas=data.notas,
        estado="solicitado",
        perfil_fiscal_id=data.perfil_fiscal_id,
        productora_id=data.productora_id,
        items=[
            PedidoItem(
                equipo_id=i.equipo_id,
                cantidad=i.cantidad,
                precio_jornada=precios[i.equipo_id],
            )
            for i in data.items
        ],
    )
    # `create_pedido_retry` reintenta ante deadlock de concurrencia (→ 503 si
    # persiste, nunca 500). Ver helper en `routes/alquileres/core.py`.
    resultado = create_pedido_retry(payload, background=background)

    # Cerrar el funnel de conversión (#280 Fase 1): marcar el carrito como
    # confirmado para que desaparezca del dashboard de carritos activos.
    if data.session_id:
        try:
            from routes.carritos import marcar_confirmado
            with get_db() as conn:
                marcar_confirmado(data.session_id, conn)
                conn.commit()
        except Exception:
            pass  # No crítico — el pedido ya se creó

    return resultado


@router.patch("/api/cliente/pedidos/{id}/cancelar")
@limiter.limit(CLIENTE_WRITE_LIMIT)
def cliente_cancelar_pedido(id: int, request: Request):
    """La legalidad de la transición (qué estados puede cancelar un cliente)
    y el auto-cancelado de solicitudes pendientes viven en
    `services.alquileres.commands.transiciones.cambiar_estado` — única puerta,
    la comparte con la transición de estado del admin."""
    session = require_cliente(request)
    cliente_id = session["cliente_id"]
    with get_db() as conn:
        # `SIN_PRINCIPAL_SQL`: un turno del Estudio vinculado no existe como
        # pedido para el cliente (#1308) — tampoco por API. Era el único write
        # que el cliente podía hacerle.
        p = conn.execute(
            f"SELECT id FROM alquileres "
            f"WHERE id = %s AND cliente_id = %s AND {SIN_PRINCIPAL_SQL}",
            (id, cliente_id),
        ).fetchone()
        if not p:
            raise HTTPException(404, "Pedido no encontrado")
        from services.alquileres.commands.transiciones import cambiar_estado
        cambiar_estado(
            conn, id, "cancelado", es_admin=False,
            actor=session.get("email") or "cliente",
        )
        conn.commit()
        return {"ok": True}


# ── Pedidos ───────────────────────────────────────────────────────────────────

@router.get("/api/cliente/pedidos")
def cliente_pedidos(request: Request):
    session = require_cliente(request)
    cliente_id = session["cliente_id"]
    with get_db() as conn:
        # `SIN_PRINCIPAL_SQL`: los turnos del Estudio vinculados a un pedido de
        # alquiler NO son pedidos del cliente (#1308) — son la misma venta que su
        # principal, que más abajo absorbe su plata vía `combinar_turnos_vinculados`.
        # Sin esto el cliente veía dos cards, con dos números y dos totales.
        # `estado != 'borrador'`: un borrador es un escenario hipotético del admin
        # (puede tener un cliente real asignado mientras se prueba algo) — el
        # cliente no debe verlo nunca, ni por accidente, hasta que salga de ahí.
        pedidos = conn.execute(f"""
            SELECT id, numero_pedido, estado, fecha_desde, fecha_hasta,
                   monto_total, monto_pagado, descuento_pct, descuento_jornadas_pct,
                   notas, created_at, perfil_fiscal_id, productora_id
            FROM alquileres
            WHERE cliente_id = %s AND estado != 'borrador' AND {SIN_PRINCIPAL_SQL}
            ORDER BY created_at DESC NULLS LAST, numero_pedido DESC
        """, (cliente_id,)).fetchall()

        from routes.alquileres import _batch_get_alquiler_items
        items_por_pedido = _batch_get_alquiler_items(conn, [p["id"] for p in pedidos])

        from services.facturacion.repo import pedidos_con_factura_emitida
        pedidos_con_factura = pedidos_con_factura_emitida(
            [p["id"] for p in pedidos], conn
        )

        # Perfil fiscal DEFAULT del cliente, una sola vez para toda la lista (no
        # por pedido) — `_enriquecer_pedido_con_total` lo respeta si ya viene
        # seteado. #1240: algunos pedidos puntuales pueden haber elegido una
        # productora o un perfil personal alternativo — se resuelven esos en
        # batch (2 queries más, no N+1) para no perder ese override en el
        # listado.
        perfil_row = conn.execute(
            "SELECT perfil_impuestos FROM clientes WHERE id = %s", (cliente_id,)
        ).fetchone()
        perfil_impuestos = row_to_dict(perfil_row).get("perfil_impuestos") if perfil_row else None

        perfil_fiscal_ids = list({p["perfil_fiscal_id"] for p in pedidos if p["perfil_fiscal_id"]})
        productora_ids = list({p["productora_id"] for p in pedidos if p["productora_id"]})
        perfil_impuestos_por_perfil_id: dict[int, str] = {}
        perfil_impuestos_por_productora_id: dict[int, str] = {}
        if perfil_fiscal_ids:
            ph = ",".join(["%s"] * len(perfil_fiscal_ids))
            rows = conn.execute(
                f"SELECT id, perfil_impuestos FROM cliente_perfiles_fiscales WHERE id IN ({ph})",
                perfil_fiscal_ids,
            ).fetchall()
            perfil_impuestos_por_perfil_id = {r["id"]: r["perfil_impuestos"] for r in rows}
        if productora_ids:
            ph = ",".join(["%s"] * len(productora_ids))
            rows = conn.execute(
                f"SELECT id, perfil_impuestos FROM productoras WHERE id IN ({ph})",
                productora_ids,
            ).fetchall()
            perfil_impuestos_por_productora_id = {r["id"]: r["perfil_impuestos"] for r in rows}

        from routes.alquileres import _enriquecer_pedido_con_total

        result = []
        for p in pedidos:
            d = row_to_dict(p)
            d["cliente_id"] = cliente_id
            if p["productora_id"] and p["productora_id"] in perfil_impuestos_por_productora_id:
                d["cliente_perfil_impuestos"] = perfil_impuestos_por_productora_id[p["productora_id"]]
            elif p["perfil_fiscal_id"] and p["perfil_fiscal_id"] in perfil_impuestos_por_perfil_id:
                d["cliente_perfil_impuestos"] = perfil_impuestos_por_perfil_id[p["perfil_fiscal_id"]]
            else:
                d["cliente_perfil_impuestos"] = perfil_impuestos
            d["items"] = [
                _proyectar(it, _ITEM_CAMPOS_PORTAL)
                for it in items_por_pedido.get(p["id"], [])
            ]

            pagos = conn.execute("""
                SELECT monto, concepto, fecha
                FROM alquiler_pagos
                WHERE pedido_id = %s AND NOT anulado
                ORDER BY fecha
            """, (p["id"],)).fetchall()
            d["pagos"] = [row_to_dict(pg) for pg in pagos]

            # Solicitudes de modificación que el cliente debe ver — sólo las
            # de aprobación (las `directo` son auditoría interna del autosave
            # en presupuesto, no relevantes para el cliente).
            solic = conn.execute("""
                SELECT id, mensaje, estado, respuesta, resolved_by,
                       resolved_at, created_at
                FROM solicitudes_modificacion
                WHERE pedido_id = %s AND tipo = 'aprobacion'
                ORDER BY created_at DESC
            """, (p["id"],)).fetchall()
            d["solicitudes"] = [row_to_dict(s) for s in solic]

            d["documentos_disponibles"] = {
                **_documentos_disponibles(d.get("estado", "")),
                "factura": p["id"] in pedidos_con_factura,
            }

            # Mismo desglose canónico que el detalle (#496) — antes esta lista
            # no lo traía y podía mostrar 0%/$0 de descuento cuando ganaba el
            # de jornadas (asimetría encontrada en la Fase B de #1219).
            _enriquecer_pedido_con_total(conn, d)
            # ...y después la plata de los turnos del Estudio vinculados: el
            # cliente ve UN pedido con UN total (#1308). Sin esto, ocultar la
            # fila del turno le escondería su plata (el total del portal
            # quedaría por debajo de lo que realmente debe).
            combinar_turnos_vinculados(conn, d)

            result.append(d)
        return result


@router.get("/api/cliente/pedidos/{id}")
def cliente_pedido_detalle(id: int, request: Request):
    session = require_cliente(request)
    cliente_id = session["cliente_id"]
    with get_db() as conn:
        # `SIN_PRINCIPAL_SQL` → 404 para un turno del Estudio vinculado (#1308):
        # deja de tener página, documentos y pagos propios de cara al cliente.
        # `estado != 'borrador'` → mismo 404 para un borrador (ver `cliente_pedidos`
        # más arriba): el cliente no debe poder ver un escenario hipotético del
        # admin, ni siquiera si adivina/guarda el `id`.
        pedido = conn.execute(f"""
            SELECT id, numero_pedido, estado, fecha_desde, fecha_hasta,
                   monto_total, monto_pagado, descuento_pct,
                   descuento_jornadas_pct, cliente_id, notas, created_at,
                   perfil_fiscal_id, productora_id
            FROM alquileres
            WHERE id = %s AND cliente_id = %s AND estado != 'borrador' AND {SIN_PRINCIPAL_SQL}
        """, (id, cliente_id)).fetchone()
        if not pedido:
            raise HTTPException(404, "Pedido no encontrado")

        d = row_to_dict(pedido)

        from routes.alquileres import _get_alquiler_items
        d["items"] = [
            _proyectar(it, _ITEM_CAMPOS_PORTAL) for it in _get_alquiler_items(conn, id)
        ]

        pagos = conn.execute("""
            SELECT monto, concepto, fecha FROM alquiler_pagos
            WHERE pedido_id = %s AND NOT anulado ORDER BY fecha
        """, (id,)).fetchall()
        d["pagos"] = [row_to_dict(p) for p in pagos]

        solicitudes = conn.execute("""
            SELECT id, mensaje, estado, respuesta, resolved_by,
                   resolved_at, created_at
            FROM solicitudes_modificacion
            WHERE pedido_id = %s AND tipo = 'aprobacion'
            ORDER BY created_at DESC
        """, (id,)).fetchall()
        d["solicitudes"] = [row_to_dict(s) for s in solicitudes]

        from services.facturacion.repo import get_factura_principal_emitida
        d["documentos_disponibles"] = {
            **_documentos_disponibles(d.get("estado", "")),
            "factura": get_factura_principal_emitida(id, conn) is not None,
        }

        # Desglose canónico (neto/IVA/total con IVA) vía services/precios.
        # Mismo helper que admin/PDF/carrito → totales coinciden en las 4
        # superficies (#496). El frontend del portal lo lee directo.
        from routes.alquileres import _enriquecer_pedido_con_total
        _enriquecer_pedido_con_total(conn, d)
        # Un pedido, un total: absorbe la plata de sus turnos del Estudio (#1308),
        # igual que la lista y que la factura.
        combinar_turnos_vinculados(conn, d)

        return d


