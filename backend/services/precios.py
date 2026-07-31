"""services/precios.py — Cálculo canónico de totales de pedidos.

Una sola fuente de verdad para el cálculo del total de un pedido. Lo
consumen los 3 sitios que lo calculaban distinto:

- ``routes.alquileres.create_pedido``
- ``routes.alquileres._apply_pedido_datos``
- ``routes.alquileres._apply_pedido_items``  (← este perdía el descuento por jornadas → bug #500)

y también el PDF (``pdf.py``), que recomputaba a mano sin descuento y con
jornadas truncadas (bug #502).

Modelo (alineado bit a bit con ``src/lib/cart-total.ts`` del front):

- Precios del catálogo son **netos** (sin IVA).
- Descuento NO acumulativo: gana el mayor entre las fuentes vigentes — la
  decisión de "quién gana" vive en ``descuentos.queries.decision.
  calcular_descuento_aplicable`` (paquete ``backend/descuentos/``, no acá).
- ``monto_total`` se PERSISTE neto (con descuento aplicado, sin IVA).
  El IVA es derivado al mostrar/facturar: solo para
  ``perfil_impuestos == 'responsable_inscripto'`` se suma 21%.

Tests: ``backend/tests/test_precios_service.py``.
"""

from __future__ import annotations

from math import ceil
from datetime import datetime
from typing import Optional, TypedDict

from descuentos.queries.decision import resolver_descuento_monto_pedido


IVA_PCT = 21.0
"""Alícuota de IVA (Argentina). Solo se aplica a Responsable Inscripto."""

PERFIL_RI = "responsable_inscripto"


# ── Tipos ────────────────────────────────────────────────────────────────


class ItemPrecio(TypedDict, total=False):
    """Forma mínima de un ítem para calcular total.

    `cobro_modo` (opcional, #805): 'jornada' (default — precio × cantidad ×
    jornadas, como los equipos del catálogo) o 'fijo' (monto único — precio ×
    cantidad, SIN multiplicar por jornadas; para líneas personalizadas tipo flete).
    `equipo_id` puede faltar/ser None en líneas personalizadas (no del catálogo).
    `es_combo` (opcional, Fase C-3 #1219, default False): la línea es un
    equipo `tipo='combo'` — ya trae su propio descuento por componente
    horneado en `precio_jornada` (`precio_combo`); el descuento GLOBAL
    (cliente/jornadas/manual) no se le vuelve a aplicar encima. Resolverlo es
    responsabilidad del caller (ver `tipos_equipo_batch`).
    """
    equipo_id: Optional[int]
    cantidad: int
    precio_jornada: int
    cobro_modo: str
    es_combo: bool


class TotalDesglose(TypedDict):
    bruto: int               # Σ(precio_jornada × cantidad × jornadas), TODAS las líneas
    bruto_descontable: int   # bruto SIN las líneas es_combo — el tope real del descuento manual en $ (C-3, #1219)
    descuento_pct: float     # % efectivo aplicado (el ganador de la jerarquía: manual > max(cliente, jornadas))
    descuento_monto: int     # bruto - neto
    neto: int                # bruto - descuento_monto — lo que se PERSISTE en monto_total
    con_iva: bool            # True si el perfil es responsable_inscripto
    iva_pct: float
    iva_monto: int           # 0 si no es RI
    total_final: int         # neto + iva_monto — lo que ve el cliente RI


# ── Funciones puras ──────────────────────────────────────────────────────


def jornadas_periodo(
    fecha_desde: Optional[datetime], fecha_hasta: Optional[datetime]
) -> int:
    """Cantidad de jornadas entre dos fechas.

    Fórmula canónica: ``ceil((hasta - desde) / 24h)``. Mínimo 1.
    Si falta alguna fecha o son iguales/invertidas devuelve 1.

    Esto reemplaza ``(d2 - d1).days`` (trunca, no cuenta jornadas con
    horas) que usaba ``pdf.py`` y daba una jornada de menos cuando había
    diferencia horaria.
    """
    if not fecha_desde or not fecha_hasta:
        return 1
    delta = fecha_hasta - fecha_desde
    horas = delta.total_seconds() / 3600
    if horas <= 0:
        return 1
    return max(1, ceil(horas / 24))


