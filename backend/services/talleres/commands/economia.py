"""Economía de una edición de taller — move-verbatim desde `routes/talleres.py`.

Nuevo miembro de la familia motor-único (MEMORIA 2026-07-24): espeja
`_regenerar_pedidos_slot` (`routes/estudio.py`) — mismo patrón conserva-
pasados/pagados + borra-y-recrea-futuros-impagos, adaptado a talleres.
"""
import calendar as _cal
from datetime import date as _dt_date, datetime, timedelta

from fastapi import HTTPException

from database import to_datetime
from services.estudio.commands.reserva import _insertar_item_centinela
from services.estudio.queries.disponibilidad import _centinela_libre
from services.estudio.queries.estudio import _get_estudio_row
from services.fechas import MESES_ES, iter_meses, mes_actual_ar

from services.talleres.constants import _ADVISORY_NS_TALLER
from services.talleres.queries.clases import clases_de_edicion
from services.talleres.queries.economia import _revenue_inscriptos, _valor_efectivo


def _fecha_hora_clase(clase: dict) -> tuple[datetime, datetime]:
    """Arma el rango datetime real de una clase — fecha (string 'YYYY-MM-DD')
    + hora_inicio_min/hora_fin_min (minutos desde medianoche), mismo shape
    que devuelve `clases_de_edicion` (`services/talleres/queries/clases.py::
    _clase_dict`)."""
    dia = _dt_date.fromisoformat(clase["fecha"])
    inicio_dia = datetime.combine(dia, datetime.min.time())
    return (
        inicio_dia + timedelta(minutes=clase["hora_inicio_min"]),
        inicio_dia + timedelta(minutes=clase["hora_fin_min"]),
    )


def _crear_turnos_taller_del_mes(
    conn, pedido_id: int, estudio: dict, clases_del_mes: list[dict], valor_total: int,
) -> None:
    """Un turno embebido del Estudio POR CADA CLASE real del mes (pedido
    explícito del dueño, 2026-08-13: reusar "Turnos del Estudio" —#1308— con
    fecha/hora reales copiadas de `clases_taller`, en vez de una línea
    "Estudio (espacio)" plana cubriendo el mes contable entero).

    NO usa `agregar_turno_embebido` (`services/estudio/commands/reserva.py`):
    esa función exige `pedido["tipo"] == "diaria"` y pisa `fecha_desde`/
    `fecha_hasta` DEL PEDIDO CONTENEDOR vía `sincronizar_fechas_con_turnos`
    — un pedido de taller tiene su PROPIO significado de esas dos columnas
    (el mes contable completo, ver el docstring de `_regenerar_pedidos_taller`)
    que no se puede pisar. Acá se reusan los primitivos de más bajo nivel
    (mismo orden lock-antes-de-insertar que `agregar_turno_embebido`: `FOR
    UPDATE` sobre el centinela → `_centinela_libre` → recién ahí el INSERT)
    sin la capa de arriba que no aplica a un pedido de taller.

    El monto YA RESUELTO (fijo o %, `_valor_efectivo` sigue siendo la única
    fuente — esta función no decide cuánto cobrar, solo cómo repartirlo) se
    divide en partes iguales entre las clases, remanente de redondeo en la
    ÚLTIMA (mismo criterio que `_partes`, más abajo)."""
    n = len(clases_del_mes)
    if n == 0:
        return
    base, resto = divmod(valor_total, n)
    for i, clase in enumerate(clases_del_mes):
        fecha_desde, fecha_hasta = _fecha_hora_clase(clase)
        monto = base + (resto if i == n - 1 else 0)
        conn.execute("SELECT id FROM equipos WHERE id = %s FOR UPDATE", (estudio["equipo_id"],))
        if not _centinela_libre(
            conn, estudio["equipo_id"], fecha_desde, fecha_hasta, estudio["buffer_horas"],
        ):
            raise HTTPException(
                409, f"El estudio no está disponible para la clase del {clase['fecha']}"
            )
        turno_id = conn.insert_returning(
            "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) VALUES (%s,%s,%s)",
            (pedido_id, fecha_desde, fecha_hasta),
        )
        _insertar_item_centinela(conn, pedido_id, estudio["equipo_id"], monto, turno_estudio_id=turno_id)


