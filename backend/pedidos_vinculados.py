"""pedidos_vinculados.py — eje `pedido_principal_id`, compartido entre capas.

Distinto del eje de `tipos_pedido.py` (que clasifica por `alquileres.tipo`):
acá el filtro es "¿esta fila es un turno del Estudio vinculado a otro pedido,
o es un pedido de primera clase?" — un turno vinculado (`pedido_principal_id`
no-null) se administra desde la página de su principal ("Turnos del Estudio")
y no debe listarse como venta propia en el worklist operativo de pedidos, pero
sigue siendo una fila real de `alquileres` con su propia plata/agenda en las
superficies donde eso importa (historial del cliente, export contable,
backup, calendario) — no se excluye ahí.

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
