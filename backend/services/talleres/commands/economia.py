"""Economía de una edición de taller — move-verbatim desde `routes/talleres.py`.

Nuevo miembro de la familia motor-único (MEMORIA 2026-07-24): espeja
`_regenerar_pedidos_slot` (`routes/estudio.py`) — mismo patrón conserva-
pasados/pagados + borra-y-recrea-futuros-impagos, adaptado a talleres.
"""
import calendar as _cal
from datetime import date as _dt_date

from database import to_datetime
from services.estudio.queries.estudio import _get_estudio_row
from services.fechas import MESES_ES, iter_meses, mes_actual_ar

from services.talleres.constants import _ADVISORY_NS_TALLER
from services.talleres.queries.economia import _revenue_inscriptos, _valor_efectivo


def _regenerar_pedidos_taller(conn, edicion: dict, taller_nombre: str, *, numero_pedido_fn) -> None:
    """(Re)genera un pedido `tipo='taller'` por mes del rango de la edición.
    Espeja `_regenerar_pedidos_slot`: preserva pasados/pagados, borra y recrea
    futuros impagos. Fix propio: también preserva un mes cuyo pedido tiene MÁS
    ítems que los que este generador crearía — protege la línea de matrícula
    que el admin tipeó a mano de un borrado silencioso en el próximo recálculo.

    `numero_pedido_fn`: inyectado en vez de importar `_next_numero_pedido` de
    `routes.alquileres` (el paquete no importa de `routes.*` — mismo patrón
    "valor ya resuelto como parámetro" de `services/estudio/CLAUDE.md`,
    extendido acá a una función porque el loop necesita un valor fresco por
    pedido, no uno solo)."""
    edicion_id = edicion["id"]
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_ADVISORY_NS_TALLER, edicion_id))

    mes_actual = mes_actual_ar()
    n_items_auto = max(1, int(edicion["usa_estudio"]) + int(edicion["usa_equipos"]))

    existentes = conn.execute(
        """
        SELECT a.id, a.fecha_desde, a.monto_pagado,
               (SELECT COUNT(*) FROM alquiler_items i WHERE i.pedido_id = a.id) AS n_items
        FROM alquileres a WHERE a.taller_edicion_id = %s
        """,
        (edicion_id,),
    ).fetchall()

    conservados: set[str] = set()
    for e in existentes:
        fd = to_datetime(e["fecha_desde"])
        mes_e = f"{fd.year:04d}-{fd.month:02d}"
        if mes_e < mes_actual or (e["monto_pagado"] or 0) > 0 or e["n_items"] > n_items_auto:
            conservados.add(mes_e)  # pasado, pagado o con más ítems de los que auto-generamos → intocable
        else:
            conn.execute("DELETE FROM alquileres WHERE id = %s", (e["id"],))

    if not edicion["activo"]:
        return

    fecha_inicio: _dt_date = edicion["fecha_inicio"]
    fecha_fin: _dt_date = edicion["fecha_fin"]
    meses = list(iter_meses(
        f"{fecha_inicio.year:04d}-{fecha_inicio.month:02d}",
        f"{fecha_fin.year:04d}-{fecha_fin.month:02d}",
    ))
    n_meses = len(meses)
    ultimo = meses[-1]

    def _partes(total: int, modo: str) -> dict:
        if modo != "total":
            return {clave: total for clave in meses}
        base, resto = divmod(total, n_meses)
        return {clave: (base + resto if clave == ultimo else base) for clave in meses}

    # `_tipo` ('fijo'|'porcentaje') resuelve el TOTAL antes de repartirlo entre
    # meses — `_partes`/`_modo` no cambian: siguen repartiendo el mismo total,
    # venga de un monto tipeado o de un % sobre lo que pagan los inscriptos.
    revenue = (
        _revenue_inscriptos(conn, edicion_id)
        if edicion["valor_estudio_tipo"] == "porcentaje" or edicion["valor_equipos_tipo"] == "porcentaje"
        else 0
    )
    valor_estudio_efectivo = _valor_efectivo(
        edicion["valor_estudio_tipo"], edicion["valor_estudio"], edicion["valor_estudio_pct"], revenue
    )
    valor_equipos_efectivo = _valor_efectivo(
        edicion["valor_equipos_tipo"], edicion["valor_equipos"], edicion["valor_equipos_pct"], revenue
    )

    valores_estudio = _partes(valor_estudio_efectivo, edicion["valor_estudio_modo"]) if edicion["usa_estudio"] else {}
    valores_equipos = _partes(valor_equipos_efectivo, edicion["valor_equipos_modo"]) if edicion["usa_equipos"] else {}
    estudio = _get_estudio_row(conn) if edicion["usa_estudio"] else None

    for (y, m) in meses:
        mes = f"{y:04d}-{m:02d}"
        if mes < mes_actual or mes in conservados:
            continue
        _, last_day = _cal.monthrange(y, m)
        fd = max(_dt_date(y, m, 1), fecha_inicio)
        fh = min(_dt_date(y, m, last_day), fecha_fin)
        mes_label = f"{MESES_ES[m - 1]} {y}"
        valor_est = valores_estudio.get((y, m), 0)
        valor_eq = valores_equipos.get((y, m), 0)

        pedido_id = conn.insert_returning(
            """
            INSERT INTO alquileres (cliente_nombre, fecha_desde, fecha_hasta, monto_total,
                                    estado, fuente, tipo, numero_pedido, taller_edicion_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (f"Taller {taller_nombre} — {mes_label}", fd, fh, valor_est + valor_eq,
             "confirmado", "taller", "taller", numero_pedido_fn(conn), edicion_id),
        )
        if edicion["usa_estudio"]:
            conn.execute(
                """
                INSERT INTO alquiler_items
                    (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
                VALUES (%s,%s,1,%s,%s,'fijo')
                """,
                (pedido_id, estudio["equipo_id"], valor_est, valor_est),
            )
        if edicion["usa_equipos"]:
            conn.execute(
                """
                INSERT INTO alquiler_items
                    (pedido_id, equipo_id, nombre_libre, cantidad, precio_jornada, subtotal, cobro_modo)
                VALUES (%s,NULL,%s,1,%s,%s,'fijo')
                """,
                (pedido_id, f"Uso de equipos — {taller_nombre}", valor_eq, valor_eq),
            )
        if not edicion["usa_estudio"] and not edicion["usa_equipos"]:
            conn.execute(
                """
                INSERT INTO alquiler_items
                    (pedido_id, equipo_id, nombre_libre, cantidad, precio_jornada, subtotal, cobro_modo)
                VALUES (%s,NULL,%s,1,0,0,'fijo')
                """,
                (pedido_id, f"Taller {taller_nombre} — {mes_label}"),
            )
