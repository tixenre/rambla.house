"""pedidos_vinculados.py — eje `pedido_principal_id`, compartido entre capas.

Distinto del eje de `tipos_pedido.py` (que clasifica por `alquileres.tipo`):
acá el filtro es "¿esta fila es un turno del Estudio vinculado a otro pedido,
o es un pedido de primera clase?".

**Un turno vinculado (`pedido_principal_id` no-null) NO es un pedido de cara a
nadie** (#1308, pedido explícito del dueño: "no quiero dobles pedidos
fantasmas... cobrar una sola cosa y facturar y establecer el estado"). Existe
como fila aparte por una sola razón: su granularidad de tiempo (una franja
horaria) es incompatible con el rango de días de un alquiler, y su economía
pertenece al Estudio. Pero en toda superficie donde lo mira un humano se
excluye la fila y **se consolida su plata en el principal**: lista de pedidos,
cuentas por cobrar, portal del cliente, historial del cliente, dashboard,
recordatorios, liquidación (identidad) y la factura (una sola, con el importe
combinado — `finanzas_flujo.pedido.combinar_turnos_vinculados`).

**Dónde SÍ sigue apareciendo la fila**, porque ahí no es ruido sino un hecho
real que se perdería: la **agenda** (calendario admin, feed iCal, agenda del
Estudio — es ocupación real del espacio), la **economía del Estudio**
(`estadisticas.py`, atribución por dueño en liquidación — el Estudio es una
unidad de negocio propia) y el **export contable / backup** (`dataio`, que
además exporta el vínculo para no revivirlo como pedido suelto al restaurar).

Vive en su propio módulo, no dentro de `tipos_pedido.py`: ese archivo está
scopeado por su propio docstring a la columna `tipo`, y su guard mecánico
(`test_tipos_pedido_source_scan.py`) escanea tuplas literales de valores de
`tipo` — un eje distinto (un self-FK) no encaja ahí. Mismo nivel del árbol de
imports (junto a `database`/`config`), consumido por dominios que no deben
depender entre sí (`routes/alquileres`, `routes/equipos`).
"""

# Sin alias — `pedido_principal_id` es la única columna con ese nombre en todo
# el schema (tabla `alquileres`), y ya tiene índice (`idx_pedidos_principal`)
# así que el filtro es barato en cualquier query que la interpole directo.
SIN_PRINCIPAL_SQL = "pedido_principal_id IS NULL"

# Inverso — para el caso contrario (encontrar los turnos vinculados de un
# pedido, ej. sumar su saldo pendiente al del principal antes de ocultarlos
# de una lista). Mismo eje, misma fuente.
TURNO_VINCULADO_SQL = "pedido_principal_id IS NOT NULL"


def es_turno_vinculado(p) -> bool:
    """True si la fila `p` de `alquileres` (dict o `PGRow`) es un turno del
    Estudio vinculado a un pedido principal. Predicado único — no repetir
    `p["pedido_principal_id"] is not None` en cada call site. Mismo motivo del
    `.keys()` explícito que `tipos_pedido._tipo_de`: `PGRow` no implementa
    `.get()`/`__contains__`, y los `FakeConn` de tests unitarios arman dicts
    parciales sin la columna."""
    return bool(p["pedido_principal_id"]) if "pedido_principal_id" in p.keys() else False
