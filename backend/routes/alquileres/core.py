"""routes/alquileres/core.py — spine del paquete de alquileres (#501; split #1254).

El `router` compartido + la creación del pedido (`create_pedido`/`create_pedido_retry`,
la puerta única con el advisory lock) + la plata (`_recalcular_total_pedido`,
`propagar_descuento_a_presupuestos`) + la edición (`_apply_pedido_datos`,
`_apply_pedido_items`). Los modelos Pydantic viven en `modelos.py`, la lectura del
detalle en `detalle.py` y el armado de mails/ICS en `services/pedidos_notificaciones.py`
— los tres re-exportados acá tal cual (issue #1254) para no romper los ~57 call-sites
existentes. Las superficies HTTP (pedidos CRUD, cotización, disponibilidad, pagos,
documentos, descuentos) viven en submódulos que registran sus rutas sobre este router.
"""

import logging
import time
from typing import Optional

import psycopg.errors

from fastapi import APIRouter, BackgroundTasks, HTTPException

from database import get_db, to_datetime
from clientes.queries.identidad import nombre_completo_cliente
# _batch_get_alquiler_items/_enriquecer_pedido_con_cliente_fiscal/_enriquecer_pedidos_con_cliente
# viven en services.pedidos_enriquecimiento (auditoría cruzada de plata, 2026-07-02) —
# reexportados acá tal cual para no tocar los call-sites existentes (este paquete +
# routes/cliente_portal). `_enriquecer_pedido_con_cliente` la usa `detalle.py` (Corte C,
# #1254) directo de la misma fuente — acá queda como puro re-export. Código nuevo
# debería importar de services.pedidos_enriquecimiento directo.
from services.pedidos_enriquecimiento import (
    _batch_get_alquiler_items,  # noqa: F401 — re-export, ver comentario arriba
    _enriquecer_pedido_con_cliente_fiscal,  # noqa: F401 — re-export, ver comentario arriba
    _enriquecer_pedido_con_cliente,  # noqa: F401 — re-export, ver comentario arriba
    _enriquecer_pedidos_con_cliente,  # noqa: F401 — re-export, ver comentario arriba
)
from services.precios import bruto_linea, calcular_total, jornadas_periodo, tipos_equipo_batch
from services.fechas import validar_rango_fechas
from descuentos.queries.jornadas import obtener_descuento_jornadas
from descuentos.queries.cliente import obtener_descuento_cliente
from tipos_pedido import es_pedido_estudio

# Modelos Pydantic del pedido: viven en `modelos.py` (split de este archivo, issue
# de tracking #1254). Re-exportados acá TAL CUAL — `routes/alquileres/__init__.py`
# los sigue importando de `core` sin cambiar una línea, y varios tests importan
# `PedidoItem`/`PedidoCreate`/etc. o `_parse_precio` vía este paquete.
from routes.alquileres.modelos import (
    PedidoCreate,
    PedidoDatos,
    PedidoEstado,  # noqa: F401 — re-export, ver comentario arriba
    PedidoItem,
    PedidoItemUpdate,  # noqa: F401 — re-export, ver comentario arriba
    _parse_precio,  # noqa: F401 — re-export, ver comentario arriba
    _validar_fecha_iso,  # noqa: F401 — re-export, ver comentario arriba
)
# Lectura del detalle de un pedido: vive en `detalle.py` (split #1254, Corte C).
# Re-exportada acá TAL CUAL — `create_pedido`/`_apply_pedido_*` (este módulo) usan
# `_get_alquiler_detail`/`_next_numero_pedido`/`_es_historico` directo; el resto
# (`_maybe_finalizar`, `_get_alquiler_items`, `_get_alquiler_pagos`,
# `_enriquecer_pedido_con_total`, `_get_historial_modificaciones`) son puro
# re-export para `pagos.py`/`documentos.py`/`pedidos.py`, que importan de
# `routes.alquileres.core` directo.
from routes.alquileres.detalle import (
    _es_historico,
    _get_alquiler_detail,
    _get_alquiler_items,  # noqa: F401 — re-export, ver comentario arriba
    _get_alquiler_pagos,  # noqa: F401 — re-export, ver comentario arriba
    _get_historial_modificaciones,  # noqa: F401 — re-export, ver comentario arriba
    _maybe_finalizar,  # noqa: F401 — re-export, ver comentario arriba
    _next_numero_pedido,
    _enriquecer_pedido_con_total,  # noqa: F401 — re-export, ver comentario arriba
)
# Armado de mails/ICS del pedido: vive en `services/pedidos_notificaciones.py`
# (split #1254, Corte B — espeja `services/pedidos_enriquecimiento`). Re-exportado
# acá TAL CUAL — lo consumen `create_pedido` (este módulo), `jobs/recordatorios.py`
# y varios tests (`routes.alquileres.core` directo o vía el paquete).
from services.pedidos_notificaciones import (
    _dispatch_pedido_creado_emails,
    _ics_adjunto_pedido,  # noqa: F401 — re-export, ver comentario arriba
    _pedido_email_context,  # noqa: F401 — re-export, ver comentario arriba
)