def _regenerar_pedidos_taller(conn, edicion: dict, taller_nombre: str, *, numero_pedido_fn) -> None:
    """(Re)genera el pedido `tipo='taller'` del MES ACTUAL de la edición —
    nunca los meses futuros por adelantado (pedido explícito del dueño,
    2026-08-13: no quiere N pedidos abiertos en simultáneo mucho antes de que
    corresponda cobrarlos). El disparador de "que aparezca el del mes nuevo"
    es el barrido diario `jobs/regenerar_pedidos_talleres.py`, que llama a
    ESTA MISMA función — no hay una segunda implementación.

    Espeja `_regenerar_pedidos_slot`: preserva pasados/pagados, borra y recrea
    el actual si no está pagado (ej. el admin cambió la Economía a mitad de
    mes). Fix propio: también preserva un mes cuyo pedido tiene MÁS ítems que
    los que este generador crearía — protege la línea de matrícula que el
    admin tipeó a mano de un borrado silencioso en el próximo recálculo.

    `_partes`/`_modo`/`_tipo` (fijo/porcentaje) siguen calculando el reparto
    completo entre TODOS los meses del rango (sin eso el remanente de "total"
    no ancla bien al mes calendario) — lo único que cambia es que acá solo se
    INSERTA la fila del mes actual; el resto del dict `valores_estudio`/
    `valores_equipos` se calcula pero no se usa todavía, hasta que le toque.

    `numero_pedido_fn`: inyectado en vez de importar `_next_numero_pedido` de
    `routes.alquileres` (el paquete no importa de `routes.*` — mismo patrón
    "valor ya resuelto como parámetro" de `services/estudio/CLAUDE.md`,
    extendido acá a una función porque el loop necesita un valor fresco por
    pedido, no uno solo).

    Estudio: turno embebido POR CLASE real, no una línea plana (pedido
    explícito del dueño, 2026-08-13). `valor_estudio_efectivo` del mes se
    reparte en partes iguales entre las clases reales de ESE mes (ver
    `_crear_turnos_taller_del_mes`) — si el mes todavía no tiene clases
    cargadas, cae a la línea plana de siempre (fallback, no se pierde la
    plata). `_n_items_auto` (antes una constante fija) ahora varía por mes
    porque el número de ítems "auto" ya no es siempre el mismo."""
    edicion_id = edicion["id"]
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_ADVISORY_NS_TALLER, edicion_id))

    mes_actual = mes_actual_ar()

    # Clases reales agrupadas por mes ("YYYY-MM", mismo slice que `clase["fecha"]`
    # ya trae) — hace falta ANTES del loop de conservación: `n_items_auto` ahora
    # varía por mes (1 turno-embebido por clase, no 1 ítem plano fijo).
    clases_por_mes: dict[str, list[dict]] = {}
    if edicion["usa_estudio"]:
        for clase in clases_de_edicion(conn, edicion_id):
            clases_por_mes.setdefault(clase["fecha"][:7], []).append(clase)

    def _n_items_auto(mes: str) -> int:
        """Cuántos ítems genera ESTE módulo para `mes` si lo regenerara de
        cero — 1 turno-embebido por clase real de ese mes (o 1 ítem plano de
        fallback si `usa_estudio` pero el mes no tiene clases cargadas
        todavía) + 1 si `usa_equipos`, piso 1 (el placeholder de "ninguno de
        los dos")."""
        n_estudio = len(clases_por_mes.get(mes, [])) if edicion["usa_estudio"] else 0
        if edicion["usa_estudio"] and n_estudio == 0:
            n_estudio = 1  # fallback plano — ver la rama de generación más abajo
        return max(1, n_estudio + int(edicion["usa_equipos"]))

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
        if mes_e < mes_actual or (e["monto_pagado"] or 0) > 0 or e["n_items"] > _n_items_auto(mes_e):
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
        if mes != mes_actual or mes in conservados:
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
            clases_mes = clases_por_mes.get(mes, [])
            if clases_mes:
                # Un turno embebido POR CLASE real (pedido del dueño,
                # 2026-08-13) — ver `_crear_turnos_taller_del_mes`.
                _crear_turnos_taller_del_mes(conn, pedido_id, estudio, clases_mes, valor_est)
            else:
                # Fallback: todavía no hay clases cargadas para este mes (el
                # admin no terminó de armar la edición) — no se puede repartir
                # entre clases que no existen, así que la plata no se pierde:
                # cae al ítem plano de siempre. `_n_items_auto` ya cuenta este
                # caso como 1 ítem (ver arriba).
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
