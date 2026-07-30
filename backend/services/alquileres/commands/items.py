"""Núcleo de ítems/total de un pedido — Fase 3 del split CQRS-lite de
`routes/alquileres/` (#1312).

Move-verbatim desde `routes/alquileres/core.py`: el recálculo de total
(`_recalcular_total_pedido`, `propagar_descuento_a_presupuestos`), la edición
de datos/ítems (`_apply_pedido_datos`, `_apply_pedido_items`) y sus helpers
(`_validar_reemplazo_items_taller`, `_fecha_cambia`, `_puede_quedar_sin_items`).
`create_pedido`/`create_pedido_retry` se quedan en `core.py` (Fase 4) —
`_apply_pedido_items` se importa de vuelta ahí para que `create_pedido` lo
siga usando.

`_resolver_descuentos_snapshot_o_vivo` NO vive acá pese a que este módulo es
su consumidor principal: es lectura pura, y el invariante duro del paquete
(`commands/` puede importar `queries/`, nunca al revés) la manda a
`services.alquileres.queries.cotizacion` (su otro consumidor real, también
de lectura) — se importa de vuelta desde ahí.

`_apply_pedido_items` es donde vive el INSERT contra el motor de reservas —
sumado a `tests/test_gate_not_bypassed.py` (`fuentes` + `ALLOWLIST_DELEGADORES`
apuntando acá) para que el guard estructural anti-bypass no pierda cobertura.
"""
from typing import TYPE_CHECKING

from fastapi import HTTPException

from database import to_datetime
from clientes.queries.identidad import nombre_completo_cliente
from services.precios import bruto_linea, calcular_total, jornadas_periodo, tipos_equipo_batch
from services.fechas import validar_rango_fechas
from tipos_pedido import es_pedido_estudio, es_pedido_derivado, es_pedido_taller
from services.alquileres.queries.detalle import _es_historico, _get_alquiler_detail
from services.alquileres.queries.cotizacion import (
    _cliente_es_dueno_de_perfil_fiscal,
    _cliente_es_miembro_de_productora,
    _resolver_descuentos_snapshot_o_vivo,
)

# Los modelos Pydantic (contrato HTTP) se quedan en routes/alquileres/modelos.py
# (no se mueven en ninguna fase) — acá solo hacen falta como forward-ref para
# los type hints, nunca en runtime, así que el import queda detrás de
# TYPE_CHECKING (no crea un import real de este paquete hacia `routes.*`).
if TYPE_CHECKING:
    from routes.alquileres.modelos import PedidoDatos, PedidoItem

# Mismo namespace que `creacion.py::_ADVISORY_NS_PEDIDO` (5390412) — DEBEN
# coincidir, es la misma serialización por equipo. Duplicado acá (no
# importado desde `creacion.py`) para no crear un ciclo de import
# (`creacion.py` ya importa `_apply_pedido_items` de este módulo).
_ADVISORY_NS_PEDIDO = 5390412


def _lock_equipos_por_id(conn, equipo_ids) -> None:
    """Serializa (`pg_advisory_xact_lock`, orden de id) cualquier escritura que
    vaya a tocar estos equipos vía `alquiler_items`/el gate de stock — mismo
    mecanismo que `create_pedido` (2026-06-22, #969): el INSERT de
    `alquiler_items` toma un FK KEY-SHARE sobre la fila de `equipos`; el gate
    de stock pide después `FOR UPDATE` (exclusivo) sobre la misma fila — sin
    serializar, dos escritores concurrentes del mismo equipo pueden
    deadlockear en el upgrade de lock. `create_pedido` ya lo hace por su
    cuenta (byte-idéntico, no se toca); este helper es la puerta para los
    otros dos escritores que tocan el MISMO equipo sin pasar por
    `create_pedido` — `_apply_pedido_items` (abajo) y
    `transiciones._revalidar_stock` — que hasta ahora no participaban de la
    misma serialización (hallazgo de auditoría, #1313/#1314).
    """
    for eid in sorted(set(equipo_ids)):
        conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_ADVISORY_NS_PEDIDO, eid))


