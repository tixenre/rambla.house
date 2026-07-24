"""Kit / componentes de un equipo (#501 fase a — extraído de `core`).

Registra sus rutas en el router compartido del paquete `routes.equipos`. Tabla
`kit_componentes`. `KitItem` y `_crea_ciclo_kit` los importan tests vía el
`__init__` del paquete (re-export).
"""
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from auth.guards import require_admin
from database import get_db
from rate_limit import limiter, ADMIN_WRITE_LIMIT
from routes.equipos.core import router
from services.contenido import contenido_de
from services.precios import precio_combo, resolver_descuento_uniforme


class KitItem(BaseModel):
    componente_id: int
    cantidad:      int   = Field(default=1, ge=1, le=9999)
    # default 0.0 (NO None): la columna kit_componentes.descuento_pct es NOT NULL,
    # un NULL explícito la viola. Rango 0..100 (% de descuento por línea de combo).
    descuento_pct: float = Field(default=0.0, ge=0, le=100)
    esencial:      bool  = True


class KitReorder(BaseModel):
    orden: list[int]  # lista de componente_id en el orden deseado


@router.get("/equipos/{id}/kit")
def get_kit(id: int):
    with get_db() as conn:
        if not conn.execute("SELECT id FROM equipos WHERE id=%s", (id,)).fetchone():
            raise HTTPException(404, "Equipo no encontrado")
        # Componentes vía la puerta única (services.contenido) — fuente única del
        # "qué incluye" derivada de kit_componentes. `solo_activos=False`: el editor
        # de kit del admin muestra TODOS los componentes (incluso retirados) para
        # poder gestionarlos — preserva el comportamiento previo (no filtraba).
        return [{
            "id":               c["kc_id"],
            "componente_id":    c["componente_id"],
            "cantidad":         c["cantidad"],
            "orden":            c["orden"],
            "descuento_pct":    c["descuento_pct"],
            "esencial":         c["esencial"],
            "nombre":           c["nombre"],
            "marca":            c["marca"],
            "modelo":           c["modelo"],
            "foto_url":         c["foto_url"],
            "visible_catalogo": c["visible_catalogo"],
        } for c in contenido_de(conn, id, solo_activos=False)]


def _crea_ciclo_kit(conn, equipo_id: int, componente_id: int) -> bool:
    """¿Agregar `componente_id` como componente de `equipo_id` crearía un ciclo?

    Hay ciclo si `equipo_id` ya es alcanzable desde `componente_id` siguiendo
    la cadena de sus propios componentes (BFS hacia abajo desde el componente
    candidato). Auto-referencia directa (equipo_id == componente_id) la maneja
    el caller, pero también la detectamos acá por las dudas.

    Sin este check, dos endpoints concurrentes podrían crear A→B y B→A y
    dejar el grafo con un ciclo, que aunque las queries actuales no recursen,
    rompe la semántica de "un kit contiene componentes" y puede causar bugs
    si alguna vez se hace un traversal recursivo.
    """
    if equipo_id == componente_id:
        return True
    visitados: set[int] = set()
    pila: list[int] = [componente_id]
    while pila:
        actual = pila.pop()
        if actual == equipo_id:
            return True
        if actual in visitados:
            continue
        visitados.add(actual)
        hijos = conn.execute(
            "SELECT componente_id FROM kit_componentes WHERE equipo_id = %s", (actual,)
        ).fetchall()
        pila.extend(h["componente_id"] for h in hijos)
    return False


