"""routes/contabilidad.py — Módulo contable (#809).

Transporte HTTP fino sobre el motor `backend/contabilidad/` (igual que
`routes/reportes.py` sobre `reportes/`). Fase 1: cuentas (CRUD) + saldos + tablero
mínimo. Acceso = cualquier admin (`require_admin`); el actor de auditoría sale de
`admin.get("email")`.
"""

import functools
import logging

import psycopg.errors
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from database import get_db
from auth.guards import require_admin
from rate_limit import limiter, ADMIN_UPLOAD_LIMIT, ADMIN_WRITE_LIMIT
from contabilidad.commands.cuentas import crear_cuenta, desactivar_cuenta, editar_cuenta
from contabilidad.queries.cuentas import listar_cuentas, obtener_cuenta
from contabilidad.queries.saldos import saldos as _saldos
from contabilidad.commands.categorias import crear_categoria
from contabilidad.queries.categorias import listar_categorias
from contabilidad.commands.movimientos import (
    actualizar_comprobante,
    anular_movimiento,
    crear_cambio_divisa,
    crear_movimiento,
    editar_movimiento,
)
from contabilidad.queries.movimientos import (
    beneficiarios_usados,
    cobros_mensuales,
    gastos_por_categoria,
    listar_movimientos,
    obtener_movimiento,
)
from contabilidad.queries.tablero import tablero as _tablero
from contabilidad.queries.pyl import ganancia_neta
from contabilidad.queries.rendicion import rendicion as _rendicion
from contabilidad.queries.posiciones import posiciones as _posiciones
from contabilidad.commands.rendicion import saldar as _saldar
from contabilidad.commands.cierres import cerrar_mes as _cerrar_mes, reabrir_mes as _reabrir_mes
from contabilidad.queries.reconciliacion import reconciliar as _reconciliar

logger = logging.getLogger(__name__)
router = APIRouter()