def _recalcular_total_pedido(conn, id: int) -> None:
    """Recalcula y persiste el total de un pedido desde su estado YA guardado.

    Fuente ÚNICA del recálculo "desde lo que hay en la base": subtotales por
    línea, `descuento_jornadas_pct` (derivado de las jornadas) y `monto_total`
    (neto). Lee los ítems, las fechas y el `descuento_pct` del propio pedido —
    no recibe nada de afuera. No toca stock.

    Jerarquía de descuento (Fase C-1, #1219): `alquileres.descuento_pct` es el
    override MANUAL del pedido (0 = sin override). El descuento de
    cliente/jornadas se lee EN VIVO **solo mientras el pedido sigue en
    `presupuesto`** (así el builder sigue al cliente en vivo, comportamiento
    de siempre); una vez que pasa a `confirmado`/`retirado`/etc. se REUSA el
    snapshot ya persistido en la fila — se sigue recalculando `monto_total`
    (los ítems SÍ se pueden corregir post-confirmado) pero con el % YA
    CONGELADO, nunca uno recién leído de `clientes`/`descuentos_jornada`.

    Bug real (encontrado auditando un pedido con un descuento "que no
    existía"): antes de este guard, CUALQUIER guardado del pedido —aunque
    fuera una nota, no algo relacionado al descuento— disparaba esta función,
    que releía `obtener_descuento_cliente` en vivo y pisaba el snapshot
    congelado sin mirar el estado. Eso viola "plata congelada" (MEMORIA
    2026-06-06): un pedido ya confirmado/retirado podía cambiar de total solo
    porque alguien tocó cualquier otro campo del formulario admin.

    Lo usan `_apply_pedido_datos` (editar fechas/cliente/descuento) y la
    edición de ítems. `propagar_descuento_a_presupuestos` también dispara esto
    cuando cambia el descuento de un cliente — pero solo alcanza presupuestos
    (columna `estado='solicitado'` en su propio WHERE), así que el guard de
    acá nunca lo bloquea a él.

    `FOR UPDATE`: lockea la fila del pedido para todo el resto de la
    transacción — sin esto, dos escritores concurrentes sobre el MISMO pedido
    (ej. `propagar_descuento_a_presupuestos` corriendo mientras un admin edita
    ítems del mismo presupuesto a mano) podían pisarse un lost-update (el que
    commitea último gana con datos parcialmente stale, sin error ni log).
    Reentrante dentro de la misma transacción (`_apply_pedido_datos` ya puede
    tener la fila lockeada al llamar acá — Postgres no deadlockea consigo
    mismo). No es el motor de reservas (ese lockea `equipos`, tabla distinta).

    No-op para pedidos DERIVADOS (`tipo` en `TIPOS_DERIVADOS` — estudio,
    estudio_fijo o taller): sus ítems llevan la plata real del espacio/promo/
    economía de la edición directo en `subtotal` (`cobro_modo='fijo'`, ver
    `routes/estudio.py` y `services/talleres/commands/economia.py`), no un
    `precio_jornada` recalculable desde jornadas/descuentos — recalcular acá
    pisaría `monto_total` a partir de esos subtotales con la fórmula de un
    alquiler normal, rompiéndolo. Para estudio/estudio_fijo esto ya se sabía
    (bug vivo detectado en la auditoría de esa economía); para taller es la
    MISMA clase de riesgo, antes sin cerrar: `bruto_linea` respeta
    `cobro_modo='fijo'` así que los SUBTOTALES por línea sobrevivían, pero
    `calcular_total` de todos modos podía aplicarle un % de descuento de
    cliente/jornadas/manual a un pedido de taller sin cliente ni jornadas
    reales — nunca se disparó porque esos campos resultan en 0 por
    coincidencia (sin `cliente_id`, sin override cargado), no por regla
    explícita. Sus ítems y su plata se editan desde los endpoints propios de
    `routes/estudio.py`/`routes/talleres.py`, que ya escriben `monto_total`
    directo.
    """
    p = conn.execute("SELECT * FROM alquileres WHERE id=%s FOR UPDATE", (id,)).fetchone()
    if not p:
        return
    if es_pedido_derivado(p):
        return
    d0 = to_datetime(p["fecha_desde"]) if p["fecha_desde"] else None
    d1 = to_datetime(p["fecha_hasta"]) if p["fecha_hasta"] else None
    jornadas = jornadas_periodo(d0, d1)
    items = conn.execute(
        "SELECT id, equipo_id, cantidad, precio_jornada, cobro_modo FROM alquiler_items WHERE pedido_id=%s",
        (id,),
    ).fetchall()
    # Subtotales persistidos por línea (los usan los visores). `bruto_linea`
    # respeta el modo de cobro (las líneas 'fijo' no multiplican por jornadas).
    for it in items:
        sub = bruto_linea(
            {"precio_jornada": it["precio_jornada"], "cantidad": it["cantidad"],
             "cobro_modo": it["cobro_modo"]},
            jornadas,
        )
        conn.execute("UPDATE alquiler_items SET subtotal=%s WHERE id=%s", (sub, it["id"]))
    descuento_jornadas_pct, descuento_cliente_pct = _resolver_descuentos_snapshot_o_vivo(conn, p, jornadas)
    # `es_combo` (Fase C-3, #1219): resuelve qué líneas quedan afuera del
    # descuento global de cliente/jornadas/manual — ya traen el suyo propio.
    tipos = tipos_equipo_batch(conn, [it["equipo_id"] for it in items if it["equipo_id"]])
    total_desglose = calcular_total(
        items=[
            {"equipo_id": it["equipo_id"], "cantidad": it["cantidad"],
             "precio_jornada": it["precio_jornada"], "cobro_modo": it["cobro_modo"],
             "es_combo": tipos.get(it["equipo_id"]) == "combo"}
            for it in items
        ],
        jornadas=jornadas,
        descuento_cliente_pct=descuento_cliente_pct,
        descuento_jornadas_pct=descuento_jornadas_pct,
        descuento_manual_pct=p["descuento_pct"] or 0,
        descuento_manual_tipo=p["descuento_manual_tipo"] or "pct",
        descuento_manual_monto=p["descuento_manual_monto"] or 0,
        perfil_impuestos=None,  # persiste NETO; IVA es derivado al mostrar.
    )
    # `descuento_cliente_pct` se persiste como SNAPSHOT (igual que jornadas) —
    # sin esto, mostrar el desglose de un pedido ya confirmado tendría que
    # volver a consultar `clientes.descuento` EN VIVO, y si el cliente cambió
    # su descuento después de confirmar, el desglose mostrado divergiría de
    # `monto_total` ya persistido (bug clase #405). Ver `desglose_de_pedido`.
    conn.execute(
        "UPDATE alquileres SET monto_total=%s, descuento_jornadas_pct=%s, "
        "descuento_cliente_pct=%s WHERE id=%s",
        (total_desglose["neto"], descuento_jornadas_pct, descuento_cliente_pct, id),
    )


