"""tipos_pedido.py — clasificación de `alquileres.tipo`, compartida entre capas.

Vive en el nivel más bajo del árbol de imports (junto a `database`/`config`) a
propósito: tanto `routes/estudio.py` (dueño de la fila) como
`routes/alquileres/` (editor genérico de pedidos) como `reportes/`
(reconciliación/liquidación) necesitan distinguir un pedido del Estudio de un
alquiler normal, sin crear un ciclo (`routes/estudio.py` ya importa de
`routes.alquileres`) ni invertir la capa (`reportes/` no importa de `routes/`
— mismo criterio que evitó que `services/facturacion` importara de
`routes.alquileres`, MEMORIA 2026-07-02).
"""

# Pedido por turno de horas (`crear_reserva_estudio`) o slot fijo mensual
# (`_regenerar_pedidos_slot`) — ambos en `routes/estudio.py`. Sus ítems llevan
# la plata real del espacio/promo en `subtotal` (`cobro_modo='fijo'`), no un
# `precio_jornada` recalculable como un alquiler normal.
TIPOS_ESTUDIO = ("estudio", "estudio_fijo")

# Pedido DERIVADO: `fecha_desde`/`fecha_hasta` NO representan un evento real de
# un día puntual (mueble contable, no reserva) — superset de `TIPOS_ESTUDIO`
# que suma `taller` (mes calendario completo de la edición, ver
# `services/talleres/commands/economia.py::_regenerar_pedidos_taller`). Todo
# derivado comparte con el Estudio: `monto_total` NO es recalculable con la
# fórmula genérica de jornadas (`_recalcular_total_pedido`) y sus fechas no se
# editan a mano vía el endpoint genérico (`update_pedido_datos`, 409). Dónde
# SÍ divergen taller de estudio/estudio_fijo (no unificar sin releer el porqué):
# el reemplazo de ítems (`_apply_pedido_items`) es un 409 en bloque para
# estudio/estudio_fijo pero una protección puntual del ítem auto para taller
# (la matrícula manual se sigue pudiendo agregar); la revalidación de stock al
# transicionar estado (`_revalidar_stock`) despacha al revalidador propio del
# Estudio para estudio/estudio_fijo pero se SALTEA por completo para taller (su
# rango es un mes contable, no una franja real — aplicarle cualquiera de los
# dos motores de disponibilidad por hora daría un resultado sin sentido).
TIPOS_DERIVADOS = TIPOS_ESTUDIO + ("taller",)

# Pedidos DERIVADOS sin retiro real (taller + estudio_fijo, NO estudio): el
# subconjunto de `TIPOS_DERIVADOS` que además no puede "salir"/"volver" un día
# puntual ni recibir el recordatorio de retiro — 'estudio' SÍ se queda (es un
# evento real, puede llevar equipos sueltos que sí se retiran). Usado por
# `routes/dashboard.py` (salen/devuelven/calendario) y
# `jobs/recordatorios.py` (bug real #445, 2026-07-28).
TIPOS_SIN_RETIRO = ("taller", "estudio_fijo")

# Formato literal para cláusulas SQL `IN`/`NOT IN` — mismo criterio que
# `reservas.estados.ESTADOS_RESERVADO`: son constantes internas (nunca se
# derivan de input), seguras para interpolar directo como
# `p.tipo NOT IN {TIPOS_DERIVADOS_SQL}`. NO interpolar nada de fuera acá.
TIPOS_ESTUDIO_SQL = "('estudio', 'estudio_fijo')"
TIPOS_DERIVADOS_SQL = "('estudio', 'estudio_fijo', 'taller')"
TIPOS_SIN_RETIRO_SQL = "('taller', 'estudio_fijo')"


def _tipo_de(p) -> str | None:
    """`p["tipo"]` si la fila lo trae, si no `None` — mismo motivo del
    `.keys()` explícito que documentaba `es_pedido_estudio` (ver abajo):
    `PGRow` no implementa `.get()`/`__contains__`, y los `FakeConn` de tests
    unitarios arman dicts parciales sin `tipo`."""
    return p["tipo"] if "tipo" in p.keys() else None


def es_pedido_estudio(p) -> bool:
    """True si la fila `p` de `alquileres` (dict o `PGRow`) es un pedido del
    Estudio (turno por hora o slot fijo — NO taller, ver `es_pedido_derivado`
    para el superset). Predicado único — no repetir `p["tipo"] in TIPOS_ESTUDIO`
    en cada call site.
    """
    return _tipo_de(p) in TIPOS_ESTUDIO


def es_pedido_derivado(p) -> bool:
    """True si la fila `p` es un pedido DERIVADO (estudio, estudio_fijo o
    taller) — su rango de fechas es contable, no un evento real. Úsalo para
    los call sites donde el tratamiento es IDÉNTICO en los 3 tipos (hoy:
    no-op de `_recalcular_total_pedido`, 409 de fecha en
    `update_pedido_datos`). Donde el tratamiento DIVERGE entre estudio y
    taller (ver el comentario de `TIPOS_DERIVADOS`), branchear explícito en
    vez de usar este predicado."""
    return _tipo_de(p) in TIPOS_DERIVADOS


def es_pedido_taller(p) -> bool:
    """True si la fila `p` es un pedido de taller. Predicado único — no
    repetir `p["tipo"] == "taller"` en cada call site: un acceso directo por
    `[]` revienta con `KeyError` sobre un `FakeConn`/dict parcial de test que
    no declaró `tipo` (`_tipo_de` lo maneja con `.keys()`, mismo motivo que
    `es_pedido_estudio`)."""
    return _tipo_de(p) == "taller"
