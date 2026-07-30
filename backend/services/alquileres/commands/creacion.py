"""Creación de un pedido — Fase 4 del split CQRS-lite de `routes/alquileres/` (#1312).

Move-verbatim desde `routes/alquileres/core.py`: `create_pedido`/`create_pedido_retry`
+ el namespace del advisory lock (`_ADVISORY_NS_PEDIDO`, BYTE-IDÉNTICO — no se
reordena el lock-antes-de-insertar ni el manejo de `DeadlockDetected`). Es la
ÚNICA puerta de creación de pedidos (admin y portal cliente). `routes/alquileres/
core.py` re-exporta `create_pedido`/`create_pedido_retry` TAL CUAL para no romper
`routes/alquileres/__init__.py` ni `routes/cliente_portal/pedidos.py`.
"""
import logging
import time
from typing import Optional, TYPE_CHECKING

import psycopg.errors

from fastapi import BackgroundTasks, HTTPException

from database import get_db
from clientes.queries.identidad import nombre_completo_cliente
from services.fechas import validar_rango_fechas
from services.alquileres.commands.items import _apply_pedido_items
from services.alquileres.commands.pedido import _next_numero_pedido
from services.alquileres.queries.cotizacion import (
    _cliente_es_dueno_de_perfil_fiscal,
    _cliente_es_miembro_de_productora,
)
from services.alquileres.queries.detalle import _get_alquiler_detail
from services.pedidos_notificaciones import _dispatch_pedido_creado_emails
from reservas import validar_stock as _check_stock

# El modelo Pydantic (contrato HTTP) se queda en routes/alquileres/modelos.py
# (no se mueve en ninguna fase) — acá solo hace falta como forward-ref para el
# type hint, nunca en runtime (mismo criterio que services/alquileres/commands/items.py).
if TYPE_CHECKING:
    from routes.alquileres.modelos import PedidoCreate

logger = logging.getLogger(__name__)

# Namespace (clave1 de `pg_advisory_xact_lock`) para serializar creación de
# pedidos por equipo. Arbitrario y privado de este flujo; evita colisión con
# otros advisory locks de la app.
_ADVISORY_NS_PEDIDO = 5390412


def create_pedido(data: "PedidoCreate", background: Optional[BackgroundTasks] = None,
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
                if not _cliente_es_dueno_de_perfil_fiscal(_conn, data.cliente_id, data.perfil_fiscal_id):
                    raise HTTPException(404, "Perfil fiscal no encontrado para este cliente.")
            if data.productora_id:
                if not _cliente_es_miembro_de_productora(_conn, data.cliente_id, data.productora_id):
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
            # Un BORRADOR nace SIN número de pedido: es un presupuesto rápido
            # (decisión del dueño), no una venta — no debe consumir un número de
            # la secuencia ni parecer un pedido real en pantalla. Lo recibe recién
            # cuando pasa a un estado real de `FLOW`
            # (`transiciones.cambiar_estado`). El resto de los pedidos lo reciben
            # acá, como siempre.
            next_num = None if estado_inicial == "borrador" else _next_numero_pedido(conn)
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
            #
            # `_apply_pedido_items` YA arma (y devuelve) el detalle completo del
            # pedido — se reusa acá en vez de descartarlo y recalcularlo después
            # del commit (hallazgo de auditoría #1313/#1314: nada muta el pedido
            # entre este punto y el commit salvo el chequeo de stock, que no
            # escribe nada, así que el detalle no puede quedar stale). Ahorra una
            # segunda armada completa (~6-8 queries) en la creación más común, y
            # de paso achica el tiempo sosteniendo el advisory lock de arriba.
            pedido = _apply_pedido_items(conn, pedido_id, data.items) if data.items else None

            if estado_inicial == "solicitado" and data.fecha_desde and data.fecha_hasta:
                problemas = _check_stock(conn, pedido_id, data.fecha_desde, data.fecha_hasta)
                if problemas:
                    raise HTTPException(409, "Sin stock: " + "; ".join(problemas))

            conn.commit()
            if pedido is None:
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


def create_pedido_retry(data: "PedidoCreate", background: Optional[BackgroundTasks] = None,
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