def propagar_descuento_a_presupuestos(conn, cliente_id: int) -> int:
    """Recotiza los presupuestos del cliente que SIGUEN su descuento en vivo
    (sin override manual) cuando el descuento del cliente cambia. Devuelve
    cuántos presupuestos tocó.

    Jerarquía de descuento (Fase C-1, #1219): ya no sobreescribe
    `alquileres.descuento_pct` — ese campo es el override MANUAL del pedido
    (0 = sin override, sigue al cliente en vivo). Antes, esta función pisaba
    ese campo sin condición en cada presupuesto abierto, lo que de paso
    clobbereaba cualquier override manual que ya existiera (bug real
    encontrado auditando #1219). Ahora solo dispara `_recalcular_total_pedido`
    (que ya lee el descuento del cliente EN VIVO) y solo para los presupuestos
    que efectivamente no tienen override — el resto no depende del cliente,
    no hace falta tocarlos.

    Solo afecta el estado `presupuesto` (no confirmado): los pedidos confirmados
    o cerrados conservan el snapshot del descuento con que se crearon — es un
    lock de precio deliberado (un pedido confirmado/facturado no debe cambiar de
    importe porque después se editó el perfil del cliente). Recibe una conexión
    abierta; el caller hace commit.
    """
    ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM alquileres WHERE cliente_id=%s AND estado='solicitado' "
            "AND (descuento_pct IS NULL OR descuento_pct = 0)",
            (cliente_id,),
        ).fetchall()
    ]
    for pid in ids:
        _recalcular_total_pedido(conn, pid)
    return len(ids)


