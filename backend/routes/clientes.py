"""
routes/clientes.py — CRUD de clientes e importación desde histórico. Las
queries/comandos de la cuenta (identidad a mostrar, historial, fiscal) viven
en `clientes/` (CQRS-lite) — este archivo es transporte HTTP.
"""

from typing import Optional

from fastapi import APIRouter, Query, HTTPException, Request
from pydantic import BaseModel

from urllib.parse import quote

from database import get_db
from services.telefono import formatear_para_guardar
from auth.guards import require_admin
from auth.commands import magic as magic_commands
from config import settings
from identity import merge
from clientes.queries import cliente as queries_cliente
from clientes.queries import fiscal as queries_fiscal
from clientes.queries import historial as queries_historial
from clientes.commands import cliente as commands_cliente
from routes.contabilidad import map_pg_errors
from rate_limit import limiter, ADMIN_WRITE_LIMIT

router = APIRouter()


# ── Modelos ──────────────────────────────────────────────────────────────────

class ClienteCreate(BaseModel):
    from pydantic import field_validator
    nombre:             str
    apellido:           str
    telefono:           str = ""
    email:              str = ""
    direccion:          str = ""
    cuit:               str = ""
    descuento:          float = 0
    perfil_impuestos:   str = "consumidor_final"
    notas:              Optional[str] = None
    direccion_maps_url: Optional[str] = None

    @field_validator("descuento")
    @classmethod
    def validate_descuento(cls, v):
        if v is None:
            return 0
        if v < 0 or v > 100:
            raise ValueError("descuento debe estar entre 0 y 100")
        return v


class ClienteUpdate(BaseModel):
    from pydantic import field_validator
    nombre:             Optional[str]   = None
    apellido:           Optional[str]   = None
    telefono:           Optional[str]   = None
    email:              Optional[str]   = None
    direccion:          Optional[str]   = None
    cuit:               Optional[str]   = None
    descuento:          Optional[float] = None
    perfil_impuestos:   Optional[str]   = None
    notas:              Optional[str]   = None
    direccion_maps_url: Optional[str]   = None

    @field_validator("descuento")
    @classmethod
    def validate_descuento(cls, v):
        if v is None:
            return v
        if v < 0 or v > 100:
            raise ValueError("descuento debe estar entre 0 y 100")
        return v


# ── Rutas ────────────────────────────────────────────────────────────────────


@router.get("/clientes")
def list_clientes(
    request:  Request,
    q:        Optional[str] = Query(None),
    page:     int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
):
    require_admin(request)
    with get_db() as conn:
        return queries_cliente.listar(conn, q, page, per_page)


# ── Fusión de duplicados (Fase 2 identidad #1098) ─────────────────────────────
# El back-office para deduplicar clientes que son la misma persona. Cablea al motor
# `identity/merge` (transaccional, con guardas). Destructivo → require_admin.
# ⚠️ ORDEN: la GET estática va ANTES de `/clientes/{id}` — si no, `/{id}` captura
# "duplicados" como id y tira 422 (colisión de rutas — cazada por el supervisor; el
# test_clientes_merge_route la clava a nivel HTTP).

@router.get("/clientes/duplicados")
def clientes_duplicados(request: Request):
    """Grupos de clientes que comparten un CUIL verificado — candidatos a fusionar
    (justo lo que el índice único de CUIL rechaza). Enriquece cada id con nombre,
    contacto, estado y nº de pedidos para que el admin elija cuál conservar."""
    require_admin(request)
    with get_db() as conn:
        return queries_cliente.duplicados(conn)


class MergeClientesIn(BaseModel):
    source: int  # se absorbe y se borra
    target: int  # sobrevive con su identidad


@router.post("/clientes/merge")
@limiter.limit(ADMIN_WRITE_LIMIT)
def merge_clientes(request: Request, body: MergeClientesIn):
    """Fusiona dos clientes que son la MISMA persona: mueve pedidos / datos / llaves /
    bitácora de `source` a `target` y borra `source`. **Destructivo e irreversible** →
    require_admin + las guardas del motor (rehúsa perder una identidad verificada o unir
    dos personas con CUIL distinto → 400)."""
    require_admin(request)
    if body.source == body.target:
        raise HTTPException(400, "No se puede fusionar un cliente consigo mismo")
    try:
        merge.merge_accounts(source=body.source, target=body.target)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "merged_into": body.target}


class InvitarClienteIn(BaseModel):
    email: str
    nombre: Optional[str] = None
    telefono: Optional[str] = None


