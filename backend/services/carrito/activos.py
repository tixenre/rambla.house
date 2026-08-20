"""Carritos activos — la lógica del estado server-side del carrito (#280 Fases 1 + 2 + 2.5).

Submódulo de `services.carrito` (F4, epic #1110). Move-verbatim de la lógica que vivía
en `routes/carritos.py`: el route quedó FINO (parsea / autentica / delega) y acá vive el
cuerpo — heartbeat (upsert), cierre del funnel, listado + métricas para el back-office.

Patrón del repo: route = transporte, service = lógica (funciones que reciben `conn`, no
objetos con estado). El conflicto de stock se calcula READ-ONLY reusando el motor de
reservas (`reservas.calcular_disponibilidad`) y la plata vía `services.precios` — nunca
con lógica de overlap/precio propia (MEMORIA 2026-05-30 / motores = fuente única).
"""

import json
import logging
from typing import Optional

from database import get_db, row_to_dict

logger = logging.getLogger(__name__)

# Un carrito sin actividad por más de esto se considera abandonado (se le estampa
# `abandonado_en` la primera vez que lo detectamos; un heartbeat nuevo lo limpia).
ABANDONO_HORAS = 24


def heartbeat_upsert(
    conn,
    session_id: str,
    items: list,
    fecha_desde: Optional[str],
    fecha_hasta: Optional[str],
    hora_desde: Optional[str],
    hora_hasta: Optional[str],
    cliente_id: Optional[int],
) -> None:
    """Persiste el estado del carrito via upsert por session_id.

    `items` es la lista de ítems del request (cada uno con `.equipo_id` y `.cantidad`).
    El `conn` lo abre y commitea el route. La asociación de cliente y la validación del
    session_id son responsabilidad del route (transporte).
    """
    total_items = sum(it.cantidad for it in items)
    monto_estimado = 0

    if items:
        enriched, monto_estimado = _enrich_items(items, fecha_desde, fecha_hasta)
    else:
        enriched = []

    items_json = json.dumps(enriched)

    conn.execute(
        """
        INSERT INTO carritos_activos (
            session_id, cliente_id, items_json,
            fecha_desde, fecha_hasta, hora_desde, hora_hasta,
            total_items, monto_estimado, updated_at
        ) VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (session_id) DO UPDATE SET
            cliente_id     = COALESCE(EXCLUDED.cliente_id, carritos_activos.cliente_id),
            items_json     = EXCLUDED.items_json,
            fecha_desde    = EXCLUDED.fecha_desde,
            fecha_hasta    = EXCLUDED.fecha_hasta,
            hora_desde     = EXCLUDED.hora_desde,
            hora_hasta     = EXCLUDED.hora_hasta,
            total_items    = EXCLUDED.total_items,
            monto_estimado = EXCLUDED.monto_estimado,
            abandonado_en  = NULL,
            updated_at     = NOW()
        """,
        (
            session_id,
            cliente_id,
            items_json,
            fecha_desde,
            fecha_hasta,
            hora_desde,
            hora_hasta,
            total_items,
            monto_estimado,
        ),
    )


def _enrich_items(
    items: list,
    fecha_desde: Optional[str],
    fecha_hasta: Optional[str],
) -> tuple[list[dict], int]:
    """Enriquece items con nombre del equipo y calcula monto estimado neto.

    Devuelve (lista_enriquecida, monto_estimado_ars).
    """
    from services.precios import calcular_total, jornadas_periodo, ItemPrecio, precio_jornada_efectivo
    from database import to_datetime

    d0 = to_datetime(fecha_desde) if fecha_desde else None
    d1 = to_datetime(fecha_hasta) if fecha_hasta else None
    jornadas = jornadas_periodo(d0, d1)

    enriched: list[dict] = []
    items_precio: list[ItemPrecio] = []

    with get_db() as conn:
        for it in items:
            # alias `e` por convención de queries sobre equipos (MEMORIA 2026-05-26)
            row = conn.execute(
                "SELECT e.nombre FROM equipos e WHERE e.id = %s",
                (it.equipo_id,),
            ).fetchone()
            nombre = row["nombre"] if row else str(it.equipo_id)
            # Precio EFECTIVO por la fuente única (MEMORIA 2026-06-29): un combo
            # NO tiene `precio_jornada` propio (es NULL, se deriva de sus
            # componentes) — leer la columna cruda lo dejaba en 0 y el combo se
            # descartaba del estimado/pipeline del dashboard admin (bug hallado
            # por auditoría de plata). Fetch por-ítem (no batch): el batch
            # `IN (...)` de #643 en `/api/cotizar` devolvió el mapa de precios
            # vacío en prod → total $0; acá el carrito es chico (no hot-path)
            # y no vale ese riesgo.
            precio = int(precio_jornada_efectivo(conn, it.equipo_id) or 0)

            enriched.append({
                "equipo_id": it.equipo_id,
                "cantidad":  it.cantidad,
                "nombre":    nombre,
            })
            if precio > 0:
                items_precio.append({
                    "equipo_id":     it.equipo_id,
                    "cantidad":      it.cantidad,
                    "precio_jornada": precio,
                    "cobro_modo":    "jornada",
                })

    if not items_precio:
        return enriched, 0

    desglose = calcular_total(items=items_precio, jornadas=jornadas)
    return enriched, desglose["neto"]