def _fecha_cambia(persistido, nuevo) -> bool:
    """True si `nuevo` (string ISO del payload, o None) representa una fecha
    DISTINTA de la ya persistida. Normaliza ambos con `to_datetime` en vez de
    comparar strings crudos: el editor admin re-envía `fecha_desde`/
    `fecha_hasta` en TODO guardado de "datos" —incluso uno que solo toca
    notas— así que comparar por igualdad de string daría falso-positivo en
    cada guardado (mismo instante, formato/precisión distintos)."""
    p_dt = to_datetime(persistido) if persistido else None
    n_dt = to_datetime(nuevo) if nuevo else None
    return p_dt != n_dt


def _apply_pedido_datos(conn, id: int, data: "PedidoDatos", es_admin: bool = False) -> dict:
    """Aplica un cambio parcial de datos (cliente/fechas/notas/descuento) al pedido.

    Lógica compartida entre el endpoint admin (`update_pedido_datos`) y la
    aplicación de propuestas del cliente (cliente_portal). Recibe una conexión
    abierta; el caller hace commit/rollback y close.

    `es_admin=True` permite fecha de retiro en el pasado (carga retroactiva del
    back-office). Las propuestas del cliente (cliente_portal) usan el default
    `False` → el cliente sigue sin poder fechar en el pasado.

    `FOR UPDATE`: lockea la fila del pedido — ver el mismo comentario en
    `_recalcular_total_pedido` (que esta función llama más abajo; relockear la
    misma fila en la misma transacción es reentrante, no deadlockea).

    Pedidos DERIVADOS (`tipo` en `TIPOS_DERIVADOS` — estudio, estudio_fijo o
    taller): un cambio de fecha/hora real se rechaza (409) — este endpoint
    nunca revalida stock (ni el genérico ni el buffer propio del espacio; ver
    `update_pedido_datos`), así que aplicarlo sin más movería un turno
    confirmado a una franja ya ocupada sin ningún chequeo, o correría la
    ventana contable de un taller sin pasar por la economía de la edición.
    Notas/cliente/etc. pasan igual (`_recalcular_total_pedido` ya es no-op
    para estos tipos). Reprogramar un turno real de estudio es un endpoint
    propio de `routes/estudio.py` (revalida `_centinela_libre`/motor); las
    fechas de un taller las gobierna la edición (`routes/talleres.py`).
    """
    p = conn.execute("SELECT * FROM alquileres WHERE id=%s FOR UPDATE", (id,)).fetchone()
    if not p:
        raise HTTPException(404, "Pedido no encontrado")

    payload = {k: v for k, v in data.model_dump(exclude_unset=True).items()}
    # Columnas TIMESTAMP: '' rompe el cast → normalizar a NULL.
    for _k in ("fecha_desde", "fecha_hasta"):
        if _k in payload and not payload[_k]:
            payload[_k] = None
    # `cliente_nombre` es NOT NULL: el "sin cliente" se representa con cadena
    # VACÍA, nunca con NULL. El autosave del editor manda
    # `cliente_nombre: d.cliente_nombre || null` (`usePedidoDraft.ts`), así que
    # un pedido todavía sin cliente asignado mandaba `None` y tumbaba el
    # guardado ENTERO con un `NotNullViolation` → 500, aunque lo único que se
    # estuviera cambiando fuera la fecha (bug real reportado por el dueño: "no
    # puedo cambiar la fecha"). Se normaliza acá, en la puerta compartida por
    # el admin Y las propuestas del portal, para que ningún caller pueda
    # volver a romperlo. Candado: `test_pedido_sin_cliente_guarda_db.py`.
    if "cliente_nombre" in payload and payload["cliente_nombre"] is None:
        payload["cliente_nombre"] = ""

    if es_pedido_derivado(p) and (
        ("fecha_desde" in payload and _fecha_cambia(p["fecha_desde"], payload["fecha_desde"]))
        or ("fecha_hasta" in payload and _fecha_cambia(p["fecha_hasta"], payload["fecha_hasta"]))
    ):
        mensaje = (
            "Las fechas de un pedido de taller las gobierna la edición (Talleres → "
            "economía) — no se editan acá."
            if es_pedido_taller(p)
            else "Las fechas de un pedido del Estudio se reprograman desde Admin → Estudio "
            "(para revalidar la disponibilidad del espacio)."
        )
        raise HTTPException(409, mensaje)

    cliente_cambio = "cliente_id" in payload and payload["cliente_id"]
    if cliente_cambio:
        c = conn.execute("SELECT * FROM clientes WHERE id=%s", (payload["cliente_id"],)).fetchone()
        if c:
            payload.setdefault("cliente_nombre",   nombre_completo_cliente(c["nombre"], c["apellido"]))
            payload.setdefault("cliente_email",    c["email"])
            payload.setdefault("cliente_telefono", c["telefono"])
            # `descuento_pct` (override manual) YA NO se copia acá (Fase C-1,
            # #1219) — 0 = "sin override, seguí al cliente en vivo" y el nuevo
            # cliente se resuelve en vivo en `_recalcular_total_pedido`. Si el
            # pedido ya tenía un override explícito, asignar OTRO cliente no
            # debería resetearlo solo — el admin lo cambia a mano si quiere.

    if "perfil_fiscal_id" in payload or "productora_id" in payload:
        # Selección tipo radio (una sola forma activa a la vez): si se manda
        # uno no-nulo, el otro se limpia solo aunque el caller no lo mande
        # explícito — evita dejar la fila con ambos apuntando a algo (#1251).
        if payload.get("perfil_fiscal_id"):
            payload["productora_id"] = None
        elif payload.get("productora_id"):
            payload["perfil_fiscal_id"] = None

        cliente_efectivo = payload.get("cliente_id") or p["cliente_id"]
        if payload.get("perfil_fiscal_id") and not cliente_efectivo:
            raise HTTPException(400, "El pedido necesita un cliente antes de elegir un perfil fiscal.")
        if payload.get("productora_id") and not cliente_efectivo:
            raise HTTPException(400, "El pedido necesita un cliente antes de elegir una productora.")
        if payload.get("perfil_fiscal_id"):
            if not _cliente_es_dueno_de_perfil_fiscal(conn, cliente_efectivo, payload["perfil_fiscal_id"]):
                raise HTTPException(404, "Perfil fiscal no encontrado para este cliente.")
        if payload.get("productora_id"):
            if not _cliente_es_miembro_de_productora(conn, cliente_efectivo, payload["productora_id"]):
                raise HTTPException(404, "Productora no encontrada para este cliente.")

    if "fecha_desde" in payload or "fecha_hasta" in payload:
        nueva_desde = payload.get("fecha_desde") or p["fecha_desde"]
        nueva_hasta = payload.get("fecha_hasta") or p["fecha_hasta"]
        if nueva_desde and nueva_hasta:
            # Históricos importados tienen fechas en el pasado por diseño. El
            # frontend manda fecha_desde junto con cualquier cambio (ej. solo
            # el descuento), así que sin este bypass no se podría editar nada.
            # El admin además puede fijar fechas pasadas (carga retroactiva); el
            # cliente (es_admin=False) sigue sin poder. Criterio por la fuente
            # única `validar_rango_fechas`.
            permitir_pasado = es_admin or _es_historico(p["fuente"])
            msg = validar_rango_fechas(
                nueva_desde, nueva_hasta, permitir_pasado=permitir_pasado
            )
            if msg:
                raise HTTPException(400, msg)

    if not payload:
        return _get_alquiler_detail(conn, id)

    cols = ", ".join(f"{k}=%s" for k in payload)
    conn.execute(f"UPDATE alquileres SET {cols} WHERE id=%s", (*payload.values(), id))

    if (
        "fecha_desde" in payload
        or "fecha_hasta" in payload
        or "descuento_pct" in payload
        or "descuento_manual_tipo" in payload
        or "descuento_manual_monto" in payload
        or cliente_cambio
    ):
        _recalcular_total_pedido(conn, id)

    return _get_alquiler_detail(conn, id)


