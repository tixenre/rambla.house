"""Cuenta del cliente: registro + perfil (#501 — extraído del god-module
`routes/cliente_portal.py`).

Alta del cliente (registro vía token de invitación, mintea la sesión) y perfil
(ver / editar datos personales y fiscales). Registra sus rutas en el router
compartido del paquete `routes.cliente_portal`. `require_cliente` (guard) vive en
`core`.
"""
import logging
from typing import Optional

from fastapi import Request, HTTPException
from pydantic import BaseModel
from itsdangerous import BadSignature, SignatureExpired

from database import get_db, row_to_dict
from auth.session import signer, _make_session_response
from identity.anchor import cuil_valido
from identity.contacts import email_comunicacion, telefono_contacto
from services.precios import es_responsable_inscripto
from services.telefono import formatear_para_guardar
from rate_limit import limiter, CLIENTE_WRITE_LIMIT
from routes.cliente_portal.core import router, require_cliente, cliente_verificado
from clientes.queries import identidad as queries_identidad
from clientes.queries import fiscal as queries_fiscal

logger = logging.getLogger(__name__)


# ── Registro ─────────────────────────────────────────────────────────────────

class RegistroCreate(BaseModel):
    token:    str
    nombre:   str
    apellido: str
    telefono: str
    direccion: str
    cuit:     str
    perfil_impuestos:   Optional[str] = "consumidor_final"
    direccion_maps_url: Optional[str] = None
    # Datos para Factura A — sólo relevantes si perfil = responsable_inscripto.
    razon_social:       Optional[str] = None
    domicilio_fiscal:   Optional[str] = None
    email_facturacion:  Optional[str] = None


@router.get("/api/cliente/registro-info")
@limiter.limit("5/minute")
def cliente_registro_info(request: Request, t: str):
    """Valida el token de registro y devuelve email/nombre. Solo lectura."""
    try:
        payload = signer.loads(t, max_age=1800)
    except (SignatureExpired, BadSignature):
        raise HTTPException(400, "Token inválido o expirado")
    if payload.get("tipo") != "registro":
        raise HTTPException(400, "Token inválido")
    return {"email": payload["email"], "name": payload["name"]}