@router.post("/clientes/invitar")
@limiter.limit(ADMIN_WRITE_LIMIT)
def invitar_cliente(request: Request, body: InvitarClienteIn):
    """Crea (o reusa) una cuenta por email y devuelve un LINK de invitación single-use
    para que el cliente la reclame (active la cuenta + registre su passkey). El admin lo
    manda por donde quiera — mismo patrón que el link de verificación (no se manda mail
    desde acá: el motor de mail es por plantilla; el admin copia el link). El email se
    valida/locked recién con Didit; el nombre/teléfono del admin son provisionales."""
    require_admin(request)
    email = (body.email or "").strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(400, "Email inválido")
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, dni_validado_at FROM clientes WHERE LOWER(email) = LOWER(%s)", (email,)
        ).fetchone()
        if row:
            # Anti-takeover: una cuenta YA verificada (identidad + pagos) NO se invita por
            # link — si se filtra, quien lo abra entra con todo adentro. Esas se recuperan
            # por Didit/CUIL (Fase 3, no se puede falsificar). Sí se invita lo no-verificado
            # (incluso clientes viejos con pedidos pero sin Didit → caso de migración).
            if row["dni_validado_at"] is not None:
                raise HTTPException(
                    400,
                    "Esa cuenta ya está verificada — el cliente la recupera por su identidad "
                    "(Didit), no por un link de invitación.",
                )
            cliente_id, ya_existia = row["id"], True
        else:
            cliente_id = conn.insert_returning(
                "INSERT INTO clientes (email, nombre, telefono, cuenta_estado) "
                "VALUES (%s, %s, %s, 'liviana')",
                (email, (body.nombre or "").strip() or None, formatear_para_guardar(body.telefono)),
            )
            conn.commit()
            ya_existia = False
    token = magic_commands.crear(email=email, purpose="invitacion", cliente_id=cliente_id)
    return {
        "ok": True,
        "cliente_id": cliente_id,
        "ya_existia": ya_existia,
        "url": f"{settings.SITE_URL}/cliente/claim?t={quote(token, safe='')}",
    }


@router.get("/clientes/{id}")
def get_cliente(id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        d = queries_cliente.obtener(conn, id)
        if d is None:
            raise HTTPException(404, "Cliente no encontrado")
        return d


@router.get("/clientes/{id}/pedidos")
def get_cliente_pedidos(id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        if not conn.execute("SELECT id FROM clientes WHERE id=%s", (id,)).fetchone():
            raise HTTPException(404, "Cliente no encontrado")
        return queries_historial.resumen(conn, id)


@router.get("/clientes/{id}/perfiles-fiscales")
def get_cliente_perfiles_fiscales(id: int, request: Request):
    """Solo lectura (#1240): perfiles fiscales personales del cliente +
    productoras a las que está vinculado — para la ficha admin. La gestión
    real vive en `POST /api/cliente/facturacion/perfiles` (self-service del
    cliente) y `routes/productoras.py` (admin, membership de productoras)."""
    require_admin(request)
    with get_db() as conn:
        if not conn.execute("SELECT id FROM clientes WHERE id=%s", (id,)).fetchone():
            raise HTTPException(404, "Cliente no encontrado")
        return queries_fiscal.resumen_fiscal(conn, id)


@router.get("/clientes/{id}/duplicados")
def get_cliente_duplicados(id: int, request: Request):
    """El grupo de duplicados (mismo CUIL verificado) que incluye a este
    cliente, si existe — sugerencia de fusión desde su propia ficha (#1251
    Fase 2). `null` si no hay ninguno. Mismo motor que `GET /clientes/duplicados`
    (la vista global), acá filtrado a uno solo."""
    require_admin(request)
    with get_db() as conn:
        if not conn.execute("SELECT id FROM clientes WHERE id=%s", (id,)).fetchone():
            raise HTTPException(404, "Cliente no encontrado")
        return queries_cliente.duplicados_de(conn, id)


@router.post("/clientes", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def create_cliente(request: Request, data: ClienteCreate):
    require_admin(request)
    with get_db() as conn:
        try:
            return commands_cliente.crear(conn, data.model_dump())
        except Exception:
            conn.rollback()
            raise


@router.patch("/clientes/{id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def update_cliente(request: Request, id: int, data: ClienteUpdate):
    require_admin(request)
    with get_db() as conn:
        try:
            actual = queries_cliente.obtener(conn, id)
            if actual is None:
                raise HTTPException(404, "Cliente no encontrado")
            updates = data.model_dump(exclude_unset=True)
            try:
                return commands_cliente.actualizar(conn, id, actual, updates)
            except ValueError as e:
                raise HTTPException(400, str(e))
        except Exception:
            conn.rollback()
            raise


@router.delete("/clientes/{id}", status_code=204)
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def delete_cliente(request: Request, id: int):
    require_admin(request)
    with get_db() as conn:
        try:
            if not conn.execute("SELECT id FROM clientes WHERE id=%s", (id,)).fetchone():
                raise HTTPException(404, "Cliente no encontrado")
            commands_cliente.eliminar(conn, id)
        except Exception:
            conn.rollback()
            raise