def _validar_reemplazo_items_taller(conn, pedido_id: int, items_nuevos: list["PedidoItem"]) -> None:
    """Un pedido de taller SÍ permite reemplazar ítems (a diferencia de
    estudio/estudio_fijo, 409 en bloque) — es la única vía hoy para agregar
    una línea de matrícula a mano (no hay un endpoint de "agregar un ítem",
    `PUT items` reemplaza todo el array). Lo que no permite es que ese
    reemplazo DESCARTE el/los ítem(s) AUTO-generados por
    `_regenerar_pedidos_taller` (`services/talleres/commands/economia.py`) —
    perderlos desatribuiría esa plata en silencio de la economía de
    Estudio/Rental, y el próximo recálculo de la edición no los repone (solo
    borra-y-recrea meses SIN plata pagada, ver esa función).

    Identifica el/los ítem(s) auto por su FORMA actual en la base (no
    recomputando contra `ediciones_taller` — más simple y alcanza): el
    centinela del Estudio (`equipo_id == estudio.equipo_id`, si `usa_estudio`)
    y/o la línea libre "Uso de equipos — …" (si `usa_equipos`). El placeholder
    "sin nada" (ni estudio ni equipos, precio 0) no se protege — no hay plata
    que perder. Agregar líneas nuevas, o editar/quitar líneas manuales
    (equipo_id o nombre_libre que NO matcheen lo de arriba), sigue libre.

    Import diferido de `services.estudio` — mismo estilo que
    `transiciones.py::_revalidar_stock` (ese paquete no importa de `routes.*`,
    así que esta dirección de import es segura, sin ciclo).
    """
    from services.estudio.queries.estudio import _get_estudio_row

    actuales = conn.execute(
        "SELECT equipo_id, nombre_libre FROM alquiler_items WHERE pedido_id=%s",
        (pedido_id,),
    ).fetchall()
    estudio = _get_estudio_row(conn)
    centinela_id = estudio["equipo_id"] if estudio else None

    tenia_centinela = bool(centinela_id) and any(a["equipo_id"] == centinela_id for a in actuales)
    nombres_equipos_actuales = {
        a["nombre_libre"] or "" for a in actuales
        if a["equipo_id"] is None and (a["nombre_libre"] or "").startswith("Uso de equipos — ")
    }
    if not tenia_centinela and not nombres_equipos_actuales:
        return  # nada reconocible que proteger (ej. el placeholder "sin nada")

    nuevos_equipo_ids = {it.equipo_id for it in items_nuevos if it.equipo_id is not None}
    nuevos_nombres_libres = {(it.nombre_libre or "") for it in items_nuevos if it.equipo_id is None}

    perdio_centinela = tenia_centinela and centinela_id not in nuevos_equipo_ids
    perdio_equipos = bool(nombres_equipos_actuales) and not (nombres_equipos_actuales & nuevos_nombres_libres)
    if perdio_centinela or perdio_equipos:
        raise HTTPException(
            409,
            "No se puede quitar la línea del espacio/equipos generada por la edición del "
            "taller (se administra desde Talleres, no acá). Podés agregar líneas nuevas, "
            "como una matrícula.",
        )