def es_responsable_inscripto(perfil_impuestos: Optional[str]) -> bool:
    """Predicado canónico para Factura A / IVA discriminado."""
    return (perfil_impuestos or "") == PERFIL_RI


def _precio_combo_calc(componentes) -> int:
    """Precio NETO por jornada de un combo: Σ(precio_componente × cantidad ×
    (1 − descuento_línea/100)), redondeado. PURO (testeable sin DB).

    `componentes`: iterable de filas con `precio_jornada`, `cantidad`,
    `descuento_pct` (el descuento por línea del combo, de `kit_componentes`)."""
    total = 0.0
    for c in componentes:
        precio = c["precio_jornada"] or 0
        cant = c["cantidad"] or 0
        desc = (c["descuento_pct"] or 0) / 100.0
        total += precio * cant * (1.0 - desc)
    return int(round(total))


def resolver_descuento_uniforme(componentes, precio_objetivo: int) -> float:
    """Dado un precio objetivo para un combo, resuelve el % de descuento UNIFORME
    (el mismo en cada línea) que hace que `_precio_combo_calc` devuelva ese precio
    exacto. PURA (testeable sin DB) — usada por el endpoint "precio objetivo" del
    combo (#1283, Fase 5), atajo para no tantear el % línea por línea a mano.

    Despejando de la fórmula de `_precio_combo_calc` (factor común `(1-d/100)`):
        precio_objetivo = bruto × (1 − d/100)  →  d = 100 × (1 − precio_objetivo/bruto)
    donde `bruto = Σ(precio_jornada × cantidad)` (el mismo total sin descontar).

    Lanza ValueError si no se puede resolver: sin componentes con precio (bruto
    <= 0, nada sobre lo que descontar) o si el objetivo supera el bruto (haría
    falta un descuento NEGATIVO — el mecanismo es un descuento, no un recargo).
    """
    bruto = sum((c["precio_jornada"] or 0) * (c["cantidad"] or 0) for c in componentes)
    if bruto <= 0:
        raise ValueError("Los componentes no tienen precio base sobre el que aplicar un descuento.")
    if precio_objetivo < 0:
        raise ValueError("El precio objetivo no puede ser negativo.")
    if precio_objetivo > bruto:
        raise ValueError(
            f"El precio objetivo (${precio_objetivo:,}) no puede superar la suma de "
            f"los componentes sin descuento (${bruto:,}) — el mecanismo es un descuento, "
            "no un recargo."
        )
    return 100.0 * (1.0 - precio_objetivo / bruto)


def precio_combo(conn, equipo_id: int) -> int:
    """C3 #635 — precio por jornada derivado de un COMBO: DINÁMICO (sigue el
    precio actual de cada componente) con el descuento por línea de cada uno.

    Lo usa `cotizar` para los equipos `tipo='combo'` en vez de su `precio_jornada`
    propio. Los kits y simples siguen con su precio propio (manual). Cómo compone
    este precio con los descuentos de cliente/jornada es decisión de negocio
    abierta (ver #635) — hoy se aplica como base y los demás descuentos stackean.
    """
    rows = conn.execute(
        "SELECT e.precio_jornada, kc.cantidad, kc.descuento_pct "
        "FROM kit_componentes kc JOIN equipos e ON e.id = kc.componente_id "
        "WHERE kc.equipo_id = %s AND e.eliminado_at IS NULL",
        (equipo_id,),
    ).fetchall()
    return _precio_combo_calc(rows)


