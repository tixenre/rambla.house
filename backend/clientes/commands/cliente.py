"""
CRUD de escritura de clientes — move-verbatim de `routes/clientes.py` (2026-07).
Solo levanta `ValueError` para lo que anticipa (not-found / nada-para-actualizar);
el route lo traduce a HTTPException. Lo que se escapa (violación de constraint,
etc.) lo cubre `@map_pg_errors` en el route.
"""
from clientes.queries import cliente as queries_cliente


def crear(conn, data: dict) -> dict:
    # `email` es UNIQUE en `clientes` — Postgres permite múltiples NULL pero NO
    # múltiples "" (string vacío cuenta como valor). El picker rápido de ficha
    # (ClienteAutocomplete) no pide email → sin este `or None`, el segundo
    # cliente creado sin email choca contra el primero con un 400 genérico
    # "ya existe un registro con ese valor".
    cliente_id = conn.insert_returning(
        """INSERT INTO clientes (nombre, apellido, telefono, email, direccion, cuit,
                                  descuento, perfil_impuestos, notas, direccion_maps_url)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            data["nombre"], data["apellido"], data["telefono"], data["email"] or None,
            data["direccion"], data["cuit"], data["descuento"], data["perfil_impuestos"],
            data["notas"], data["direccion_maps_url"],
        ),
    )
    conn.commit()
    return queries_cliente.obtener(conn, cliente_id)


def actualizar(conn, cliente_id: int, actual: dict, updates: dict) -> dict:
    """`actual` = fila ya resuelta por el caller (evita una segunda ida a la
    base solo para leer el `descuento` viejo). Si `descuento` cambió, dispara
    la recotización de presupuestos SIN override manual — misma transacción,
    atómico (Fase C-1, #1219; el descuento del cliente ya se lee en vivo, acá
    solo se dispara el recálculo)."""
    if not updates:
        raise ValueError("Nada para actualizar")
    # Mismo criterio que `crear`: vaciar el email en una edición no puede
    # guardar "" (choca contra el UNIQUE) — se guarda NULL.
    if updates.get("email") == "":
        updates = {**updates, "email": None}
    set_clause = ", ".join(f"{k}=%s" for k in updates) + ", updated_at=CURRENT_TIMESTAMP"
    conn.execute(f"UPDATE clientes SET {set_clause} WHERE id=%s", list(updates.values()) + [cliente_id])
    if "descuento" in updates and (updates["descuento"] or 0) != (actual.get("descuento") or 0):
        from routes.alquileres import propagar_descuento_a_presupuestos
        propagar_descuento_a_presupuestos(conn, cliente_id)
    conn.commit()
    return queries_cliente.obtener(conn, cliente_id)


def eliminar(conn, cliente_id: int) -> None:
    """Soft delete (#1251 Fase 2) — antes era un DELETE físico. Mismo patrón
    que equipos (#206): `eliminado_at` marca la baja, no se borra la fila
    (preserva el historial de pedidos que la referencian)."""
    conn.execute("UPDATE clientes SET eliminado_at = CURRENT_TIMESTAMP WHERE id=%s", (cliente_id,))
    conn.commit()