def marcar_confirmado(session_id: str, conn) -> None:
    """Cierra el funnel: marca el carrito como confirmado al crear el pedido.

    UPSERT, no un UPDATE plano: el heartbeat del carrito viaja por `fetch`
    sin `await` (fire-and-forget, mismo patrón que el heartbeat de
    inscripción a talleres) — puede llegar a la base DESPUÉS de este commit
    (red lenta). Con un UPDATE simple, esa llegada tardía no encontraba fila
    (todavía no existía) y el heartbeat posterior insertaba una fila nueva
    `confirmado=FALSE` para un carrito que YA se convirtió en pedido —
    aparecía como "activo/abandonado" en el dashboard pese a estar cerrado
    (mismo bug de fondo que talleres_borrador.marcar_confirmado, 2026-08-20).
    El upsert garantiza `confirmado=TRUE` sin importar el orden de llegada:
    el heartbeat que llegue después solo actualiza items/fechas/montos,
    nunca toca `confirmado` (no está en su propio `SET`)."""
    conn.execute(
        """
        INSERT INTO carritos_activos (session_id, confirmado, updated_at)
        VALUES (%s, TRUE, NOW())
        ON CONFLICT (session_id) DO UPDATE SET
            confirmado = TRUE,
            updated_at = NOW()
        """,
        (session_id,),
    )


def listar_carritos_admin(conn, horas: int = 72) -> dict:
    """Lista carritos activos + métricas de funnel para el back-office.

    Devuelve, en una sola respuesta para que el dashboard refresque en un solo
    loop: la lista de carritos no confirmados (con flag de abandono y conflicto
    de stock por carrito), KPIs del funnel, ranking de demanda latente y la
    serie de carritos creados/confirmados por día.

    El parámetro `horas` amplía la ventana de la lista (ej. ?horas=168 = 7 días).
    El `conn` lo abre el route; la autenticación de admin también vive en el route.
    """
    from reservas.disponibilidad import calcular_disponibilidad

    # Estampar abandono: la primera vez que un carrito cruza el umbral sin
    # actividad le ponemos `abandonado_en`. Idempotente; un heartbeat nuevo
    # lo limpia (ver upsert). Es bookkeeping barato sobre el índice de updated_at.
    conn.execute(
        """
        UPDATE carritos_activos
        SET abandonado_en = NOW()
        WHERE NOT confirmado
          AND abandonado_en IS NULL
          AND total_items > 0
          AND updated_at < NOW() - (%s || ' hours')::interval
        """,
        (str(ABANDONO_HORAS),),
    )
    conn.commit()

    rows = conn.execute(
        """
        SELECT
            ca.id,
            ca.session_id,
            ca.cliente_id,
            cl.nombre       AS cliente_nombre,
            cl.email        AS cliente_email,
            cl.telefono     AS cliente_telefono,
            ca.items_json,
            ca.fecha_desde,
            ca.fecha_hasta,
            ca.hora_desde,
            ca.hora_hasta,
            ca.total_items,
            ca.monto_estimado,
            ca.confirmado,
            ca.abandonado_en,
            ca.created_at,
            ca.updated_at
        FROM carritos_activos ca
        LEFT JOIN clientes cl ON cl.id = ca.cliente_id
        WHERE NOT ca.confirmado
          AND ca.total_items > 0
          AND ca.updated_at > NOW() - (%s || ' hours')::interval
        ORDER BY ca.updated_at DESC
        LIMIT 200
        """,
        (str(horas),),
    ).fetchall()

    carritos = []
    for r in rows:
        d = row_to_dict(r)
        raw = d.pop("items_json")
        d["items"] = raw if isinstance(raw, list) else json.loads(raw or "[]")
        d["abandonado"] = d.pop("abandonado_en", None) is not None
        carritos.append(d)

    # Conflicto de stock por carrito (READ-ONLY, motor de reservas). Cacheamos
    # la disponibilidad por par de fechas para no recalcular el motor por carrito.
    disp_cache: dict[tuple[str, str], dict] = {}
    for c in carritos:
        fd, fh = c.get("fecha_desde"), c.get("fecha_hasta")
        if not fd or not fh:
            c["sin_stock"] = False
            continue
        fd, fh = str(fd), str(fh)
        key = (fd, fh)
        if key not in disp_cache:
            disp_cache[key] = calcular_disponibilidad(conn, fd, fh)
        disp = disp_cache[key]
        sin_stock = False
        for it in c["items"]:
            libres = disp.get(str(it["equipo_id"]))
            it["disponible"] = libres
            if libres is not None and it.get("cantidad", 0) > libres:
                sin_stock = True
        c["sin_stock"] = sin_stock

    stats = _calcular_stats(conn, carritos)
    demanda = _calcular_demanda(carritos)
    por_dia = _carritos_por_dia(conn)

    return {
        "carritos": carritos,
        "total": len(carritos),
        "stats": stats,
        "demanda": demanda,
        "por_dia": por_dia,
    }