def precios_combo_batch(conn, equipo_ids) -> dict[int, int]:
    """Precio efectivo por jornada de varios COMBOS en UNA sola query (evita N+1 en
    el catálogo). Devuelve `{equipo_id: precio_efectivo}` para los ids que tengan
    componentes vivos; un combo sin componentes no aparece (el caller cae a 0). Mismo
    cálculo que `precio_combo` (reusa `_precio_combo_calc`)."""
    ids = list(equipo_ids)
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT kc.equipo_id, e.precio_jornada, kc.cantidad, kc.descuento_pct "
        "FROM kit_componentes kc JOIN equipos e ON e.id = kc.componente_id "
        "WHERE kc.equipo_id = ANY(%s) AND e.eliminado_at IS NULL",
        (ids,),
    ).fetchall()
    por_combo: dict[int, list] = {}
    for r in rows:
        por_combo.setdefault(r["equipo_id"], []).append(r)
    return {eid: _precio_combo_calc(comps) for eid, comps in por_combo.items()}


def tipos_equipo_batch(conn, equipo_ids) -> dict[int, str]:
    """`tipo` (simple/kit/combo) de varios equipos en UNA sola query — evita N+1
    al resolver qué líneas son `es_combo` para `calcular_total` (Fase C-3,
    #1219: los combos no acumulan el descuento GLOBAL de cliente/jornadas/
    manual encima de su propio descuento por componente)."""
    ids = list(equipo_ids)
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT id, tipo FROM equipos WHERE id = ANY(%s)", (ids,)
    ).fetchall()
    return {r["id"]: r["tipo"] for r in rows}


def precios_efectivos_batch(conn, equipo_ids) -> dict[int, int]:
    """Precio por jornada EFECTIVO de varios equipos en UNA sola tanda de queries
    (evita N+1) — mismo cálculo que `precio_jornada_efectivo`, fila por fila:
    kit/simple → su `precio_jornada` propio; combo → `precios_combo_batch`. Un id
    inexistente/soft-deleted no aparece en el resultado (igual que
    `precio_jornada_efectivo` devuelve `None` para ese caso) — el caller decide
    el fallback.

    Usa `= ANY(%s)` (mismo patrón ya probado de `precios_combo_batch`/
    `tipos_equipo_batch`), NO un `IN (...)` armado a mano — ese fue el patrón que
    #643 revirtió en `/api/cotizar` (devolvió el mapa de precios vacío en prod,
    total $0). Dos queries totales sin importar cuántos ids, en vez de 1-2 por
    ítem."""
    ids = list(equipo_ids)
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT id, precio_jornada, tipo FROM equipos WHERE id = ANY(%s) AND eliminado_at IS NULL",
        (ids,),
    ).fetchall()
    combo_ids = [r["id"] for r in rows if r["tipo"] == "combo"]
    combo_precios = precios_combo_batch(conn, combo_ids) if combo_ids else {}
    return {
        r["id"]: combo_precios.get(r["id"], 0) if r["tipo"] == "combo" else int(r["precio_jornada"] or 0)
        for r in rows
    }


def precio_jornada_efectivo(conn, equipo_id: int) -> Optional[int]:
    """Precio por jornada EFECTIVO de un equipo, resuelto en UN solo lugar: para un
    COMBO se deriva en vivo de sus componentes (`precio_combo`, C3 #635); un kit/simple
    usa su `precio_jornada` propio. `None` si el equipo no existe (o está soft-deleted).

    Fuente ÚNICA de "qué precio por jornada toma este equipo": la consumen `cotizar`,
    `cliente_crear_pedido` y `cliente_modificar_pedido` → lo que el carrito COTIZA es lo
    que se PERSISTE (cierra el drift de combos cotizado≠cobrado). El gate de seguridad
    "solo equipos de catálogo / el cliente no decide el precio" vive en cada consumidor,
    no acá — esto solo resuelve plata.
    """
    row = conn.execute(
        "SELECT precio_jornada, tipo FROM equipos WHERE id = %s AND eliminado_at IS NULL",
        (equipo_id,),
    ).fetchone()
    if not row:
        return None
    if row["tipo"] == "combo":
        return precio_combo(conn, equipo_id)
    return int(row["precio_jornada"] or 0)