def _puede_quedar_sin_items(conn, p) -> bool:
    """¿Este pedido puede quedarse con CERO ítems de alquiler?

    Sí en dos casos, y en los dos "vacío" no significa "pedido sin contenido":

    1. **Borrador** — es un presupuesto rápido que se está armando (misma
       excepción que ya hacía `create_pedido`: un borrador nace vacío). Sacar el
       último equipo mientras se piensa es normal; obligar a dejar uno hacía que
       el auto-guardado no pudiera persistir el cambio y la pantalla quedara en
       "Sin guardar" para siempre (lo reportó el dueño: "cuando saco un equipo,
       no se guarda").
    2. **Tiene un turno del Estudio vinculado** (#1308) — el contenido del
       pedido son esas horas de estudio; que no haya equipos es un pedido
       perfectamente válido ("2 horas de estudio y nada más").

    Un pedido de primera clase, ya solicitado y sin turnos, SIGUE necesitando al
    menos un ítem: ahí vacío sí es un pedido sin nada.
    """
    if p["estado"] == "borrador":
        return True
    # Mismo filtro que usan el pago combinado (`pagos.py`) y la factura
    # combinada (`finanzas_flujo.pedido`): un turno cancelado ya no es contenido.
    row = conn.execute(
        "SELECT 1 FROM alquileres WHERE pedido_principal_id = %s AND estado <> 'cancelado' LIMIT 1",
        (p["id"],),
    ).fetchone()
    return row is not None


