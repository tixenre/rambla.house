"""Cotización canónica del carrito (#501 — extraído del god-module `routes/alquileres.py`).

Fuente única del total del carrito: el front manda solo `items` (equipo_id +
cantidad) y fechas; el backend pone los precios (de `equipos`), el perfil/descuento
del cliente y devuelve el desglose de `services.precios.calcular_total`. Registra su
ruta sobre el router compartido del paquete `routes.alquileres`.
"""
from typing import Optional

from fastapi import Request
from pydantic import BaseModel, field_validator

from database import get_db, to_datetime
from rate_limit import limiter
from auth.guards import is_admin_email
from auth.session import dev_bypass_enabled, get_session
from services.precios import (
    bruto_linea,
    calcular_total,
    jornadas_periodo,
    precio_jornada_efectivo,
    tipos_equipo_batch,
)
from descuentos.queries.decision import resolver_origen_pedido_monto
from descuentos.queries.jornadas import obtener_descuento_jornadas
from services.facturacion.repo import factura_c_vigente
from routes.alquileres.core import router, _resolver_descuentos_snapshot_o_vivo
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

    El front NO calcula el total: manda solo `items` (equipo_id + cantidad) y,
    si las hay, las fechas. El backend pone TODO lo demás:
    - el `precio_jornada` de cada equipo (de la tabla `equipos`, no se confía
      en lo que mande el front),
    - el perfil tributario y el descuento del cliente (cliente logueado → el
      suyo; admin → el del `cliente_id` que pase; anónimo → `consumidor_final`),
    - el descuento por jornadas.

    **Sin fechas = modo estimado:** jornadas=1, sin descuentos ni IVA (es solo
    referencia de precio mientras el cliente no eligió período). Replica el
    comportamiento histórico del carrito en armado.

    Devuelve el desglose de `services.precios.calcular_total` + `descuento_origen`
    y `subtotal_por_jornada` (para el UI), de modo que el front muestre los
    números tal cual. Reemplaza el cálculo duplicado del front
    (`src/lib/cart-total.ts`). Ver #617.
    """
    with get_db() as conn:
        # Jornadas: misma fórmula única (ceil/24h). Sin fechas → 1.
        d0 = to_datetime(data.fecha_desde) if data.fecha_desde else None
        d1 = to_datetime(data.fecha_hasta) if data.fecha_hasta else None
        jornadas = jornadas_periodo(d0, d1)
        tiene_fechas = bool(d0 and d1)

        session = get_session(request)
        # Mismo criterio que `require_admin` (auth/guards.py): el bypass de
        # dev (ADMIN_BYPASS_AUTH=1, nunca en prod) también cuenta como admin
        # acá — si no, el preview en vivo ignora el override de descuento
        # aunque el guardado (que sí pasa por require_admin) lo haya aceptado.
        es_admin = dev_bypass_enabled() or bool(session and is_admin_email(session.get("email")))
        respetar_precio_item = es_admin and bool(data.respetar_precio_item)

        # Precios desde el backend. Equipos inexistentes/eliminados se ignoran
        # (cotización best-effort: el carrito puede tener algo que ya no está).
        # Fetch por-ítem (lookup por PK indexada): se revirtió el batch `IN (...)`
        # de #643 que devolvía precios_map vacío en prod → total $0 (regresión).
        # `tipos_equipo_batch` (solo id+tipo, query aparte) SÍ va en batch — no
        # toca el precio, resuelve `es_combo` para el descuento no-acumulable
        # (Fase C-3, #1219).
        tipos = tipos_equipo_batch(
            conn, [it.equipo_id for it in data.items if it.equipo_id is not None]
        )
        items_para_total = []
        for it in data.items:
            if it.cantidad <= 0:
                continue
            # Línea personalizada (#805): no es del catálogo → su precio y modo de
            # cobro los pone el front (el admin la edita libre, igual que ya confía
            # el precio editable por línea en PUT /items). No reserva stock.
            if it.equipo_id is None:
                items_para_total.append({
                    "equipo_id": None,
                    "cantidad": it.cantidad,
                    "precio_jornada": int(it.precio_jornada or 0),
                    "cobro_modo": it.cobro_modo or "jornada",
                })
                continue
            # Admin editando un pedido existente (`respetar_precio_item`): usa el
            # precio de línea que manda el front (el snapshot congelado del
            # pedido, editable por el admin) en vez de recotizar contra el
            # catálogo — así el total "en vivo" del editor coincide siempre con
            # el que persiste `_recalcular_total_pedido` al guardar.
            if respetar_precio_item and it.precio_jornada is not None:
                precio = int(it.precio_jornada)
            else:
                # Precio efectivo por jornada (combo → derivado de componentes
                # C3 #635; kit/simple → su precio propio), fuente única.
                precio = precio_jornada_efectivo(conn, it.equipo_id)
                if precio is None:
                    continue
            items_para_total.append({
                "equipo_id": it.equipo_id,
                "cantidad": it.cantidad,
                "precio_jornada": precio,
                # Antes hardcodeado a "jornada": un ítem de catálogo con
                # cobro_modo='fijo' persistido (ej. el centinela del Estudio en
                # un pedido de taller) se multiplicaba igual por las jornadas
                # del rango — para un taller (rango = mes contable completo)
                # esto inflaba el "Desglose"/"Cobranza" del editor a un
                # múltiplo absurdo del monto_total real. El front ya manda el
                # cobro_modo real de la línea junto con `precio_jornada`
                # cuando `respetar_precio_item` (mismo `if` de arriba,
                # `lib/cotizacion.ts`); sin ese contexto (carrito público,
                # cotización nueva) no lo manda y cae al default de siempre.
                "cobro_modo": it.cobro_modo or "jornada",
                "es_combo": tipos.get(it.equipo_id) == "combo",
            })
        subtotal_por_jornada = sum(
            it["precio_jornada"] * it["cantidad"] for it in items_para_total
        )

        # Perfil tributario + descuento del cliente. Solo en modo firme (con
        # fechas): sin fechas es un estimado sin IVA ni descuentos.
        perfil = None
        descuento_cliente_pct = 0.0
        descuento_jornadas_pct = 0.0
        descuento_manual_pct = 0.0
        descuento_manual_tipo = "pct"
        descuento_manual_monto = 0.0
        # Definido acá (no solo dentro de `if tiene_fechas:`) para que el chequeo de
        # Factura C más abajo pueda leerlo sin importar el modo — sin fechas nunca
        # hay pedido congelado, así que `factura_c_vigente` simplemente no corre.
        pedido_congelado = None
        if tiene_fechas:
            # ¿El preview es el editor de un pedido con la plata YA congelada?
            # Entonces el descuento (cliente + jornadas) sale del MISMO snapshot
            # que persiste el guardado (`_resolver_descuentos_snapshot_o_vivo`),
            # NO en vivo — si no, el total del editor mostraría un descuento
            # distinto al de `monto_total` / la lista de pedidos (MEMORIA
            # 2026-06-06 "plata congelada"). El perfil fiscal (IVA) sí sigue en
            # vivo. Presupuesto (o sin `pedido_id`) → flujo en vivo de siempre.
            if es_admin and data.pedido_id:
                pedido_congelado = conn.execute(
                    "SELECT estado, cliente_id, descuento_jornadas_pct, "
                    "descuento_cliente_pct, perfil_fiscal_id, productora_id "
                    "FROM alquileres WHERE id=%s",
                    (data.pedido_id,),
                ).fetchone()
                if pedido_congelado and pedido_congelado["estado"] == "solicitado":
                    pedido_congelado = None  # presupuesto sigue el descuento en vivo
            # ¿Para qué cliente se cotiza?
            #   - Admin (back-office): SIEMPRE el cliente del pedido (`data.cliente_id`),
            #     nunca la ficha de la propia sesión. La admin-ness la da el EMAIL
            #     (`require_admin`/`is_admin_email`), no el `role` — un dueño que se
            #     logueó por el portal de cliente tiene una sesión `role="cliente"` +
            #     su propio `cliente_id` Y además es admin. Con la precedencia vieja
            #     (rama `role=="cliente"` primero) el builder cotizaba con el descuento
            #     de la ficha del PROPIO admin para TODOS los pedidos, no la del pedido
            #     → "descuento fantasma" (#1231). El camino que PERSISTE la plata
            #     (`_recalcular_total_pedido`) ya usaba el cliente del pedido, así que
            #     esto era solo el preview mintiendo, no datos corruptos.
            #   - Cliente puro (portal): su propia ficha.
            #   - Anónimo (sin sesión): sin descuento de cliente.
            target_cliente_id = None
            es_sesion_cliente = False
            if es_admin:
                target_cliente_id = data.cliente_id
            elif session and session.get("role") == "cliente" and session.get("cliente_id"):
                target_cliente_id = session["cliente_id"]
                es_sesion_cliente = True
            if target_cliente_id:
                c = conn.execute(
                    "SELECT perfil_impuestos, descuento FROM clientes WHERE id=%s",
                    (target_cliente_id,),
                ).fetchone()
                if c:
                    perfil = c["perfil_impuestos"]
                    # Congelado: el descuento sale del snapshot (más abajo), no
                    # del vivo. El perfil (IVA) sí es en vivo siempre.
                    if pedido_congelado is None:
                        descuento_cliente_pct = c["descuento"] or 0.0
                # #1240: solo la sesión cliente puede elegir facturar a nombre de
                # un perfil personal alternativo o una productora (el admin no
                # manda estos campos para el pedido de otro cliente).
                # `_resolver_datos_fiscales_pedido` scopea `perfil_fiscal_id` por
                # `cliente_id` sola, pero NO valida membership de `productora_id`
                # (asume que el caller ya lo hizo, como sí hace la creación real
                # del pedido) — acá se valida explícitamente antes de usarlo, para
                # no dejar que cualquier sesión cliente cotice con el perfil
                # fiscal de una productora ajena solo adivinando su id.
                productora_id_valida = None
                if es_sesion_cliente and data.productora_id:
                    vinculado = conn.execute(
                        "SELECT 1 FROM productora_miembros WHERE productora_id = %s AND cliente_id = %s",
                        (data.productora_id, target_cliente_id),
                    ).fetchone()
                    if vinculado:
                        productora_id_valida = data.productora_id
                if es_sesion_cliente and (data.perfil_fiscal_id or productora_id_valida):
                    from services.pedidos_enriquecimiento import _resolver_datos_fiscales_pedido

                    fiscal = _resolver_datos_fiscales_pedido(
                        conn, target_cliente_id, data.perfil_fiscal_id, productora_id_valida
                    )
                    if fiscal.get("perfil_impuestos"):
                        perfil = fiscal["perfil_impuestos"]
            # Pedido YA EXISTENTE que quedó atado a un perfil fiscal alternativo o
            # productora (selector "Facturar a nombre de" del checkout, #1240,
            # columnas `perfil_fiscal_id`/`productora_id` de `alquileres`) — a
            # diferencia del bloque de arriba (que solo confía en `data.perfil_fiscal_id`/
            # `data.productora_id` cuando los manda una SESIÓN DE CLIENTE, nunca un admin
            # cotizando para el cliente de otro), acá se lee lo que el PROPIO PEDIDO ya
            # tiene persistido — no hay nada que validar de membership, ya se validó
            # cuando se guardó. Sin esto, el admin editando un pedido ya facturado contra
            # un perfil RI seguía viendo el perfil default de la cuenta (a menudo
            # Consumidor Final / sin perfil) → "Desglose"/"Cobranza" mostraban un total
            # SIN IVA mientras la factura real (`services.finanzas_flujo.pedido.
            # desglose_de_pedido`, que sí resuelve esto) facturaba con IVA — dos totales
            # del mismo pedido que no podían coincidir. Mismo helper, misma fuente única.
            if pedido_congelado and (
                pedido_congelado["perfil_fiscal_id"] or pedido_congelado["productora_id"]
            ):
                from services.pedidos_enriquecimiento import _resolver_datos_fiscales_pedido

                fiscal_pedido = _resolver_datos_fiscales_pedido(
                    conn,
                    pedido_congelado["cliente_id"],
                    pedido_congelado["perfil_fiscal_id"],
                    pedido_congelado["productora_id"],
                )
                if fiscal_pedido.get("perfil_impuestos"):
                    perfil = fiscal_pedido["perfil_impuestos"]
            # Override MANUAL del admin (lo edita en vivo en el builder del
            # pedido) — jerarquía (Fase C-1, #1219): gana OUTRIGHT sobre
            # cliente/jornadas, ya NO reemplaza el descuento del cliente para
            # que compita por tamaño. Fase C-2 (#1219): el override puede ser
            # % (de siempre) o $ fijo, mismo campo de la UI.
            if es_admin and data.descuento_pct:
                descuento_manual_pct = data.descuento_pct
            if es_admin and data.descuento_manual_tipo:
                descuento_manual_tipo = data.descuento_manual_tipo
            if es_admin and data.descuento_manual_monto:
                descuento_manual_monto = data.descuento_manual_monto
            if pedido_congelado is None:
                descuento_jornadas_pct = obtener_descuento_jornadas(conn, jornadas)
            else:
                # Pedido no-presupuesto: descuento (jornadas + cliente) del MISMO
                # snapshot que la persistencia → el editor no puede divergir de
                # `monto_total`. El override manual (arriba) sí sigue en vivo.
                descuento_jornadas_pct, descuento_cliente_pct = (
                    _resolver_descuentos_snapshot_o_vivo(conn, pedido_congelado, jornadas)
                )

        desglose = calcular_total(
            items=items_para_total,
            jornadas=jornadas,
            descuento_cliente_pct=descuento_cliente_pct,
            descuento_jornadas_pct=descuento_jornadas_pct,
            descuento_manual_pct=descuento_manual_pct,
            descuento_manual_tipo=descuento_manual_tipo,
            descuento_manual_monto=descuento_manual_monto,
            perfil_impuestos=perfil,
        )

        # Si el pedido YA tiene una Factura C emitida, el cliente NO va a pagar el
        # 21% que su perfil fiscal sugeriría — un emisor Monotributo nunca lo suma
        # (2026-07-27). Sin esto, el Desglose/Cobranza de la página seguía mostrando
        # "resta $X + IVA" después de facturarse sin IVA, un desfasaje real entre lo
        # que el pedido dice que falta cobrar y lo que la factura real ya cobró.
        if pedido_congelado and data.pedido_id and factura_c_vigente(data.pedido_id, conn):
            desglose["con_iva"] = False
            desglose["iva_monto"] = 0
            desglose["total_final"] = desglose["neto"]

        # ── Combinado: el pedido + sus turnos del Estudio vinculados (#1308) ──
        # El rail muestra UN solo total con IVA para las dos partes. El IVA
        # sobre el neto combinado es una REGLA DE PLATA, así que la resuelve el
        # backend (MEMORIA 2026-06-29 — el front no calcula plata): sin esto el
        # rail sumaba un principal CON IVA a turnos SIN IVA (el `monto_total`
        # persistido es neto) y mostraba menos de lo que la factura cobra.
        #
        # Reusa la MISMA función que arma la factura combinada
        # (`finanzas_flujo.pedido.combinar_turnos_vinculados`), sobre un dict
        # con la forma que espera — así el rail y el comprobante no pueden
        # divergir. Clave ADITIVA (`combinado`): los campos existentes del
        # desglose siguen siendo los del PRINCIPAL solo, intactos para todos
        # los demás consumidores. `None` cuando no hay turnos.
        # `es_admin and pedido_id` (no `pedido_congelado`): un pedido en
        # `solicitado` también puede tener turnos vinculados y su rail necesita
        # el mismo total combinado — `pedido_congelado` es `None` ahí a
        # propósito (sigue el descuento del cliente en vivo), no significa "sin
        # turnos".
        combinado = None
        if es_admin and data.pedido_id:
            from services.finanzas_flujo.pedido import combinar_turnos_vinculados

            shim = {
                "id": data.pedido_id,
                "pedido_principal_id": None,
                "bruto": desglose["bruto"],
                "monto_total": desglose["neto"],
                "monto_pagado": 0,
                "con_iva": desglose["con_iva"],
            }
            combinar_turnos_vinculados(conn, shim)
            if shim["monto_total"] != desglose["neto"]:
                combinado = {
                    "turnos_total": shim["monto_total"] - desglose["neto"],
                    "neto": shim["monto_total"],
                    "con_iva": desglose["con_iva"],
                    "iva_monto": shim["iva_monto"],
                    "total_final": shim["total_con_iva"],
                }

        # Cuál descuento ganó (para el label del UI) — misma jerarquía que
        # decidió el pct en `calcular_total`, así nunca puede divergir.
        descuento_origen = resolver_origen_pedido_monto(
            descuento_manual_tipo, descuento_manual_pct, descuento_manual_monto,
            descuento_cliente_pct, descuento_jornadas_pct,
        )

        # Desglose POR LÍNEA para que el front MUESTRE (no calcule) el detalle por
        # equipo: `subtotal_por_jornada` (siempre, el "$X/día" del ítem) + `bruto`/`neto`
        # del período (cuando hay fechas). El neto por línea reparte el descuento ganado
        # con el mismo redondeo por línea que usaba el front; la suma de netos por línea
        # puede diferir del neto total por unos pesos (redondeo independiente por línea)
        # → el TOTAL autoritativo es `neto` (top-level), las líneas son detalle de display.
        # `equipo_id` None = línea personalizada (#805). Combos (`es_combo`, Fase
        # C-3 #1219) no reciben el % ganador — ya vienen con su propio descuento
        # de componente horneado en `precio_jornada`.
        pct_aplicado = desglose["descuento_pct"]
        lineas = []
        for it in items_para_total:
            bruto = bruto_linea(it, jornadas)
            dto = 0 if it.get("es_combo") else int(round(bruto * pct_aplicado / 100))
            lineas.append({
                "equipo_id": it["equipo_id"],
                "cantidad": it["cantidad"],
                "precio_jornada": it["precio_jornada"],
                "subtotal_por_jornada": it["precio_jornada"] * it["cantidad"],
                "bruto": bruto,
                "neto": bruto - dto,
            })

        return {
            "jornadas": jornadas,
            "subtotal_por_jornada": int(subtotal_por_jornada),
            "descuento_origen": descuento_origen,
            "lineas": lineas,
            "combinado": combinado,
            **desglose,
        }