def bruto_linea(it: ItemPrecio, jornadas: int) -> int:
    """Bruto (neto sin descuento) de UNA línea — fuente única del subtotal por línea.

    'jornada' (default): precio × cantidad × jornadas (equipos del catálogo).
    'fijo' (#805, líneas personalizadas tipo flete): precio × cantidad, SIN jornadas.
    """
    cant = int(it.get("cantidad") or 0)
    precio = int(it.get("precio_jornada") or 0)
    mult = 1 if (it.get("cobro_modo") or "jornada") == "fijo" else max(1, int(jornadas or 1))
    return precio * cant * mult


def calcular_total(
    items: list[ItemPrecio],
    jornadas: int,
    descuento_cliente_pct: Optional[float] = 0.0,
    descuento_jornadas_pct: Optional[float] = 0.0,
    perfil_impuestos: Optional[str] = None,
    descuento_manual_pct: Optional[float] = 0.0,
    descuento_manual_tipo: Optional[str] = "pct",
    descuento_manual_monto: Optional[float] = 0,
) -> TotalDesglose:
    """Cálculo canónico del total de un pedido.

    Argumentos:
      items:                       [{equipo_id, cantidad, precio_jornada}], precios NETOS.
      jornadas:                    cantidad de jornadas (usar ``jornadas_periodo``).
      descuento_cliente_pct:       ``clientes.descuento`` (0..100), leído EN VIVO por el caller.
      descuento_jornadas_pct:      interpolado por ``descuentos.queries.jornadas.obtener_descuento_jornadas``.
      perfil_impuestos:            ``'responsable_inscripto'`` para sumar IVA 21%.
      descuento_manual_pct:        override explícito del pedido en % (``alquileres.descuento_pct``,
                                    0 = sin override), usado cuando ``descuento_manual_tipo == "pct"``.
      descuento_manual_tipo:       ``"pct"`` (default, de siempre) o ``"monto"`` (Fase C-2, #1219):
                                    el override es un $ fijo en vez de un %.
      descuento_manual_monto:      override explícito del pedido en $ (``alquileres.descuento_manual_monto``),
                                    usado cuando ``descuento_manual_tipo == "monto"``. Capeado al bruto
                                    DESCONTABLE (no al bruto total — ver nota de combos abajo).

    Jerarquía (Fase C-1, #1219): si el override manual está seteado (≠0 según
    su tipo) gana OUTRIGHT sobre cliente/jornadas — ver
    ``descuentos.queries.decision.resolver_descuento_monto_pedido``.

    Combos no acumulables (Fase C-3, #1219): las líneas con ``es_combo=True``
    (ver ``tipos_equipo_batch``) ya traen su propio descuento por componente
    horneado en ``precio_jornada`` (``precio_combo``) — el descuento GLOBAL
    (cliente/jornadas/manual) se calcula solo sobre el bruto de las líneas
    NO-combo (``bruto_descontable``) y no las toca. ``bruto`` (el subtotal que
    se MUESTRA) sigue siendo la suma de TODAS las líneas.

    El backend debe PERSISTIR ``neto`` en ``alquileres.monto_total`` (sin IVA).
    El ``total_final`` (con IVA si aplica) es lo que se MUESTRA al cliente RI.
    """
    j = max(1, int(jornadas or 1))
    bruto = sum(bruto_linea(it, j) for it in items)
    bruto_descontable = sum(
        bruto_linea(it, j) for it in items if not it.get("es_combo")
    )
    resuelto = resolver_descuento_monto_pedido(
        bruto_descontable, descuento_manual_tipo, descuento_manual_pct, descuento_manual_monto,
        descuento_cliente_pct, descuento_jornadas_pct,
    )
    descuento_monto = resuelto["monto"]
    pct = resuelto["pct"]
    neto = int(bruto - descuento_monto)
    con_iva = es_responsable_inscripto(perfil_impuestos)
    iva_monto = int(round(neto * IVA_PCT / 100)) if con_iva else 0
    return {
        "bruto": int(bruto),
        "bruto_descontable": int(bruto_descontable),
        "descuento_pct": pct,
        "descuento_monto": descuento_monto,
        "neto": neto,
        "con_iva": con_iva,
        "iva_pct": IVA_PCT,
        "iva_monto": iva_monto,
        "total_final": neto + iva_monto,
    }