def _apply_pedido_items(conn, id: int, items: list["PedidoItem"]) -> dict:
    """Reemplaza los ítems del pedido por `items`. Recalcula subtotales y monto.

    No valida stock — el caller debe llamar a `_check_stock` si corresponde.
    Lógica compartida entre admin y portal cliente.

    `FOR UPDATE`: lockea la fila del pedido — mismo motivo que
    `_recalcular_total_pedido` (evitar lost-update entre dos escritores
    concurrentes del mismo pedido).

    Rechaza pedidos del Estudio (`tipo` en `TIPOS_ESTUDIO`, 409 en bloque):
    este reemplazo reconstruye subtotales con la fórmula de un alquiler normal
    (jornadas × precio de catálogo) y perdería el ítem centinela que bloquea
    el espacio — sus ítems se editan desde `routes/estudio.py`. Un taller NO
    se bloquea en bloque (ver `_validar_reemplazo_items_taller`): agregar una
    línea de matrícula a mano sigue siendo válido, solo se protege el ítem auto.
    """
    p = conn.execute("SELECT * FROM alquileres WHERE id=%s FOR UPDATE", (id,)).fetchone()
    if not p:
        raise HTTPException(404, "Pedido no encontrado")
    if es_pedido_estudio(p):
        raise HTTPException(
            409, "Los ítems de un pedido del Estudio se editan desde Admin → Estudio."
        )
    if es_pedido_taller(p):
        _validar_reemplazo_items_taller(conn, id, items)
    if not items and not _puede_quedar_sin_items(conn, p):
        raise HTTPException(400, "Debe tener al menos un ítem")

    # Serializar por equipo ANTES de reemplazar los ítems (mismo criterio que
    # `create_pedido`, #969) — sin esto, este reemplazo (llamado por
    # `PUT /alquileres/{id}/items`) no participaba de la misma serialización
    # y podía deadlockear contra un `create_pedido` concurrente del mismo
    # equipo (hallazgo de auditoría, #1313/#1314).
    _lock_equipos_por_id(conn, (it.equipo_id for it in items if it.equipo_id is not None))

    d0 = to_datetime(p["fecha_desde"]) if p["fecha_desde"] else None
    d1 = to_datetime(p["fecha_hasta"]) if p["fecha_hasta"] else None
    jornadas = jornadas_periodo(d0, d1)

    # Armar las líneas preservando el orden de llegada (= el orden que arma el
    # front, incl. drag-reorder #806). Las de catálogo se CONSOLIDAN por equipo
    # (sumar cantidades) — sino dos rows del mismo equipo pasan el gate (que
    # consolida) pero quedan dos filas. Las líneas personalizadas (#805, sin
    # equipo_id) NO se consolidan: cada una es única (nombre/precio/modo propios).
    lineas: list[dict] = []
    equipo_idx: dict[int, int] = {}  # equipo_id → índice en `lineas`
    for it in items:
        if it.equipo_id is None:
            lineas.append({
                "equipo_id": None,
                "cantidad": it.cantidad,
                "precio_jornada": it.precio_jornada,
                "nombre_libre": (it.nombre_libre or "").strip(),
                "cobro_modo": it.cobro_modo or "jornada",
            })
        elif it.equipo_id in equipo_idx:
            e = lineas[equipo_idx[it.equipo_id]]
            e["cantidad"] += it.cantidad
            # Precios distintos para el mismo equipo: usamos el mayor (defensivo).
            e["precio_jornada"] = max(e["precio_jornada"], it.precio_jornada)
        else:
            equipo_idx[it.equipo_id] = len(lineas)
            lineas.append({
                "equipo_id": it.equipo_id,
                "cantidad": it.cantidad,
                "precio_jornada": it.precio_jornada,
                "nombre_libre": None,
                # Preserva el modo entrante en vez de hardcodear 'jornada': un
                # pedido de taller (`_regenerar_pedidos_taller`) tiene un ítem
                # de catálogo (el centinela del Estudio) en 'fijo' — pisarlo acá
                # lo rompería en el próximo guardado de CUALQUIER cosa del
                # pedido (el front reenvía el array completo). Sin efecto en
                # pedidos normales: sus ítems de catálogo siempre traen
                # 'jornada' desde que se cargaron.
                "cobro_modo": it.cobro_modo or "jornada",
            })

    # `orden` por posición; subtotal por línea vía `bruto_linea` (respeta cobro_modo).
    # Tipo por equipo EN BATCH (mismo helper que ya usa `_recalcular_total_pedido`
    # más arriba en este archivo) — antes era una query por línea (N+1 real,
    # hallazgo de auditoría #1313/#1314), sostenida además dentro del advisory
    # lock de `create_pedido` cuando esta función corre desde ahí.
    tipos_lineas = tipos_equipo_batch(
        conn, [ln["equipo_id"] for ln in lineas if ln["equipo_id"] is not None]
    )
    rows = []
    for orden, ln in enumerate(lineas):
        if ln["equipo_id"] is not None:
            if ln["equipo_id"] not in tipos_lineas:
                raise HTTPException(404, f"Equipo {ln['equipo_id']} no encontrado")
            # `es_combo` (Fase C-3, #1219): no acumula el descuento global — ya
            # trae el suyo propio horneado en `precio_jornada`.
            ln["es_combo"] = tipos_lineas[ln["equipo_id"]] == "combo"
        subtotal = bruto_linea(ln, jornadas)
        rows.append((
            id, ln["equipo_id"], ln["cantidad"], ln["precio_jornada"],
            subtotal, orden, ln["nombre_libre"], ln["cobro_modo"],
        ))

    # Re-aplicar la jerarquía completa (manual > cliente-en-vivo > jornadas),
    # como hacen las otras 2 sedes. Antes solo se aplicaba el del cliente →
    # editar ítems perdía el descuento por jornadas (#500). Acá se calcula
    # desde los ítems en memoria (los que estamos por insertar), no desde la base.
    #
    # Mismo guard que `_recalcular_total_pedido` (misma fuente única,
    # `_resolver_descuentos_snapshot_o_vivo`): una vez que el pedido pasa de
    # `presupuesto`, el % de cliente/jornadas queda CONGELADO (se reusa el
    # snapshot ya persistido) — editar ítems de un pedido confirmado no debe
    # poder cambiar el % de descuento, solo el bruto/monto que ese % multiplica.
    #
    # `taller` NUNCA pasa por esta jerarquía (bug latente cerrado en esta
    # pasada): a diferencia de estudio/estudio_fijo (bloqueados en bloque más
    # arriba), un taller SÍ llega hasta acá para poder agregar matrícula — pero
    # su monto es la suma llana de sus líneas (`_regenerar_pedidos_taller`),
    # sin cliente ni jornadas reales. Sin este branch, `calcular_total` le
    # aplicaría igual cualquier `descuento_pct`/`descuento_manual_*` que la
    # fila tuviera cargado (0 hoy por coincidencia, no por regla — mismo tipo
    # de riesgo que ya se cerró en `_recalcular_total_pedido`).
    if es_pedido_taller(p):
        monto_total = sum(r[4] for r in rows)  # r[4] = subtotal (bruto_linea, ya sin descuento)
        descuento_jornadas_pct, descuento_cliente_pct = 0, 0
    else:
        descuento_jornadas_pct, descuento_cliente_pct = _resolver_descuentos_snapshot_o_vivo(conn, p, jornadas)
        total_desglose = calcular_total(
            items=lineas,  # incluye cobro_modo por línea (líneas 'fijo' no × jornadas)
            jornadas=jornadas,
            descuento_cliente_pct=descuento_cliente_pct,
            descuento_jornadas_pct=descuento_jornadas_pct,
            descuento_manual_pct=p["descuento_pct"] or 0,
            descuento_manual_tipo=p["descuento_manual_tipo"] or "pct",
            descuento_manual_monto=p["descuento_manual_monto"] or 0,
            perfil_impuestos=None,  # persiste NETO; IVA derivado al mostrar.
        )
        monto_total = total_desglose["neto"]

    conn.execute("DELETE FROM alquiler_items WHERE pedido_id=%s", (id,))
    conn.executemany("""
        INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, orden, nombre_libre, cobro_modo)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, rows)
    conn.execute(
        "UPDATE alquileres SET monto_total=%s, descuento_jornadas_pct=%s, "
        "descuento_cliente_pct=%s WHERE id=%s",
        (monto_total, descuento_jornadas_pct, descuento_cliente_pct, id),
    )

    return _get_alquiler_detail(conn, id)
