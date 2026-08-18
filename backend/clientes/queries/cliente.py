"""
Listado/detalle de clientes para la ficha admin. Move-verbatim de
`routes/clientes.py` (2026-07). El `nombre_legal`/`direccion_legal` de cada
fila sale de `clientes.queries.identidad` (fuente única, ver ese módulo).
"""
from database import row_to_dict
from busqueda import construir

from clientes.queries.identidad import nombre_legal, direccion_legal
from identity.contacts import email_comunicacion, telefono_contacto

# Campos buscables del cliente. El combinado nombre+apellido permite que
# "santiago perez" matchee/rankee aunque nombre y apellido sean campos distintos.
CAMPOS_BUSCABLES = [
    "(c.nombre || ' ' || c.apellido)",
    "c.nombre",
    "c.apellido",
    "c.email",
    "c.cuit",
    "c.telefono",
]


def _enriquecer(d: dict) -> dict:
    d["nombre_legal"] = nombre_legal(d)
    d["direccion_legal"] = direccion_legal(d)
    return d


def listar(conn, q: str | None, page: int, per_page: int) -> dict:
    offset = (page - 1) * per_page
    # Soft delete (#1251 Fase 2): la lista oculta los eliminados por default,
    # mismo criterio que equipos (#206) — `obtener` (fetch por id) SÍ los
    # muestra (un pedido viejo puede seguir apuntando a un cliente borrado).
    where = "WHERE c.eliminado_at IS NULL"
    params: list = []

    # Búsqueda fuzzy unificada (backend/busqueda): sin tildes, sin guiones,
    # multi-palabra cruzando campos y ranking por relevancia (el mejor match
    # primero, consistente — antes ordenaba alfabético y "a veces traía otro").
    pred = construir(CAMPOS_BUSCABLES, q) if q else None
    if pred and pred.activo:
        where += f" AND ({pred.where})"
        params += pred.where_params

    total = conn.execute(f"SELECT COUNT(*) FROM clientes c {where}", params).fetchone()[0]
    if pred and pred.activo:
        select_params = pred.score_params + params + [per_page, offset]
        rows = conn.execute(
            f"SELECT c.*, ({pred.score}) AS _score FROM clientes c {where} "
            f"ORDER BY _score DESC, c.apellido, c.nombre LIMIT %s OFFSET %s",
            select_params,
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT c.* FROM clientes c {where} ORDER BY c.apellido, c.nombre LIMIT %s OFFSET %s",
            params + [per_page, offset],
        ).fetchall()

    items = []
    for r in rows:
        d = row_to_dict(r)
        d.pop("_score", None)  # interno del ranking, no parte del contrato
        items.append(_enriquecer(d))
    return {"total": total, "page": page, "per_page": per_page, "items": items}


def obtener(conn, cliente_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    if not row:
        return None
    d = _enriquecer(row_to_dict(row))
    # Vista resuelta para DISPLAY (mismo criterio que GET /api/cliente/me,
    # identity/contacts.py): el email/teléfono BASE de arriba siguen intactos
    # para el form de edición de la ficha — esto es aditivo, no un reemplazo.
    # El teléfono verificado por Didit puede diferir del autodeclarado (sin
    # esto, la ficha admin mostraba "sin contacto" para un cliente que el
    # sistema SÍ sabe contactar, mismo bug que en la card del pedido).
    d["email_comunicacion"] = email_comunicacion(conn, cliente_id)
    d["telefono_contacto"] = telefono_contacto(conn, cliente_id)
    return d


def _enriquecer_grupo_duplicado(conn, cuil: str, ids: list[int]) -> dict:
    clientes = []
    for cid in ids:
        row = conn.execute(
            """SELECT c.id, c.nombre, c.apellido, c.email, c.telefono,
                      c.nombre_completo_renaper, c.dni_validado_at, c.created_at,
                      (SELECT COUNT(*) FROM alquileres a WHERE a.cliente_id = c.id) AS pedidos
                 FROM clientes c WHERE c.id = %s""",
            (cid,),
        ).fetchone()
        if row:
            clientes.append(row_to_dict(row))
    return {"cuil": cuil, "clientes": clientes}


def duplicados(conn) -> list[dict]:
    """Grupos de clientes que comparten un CUIL verificado — candidatos a
    fusionar (justo lo que el índice único de CUIL rechaza)."""
    from identity import merge

    return [
        _enriquecer_grupo_duplicado(conn, g["cuil"], g["ids"])
        for g in merge.candidatos_duplicados(conn)
    ]


def duplicados_de(conn, cliente_id: int) -> dict | None:
    """El grupo de duplicados (mismo CUIL verificado) que incluye a este
    cliente puntual, si existe — para sugerir la fusión desde su propia
    ficha (#1251 Fase 2). Reusa `identity.merge.candidatos_duplicados` (ya
    agrega por CUIL, barato) en vez de una query nueva."""
    from identity import merge

    for g in merge.candidatos_duplicados(conn):
        if cliente_id in g["ids"]:
            return _enriquecer_grupo_duplicado(conn, g["cuil"], g["ids"])
    return None