def map_pg_errors(fn):
    """Traduce a un 400 limpio los errores de Postgres que se cuelan más allá de
    las cotas de `Field(...)` del body (auditoría 2026-07-02) — sin esto, un
    `NumericValueOutOfRange`/`UniqueViolation` no anticipado por el motor (que
    ya devuelve `ValueError`→400 para lo que sí anticipa) sube crudo al handler
    global (`main.py`), que expone `f"{type(exc).__name__}: {exc}"` — nombre de
    constraint/columna de Postgres — al cliente. No reemplaza `except ValueError`
    (ya lo maneja cada endpoint); compone alrededor de él. Reusado en
    `routes/alquileres/pagos.py`."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except psycopg.errors.UniqueViolation:
            raise HTTPException(400, "Ya existe un registro con ese valor.")
        except psycopg.errors.NumericValueOutOfRange:
            raise HTTPException(400, "Un valor numérico es demasiado grande.")
    return wrapper


class CuentaCreate(BaseModel):
    nombre: str = Field(max_length=120)
    tipo: str = Field(max_length=20)
    socio: str | None = Field(default=None, max_length=40)
    moneda: str = Field(default="ARS", max_length=3)
    saldo_inicial: int = Field(default=0, ge=-2_000_000_000, le=2_000_000_000)
    fecha_apertura: str | None = Field(default=None, max_length=10)
    orden: int = Field(default=0, ge=0, le=10_000)


class CuentaUpdate(BaseModel):
    nombre: str | None = Field(default=None, max_length=120)
    saldo_inicial: int | None = Field(default=None, ge=-2_000_000_000, le=2_000_000_000)
    fecha_apertura: str | None = Field(default=None, max_length=10)
    orden: int | None = Field(default=None, ge=0, le=10_000)
    activa: bool | None = None


@router.get("/admin/contabilidad/saldos")
def get_saldos(request: Request):
    """Saldos de todas las cuentas activas + total disponible. Los ingresos por
    alquiler ya vienen derivados de `alquiler_pagos`."""
    require_admin(request)
    with get_db() as conn:
        return _saldos(conn)


@router.get("/admin/contabilidad/tablero")
def get_tablero(request: Request, mes: str | None = None):
    """Tablero financiero: plata disponible por caja + ganancia neta del mes +
    rendición pendiente. `mes` opcional ('YYYY-MM', default: mes actual)."""
    require_admin(request)
    with get_db() as conn:
        try:
            return _tablero(conn, mes)
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.get("/admin/contabilidad/cuentas")
def get_cuentas(request: Request, incluir_inactivas: bool = False):
    """Cuentas crudas (para administrar). `incluir_inactivas=true` trae también las
    dadas de baja."""
    require_admin(request)
    with get_db() as conn:
        return {"cuentas": listar_cuentas(conn, incluir_inactivas=incluir_inactivas)}


@router.post("/admin/contabilidad/cuentas")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def post_cuenta(request: Request, body: CuentaCreate):
    """Crea una cuenta/caja nueva."""
    admin = require_admin(request)
    with get_db() as conn:
        try:
            cuenta = crear_cuenta(
                conn,
                nombre=body.nombre,
                tipo=body.tipo,
                socio=body.socio,
                moneda=body.moneda,
                saldo_inicial=body.saldo_inicial,
                fecha_apertura=body.fecha_apertura,
                orden=body.orden,
                por=admin.get("email"),
            )
            conn.commit()
            return cuenta
        except ValueError as e:
            conn.rollback()
            raise HTTPException(400, str(e))
        except Exception:
            conn.rollback()
            raise


@router.patch("/admin/contabilidad/cuentas/{cuenta_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def patch_cuenta(request: Request, cuenta_id: int, body: CuentaUpdate):
    """Edita una cuenta. No se puede cambiar tipo ni socio."""
    admin = require_admin(request)
    campos = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None
              or k == "activa"}
    with get_db() as conn:
        try:
            cuenta = editar_cuenta(conn, cuenta_id, campos=campos, por=admin.get("email"))
            conn.commit()
            return cuenta
        except ValueError as e:
            conn.rollback()
            raise HTTPException(400, str(e))
        except Exception:
            conn.rollback()
            raise


@router.delete("/admin/contabilidad/cuentas/{cuenta_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def delete_cuenta(request: Request, cuenta_id: int):
    """Baja lógica de una cuenta (falla si tiene saldo distinto de cero)."""
    admin = require_admin(request)
    with get_db() as conn:
        try:
            cuenta = desactivar_cuenta(conn, cuenta_id, por=admin.get("email"))
            conn.commit()
            return cuenta
        except ValueError as e:
            conn.rollback()
            raise HTTPException(400, str(e))
        except Exception:
            conn.rollback()
            raise


# ── Categorías de gasto ─────────────────────────────────────────────────────

class CategoriaCreate(BaseModel):
    nombre: str = Field(max_length=80)


@router.get("/admin/contabilidad/categorias")
def get_categorias(request: Request):
    require_admin(request)
    with get_db() as conn:
        return {"categorias": listar_categorias(conn)}


@router.get("/admin/contabilidad/beneficiarios")
def get_beneficiarios(request: Request):
    """Beneficiarios ya usados, para el autocompletado del formulario."""
    require_admin(request)
    with get_db() as conn:
        return {"beneficiarios": beneficiarios_usados(conn)}


@router.post("/admin/contabilidad/categorias")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def post_categoria(request: Request, body: CategoriaCreate):
    require_admin(request)
    with get_db() as conn:
        try:
            cat = crear_categoria(conn, body.nombre)
            conn.commit()
            return cat
        except ValueError as e:
            conn.rollback()
            raise HTTPException(400, str(e))
        except Exception:
            conn.rollback()
            raise


# ── Movimientos (gasto / transferencia / retiro / aporte / ajuste) ──────────

class MovimientoCreate(BaseModel):
    tipo: str = Field(max_length=20)
    monto: int = Field(gt=0, le=2_000_000_000)
    cuenta_origen_id: int | None = Field(default=None, gt=0, lt=2_147_483_647)
    cuenta_destino_id: int | None = Field(default=None, gt=0, lt=2_147_483_647)
    categoria_id: int | None = Field(default=None, gt=0, lt=2_147_483_647)
    metodo: str | None = Field(default=None, max_length=20)
    fecha: str | None = Field(default=None, max_length=10)
    nota: str | None = Field(default=None, max_length=500)
    beneficiario: str | None = Field(default=None, max_length=120)


class MovimientoUpdate(BaseModel):
    monto: int | None = Field(default=None, gt=0, le=2_000_000_000)
    cuenta_origen_id: int | None = Field(default=None, gt=0, lt=2_147_483_647)
    cuenta_destino_id: int | None = Field(default=None, gt=0, lt=2_147_483_647)
    categoria_id: int | None = Field(default=None, gt=0, lt=2_147_483_647)
    metodo: str | None = Field(default=None, max_length=20)
    fecha: str | None = Field(default=None, max_length=10)
    nota: str | None = Field(default=None, max_length=500)
    beneficiario: str | None = Field(default=None, max_length=120)


class AnularBody(BaseModel):
    motivo: str = Field(max_length=500)


class CambioDivisaCreate(BaseModel):
    cuenta_origen_id: int = Field(gt=0, lt=2_147_483_647)
    cuenta_destino_id: int = Field(gt=0, lt=2_147_483_647)
    monto_origen: int | None = Field(default=None, gt=0, le=2_000_000_000)
    monto_destino: int | None = Field(default=None, gt=0, le=2_000_000_000)
    cotizacion: float | None = Field(default=None, gt=0, le=1_000_000)
    fecha: str | None = Field(default=None, max_length=10)
    nota: str | None = Field(default=None, max_length=500)


@router.get("/admin/contabilidad/movimientos")
def get_movimientos(
    request: Request,
    tipo: str | None = None,
    cuenta_id: int | None = None,
    categoria_id: int | None = None,
    beneficiario: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    incluir_anulados: bool = False,
    limit: int = 500,
):
    require_admin(request)
    with get_db() as conn:
        # Movimientos manuales (salvo que se filtre solo cobros).
        movs = (
            []
            if tipo == "cobro"
            else listar_movimientos(
                conn, tipo=tipo, cuenta_id=cuenta_id, categoria_id=categoria_id,
                beneficiario=beneficiario, desde=desde, hasta=hasta,
                incluir_anulados=incluir_anulados, limit=limit,
            )
        )
        # Cobros de pedidos agregados por mes (read-only) — se muestran junto a los
        # movimientos salvo que se filtre por tipo manual / categoría / beneficiario
        # (los cobros no tienen esos atributos).
        cobros: list = []
        if tipo in (None, "", "cobro") and not categoria_id and not beneficiario:
            cobrador = None
            if cuenta_id:
                cta = obtener_cuenta(conn, cuenta_id)
                cobrador = cta["socio"] if cta else None
                # Caja sin cobrador (Efectivo/Banco/Dólares) → no recibe cobros.
                if not cobrador:
                    cobros = []
                    return {"movimientos": movs, "cobros": cobros, "count": len(movs)}
            cobros = cobros_mensuales(conn, desde=desde, hasta=hasta, cobrador=cobrador)
    return {"movimientos": movs, "cobros": cobros, "count": len(movs)}


@router.post("/admin/contabilidad/movimientos")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def post_movimiento(request: Request, body: MovimientoCreate):
    """Registra un movimiento (gasto/transferencia/retiro/aporte/ajuste)."""
    admin = require_admin(request)
    with get_db() as conn:
        try:
            mov = crear_movimiento(
                conn, tipo=body.tipo, monto=body.monto,
                cuenta_origen_id=body.cuenta_origen_id,
                cuenta_destino_id=body.cuenta_destino_id,
                categoria_id=body.categoria_id, metodo=body.metodo,
                fecha=body.fecha, nota=body.nota, beneficiario=body.beneficiario,
                por=admin.get("email"),
            )
            conn.commit()
            return mov
        except ValueError as e:
            conn.rollback()
            raise HTTPException(400, str(e))
        except Exception:
            conn.rollback()
            raise


@router.post("/admin/contabilidad/cambio-divisa")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def post_cambio_divisa(request: Request, body: CambioDivisaCreate):
    """Compra/venta de divisa (ej. pesos → dólares): registra los dos `ajuste`
    atados de `crear_cambio_divisa`. Mandá 2 de {monto_origen, monto_destino,
    cotizacion} — el tercero se deriva."""
    admin = require_admin(request)
    with get_db() as conn:
        try:
            resultado = crear_cambio_divisa(
                conn, cuenta_origen_id=body.cuenta_origen_id,
                cuenta_destino_id=body.cuenta_destino_id,
                monto_origen=body.monto_origen, monto_destino=body.monto_destino,
                cotizacion=body.cotizacion, fecha=body.fecha, nota=body.nota,
                por=admin.get("email"),
            )
            conn.commit()
            return resultado
        except ValueError as e:
            conn.rollback()
            raise HTTPException(400, str(e))
        except Exception:
            conn.rollback()
            raise


@router.patch("/admin/contabilidad/movimientos/{mov_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def patch_movimiento(request: Request, mov_id: int, body: MovimientoUpdate):
    admin = require_admin(request)
    campos = body.model_dump(exclude_unset=True)
    with get_db() as conn:
        try:
            mov = editar_movimiento(conn, mov_id, campos=campos, por=admin.get("email"))
            conn.commit()
            return mov
        except ValueError as e:
            conn.rollback()
            raise HTTPException(400, str(e))
        except Exception:
            conn.rollback()
            raise


@router.post("/admin/contabilidad/movimientos/{mov_id}/anular")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def anular_mov(request: Request, mov_id: int, body: AnularBody):
    """Soft-delete con motivo: la plata nunca se borra, queda anulada y trazable."""
    admin = require_admin(request)
    with get_db() as conn:
        try:
            mov = anular_movimiento(conn, mov_id, motivo=body.motivo, por=admin.get("email"))
            conn.commit()
            return mov
        except ValueError as e:
            conn.rollback()
            raise HTTPException(400, str(e))
        except Exception:
            conn.rollback()
            raise


_COMPROBANTE_MAX = 5 * 1024 * 1024  # 5 MB
_COMPROBANTE_TIPOS = ("application/pdf", "image/jpeg", "image/png", "image/webp")


@router.post("/admin/contabilidad/movimientos/{mov_id}/comprobante")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
async def subir_comprobante(request: Request, mov_id: int, file: UploadFile = File(...)):
    """Adjunta un comprobante (PDF o imagen) a un movimiento. Sube a R2 reusando
    la infra de media (`services/media/storage`)."""
    admin = require_admin(request)
    content = await file.read()
    if len(content) > _COMPROBANTE_MAX:
        raise HTTPException(400, "El comprobante supera los 5 MB.")
    ctype = (file.content_type or "").lower()
    if ctype not in _COMPROBANTE_TIPOS:
        raise HTTPException(400, "Formato no soportado (subí un PDF o una imagen).")

    with get_db() as conn:
        mov = obtener_movimiento(conn, mov_id)
        if not mov:
            raise HTTPException(404, "El movimiento no existe.")
        try:
            from services.media.service import store_raw_document
            from services.media import storage

            # Borrado best-effort del comprobante anterior.
            vieja = mov.get("comprobante_key")
            if vieja:
                storage.delete_object(vieja, private=True)

            key, presigned = store_raw_document(
                content,
                kind="comprobante-contabilidad",
                ref=str(mov_id),
                content_type=ctype,
                presign_expires=3600,
            )
            actualizar_comprobante(conn, mov_id, key=key, por=admin.get("email"))
            conn.commit()
            return {"comprobante_url": presigned, "comprobante_key": key}
        except HTTPException:
            conn.rollback()
            raise
        except ValueError as e:
            conn.rollback()
            raise HTTPException(400, str(e))
        except Exception:
            conn.rollback()
            logger.exception("No se pudo subir el comprobante")
            raise HTTPException(502, "No se pudo subir el comprobante")


@router.get("/admin/contabilidad/gastos")
def get_gastos(request: Request, desde: str | None = None, hasta: str | None = None):
    """Gastos agrupados por categoría en la ventana (para el tablero / análisis)."""
    require_admin(request)
    with get_db() as conn:
        filas = gastos_por_categoria(conn, desde, hasta)
    return {"por_categoria": filas, "total": sum(f["monto"] for f in filas)}


@router.get("/admin/contabilidad/pyl/{mes}")
def get_pyl(request: Request, mes: str):
    """Ganancia neta del mes (ingresos devengados − gastos)."""
    require_admin(request)
    with get_db() as conn:
        try:
            return ganancia_neta(conn, mes)
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.get("/admin/contabilidad/reporte/{mes}")
def get_reporte_mensual(request: Request, mes: str):
    """Reporte mensual completo de Rental: devengado + percibido + gastos +
    ganancia + cargos de socios + cuenta corriente, derivado del motor."""
    require_admin(request)
    from contabilidad.queries.reporte_mensual import reporte_mensual

    with get_db() as conn:
        try:
            return reporte_mensual(conn, mes)
        except ValueError as e:
            raise HTTPException(400, str(e))


# ── Rendición de cuentas mensual entre socios ───────────────────────────────

class SaldarBody(BaseModel):
    de: str = Field(max_length=20)
    a: str = Field(max_length=20)
    monto: int = Field(gt=0, le=2_000_000_000)
    metodo: str | None = Field(default=None, max_length=20)
    fecha: str | None = Field(default=None, max_length=10)
    nota: str | None = Field(default=None, max_length=500)


@router.get("/admin/contabilidad/rendicion/{mes}")
def get_rendicion(request: Request, mes: str):
    """Rendición del mes: cuánto le corresponde y cuánto cobró cada parte, el
    saldo pendiente, los movimientos sugeridos y lo ya rendido."""
    require_admin(request)
    with get_db() as conn:
        try:
            return _rendicion(conn, mes)
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.get("/admin/contabilidad/posiciones")
def get_posiciones(request: Request):
    """Posición ACUMULADA de las 4 partes al día de hoy: cuánto le falta recibir o
    cuánto tiene de más cada una, sumando todo desde el clean start. Es la lectura
    que dice si mover plata tiene sentido — a diferencia de `/rendicion/{mes}`, que
    es la foto de UN mes y arranca de cero cada vez."""
    require_admin(request)
    with get_db() as conn:
        return _posiciones(conn)


@router.post("/admin/contabilidad/rendicion/{mes}/saldar")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def post_saldar(request: Request, mes: str, body: SaldarBody):
    """Registra un saldado real de rendición (transferencia entre las cajas de las
    partes, marcada como rendición en el libro)."""
    admin = require_admin(request)
    with get_db() as conn:
        try:
            mov = _saldar(
                conn, mes, de=body.de, a=body.a, monto=body.monto,
                metodo=body.metodo, fecha=body.fecha, nota=body.nota,
                por=admin.get("email"),
            )
            conn.commit()
            return mov
        except ValueError as e:
            conn.rollback()
            raise HTTPException(400, str(e))
        except Exception:
            conn.rollback()
            raise


# ── Reconciliación + cierre contable del mes ────────────────────────────────

@router.get("/admin/contabilidad/reconciliacion")
def get_reconciliacion(request: Request):
    """Semáforo de confianza: chequea que la plata del módulo cuadre."""
    require_admin(request)
    with get_db() as conn:
        return _reconciliar(conn)


@router.post("/admin/contabilidad/cierres/{mes}")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def post_cierre(request: Request, mes: str):
    """Cierra un mes contable: congela la foto y traba la edición de sus
    movimientos. Idempotente."""
    admin = require_admin(request)
    with get_db() as conn:
        try:
            return _cerrar_mes(conn, mes, admin.get("email"))
        except ValueError as e:
            conn.rollback()
            raise HTTPException(400, str(e))


@router.delete("/admin/contabilidad/cierres/{mes}")
@limiter.limit(ADMIN_WRITE_LIMIT)
@map_pg_errors
def delete_cierre(request: Request, mes: str):
    """Reabre un mes contable cerrado."""
    require_admin(request)
    with get_db() as conn:
        try:
            reabierto = _reabrir_mes(conn, mes)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"mes": mes, "cerrado": False, "reabierto": reabierto}
