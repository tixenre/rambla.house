"""Descuentos por jornadas (#501 — extraído del god-module `routes/alquileres.py`).

Transporte HTTP fino sobre el motor `backend/descuentos/` (CQRS-lite): la
lógica de la escala de descuento por cantidad de jornadas vive en
`descuentos.queries.jornadas` / `descuentos.commands.jornadas`. Registra sus
rutas en el router compartido del paquete `routes.alquileres`.
"""
from fastapi import Query, Request, HTTPException
from pydantic import BaseModel

from database import get_db
from auth.guards import require_admin
from rate_limit import limiter, ADMIN_WRITE_LIMIT
from descuentos.commands.jornadas import crear_descuento_jornada, eliminar_descuento_jornada
from descuentos.queries.jornadas import interpolar_descuento_jornadas, listar_descuentos_jornada
from routes.alquileres.core import router


# ── Descuentos por jornadas ───────────────────────────────────────────────────

class DescuentoJornadaIn(BaseModel):
    jornadas: int
    pct: float


@router.get("/descuentos-jornada")
def get_descuentos_jornada(request: Request):
    """Devuelve los puntos ancla de descuentos por jornadas.

    `require_admin` explícito (#1219): el comentario histórico "público — lo
    usa el carrito" estaba stale — el único consumidor real es
    `/admin/settings` vía `authedJson`, no el carrito público (que cotiza a
    través de `/api/cotizar`, que sí es público). Antes de este fix, la falta
    de allowlist en `middleware.py` lo dejaba accesible a CUALQUIER sesión
    logueada (no solo admin) — dato de baja sensibilidad, pero sin motivo
    para no acotarlo al único consumidor real.
    """
    require_admin(request)
    with get_db() as conn:
        return listar_descuentos_jornada(conn)


@router.get("/descuentos-jornada/interpolar")
def get_descuentos_jornada_interpolados(request: Request, jornadas: list[int] = Query(...)):
    """% interpolado para cada cantidad de jornadas pedida — misma fuente que
    `/api/cotizar` (`interpolar_descuento_jornadas`), UNA sola query de los
    puntos ancla. `require_admin`, mismo criterio que el listado de arriba.

    El front NO reimplementa la interpolación: la pide acá. La usa el preview
    de `/admin/settings` → Descuentos por jornada (antes calculaba localmente
    y podía redondear distinto al backend, #1219).
    """
    require_admin(request)
    if not jornadas:
        raise HTTPException(400, "jornadas no puede estar vacío")
    with get_db() as conn:
        rows = listar_descuentos_jornada(conn)
    # `pct` es NUMERIC en la DB → psycopg lo devuelve como Decimal. Sin coercer
    # acá, `t * (p1 - p0)` (t float) revienta TypeError — el mismo bug
    # histórico que documenta `obtener_descuento_jornadas`.
    puntos = [(int(r["jornadas"]), float(r["pct"])) for r in rows]
    return [{"jornadas": j, "pct": interpolar_descuento_jornadas(puntos, j)} for j in jornadas]


@router.post("/admin/descuentos-jornada", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
def create_descuento_jornada(data: DescuentoJornadaIn, request: Request):
    require_admin(request)
    with get_db() as conn:
        try:
            return crear_descuento_jornada(conn, jornadas=data.jornadas, pct=data.pct)
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.delete("/admin/descuentos-jornada/{id}", status_code=204)
@limiter.limit(ADMIN_WRITE_LIMIT)
def delete_descuento_jornada(id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        eliminar_descuento_jornada(conn, id)