def _calcular_stats(conn, carritos: list[dict]) -> dict:
    """KPIs del funnel: pipeline, identificación, abandono y conversión 7d."""
    activos = len(carritos)
    pipeline_ars = sum(int(c.get("monto_estimado") or 0) for c in carritos)
    identificados = sum(1 for c in carritos if c.get("cliente_id"))
    abandonados = sum(1 for c in carritos if c.get("abandonado"))

    # Conversión de los últimos 7 días: confirmados / creados (con items).
    row = conn.execute(
        """
        SELECT
            COUNT(*)                              AS creados,
            COUNT(*) FILTER (WHERE confirmado)    AS confirmados
        FROM carritos_activos
        WHERE total_items > 0
          AND created_at > NOW() - INTERVAL '7 days'
        """
    ).fetchone()
    creados_7d = int(row["creados"] or 0)
    confirmados_7d = int(row["confirmados"] or 0)
    conversion_pct = round(100.0 * confirmados_7d / creados_7d, 1) if creados_7d else 0.0

    return {
        "activos": activos,
        "pipeline_ars": pipeline_ars,
        "identificados": identificados,
        "anonimos": activos - identificados,
        "abandonados": abandonados,
        "creados_7d": creados_7d,
        "confirmados_7d": confirmados_7d,
        "conversion_pct": conversion_pct,
    }


def _calcular_demanda(carritos: list[dict]) -> list[dict]:
    """Ranking de demanda latente: equipos más presentes en carritos activos.

    Por equipo: en cuántos carritos aparece (`carritos`) y cuántas unidades se
    piden en total (`unidades`). Ordenado por presencia y luego por unidades.
    """
    agg: dict[int, dict] = {}
    for c in carritos:
        for it in c.get("items", []):
            eid = it.get("equipo_id")
            if eid is None:
                continue
            a = agg.setdefault(
                eid, {"equipo_id": eid, "nombre": it.get("nombre") or str(eid), "carritos": 0, "unidades": 0}
            )
            a["carritos"] += 1
            a["unidades"] += int(it.get("cantidad") or 0)
    ranking = sorted(agg.values(), key=lambda a: (a["carritos"], a["unidades"]), reverse=True)
    return ranking[:10]


def _carritos_por_dia(conn) -> list[dict]:
    """Serie de los últimos 14 días: carritos creados y confirmados por día."""
    rows = conn.execute(
        """
        SELECT
            to_char(created_at, 'YYYY-MM-DD')   AS dia,
            COUNT(*)                            AS creados,
            COUNT(*) FILTER (WHERE confirmado)  AS confirmados
        FROM carritos_activos
        WHERE total_items > 0
          AND created_at > NOW() - INTERVAL '14 days'
        GROUP BY to_char(created_at, 'YYYY-MM-DD')
        ORDER BY to_char(created_at, 'YYYY-MM-DD')
        """
    ).fetchall()
    return [
        {"dia": r["dia"], "creados": int(r["creados"] or 0), "confirmados": int(r["confirmados"] or 0)}
        for r in rows
    ]