@router.post("/equipos/{id}/kit", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
def add_kit_item(id: int, data: KitItem, request: Request):
    require_admin(request)
    if id == data.componente_id:
        raise HTTPException(400, "Un equipo no puede ser componente de sí mismo")
    with get_db() as conn:
        try:
            if not conn.execute("SELECT id FROM equipos WHERE id=%s", (id,)).fetchone():
                raise HTTPException(404, "Equipo no encontrado")
            if not conn.execute(
                "SELECT id FROM equipos WHERE id=%s AND eliminado_at IS NULL", (data.componente_id,)
            ).fetchone():
                raise HTTPException(404, "Componente no encontrado")
            if _crea_ciclo_kit(conn, id, data.componente_id):
                raise HTTPException(
                    400,
                    "Agregar este componente crearía un ciclo en los kits "
                    "(el componente ya contiene a este equipo en su cadena).",
                )
            try:
                # El editor de kit llama este mismo POST por cada campo que se
                # ajusta (cantidad, descuento, esencial) — el WHERE evita un
                # UPDATE (y su dead row) cuando el valor ya es el mismo.
                conn.execute("""
                    INSERT INTO kit_componentes (equipo_id, componente_id, cantidad, descuento_pct, esencial)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT(equipo_id, componente_id) DO UPDATE SET
                        cantidad=excluded.cantidad,
                        descuento_pct=excluded.descuento_pct,
                        esencial=excluded.esencial
                    WHERE kit_componentes.cantidad IS DISTINCT FROM excluded.cantidad
                       OR kit_componentes.descuento_pct IS DISTINCT FROM excluded.descuento_pct
                       OR kit_componentes.esencial IS DISTINCT FROM excluded.esencial
                """, (id, data.componente_id, data.cantidad, data.descuento_pct, data.esencial))
                conn.commit()
            except Exception as e:
                raise HTTPException(400, str(e))
            return get_kit(id)
        except Exception:
            conn.rollback()
            raise


@router.delete("/equipos/{id}/kit/{componente_id}", status_code=204)
@limiter.limit(ADMIN_WRITE_LIMIT)
def remove_kit_item(id: int, componente_id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        try:
            conn.execute(
                "DELETE FROM kit_componentes WHERE equipo_id=%s AND componente_id=%s",
                (id, componente_id)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


class PrecioObjetivoBody(BaseModel):
    precio_objetivo: int = Field(ge=0, le=2_147_483_647)


@router.post("/admin/equipos/{id}/combo/precio-objetivo")
@limiter.limit(ADMIN_WRITE_LIMIT)
def set_precio_objetivo_combo(id: int, data: PrecioObjetivoBody, request: Request):
    """Aplica un % de descuento UNIFORME a TODAS las líneas del combo para que
    su precio derivado (`precio_combo`) sea exactamente `precio_objetivo` —
    atajo para no tener que tantear el % línea por línea a mano (#1283 Fase 5).
    """
    require_admin(request)
    with get_db() as conn:
        try:
            eq = conn.execute("SELECT tipo FROM equipos WHERE id=%s", (id,)).fetchone()
            if not eq:
                raise HTTPException(404, "Equipo no encontrado")
            if eq["tipo"] != "combo":
                raise HTTPException(400, "Solo se puede fijar un precio objetivo para un combo")
            # Mismo WHERE que `precio_combo` (services/precios.py): componentes
            # vivos del combo — para que el % resuelto coincida con lo que se
            # recalcula después.
            rows = conn.execute(
                "SELECT e.precio_jornada, kc.cantidad "
                "FROM kit_componentes kc JOIN equipos e ON e.id = kc.componente_id "
                "WHERE kc.equipo_id = %s AND e.eliminado_at IS NULL",
                (id,),
            ).fetchall()
            if not rows:
                raise HTTPException(400, "El combo no tiene componentes")
            try:
                descuento = resolver_descuento_uniforme(rows, data.precio_objetivo)
            except ValueError as e:
                raise HTTPException(400, str(e))
            conn.execute(
                "UPDATE kit_componentes SET descuento_pct = %s WHERE equipo_id = %s",
                (descuento, id),
            )
            conn.commit()
            return {"kit": get_kit(id), "precio_combo": precio_combo(conn, id)}
        except Exception:
            conn.rollback()
            raise


@router.post("/admin/equipos/{id}/kit/reorder")
@limiter.limit(ADMIN_WRITE_LIMIT)
def reorder_kit(id: int, data: KitReorder, request: Request):
    """Reordena los componentes del kit según el array de componente_id."""
    require_admin(request)
    with get_db() as conn:
        try:
            for i, componente_id in enumerate(data.orden):
                # Reordenar sin mover nada (abrir/cerrar el editor, soltar en
                # el mismo lugar) no debería generar un UPDATE por fila.
                conn.execute(
                    "UPDATE kit_componentes SET orden=%s "
                    "WHERE equipo_id=%s AND componente_id=%s AND orden IS DISTINCT FROM %s",
                    (i, id, componente_id, i)
                )
            conn.commit()
            return {"ok": True}
        except Exception:
            conn.rollback()
            raise