# Motor de reservas: la fuente única vive en el paquete `reservas`. Acá se
# importan solo los nombres que este módulo usa internamente (las transiciones
# de estado validan con `validar_stock`). `ESTADOS_RESERVADO` se re-exporta
# porque es la constante canónica del dominio. El resto de las primitivas se
# importan directo de `reservas` donde se usan (routes.estudio,
# routes.cliente_portal, routes.alquileres.disponibilidad). Ver issue #501, Fase 1.
from reservas import (
    ESTADOS_RESERVADO,  # noqa: F401 — re-export canónico (guard: test_reservas_sql_safety)
    validar_stock as _check_stock,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Rutas de pedidos ─────────────────────────────────────────────────────────

# Namespace (clave1 de `pg_advisory_xact_lock`) para serializar creación de
# pedidos por equipo. Arbitrario y privado de este flujo; evita colisión con
# otros advisory locks de la app.
_ADVISORY_NS_PEDIDO = 5390412


def create_pedido(data: PedidoCreate, background: Optional[BackgroundTasks] = None,
                  es_admin: bool = False):
    """Lógica interna de creación de pedido. Llamada por el endpoint admin
    (`create_pedido_endpoint`) y también por `cliente_portal.cliente_crear_pedido`
    que tiene su propio `require_cliente`."""
    if not data.items and data.estado != "borrador":
        raise HTTPException(400, "El pedido debe tener al menos un ítem")
    # Defense-in-depth (#1240, hallazgo de revisión): `cliente_crear_pedido` ya
    # valida esto antes de llamar acá, pero esta es la ÚNICA puerta real de
    # creación — sin este chequeo acá, cualquier caller futuro que sete ambos
    # campos rompería el `CHECK chk_alquileres_facturacion_target` sin capturar
    # (el único except de abajo es `DeadlockDetected`) → 500 crudo en vez de 400.
    if data.perfil_fiscal_id and data.productora_id:
        raise HTTPException(400, "Un pedido no puede facturar a un perfil personal y a una productora a la vez.")
    # Mismo defense-in-depth que la excluyencia de arriba: `cliente_crear_pedido`
    # ya valida membership antes de llamar acá, pero esta es la ÚNICA puerta
    # real — sin esto, el builder admin podría apuntar un pedido a la
    # productora/perfil de OTRO cliente por un bug de UI.
    if data.perfil_fiscal_id or data.productora_id:
        with get_db() as _conn:
            if data.perfil_fiscal_id:
                propio = _conn.execute(
                    "SELECT 1 FROM cliente_perfiles_fiscales WHERE id = %s AND cliente_id = %s",
                    (data.perfil_fiscal_id, data.cliente_id),
                ).fetchone()
                if not propio:
                    raise HTTPException(404, "Perfil fiscal no encontrado para este cliente.")
            if data.productora_id:
                vinculado = _conn.execute(
                    "SELECT 1 FROM productora_miembros WHERE productora_id = %s AND cliente_id = %s",
                    (data.productora_id, data.cliente_id),
                ).fetchone()
                if not vinculado:
                    raise HTTPException(404, "Productora no encontrada para este cliente.")

    cliente_nombre   = data.cliente_nombre
    cliente_email    = data.cliente_email
    cliente_telefono = data.cliente_telefono

    with get_db() as conn:
        try:
            # `descuento_pct` (override manual del pedido) arranca en 0 = "sin
            # override, seguí al cliente en vivo" (Fase C-1, #1219) — YA NO se
            # copia el descuento del cliente acá; `_apply_pedido_items` (más
            # abajo) lo resuelve en vivo vía `obtener_descuento_cliente`.
            descuento_pct = 0.0
            if data.cliente_id:
                c = conn.execute("SELECT * FROM clientes WHERE id=%s", (data.cliente_id,)).fetchone()
                if c:
                    cliente_nombre   = nombre_completo_cliente(c["nombre"], c["apellido"])
                    cliente_email    = cliente_email    or c["email"]
                    cliente_telefono = cliente_telefono or c["telefono"]

            # Ambas fechas o ninguna: un pedido con una sola fecha es incoherente
            # (no se puede calcular jornadas ni chequear stock).
            if bool(data.fecha_desde) != bool(data.fecha_hasta):
                raise HTTPException(400, "Indicá fecha de retiro y devolución, o ninguna")

            if data.fecha_desde and data.fecha_hasta:
                # Criterio de fechas por la fuente única `validar_rango_fechas`.
                # El admin puede crear con fecha pasada (carga retroactiva); el
                # cliente no (la distinción la pasa `create_pedido_endpoint`).
                msg = validar_rango_fechas(
                    data.fecha_desde, data.fecha_hasta, permitir_pasado=es_admin
                )
                if msg:
                    raise HTTPException(400, msg)

            # Serializar la creación sobre cada equipo del pedido ANTES de
            # insertar los ítems. El insert de `alquiler_items` toma un FK
            # KEY-SHARE sobre la fila de `equipos`; el gate de stock pide luego
            # FOR UPDATE (exclusivo) sobre la misma fila → dos pedidos concurrentes
            # del mismo equipo se deadlockean en el upgrade de lock (salía 500).
            # El advisory lock (xact-scoped, tomado en orden de id para no
            # deadlockear entre transacciones) los pone en fila: cada uno espera
            # su turno y corre limpio (201 o 409 real por falta de stock). NO toca
            # el FOR UPDATE del gate (motor de reservas = sagrado); se libera solo
            # al commit/rollback. `create_pedido_retry` queda de backstop.
            for _eid in sorted({it.equipo_id for it in data.items
                                if getattr(it, "equipo_id", None)}):
                conn.execute("SELECT pg_advisory_xact_lock(%s, %s)",
                             (_ADVISORY_NS_PEDIDO, _eid))

            estado_inicial = data.estado if data.estado in {"borrador", "solicitado"} else "solicitado"
            next_num = _next_numero_pedido(conn)
            # `fuente`: distingue quién originó el pedido para que el label del admin
            # ("back-office" vs "portal del cliente") sea confiable — antes esta columna
            # nunca se escribía acá y todo caía al default 'sistema' de la tabla, así que
            # un pedido creado por un cliente vía `cliente_crear_pedido` (es_admin=False)
            # se mostraba igual que uno cargado a mano desde el back-office.
            fuente = "sistema" if es_admin else "portal"
            # Cabecera primero con totales en 0; los ítems se aplican vía el helper
            # canónico, que recalcula monto_total y descuento_jornadas_pct.
            pedido_id = conn.insert_returning("""
                INSERT INTO alquileres (cliente_nombre, cliente_email, cliente_telefono,
                                     cliente_id, notas, fecha_desde, fecha_hasta,
                                     monto_total, estado, numero_pedido,
                                     descuento_pct, descuento_jornadas_pct, fuente,
                                     perfil_fiscal_id, productora_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (cliente_nombre, cliente_email, cliente_telefono,
                  data.cliente_id, data.notas, data.fecha_desde or None, data.fecha_hasta or None,
                  0, estado_inicial, next_num,
                  descuento_pct, 0.0, fuente,
                  data.perfil_fiscal_id, data.productora_id))

            # Ítems vía la fuente única `_apply_pedido_items` (#805): preserva las
            # líneas personalizadas (equipo_id None → nombre_libre/cobro_modo/orden),
            # consolida las de catálogo y respeta cobro_modo='fijo' (no × jornadas).
            # El armado inline anterior asumía equipo_id válido → 404 al crear con una
            # línea libre, y descartaba nombre_libre/cobro_modo. Borradores: sin ítems.
            if data.items:
                _apply_pedido_items(conn, pedido_id, data.items)

            if estado_inicial == "solicitado" and data.fecha_desde and data.fecha_hasta:
                problemas = _check_stock(conn, pedido_id, data.fecha_desde, data.fecha_hasta)
                if problemas:
                    raise HTTPException(409, "Sin stock: " + "; ".join(problemas))

            conn.commit()
            pedido = _get_alquiler_detail(conn, pedido_id)
        except psycopg.errors.DeadlockDetected:
            # Deadlock transitorio por upgrade de lock bajo concurrencia (FK
            # KEY-SHARE del insert de ítems + FOR UPDATE del gate sobre la misma
            # fila de `equipos`). PG aborta una de las transacciones. NO es un
            # error nuestro: el caller (`create_pedido_retry`) reintenta. No lo
            # logueamos como error para no ensuciar; sólo rollback + propagar.
            conn.rollback()
            raise
        except Exception:
            logger.error("Error creando pedido", exc_info=True)
            conn.rollback()
            raise

    # Mails fuera del try/finally del DB: si fallan no rollbackean el pedido
    # (igual send_email no propaga, pero por las dudas). Solo se mandan si
    # el pedido salió de borrador — drafts no notifican.
    if pedido and pedido.get("estado") != "borrador":
        _dispatch_pedido_creado_emails(background, pedido)
    return pedido


def create_pedido_retry(data: PedidoCreate, background: Optional[BackgroundTasks] = None,
                        es_admin: bool = False, intentos: int = 5):
    """Crea un pedido reintentando ante deadlock de Postgres (concurrencia).

    Bajo reservas concurrentes del mismo equipo, dos transacciones se bloquean
    mutuamente — el insert de `alquiler_items` toma un FK KEY-SHARE sobre la fila
    de `equipos` y el gate de stock pide FOR UPDATE (exclusivo) sobre esa misma
    fila → PG detecta el deadlock y aborta una (`DeadlockDetected`), que sin esto
    salía como **500**. Reintentar es el patrón estándar: serializa y resuelve,
    SIN tocar el lock (el motor de reservas es sagrado), sin overbooking (el gate
    corre íntegro en cada intento) ni pedidos huérfanos (rollback antes de cada
    reintento). Agotados los intentos → **503** (carga puntual), nunca 500.

    Es la ÚNICA puerta de creación de pedidos para los endpoints (cliente y
    back-office): centraliza el reintento en una sola fuente.
    """
    for i in range(intentos):
        try:
            return create_pedido(data, background=background, es_admin=es_admin)
        except psycopg.errors.DeadlockDetected:
            if i == intentos - 1:
                logger.warning("Pedido: deadlock persistente tras %d intentos → 503", intentos)
                raise HTTPException(
                    503, "Hay mucha demanda sobre ese equipo en este momento. "
                         "Reintentá en unos segundos.")
            time.sleep(0.04 * (i + 1))   # backoff corto; el scheduling rompe el ciclo
    # Inalcanzable con intentos >= 1 (la última vuelta siempre retorna o tira 503);
    # blindaje por si se invocara con intentos <= 0.
    raise HTTPException(503, "No se pudo crear el pedido")


def _resolver_descuentos_snapshot_o_vivo(conn, p, jornadas: int) -> tuple[float, float]:
    """Descuento de jornadas + de cliente: en vivo mientras el pedido sigue en
    `presupuesto`, snapshot ya persistido en la fila una vez que avanzó.

    Fuente ÚNICA de este guard — antes vivía duplicado, idéntico, en
    `_recalcular_total_pedido` y `_apply_pedido_items` (mismo invariante de
    "plata congelada" escrito dos veces, con el riesgo de que una copia se
    actualizara y la otra no). `p` es la fila de `alquileres` ya leída por el
    caller (`estado`, `descuento_jornadas_pct`, `descuento_cliente_pct`,
    `cliente_id`).
    """
    if p["estado"] == "solicitado":
        return obtener_descuento_jornadas(conn, jornadas), obtener_descuento_cliente(conn, p["cliente_id"])
    return p["descuento_jornadas_pct"] or 0, p["descuento_cliente_pct"] or 0


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

    No-op para pedidos del Estudio (`tipo` en `TIPOS_ESTUDIO`): sus ítems
    llevan la plata real del espacio/promo directo en `subtotal`
    (`cobro_modo='fijo'`, ver `routes/estudio.py`), no un `precio_jornada`
    recalculable desde jornadas/descuentos — recalcular acá pisaría
    `monto_total` a partir de esos subtotales con la fórmula de un alquiler
    normal, rompiéndolo (bug vivo detectado en la auditoría de la economía
    del Estudio). Sus ítems y su plata se editan desde los endpoints propios
    de `routes/estudio.py`, que ya escriben `monto_total` directo.
    """
    p = conn.execute("SELECT * FROM alquileres WHERE id=%s FOR UPDATE", (id,)).fetchone()
    if not p:
        return
    if es_pedido_estudio(p):
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

    Pedidos del Estudio (`tipo` en `TIPOS_ESTUDIO`): un cambio de fecha/hora
    real se rechaza (409) — este endpoint nunca revalida stock (ni el genérico
    ni el buffer propio del espacio; ver `update_pedido_datos`), así que
    aplicarlo sin más movería un turno confirmado a una franja ya ocupada sin
    ningún chequeo. Notas/cliente/etc. pasan igual (`_recalcular_total_pedido`
    ya es no-op para este tipo). Reprogramar un turno real es un endpoint
    propio de `routes/estudio.py` (revalida `_centinela_libre`/motor).
    """
    p = conn.execute("SELECT * FROM alquileres WHERE id=%s FOR UPDATE", (id,)).fetchone()
    if not p:
        raise HTTPException(404, "Pedido no encontrado")

    payload = {k: v for k, v in data.model_dump(exclude_unset=True).items()}
    # Columnas TIMESTAMP: '' rompe el cast → normalizar a NULL.
    for _k in ("fecha_desde", "fecha_hasta"):
        if _k in payload and not payload[_k]:
            payload[_k] = None

    if es_pedido_estudio(p) and (
        ("fecha_desde" in payload and _fecha_cambia(p["fecha_desde"], payload["fecha_desde"]))
        or ("fecha_hasta" in payload and _fecha_cambia(p["fecha_hasta"], payload["fecha_hasta"]))
    ):
        raise HTTPException(
            409,
            "Las fechas de un pedido del Estudio se reprograman desde Admin → Estudio "
            "(para revalidar la disponibilidad del espacio).",
        )

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
            propio = conn.execute(
                "SELECT 1 FROM cliente_perfiles_fiscales WHERE id = %s AND cliente_id = %s",
                (payload["perfil_fiscal_id"], cliente_efectivo),
            ).fetchone()
            if not propio:
                raise HTTPException(404, "Perfil fiscal no encontrado para este cliente.")
        if payload.get("productora_id"):
            vinculado = conn.execute(
                "SELECT 1 FROM productora_miembros WHERE productora_id = %s AND cliente_id = %s",
                (payload["productora_id"], cliente_efectivo),
            ).fetchone()
            if not vinculado:
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


def _apply_pedido_items(conn, id: int, items: list["PedidoItem"]) -> dict:
    """Reemplaza los ítems del pedido por `items`. Recalcula subtotales y monto.

    No valida stock — el caller debe llamar a `_check_stock` si corresponde.
    Lógica compartida entre admin y portal cliente.

    `FOR UPDATE`: lockea la fila del pedido — mismo motivo que
    `_recalcular_total_pedido` (evitar lost-update entre dos escritores
    concurrentes del mismo pedido).

    Rechaza pedidos del Estudio (`tipo` en `TIPOS_ESTUDIO`, 409): este
    reemplazo reconstruye subtotales con la fórmula de un alquiler normal
    (jornadas × precio de catálogo) y perdería el ítem centinela que bloquea
    el espacio — sus ítems se editan desde `routes/estudio.py`.
    """
    p = conn.execute("SELECT * FROM alquileres WHERE id=%s FOR UPDATE", (id,)).fetchone()
    if not p:
        raise HTTPException(404, "Pedido no encontrado")
    if es_pedido_estudio(p):
        raise HTTPException(
            409, "Los ítems de un pedido del Estudio se editan desde Admin → Estudio."
        )
    if not items:
        raise HTTPException(400, "Debe tener al menos un ítem")

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
                "cobro_modo": "jornada",
            })

    # `orden` por posición; subtotal por línea vía `bruto_linea` (respeta cobro_modo).
    rows = []
    for orden, ln in enumerate(lineas):
        if ln["equipo_id"] is not None:
            eq = conn.execute(
                "SELECT id, tipo FROM equipos WHERE id=%s", (ln["equipo_id"],)
            ).fetchone()
            if not eq:
                raise HTTPException(404, f"Equipo {ln['equipo_id']} no encontrado")
            # `es_combo` (Fase C-3, #1219): no acumula el descuento global — ya
            # trae el suyo propio horneado en `precio_jornada`.
            ln["es_combo"] = eq["tipo"] == "combo"
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


