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


def es_pedido_estudio(p) -> bool:
    """True si la fila `p` de `alquileres` (dict o `PGRow`) es un pedido del
    Estudio. Predicado único — no repetir `p["tipo"] in TIPOS_ESTUDIO` en cada
    call site.

    Chequea con `"tipo" in p.keys()` en vez de `"tipo" in p` o `p.get(...)`:
    `PGRow` (`database/core.py`) no implementa `.get()` ni `__contains__`, y
    su `__iter__` itera los VALORES de la fila, no los nombres de columna —
    `"tipo" in p` sobre un `PGRow` compararía "tipo" contra esos valores, no
    contra si la columna existe. Una fila real de `alquileres` SIEMPRE trae
    `tipo` (`NOT NULL DEFAULT 'diaria'`); el `.keys()` explícito solo importa
    para los `FakeConn` de tests unitarios que arman un dict parcial con
    únicamente las columnas que ese test necesita.
    """
    return "tipo" in p.keys() and p["tipo"] in TIPOS_ESTUDIO