@router.post("/api/cliente/registro")
@limiter.limit("5/minute")
def cliente_registro(request: Request, data: RegistroCreate):
    # Validar token de registro (firmado por Google callback, max 30 min)
    try:
        payload = signer.loads(data.token, max_age=1800)
    except SignatureExpired:
        raise HTTPException(400, "El enlace de registro expiró. Volvé a ingresar con Google.")
    except BadSignature:
        raise HTTPException(400, "Token de registro inválido.")

    if payload.get("tipo") != "registro":
        raise HTTPException(400, "Token inválido.")

    email = payload["email"]
    name  = payload["name"]

    if not data.nombre.strip() or not data.apellido.strip() or not data.telefono.strip():
        raise HTTPException(400, "Nombre, apellido y teléfono son obligatorios.")

    with get_db() as conn:
        # Verificar que no se haya registrado ya (doble submit)
        existente = conn.execute(
            "SELECT id FROM clientes WHERE LOWER(email) = LOWER(%s)", (email,)
        ).fetchone()
        if existente:
            cliente_id = existente["id"]
        else:
            # Sólo guardamos datos de Factura A si el perfil es responsable
            # inscripto — el resto los puede tener vacíos en DB.
            perfil = data.perfil_impuestos or "consumidor_final"
            es_ri = es_responsable_inscripto(perfil)
            conn.execute("""
                INSERT INTO clientes (
                    nombre, apellido, email, telefono, direccion, cuit,
                    perfil_impuestos, direccion_maps_url,
                    razon_social, domicilio_fiscal, email_facturacion
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data.nombre.strip(),
                data.apellido.strip(),
                email,
                formatear_para_guardar(data.telefono),
                data.direccion.strip() or "-",
                data.cuit.strip() or "-",
                perfil,
                data.direccion_maps_url or None,
                (data.razon_social or "").strip() or None if es_ri else None,
                (data.domicilio_fiscal or "").strip() or None if es_ri else None,
                (data.email_facturacion or "").strip().lower() or None if es_ri else None,
            ))
            conn.commit()
            cliente_id = conn.execute(
                "SELECT id FROM clientes WHERE LOWER(email) = LOWER(%s)", (email,)
            ).fetchone()["id"]

    # Registrar las llaves de login de la cuenta (idempotente): el mail (handle de
    # magic-link) y, si vino del callback de Google, su `sub` estable → la cuenta nace
    # con sus llaves en `login_identities`.
    from auth.commands.identities import link_identity  # perezoso: evita ciclo con auth/__init__
    link_identity(cliente_id=cliente_id, method="email", identifier=email.lower(), verified=True)
    google_sub = payload.get("google_sub")
    if google_sub:
        link_identity(cliente_id=cliente_id, method="google", identifier=google_sub,
                      email=email.lower(), verified=True)

    # Mintea la sesión por el punto único (jti + revocación) — FUERA del `with`
    # porque `_make_session_response` abre su propia conexión (no anidar pools).
    return _make_session_response(
        email, name,
        extra={"role": "cliente", "cliente_id": cliente_id},
        request=request,
    )


# ── Claim de invitación (Fase 4 identidad #1098) ──────────────────────────────
# El admin invita (routes/clientes.py::invitar_cliente) → manda un link single-use → el
# cliente lo abre, lo RECLAMA (consume el magic-link) y queda logueado → registra su
# passkey desde "Métodos de acceso". El email se vincula-como-llave al reclamar (probó
# control del canal). Reusa auth/magic + el punto único de minteo `_make_session_response`.

class ClaimIn(BaseModel):
    token: str


@router.get("/api/cliente/claim-info")
@limiter.limit("10/minute")
def cliente_claim_info(request: Request, t: str):
    """Previsualiza una invitación SIN consumirla (para el landing)."""
    from auth.queries import magic as magic_queries
    ctx = magic_queries.peek(t, purpose="invitacion")
    if not ctx:
        raise HTTPException(400, "Invitación inválida, vencida o ya usada.")
    with get_db() as conn:
        row = conn.execute(
            "SELECT nombre FROM clientes WHERE id=%s", (ctx["cliente_id"],)
        ).fetchone()
    return {"email": ctx["email"], "nombre": row_to_dict(row).get("nombre") if row else None}


@router.post("/api/cliente/claim")
@limiter.limit("10/minute")
def cliente_claim(request: Request, data: ClaimIn):
    """Reclama una cuenta invitada: CONSUME el magic-link (single-use), vincula el email
    como llave verificada y MINTEA la sesión. El cliente queda logueado → registra su
    passkey desde 'Métodos de acceso'."""
    from auth.commands import magic as magic_commands
    ctx = magic_commands.consumir(data.token, purpose="invitacion")
    if not ctx:
        raise HTTPException(400, "Invitación inválida, vencida o ya usada.")
    cliente_id, email = ctx["cliente_id"], ctx["email"]
    with get_db() as conn:
        row = conn.execute("SELECT id, nombre FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
        if not row:
            raise HTTPException(404, "La cuenta de esta invitación ya no existe.")
        nombre = row_to_dict(row).get("nombre") or ""
    from auth.commands.identities import link_identity
    link_identity(cliente_id=cliente_id, method="email", identifier=email, verified=True)
    return _make_session_response(
        email, nombre, extra={"role": "cliente", "cliente_id": cliente_id}, request=request,
    )


# ── Perfil ────────────────────────────────────────────────────────────────────

@router.get("/api/cliente/me")
def cliente_me(request: Request):
    session = require_cliente(request)
    cliente_id = session["cliente_id"]
    with get_db() as conn:
        # `created_at` lo usa el drawer del portal para mostrar "Cliente desde
        # [año]" — no es opcional, el cliente espera verlo en su perfil.
        row = conn.execute(
            """SELECT id, nombre, apellido, email, telefono, direccion, cuit,
                      perfil_impuestos, descuento, direccion_maps_url,
                      razon_social, domicilio_fiscal, email_facturacion,
                      created_at,
                      dni, cuil, dni_validado_at,
                      nombre_renaper, apellido_renaper, fecha_nacimiento_renaper,
                      direccion_renaper, apodo,
                      dni_verificacion_estado, dni_verificacion_motivo
               FROM clientes WHERE id = %s""",
            (cliente_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Cliente no encontrado")
        d = row_to_dict(row)
        # Vista resuelta para DISPLAY (checkout/portal/donde haga falta mostrar
        # "quién es" sin reimplementar la regla): mismo criterio que ya usan
        # contrato/remito — RENAPER si está verificado, si no el dato base
        # (`clientes.queries.identidad`, fuente única con el lado admin) — y el
        # contacto CANÓNICO (`email_comunicacion`/`telefono_contacto`,
        # identity/contacts.py: el teléfono verificado por Didit puede diferir
        # del autodeclarado). Los campos base de arriba siguen intactos para
        # los forms de edición (Contacto/Facturación) — esto es aditivo.
        d["nombre_legal"] = queries_identidad.nombre_legal(d)
        d["direccion_legal"] = queries_identidad.direccion_legal(d)
        d["email_comunicacion"] = email_comunicacion(conn, cliente_id)
        d["telefono_contacto"] = telefono_contacto(conn, cliente_id)
        return d


class VerificarCuitIn(BaseModel):
    # Default "" (no obligatorio a nivel Pydantic) para que el candado de
    # guard (`test_endpoint_cliente_rechaza_sesion_no_cliente`, body {}) llegue
    # a `require_cliente` — la validación real del CUIT es la de abajo.
    cuit: str = ""


@router.post("/api/cliente/facturacion/verificar-cuit")
@limiter.limit("10/minute")
def cliente_verificar_cuit(data: VerificarCuitIn, request: Request):
    """⏰ LEGACY: delegado fino de `POST /api/cliente/facturacion/perfiles`
    (#1240) — se mantiene con esta forma de respuesta (best-effort, siempre
    200) solo mientras el frontend viejo (`FacturacionForm`, antes de la Fase
    7 de #1240) no migre al endpoint nuevo. Remover cuando esa migración
    mergee. No duplica la verificación: reusa `verificar_y_crear_perfil_fiscal`
    tal cual (mismo bloqueo si AFIP no clasifica la condición IVA)."""
    session = require_cliente(request)
    cliente_id = session["cliente_id"]
    cuit = data.cuit.strip()
    if not cuil_valido(cuit):
        raise HTTPException(400, "CUIT/CUIL inválido — verificá el número.")

    from services.facturacion.padron import verificar_y_crear_perfil_fiscal
    with get_db() as conn:
        try:
            persona = verificar_y_crear_perfil_fiscal(cuit, cliente_id, conn)
        except RuntimeError as e:
            conn.rollback()
            return {"encontrado": False, "motivo": str(e)}
        conn.commit()

    return {
        "encontrado": True,
        "cuit": cuit,
        "perfil_impuestos": persona.condicion_iva,
        "razon_social": persona.razon_social,
        "domicilio_fiscal": persona.domicilio,
    }


# ── Perfiles fiscales múltiples (#1240) ──────────────────────────────────────
# El cliente puede tener VARIOS CUIT propios (personal, freelance, etc.) —
# `cliente_perfiles_fiscales`. Toda fila nace de una verificación real contra
# AFIP (`verificar_y_crear_perfil_fiscal`, bloqueante) — cierra el fallback de
# entrada manual sin verificar que tenía `cliente_update_me`. Las productoras
# (entidad fiscal compartida, admin-only) viven en `routes/productoras.py`;
# el cliente solo las LEE (`GET /api/cliente/productoras` más abajo).

class PerfilFiscalCreate(BaseModel):
    cuit: str
    etiqueta: Optional[str] = None
    email_facturacion: Optional[str] = None


@router.get("/api/cliente/facturacion/perfiles")
def cliente_listar_perfiles_fiscales(request: Request):
    session = require_cliente(request)
    cliente_id = session["cliente_id"]
    with get_db() as conn:
        return queries_fiscal.perfiles_fiscales(conn, cliente_id)


@router.post("/api/cliente/facturacion/perfiles", status_code=201)
@limiter.limit("10/minute")
def cliente_crear_perfil_fiscal(data: PerfilFiscalCreate, request: Request):
    """Da de alta (o refresca) un perfil fiscal personal — BLOQUEANTE: si AFIP
    no puede confirmar el CUIT, 422 con el motivo real, no se guarda nada a
    medias (cierra el fallback manual que tenía `cliente_update_me`)."""
    session = require_cliente(request)
    cliente_id = session["cliente_id"]
    cuit = data.cuit.strip()
    if not cuil_valido(cuit):
        raise HTTPException(400, "CUIT/CUIL inválido — verificá el número.")

    from services.facturacion.padron import verificar_y_crear_perfil_fiscal
    with get_db() as conn:
        try:
            verificar_y_crear_perfil_fiscal(cuit, cliente_id, conn, etiqueta=data.etiqueta)
        except RuntimeError as e:
            conn.rollback()
            raise HTTPException(422, f"AFIP no pudo confirmar este CUIT: {e}")
        if data.email_facturacion:
            # No lo resuelve ARCA — campo libre, igual que ya era antes de #1240.
            conn.execute(
                """UPDATE cliente_perfiles_fiscales SET email_facturacion = %s
                   WHERE cliente_id = %s AND cuit = %s""",
                (data.email_facturacion.strip().lower(), cliente_id, cuit),
            )
        conn.commit()
        row = conn.execute(
            """SELECT id, cuit, perfil_impuestos, razon_social, domicilio_fiscal,
                      email_facturacion, etiqueta, es_default
               FROM cliente_perfiles_fiscales
               WHERE cliente_id = %s AND cuit = %s""",
            (cliente_id, cuit),
        ).fetchone()
    return row_to_dict(row) if row else {}


@router.patch("/api/cliente/facturacion/perfiles/{perfil_id}/default")
@limiter.limit(CLIENTE_WRITE_LIMIT)
def cliente_marcar_perfil_default(perfil_id: int, request: Request):
    """Marca un perfil como el default de la cuenta — desmarca el anterior en
    la MISMA transacción (el índice único parcial `uq_cliente_perfiles_
    fiscales_default` nunca ve dos filas TRUE a la vez: primero se ponen todas
    en FALSE, después se marca la elegida)."""
    session = require_cliente(request)
    cliente_id = session["cliente_id"]
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM cliente_perfiles_fiscales WHERE id = %s AND cliente_id = %s",
            (perfil_id, cliente_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Perfil fiscal no encontrado")
        conn.execute(
            "UPDATE cliente_perfiles_fiscales SET es_default = FALSE WHERE cliente_id = %s",
            (cliente_id,),
        )
        conn.execute(
            "UPDATE cliente_perfiles_fiscales SET es_default = TRUE, updated_at = now() WHERE id = %s",
            (perfil_id,),
        )
        conn.commit()
    return {"ok": True}


@router.get("/api/cliente/productoras")
def cliente_listar_productoras(request: Request):
    """Productoras a las que el cliente autenticado está vinculado — solo
    lectura (la crea/edita/vincula el admin, `routes/productoras.py`).
    Alimenta la pantalla "Mis productoras" del portal y el selector del
    checkout."""
    session = require_cliente(request)
    cliente_id = session["cliente_id"]
    with get_db() as conn:
        return queries_fiscal.productoras_vinculadas(conn, cliente_id, solo_facturables=True)


class PerfilUpdate(BaseModel):
    nombre:    Optional[str] = None
    apellido:  Optional[str] = None
    telefono:  Optional[str] = None
    direccion: Optional[str] = None
    apodo:     Optional[str] = None


@router.patch("/api/cliente/me")
@limiter.limit(CLIENTE_WRITE_LIMIT)
def cliente_update_me(data: PerfilUpdate, request: Request):
    """Permite al cliente actualizar sus datos personales.

    Tras verificar identidad (dni_validado_at IS NOT NULL), `nombre`/`apellido`/
    `direccion` quedan bloqueados — son los datos que certifica RENAPER, y el
    portal los muestra en modo lectura desde `*_renaper` una vez verificado.
    `telefono`/`apodo` tampoco se bloquean nunca. NO se permite cambiar email
    (clave de identidad OAuth) ni descuento.

    Los datos FISCALES (cuit/perfil_impuestos/razon_social/domicilio_fiscal/
    email_facturacion) ya NO se editan acá (#1240) — cerraba un fallback de
    entrada manual sin verificar contra AFIP. Viven en
    `POST /api/cliente/facturacion/perfiles` (bloqueante: solo se guarda lo
    que ARCA confirma para el CUIT tipeado)."""
    session = require_cliente(request)
    cliente_id = session["cliente_id"]

    with get_db() as conn:
        verificado = cliente_verificado(conn, cliente_id)

    # Campos bloqueados post-verificación: solo los que certifica RENAPER.
    _BLOQUEADOS = ("nombre", "apellido", "direccion")
    if verificado:
        for campo in _BLOQUEADOS:
            if getattr(data, campo, None) is not None:
                raise HTTPException(
                    403,
                    "Los datos personales no pueden modificarse tras la verificación de identidad. "
                    "Solo podés editar teléfono y apodo.",
                )

    sets, vals = [], []
    if data.nombre is not None:
        n = data.nombre.strip()
        if not n:
            raise HTTPException(400, "El nombre no puede estar vacío")
        sets.append("nombre = %s"); vals.append(n)
    if data.apellido is not None:
        sets.append("apellido = %s"); vals.append(data.apellido.strip())
    if data.telefono is not None:
        sets.append("telefono = %s"); vals.append(formatear_para_guardar(data.telefono))
    if data.direccion is not None:
        sets.append("direccion = %s"); vals.append(data.direccion.strip())
    if data.apodo is not None:
        sets.append("apodo = %s"); vals.append(data.apodo.strip() or None)

    if not sets:
        raise HTTPException(400, "Sin cambios")

    with get_db() as conn:
        try:
            vals.append(cliente_id)
            conn.execute(f"UPDATE clientes SET {', '.join(sets)} WHERE id = %s", tuple(vals))
            conn.commit()
            row = conn.execute(
                """SELECT id, nombre, apellido, email, telefono, direccion, cuit,
                          perfil_impuestos, descuento, direccion_maps_url,
                          razon_social, domicilio_fiscal, email_facturacion,
                          dni, cuil, dni_validado_at,
                          nombre_renaper, apellido_renaper, fecha_nacimiento_renaper,
                          direccion_renaper, apodo,
                          dni_verificacion_estado, dni_verificacion_motivo
                   FROM clientes WHERE id = %s""",
                (cliente_id,),
            ).fetchone()
            return row_to_dict(row) if row else {}
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            logger.exception("Error al actualizar el perfil del cliente")
            raise HTTPException(500, "No se pudo actualizar el perfil")
