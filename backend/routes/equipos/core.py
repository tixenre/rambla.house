"""
routes/equipos.py — CRUD de equipos, kits, categorías y fichas.
"""

import calendar as _cal
import datetime
import logging
import re
from datetime import date as _date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Query, HTTPException, Request, Response
from pydantic import BaseModel, Field

from database import (
    get_db, row_to_dict,
    MARCA_SUBQUERY, MARCA_NOMBRE_EXPR,
)
from rate_limit import limiter, ADMIN_WRITE_LIMIT
from busqueda import construir
from reservas import (
    reservado_total,
    ESTADOS_RESERVADO,  # noqa: F401 — re-export canónico (guard: test_reservas_sql_safety)
)
from reservas.semantics import parientes_de
from auth.session import get_session
from auth.guards import require_admin
from services.nombre_service import actualizar_nombres_de
from services.catalogo import proyectar_lista, proyectar_uno
from services.categorias import (
    set_categoria_masivo,
    add_categoria_masivo,
    remove_categoria_masivo,
    copiar_categorias,
    expandir_a_descendientes,
    sql_filtro_categoria,
    sql_filtro_equipos_por_categoria,
    buscar_id_por_nombre,
)
from services.specs.queries.search_source import specs_search_expr
from services.categorias.errors import CategoriaNoExiste
# `delete_equipo` limpia el blob HTML scrapeado en R2 al borrar un equipo; los
# endpoints de fotos viven en `routes.equipos.fotos` (importan estos mismos
# helpers de `services.media.storage` por su cuenta). Lo testea
# `test_delete_equipo_r2_cleanup` parcheando estos nombres sobre `core`.
from services.media.storage import _r2_config, delete_object as _delete_from_r2

router = APIRouter()


# Campos buscables del equipo (motor único backend/busqueda). Incluye la marca
# (subquery por brand_id), los textos de la ficha (descripción + keywords), y
# las specs estructuradas (#1163 F4: value+label+aliases de cada spec, vía el
# embudo de alias de valor) — la barra es un "find anything": buscás "log3",
# "iso 25600" o "FF" y aparece aunque la palabra viva en un spec, no en el
# nombre ni en la ficha.
_FICHA_EXPR = (
    "(SELECT string_agg(coalesce(ef.descripcion, '') || ' ' || coalesce(ef.keywords_json, ''), ' ') "
    "FROM equipo_fichas ef WHERE ef.equipo_id = e.id)"
)
CAMPOS_EQUIPO = [
    "e.nombre", MARCA_NOMBRE_EXPR, "e.modelo", "e.serie", _FICHA_EXPR,
    specs_search_expr(),
]


# ── Modelos ──────────────────────────────────────────────────────────────────

def _validar_categoria_specs(v: Optional[str]) -> Optional[str]:
    """Valida que la categoría de specs sea una del registry (o None)."""
    if v is None or v == "":
        return None
    from services.specs import REGISTRY
    if v not in REGISTRY.categorias:
        validas = ", ".join(REGISTRY.categorias)
        raise ValueError(f"categoria_specs inválida: '{v}'. Opciones: {validas}")
    return v


_TIPOS_EQUIPO = frozenset({"simple", "kit", "combo"})


def _validar_tipo(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in _TIPOS_EQUIPO:
        raise ValueError(f"tipo inválido: '{v}'. Opciones: simple, kit, combo")
    return v


class EquipoCreate(BaseModel):
    from pydantic import field_validator
    nombre:           str
    marca:            Optional[str]   = None
    modelo:           Optional[str]   = None
    cantidad:         int             = Field(default=1, ge=0, le=9999)
    precio_jornada:   Optional[int]   = Field(default=None, ge=0, le=2_147_483_647)
    precio_usd:       Optional[float] = Field(default=None, ge=0)
    roi_pct:          Optional[float] = Field(default=None, ge=0, le=100)
    valor_reposicion: Optional[float] = Field(default=None, ge=0)
    foto_url:         Optional[str]   = None
    fecha_compra:     Optional[str]   = None
    serie:            Optional[str]   = None
    bh_url:           Optional[str]   = None
    dueno:            Optional[str]   = "Rental"
    visible_catalogo: Optional[int]   = 1
    estado:           Optional[str]   = "operativo"   # operativo / en_mantenimiento / fuera_servicio
    ficha_completa:   Optional[bool]  = False
    # Categoría de specs (1 de las 5 del registry): define qué specs aplican.
    categoria_specs: Optional[str] = None
    # Tipo de producto: 'simple' = equipo suelto, 'kit' = con accesorios compartidos,
    # 'combo' = agrupación derivada. Gobierna precio, stock y disponibilidad.
    tipo:            Optional[str]   = "simple"

    @field_validator("precio_jornada")
    @classmethod
    def validate_precio(cls, v):
        if v is not None and v < 0:
            raise ValueError("precio_jornada no puede ser negativo")
        return v

    @field_validator("cantidad")
    @classmethod
    def validate_cantidad(cls, v):
        if v is not None and v < 0:
            raise ValueError("cantidad no puede ser negativa")
        return v

    @field_validator("categoria_specs")
    @classmethod
    def validate_categoria_specs(cls, v):
        return _validar_categoria_specs(v)

    @field_validator("tipo")
    @classmethod
    def validate_tipo(cls, v):
        return _validar_tipo(v)


class EquipoUpdate(BaseModel):
    from pydantic import field_validator
    nombre:           Optional[str]   = None
    marca:            Optional[str]   = None
    modelo:           Optional[str]   = None
    cantidad:         Optional[int]   = Field(default=None, ge=0, le=9999)
    precio_jornada:   Optional[int]   = Field(default=None, ge=0, le=2_147_483_647)
    # Flag explícito que el frontend manda para indicar si el precio
    # viene de la fórmula (auto, false) o lo tipeó el admin a mano (true).
    # Si no se manda y se cambia precio_jornada, el endpoint infiere
    # según contexto (ver update_equipo).
    precio_jornada_manual: Optional[bool] = None
    precio_usd:       Optional[float] = Field(default=None, ge=0)
    roi_pct:          Optional[float] = Field(default=None, ge=0, le=100)
    valor_reposicion: Optional[float] = Field(default=None, ge=0)
    foto_url:         Optional[str]   = None
    fecha_compra:     Optional[str]   = None
    serie:            Optional[str]   = None
    bh_url:           Optional[str]   = None
    dueno:            Optional[str]   = None
    visible_catalogo: Optional[int]   = None
    estado:           Optional[str]   = None
    ficha_completa:   Optional[bool]  = None
    # Categoría de specs (1 de las 5 del registry): define qué specs aplican.
    categoria_specs: Optional[str] = None
    # Tipo de producto: 'simple' / 'kit' / 'combo'.
    tipo:            Optional[str]   = None

    @field_validator("precio_jornada")
    @classmethod
    def validate_precio(cls, v):
        if v is not None and v < 0:
            raise ValueError("precio_jornada no puede ser negativo")
        return v

    @field_validator("cantidad")
    @classmethod
    def validate_cantidad(cls, v):
        if v is not None and v < 0:
            raise ValueError("cantidad no puede ser negativa")
        return v

    @field_validator("categoria_specs")
    @classmethod
    def validate_categoria_specs(cls, v):
        return _validar_categoria_specs(v)

    @field_validator("tipo")
    @classmethod
    def validate_tipo(cls, v):
        return _validar_tipo(v)


# ── Disponibilidad en tiempo real ────────────────────────────────────────────

@router.get("/equipos/afuera")
def equipos_afuera():
    """
    Devuelve los equipos actualmente retirados (pedidos en estado 'retirado'
    con fecha_hasta >= hoy), con cantidad afuera y fecha de devolución.
    Respuesta: { "equipo_id": { cantidad_afuera, stock_total, devuelve, pedidos } }
    """
    today = datetime.date.today().isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                pi.equipo_id,
                e.cantidad                                              AS stock_total,
                SUM(pi.cantidad)                                        AS cantidad_afuera,
                MIN(p.fecha_hasta)                                      AS devuelve_pronto,
                MAX(p.fecha_hasta)                                      AS devuelve_ultimo,
                STRING_AGG(
                    COALESCE(c.nombre || ' ' || c.apellido, p.cliente_nombre),
                    ', '
                )                                                       AS clientes
            FROM alquiler_items pi
            JOIN alquileres  p ON p.id  = pi.pedido_id
            JOIN equipos  e ON e.id  = pi.equipo_id
            LEFT JOIN clientes c ON c.id = p.cliente_id
            WHERE p.estado    = 'retirado'
              AND p.fecha_hasta >= %s
            GROUP BY pi.equipo_id, e.cantidad
        """, (today,)).fetchall()
        return {str(r["equipo_id"]): row_to_dict(r) for r in rows}


@router.get("/equipos/kpis")
def equipos_kpis(request: Request):
    """KPIs del inventario para el header de /admin/equipos:
    - total: equipos FÍSICOS del catálogo (no eliminados). Excluye los combos: un
      combo es un bundle (sin stock propio, precio derivado), no un equipo distinto.
    - en_uso_hoy: unidades en pedidos retirados que solapan hoy.
    - mantenimiento: equipos con mantenimiento que bloquea stock activo hoy.
    """
    require_admin(request)
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM equipos "
            "WHERE eliminado_at IS NULL AND es_recurso_interno = FALSE AND tipo != 'combo'"
        ).fetchone()[0]
        en_uso_hoy = conn.execute("""
            SELECT COALESCE(SUM(pi.cantidad), 0)
            FROM alquiler_items pi
            JOIN alquileres p ON p.id = pi.pedido_id
            WHERE p.estado = 'retirado'
              AND p.fecha_desde::date <= CURRENT_DATE
              AND p.fecha_hasta::date >= CURRENT_DATE
        """).fetchone()[0]
        mantenimiento = conn.execute("""
            SELECT COUNT(DISTINCT equipo_id)
            FROM equipo_mantenimiento
            WHERE bloquea_stock = TRUE
              AND fecha::date <= CURRENT_DATE
              AND COALESCE(fecha_hasta, fecha)::date >= CURRENT_DATE
        """).fetchone()[0]
        return {
            "total": int(total or 0),
            "en_uso_hoy": int(en_uso_hoy or 0),
            "mantenimiento": int(mantenimiento or 0),
        }


# ── Rutas de equipos ─────────────────────────────────────────────────────────


@router.get("/equipos")
def list_equipos(
    request:       Request,
    response:      Response,
    q:                Optional[str]  = Query(None),
    categoria:        Optional[str]  = Query(None),
    marca:            Optional[str]  = Query(None, description="Filtra por nombre exacto de marca"),
    solo_visibles:    Optional[bool] = Query(None),
    solo_incompletos: Optional[bool] = Query(None),
    falta: Optional[str] = Query(None, description="Filtra equipos sin un campo: foto|categoria|nombre_publico|descripcion|serie|valor_reposicion (#350)"),
    incluir_eliminados: Optional[bool] = Query(None, description="Si true (solo admin), incluye soft-deleted"),
    solo_eliminados:  Optional[bool] = Query(None, description="Si true (solo admin), SOLO soft-deleted (vista papelera)"),
    sort:          Optional[str]  = Query(None, description="ranking | nombre | precio_asc | precio_desc | id"),
    spec:          Optional[list[str]] = Query(None, description="Filtros por specs: spec=key:valor"),
    page:          int = Query(1, ge=1),
    per_page:      int = Query(200, ge=1, le=500),
    desde:         Optional[str]  = Query(None, description="Fecha inicio (YYYY-MM-DD) para calcular disponibilidad"),
    hasta:         Optional[str]  = Query(None, description="Fecha fin (YYYY-MM-DD) para calcular disponibilidad"),
    incluir_detalle: Optional[bool] = Query(
        None,
        description="Si false (solo admin — se ignora en catálogo público), "
        "saltea kit/ficha/specs para vistas de listado que no los muestran "
        "(ej. la tabla de búsqueda del admin). El detalle de un equipo puntual "
        "(GET /equipos/{id}) los trae completos siempre, sin cambios.",
    ),
):
    """Lista equipos con sort y filtros.

    sort por defecto: "ranking" → ORDER BY relevancia_manual ASC,
    popularidad_score DESC, nombre ASC. Otros valores: nombre,
    precio_asc, precio_desc, id.

    spec: filtros por specs estructurados. Formato `key:valor`. Múltiples
    valores se AND-ean. Ej. `?spec=montura:E&spec=video_max:4K` filtra
    equipos con montura=E Y video_max=4K.
    """
    offset = (page - 1) * per_page
    base_sql = "FROM equipos e WHERE 1=1"
    params: list = []

    # El centinela del Estudio (es_recurso_interno) no es un producto del
    # catálogo: se excluye SIEMPRE (público y admin), filtros incluidos.
    base_sql += " AND e.es_recurso_interno = FALSE"

    session = get_session(request)
    is_admin = bool(session)
    # Descuento de catálogo (jornadas vs. cliente, no acumulable): solo aplica
    # para una sesión CLIENTE puntual (no admin) — mismo criterio de precedencia
    # que `routes/alquileres/cotizacion.py` (un admin navegando el catálogo no
    # tiene "su propio" descuento de cliente que mostrar).
    cliente_id = (
        session["cliente_id"]
        if session and session.get("role") == "cliente" and session.get("cliente_id")
        else None
    )
    if solo_visibles or not is_admin:
        base_sql += " AND e.visible_catalogo = 1 AND e.estado != 'fuera_servicio'"

    # Filtro admin: equipos cuya ficha el admin aún no marcó como completa.
    if solo_incompletos and is_admin:
        base_sql += " AND e.ficha_completa = FALSE"

    # Filtro por campo faltante (#350) — alimenta los CTAs del dashboard de calidad.
    # Mismos criterios que /api/admin/inventario/calidad para consistencia.
    if falta and is_admin:
        FALTA_SQL = {
            "foto":              " AND NULLIF(TRIM(COALESCE(e.foto_url, '')), '') IS NULL",
            "nombre_publico":    " AND NULLIF(TRIM(COALESCE(e.nombre_publico, '')), '') IS NULL",
            "serie":             " AND NULLIF(TRIM(COALESCE(e.serie, '')), '') IS NULL",
            "valor_reposicion":  " AND (e.valor_reposicion IS NULL OR e.valor_reposicion = 0)",
            "descripcion": (
                " AND NOT EXISTS ("
                " SELECT 1 FROM equipo_fichas f"
                " WHERE f.equipo_id = e.id"
                " AND NULLIF(TRIM(COALESCE(f.descripcion, '')), '') IS NOT NULL)"
            ),
            "categoria": sql_filtro_categoria(),
        }
        if falta in FALTA_SQL:
            base_sql += FALTA_SQL[falta]

    # Soft delete (#206): por default solo activos. Admin puede pedir ver
    # eliminados (papelera) o todos.
    if is_admin and solo_eliminados:
        base_sql += " AND e.eliminado_at IS NOT NULL"
    elif is_admin and incluir_eliminados:
        pass  # no filter
    else:
        base_sql += " AND e.eliminado_at IS NULL"

    # ── Filtros por specs estructurados (PR E) ──
    # Cada `spec=key:valor` agrega un AND EXISTS sobre equipo_specs.
    # Post refactor unificar_specs_definitions: el key del query string sigue
    # siendo el spec_key humano (montura, formato, etc.); resolvemos a
    # spec_def_id vía JOIN.
    if spec:
        for s in spec:
            if ":" not in s:
                continue
            key, value = s.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if not key or not value:
                continue
            base_sql += (
                " AND EXISTS ("
                " SELECT 1 FROM equipo_specs es"
                " JOIN spec_definitions sd ON sd.id = es.spec_def_id"
                " WHERE es.equipo_id = e.id AND LOWER(sd.spec_key) = %s"
                " AND LOWER(es.value) = LOWER(%s))"
            )
            params += [key, value]
    # Búsqueda fuzzy global (motor único backend/busqueda): sin tildes
    # ("bateria"→"Batería"), sin guiones ("a7 iii"→"A7-III"), multi-palabra
    # cruzando campos ("sony fx3") y con tolerancia a typos. El ranking por
    # relevancia (más abajo) ordena el mejor match primero.
    pred = construir(CAMPOS_EQUIPO, q) if q else None
    if pred and pred.activo:
        base_sql += f" AND ({pred.where})"
        params += pred.where_params
    if categoria:
        try:
            cat_id = int(categoria)
        except ValueError:
            with get_db() as conn0:
                cat_id = buscar_id_por_nombre(conn0, categoria)
        if cat_id is not None:
            with get_db() as conn0:
                sub_ids = expandir_a_descendientes(conn0, cat_id)
            if sub_ids:
                fragment, _ = sql_filtro_equipos_por_categoria("e", sub_ids)
                base_sql += fragment
                params += sub_ids
            else:
                base_sql += " AND 1=0"
        else:
            base_sql += " AND 1=0"
    if marca:
        # Filtro por marca exacta (case-insensitive) contra marcas.nombre (brand_id FK).
        base_sql += f" AND LOWER(COALESCE({MARCA_NOMBRE_EXPR}, '')) = LOWER(%s)"
        params.append(marca)

    # El catálogo público SIEMPRE necesita el detalle completo (filtra/rankea
    # por specs y kit client-side) — `incluir_detalle=false` solo lo puede
    # pedir una sesión admin.
    incluir_detalle_val = (incluir_detalle if incluir_detalle is not None else True) if is_admin else True

    with get_db() as conn:
        result = proyectar_lista(
            conn,
            filtro_sql=base_sql,
            filtro_params=params,
            sort=sort,
            pred=pred,
            page=page,
            per_page=per_page,
            desde=desde,
            hasta=hasta,
            is_admin=is_admin,
            incluir_detalle=incluir_detalle_val,
            cliente_id=cliente_id,
        )
    # Cache: respuesta pública estable para un set dado de params;
    # admin recibe no-store (ve equipos no-visibles y filtros extra).
    response.headers["Cache-Control"] = (
        "private, no-store" if is_admin
        else "public, max-age=60, stale-while-revalidate=300"
    )
    return result


@router.get("/equipos/{id_or_slug}")
def get_equipo(
    id_or_slug: str,
    request: Request,
    desde: Optional[str] = Query(None, description="Fecha inicio (YYYY-MM-DD) para descuento por jornadas"),
    hasta: Optional[str] = Query(None, description="Fecha fin (YYYY-MM-DD) para descuento por jornadas"),
):
    """Devuelve el detalle de un equipo.

    Acepta tanto ID numérico puro (`47`) como slug-id mixto al estilo
    Stack Overflow (`sony-fx3-cuerpo-47`). El slug es solo cosmético —
    el ID al final es lo que importa. Esto mejora SEO (keywords en URL)
    sin perder back-compat con URLs viejas `/equipo/47`.

    Si el cliente manda solo el slug sin ID (`sony-fx3-cuerpo`), devuelve
    400 — preferimos ser explícitos y no adivinar.

    `desde`/`hasta` (opcionales, ambas o ninguna): con las fechas del carrito
    global, la ficha trae el descuento por jornadas/cliente ya resuelto
    (`descuento_pct`/`descuento_origen`/`precio_jornada_final`) — mismo
    criterio que `GET /equipos`.
    """
    # Caso 1: ID puro (compat con URLs viejas)
    if id_or_slug.isdigit():
        actual_id = int(id_or_slug)
    else:
        # Caso 2: slug-id, extraer el ID del final.
        m = re.search(r"-(\d+)$", id_or_slug)
        if not m:
            raise HTTPException(400, "URL inválida — falta el id del equipo")
        actual_id = int(m.group(1))

    session = get_session(request)
    cliente_id = (
        session["cliente_id"]
        if session and session.get("role") == "cliente" and session.get("cliente_id")
        else None
    )

    with get_db() as conn:
        equipo = proyectar_uno(conn, actual_id, desde=desde, hasta=hasta, cliente_id=cliente_id)
    if not equipo:
        raise HTTPException(404, "Equipo no encontrado")
    return equipo


# Series tipo "N/A", "ND", "-", "Sin serie" se aceptan duplicadas — son
# placeholders comunes para equipos sin serial real.
_PLACEHOLDER_SERIE_RE = re.compile(r"^(n/?a|n/?d|sin\s*serie|-+)$", re.IGNORECASE)


def _serie_es_placeholder(serie: Optional[str]) -> bool:
    if not serie:
        return True
    return bool(_PLACEHOLDER_SERIE_RE.match(serie.strip()))


def _check_serie_unica(conn, serie: Optional[str], exclude_id: Optional[int] = None) -> None:
    """Lanza 409 si la serie ya existe en otro equipo activo (no eliminado).
    Series placeholder (N/A, ND, -, sin serie) NO se chequean."""
    if _serie_es_placeholder(serie):
        return
    serie_norm = (serie or "").strip()
    if not serie_norm:
        return
    query = """
        SELECT id, nombre FROM equipos
        WHERE TRIM(LOWER(serie)) = LOWER(%s)
          AND eliminado_at IS NULL
    """
    params: list = [serie_norm]
    if exclude_id is not None:
        query += " AND id != %s"
        params.append(exclude_id)
    query += " LIMIT 1"
    existing = conn.execute(query, tuple(params)).fetchone()
    if existing:
        ed = row_to_dict(existing) if not isinstance(existing, dict) else existing
        raise HTTPException(
            409,
            f"La serie '{serie_norm}' ya existe en el equipo #{ed['id']} ('{ed['nombre']}'). "
            "Las series deben ser únicas por equipo (excepto placeholders como N/A).",
        )


def _resolve_brand_id(conn, nombre: str | None) -> int | None:
    """Find-or-create de marca por nombre (case-insensitive). Devuelve el id
    o None si nombre vacío. La marca (`marcas.nombre`) es la fuente única del
    nombre de marca; equipos.brand_id la referencia."""
    if not nombre or not nombre.strip():
        return None
    nombre = nombre.strip()
    row = conn.execute(
        "SELECT id FROM marcas WHERE LOWER(nombre) = LOWER(%s) LIMIT 1", (nombre,)
    ).fetchone()
    if row:
        return row["id"]
    conn.execute(
        "INSERT INTO marcas (nombre) VALUES (%s) ON CONFLICT (nombre) DO NOTHING", (nombre,)
    )
    row = conn.execute(
        "SELECT id FROM marcas WHERE LOWER(nombre) = LOWER(%s) LIMIT 1", (nombre,)
    ).fetchone()
    return row["id"] if row else None


@router.post("/equipos", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
def create_equipo(data: EquipoCreate, request: Request):
    require_admin(request)
    with get_db() as conn:
        try:
            # Validar serie única (rechaza 409 si choca con otro activo)
            _check_serie_unica(conn, data.serie)
            brand_id = _resolve_brand_id(conn, data.marca)
            new_id = conn.insert_returning("""
                INSERT INTO equipos (nombre, brand_id, modelo, cantidad,
                                     precio_jornada, precio_usd, roi_pct,
                                     valor_reposicion, foto_url, fecha_compra,
                                     serie, bh_url, dueno, visible_catalogo, estado,
                                     ficha_completa, categoria_specs, tipo)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (data.nombre, brand_id, data.modelo, data.cantidad,
                  data.precio_jornada, data.precio_usd, data.roi_pct,
                  data.valor_reposicion, data.foto_url, _normalize_fecha_compra(data.fecha_compra),
                  data.serie, data.bh_url, data.dueno, data.visible_catalogo, data.estado,
                  bool(data.ficha_completa), data.categoria_specs, data.tipo or "simple"))
            # Hook: calcular nombre_publico inicial. No falla el create si esto
            # rompe (ej. si los servicios no están disponibles).
            try:
                actualizar_nombres_de(conn, new_id, commit=False)
            except Exception:
                pass
            # Slug en la creación: el equipo nuevo nace con slug (clave natural
            # del export dataio) por el camino correcto, no por el self-heal del
            # export (#922). Idempotente; reusa la fuente única del backfill.
            from dataio.slug import backfill_equipos_slug
            backfill_equipos_slug(conn)
            conn.commit()
            row    = conn.execute(f"SELECT *, {MARCA_SUBQUERY} FROM equipos e WHERE id=%s", (new_id,)).fetchone()
            return row_to_dict(row)
        except Exception:
            conn.rollback()
            raise


def _normalize_fecha_compra(value):
    """`equipos.fecha_compra` es DATE, pero el front (MonthYearPicker) manda
    "YYYY-MM" (mes/año — issue #109). Postgres no castea "YYYY-MM" a DATE
    ('2024-01'::date es inválido → 500), así que completamos al día 1.
    Vacío → None. "YYYY-MM-DD" se deja igual."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return f"{s}-01"
    return s


@router.patch("/equipos/{id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def update_equipo(id: int, data: EquipoUpdate, request: Request):
    require_admin(request)
    with get_db() as conn:
        try:
            existing = conn.execute(f"SELECT *, {MARCA_SUBQUERY} FROM equipos e WHERE id=%s", (id,)).fetchone()
            if not existing:
                raise HTTPException(404, "Equipo no encontrado")
            updates = data.model_dump(exclude_unset=True)
            if not updates:
                raise HTTPException(400, "Nada para actualizar")
            # marca → brand_id: marcas.nombre es la fuente única. Resolvemos la
            # FK y NO escribimos la columna marca (eliminada).
            marca_cambio = "marca" in updates
            if marca_cambio:
                updates["brand_id"] = _resolve_brand_id(conn, updates.pop("marca"))
            # fecha_compra es DATE; el front (MonthYearPicker) manda "YYYY-MM" →
            # completar a "YYYY-MM-01"; vacío → NULL (ver _normalize_fecha_compra).
            if "fecha_compra" in updates:
                updates["fecha_compra"] = _normalize_fecha_compra(updates["fecha_compra"])
            # Validar serie única si se está cambiando (excluyendo este equipo).
            # Rechaza si otra fila activa tiene la misma serie.
            if "serie" in updates:
                _check_serie_unica(conn, updates["serie"], exclude_id=id)
            # Registrar cambio de precio si cambió
            if "precio_jornada" in updates and updates["precio_jornada"] != existing["precio_jornada"]:
                conn.execute(
                    "INSERT INTO equipo_precio_historial (equipo_id, precio_jornada) VALUES (%s,%s)",
                    (id, updates["precio_jornada"]),
                )
            # Inferencia del flag `precio_jornada_manual` cuando el cliente
            # no lo manda explícito. Heurística:
            #   - Si llega precio_jornada SIN roi_pct → asumimos override
            #     manual del admin (editó el precio directamente).
            #   - Si llega precio_jornada JUNTO con roi_pct → asumimos
            #     cálculo automático (el frontend recalculó la fórmula
            #     desde el ROI nuevo).
            # El frontend puede enviar `precio_jornada_manual` para ser
            # explícito y este bloque se saltea.
            if (
                "precio_jornada" in updates
                and "precio_jornada_manual" not in updates
            ):
                updates["precio_jornada_manual"] = "roi_pct" not in updates
            set_clause = ", ".join(f"{k} = %s" for k in updates)
            set_clause += ", updated_at = CURRENT_TIMESTAMP"
            conn.execute(f"UPDATE equipos SET {set_clause} WHERE id = %s",
                         list(updates.values()) + [id])
            # Hook: si cambió algo que afecta el nombre público, recalcular.
            # No falla el update si el recálculo rompe.
            if marca_cambio or any(k in updates for k in ("nombre", "modelo")):
                try:
                    actualizar_nombres_de(conn, id, commit=False)
                except Exception:
                    pass
            conn.commit()
            row    = conn.execute(f"SELECT *, {MARCA_SUBQUERY} FROM equipos e WHERE id=%s", (id,)).fetchone()
            return row_to_dict(row)
        except Exception:
            conn.rollback()
            raise


@router.post("/equipos/{id}/duplicate")
@limiter.limit(ADMIN_WRITE_LIMIT)
def duplicate_equipo(id: int, request: Request):
    """
    Duplica un equipo: copia equipo + ficha + categorías + kit. La nueva fila
    arranca con `serie` vacía (debe ser única por equipo), `ficha_completa = false`
    (para forzar al admin a revisar) y `cantidad = 1` (default seguro).
    Útil cuando comprás varias unidades del mismo modelo con series distintas.
    """
    require_admin(request)
    with get_db() as conn:
        try:
            src = conn.execute(f"SELECT *, {MARCA_SUBQUERY} FROM equipos e WHERE id=%s", (id,)).fetchone()
            if not src:
                raise HTTPException(404, "Equipo no encontrado")
            src_d = row_to_dict(src)

            new_id = conn.insert_returning("""
                INSERT INTO equipos (
                    nombre, brand_id, modelo, cantidad,
                    precio_jornada, precio_usd, roi_pct,
                    valor_reposicion, foto_url, fecha_compra,
                    serie, bh_url, dueno, visible_catalogo, estado,
                    ficha_completa, tipo
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                f"{src_d['nombre']} (copia)",
                src_d.get("brand_id"), src_d.get("modelo"), 1,
                src_d.get("precio_jornada"), src_d.get("precio_usd"), src_d.get("roi_pct"),
                src_d.get("valor_reposicion"), src_d.get("foto_url"), _normalize_fecha_compra(src_d.get("fecha_compra")),
                None,  # serie vacía
                src_d.get("bh_url"), src_d.get("dueno"), src_d.get("visible_catalogo", 1), src_d.get("estado", "operativo"),
                False,  # ficha_completa false para que el admin la revise
                src_d.get("tipo", "simple"),  # hereda el tipo del original
            ))

            # Copiar ficha si existe
            ficha = conn.execute("SELECT * FROM equipo_fichas WHERE equipo_id=%s", (id,)).fetchone()
            if ficha:
                f = row_to_dict(ficha)
                cols = [k for k in f.keys() if k not in ("equipo_id", "created_at", "updated_at")]
                placeholders = ", ".join(["%s"] * (len(cols) + 1))
                conn.execute(
                    f"INSERT INTO equipo_fichas (equipo_id, {', '.join(cols)}) VALUES ({placeholders})",
                    [new_id] + [f.get(c) for c in cols],
                )

            copiar_categorias(conn, id, new_id)

            # Copiar kit
            kit = conn.execute(
                "SELECT componente_id, cantidad, orden FROM kit_componentes WHERE equipo_id=%s", (id,)
            ).fetchall()
            conn.executemany(
                "INSERT INTO kit_componentes (equipo_id, componente_id, cantidad, orden) VALUES (%s, %s, %s, %s)",
                [(new_id, componente_id, cantidad, orden) for (componente_id, cantidad, orden) in kit],
            )

            conn.commit()
            row = conn.execute(f"SELECT *, {MARCA_SUBQUERY} FROM equipos e WHERE id=%s", (new_id,)).fetchone()
            return row_to_dict(row)
        except Exception:
            conn.rollback()
            raise


@router.post("/equipos/{id}/restore")
@limiter.limit(ADMIN_WRITE_LIMIT)
def restore_equipo(id: int, request: Request):
    """Restaura un equipo soft-deleted (eliminado_at = NULL). #206."""
    require_admin(request)
    with get_db() as conn:
        try:
            row = conn.execute(
                "SELECT id, eliminado_at FROM equipos WHERE id=%s", (id,)
            ).fetchone()
            if not row:
                raise HTTPException(404, "Equipo no encontrado")
            if row["eliminado_at"] is None:
                return {"ok": True, "message": "Ya estaba activo"}
            conn.execute(
                "UPDATE equipos SET eliminado_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id=%s",
                (id,),
            )
            conn.commit()
            return {"ok": True}
        except Exception:
            conn.rollback()
            raise


class BulkActionInput(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=500)
    action: str   # "set_visible" | "set_ficha_completa" | "set_categoria" | "add_categoria" | "remove_categoria" | "delete"
    visible: Optional[bool] = None
    ficha_completa: Optional[bool] = None
    categoria_id: Optional[int] = None


@router.post("/admin/equipos/bulk")
@limiter.limit(ADMIN_WRITE_LIMIT)
def bulk_action(payload: BulkActionInput, request: Request):
    """Aplica una acción a varios equipos a la vez. Acciones soportadas:
    - set_visible (visible: bool)
    - set_ficha_completa (ficha_completa: bool)
    - set_categoria (categoria_id: int) — REEMPLAZA las categorías existentes
    - delete (soft delete — marca eliminado_at; #206)

    Retorna {"affected": N} con la cantidad de equipos modificados.
    """
    require_admin(request)
    ids = payload.ids
    if not ids:
        return {"affected": 0}

    placeholders = ",".join(["%s"] * len(ids))
    with get_db() as conn:
        try:
            if payload.action == "set_visible":
                if payload.visible is None:
                    raise HTTPException(400, "set_visible requiere visible: bool")
                v = 1 if payload.visible else 0
                conn.execute(
                    f"UPDATE equipos SET visible_catalogo = %s, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                    [v, *ids],
                )

            elif payload.action == "set_ficha_completa":
                if payload.ficha_completa is None:
                    raise HTTPException(400, "set_ficha_completa requiere ficha_completa: bool")
                conn.execute(
                    f"UPDATE equipos SET ficha_completa = %s, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                    [bool(payload.ficha_completa), *ids],
                )

            elif payload.action == "set_categoria":
                if not payload.categoria_id:
                    raise HTTPException(400, "set_categoria requiere categoria_id: int")
                try:
                    set_categoria_masivo(conn, ids, payload.categoria_id)
                except CategoriaNoExiste as e:
                    raise HTTPException(404, str(e))

            elif payload.action == "add_categoria":
                if not payload.categoria_id:
                    raise HTTPException(400, "add_categoria requiere categoria_id: int")
                try:
                    add_categoria_masivo(conn, ids, payload.categoria_id)
                except CategoriaNoExiste as e:
                    raise HTTPException(404, str(e))

            elif payload.action == "remove_categoria":
                if not payload.categoria_id:
                    raise HTTPException(400, "remove_categoria requiere categoria_id: int")
                remove_categoria_masivo(conn, ids, payload.categoria_id)

            elif payload.action == "delete":
                # Soft delete: consistente con el endpoint single DELETE (#206).
                conn.execute(
                    f"UPDATE equipos SET eliminado_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                    ids,
                )

            elif payload.action == "delete_permanent":
                # Hard delete (DROP). Usado desde la vista papelera para vaciar
                # definitivamente. CASCADE borra ficha, kit, categorías, etiquetas
                # del equipo. Los alquiler_items quedan huérfanos pero el catálogo
                # público ya no los referencia. #punto4
                conn.execute(
                    f"DELETE FROM equipos WHERE id IN ({placeholders})",
                    ids,
                )

            else:
                raise HTTPException(400, f"Acción desconocida: {payload.action}")

            conn.commit()
            return {"affected": len(ids)}
        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("bulk_action falló: %s", payload.action)
            raise HTTPException(500, f"Error bulk: {type(e).__name__}")


@router.delete("/equipos/{id}", status_code=204)
@limiter.limit(ADMIN_WRITE_LIMIT)
def delete_equipo(id: int, request: Request):
    """Soft delete: marca eliminado_at = NOW(). Preserva historial de
    alquileres del equipo dado de baja. Restaurable vía POST /restore (#206)."""
    require_admin(request)
    html_source_url = None
    with get_db() as conn:
        try:
            row = conn.execute(
                "SELECT id, html_source_url FROM equipos WHERE id=%s", (id,)
            ).fetchone()
            if not row:
                raise HTTPException(404, "Equipo no encontrado")
            html_source_url = row["html_source_url"]
            conn.execute(
                "UPDATE equipos SET eliminado_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id=%s",
                (id,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # Cleanup R2 blob after successful soft-delete (best-effort, no rollback if fails).
    if html_source_url:
        try:
            cfg = _r2_config()
            key = html_source_url.removeprefix(f"{cfg['public_base']}/")
            _delete_from_r2(key)
        except Exception as _e:
            logger.warning("delete_equipo: no se pudo borrar HTML blob de R2: %s", _e)


@router.get("/equipos/{id}/disponibilidad-calendario")
def disponibilidad_calendario(
    id: int,
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
):
    """Estado de disponibilidad por día de UN equipo (#808), catálogo-facing.

    Devuelve `{'stock': N, 'dias': {YYYY-MM-DD: 'parcial'|'reservado'}}` — los días
    `libre` se OMITEN (default en el front). Lectura sobre el motor de reservas
    (`estado_diario_equipo`), sin recalcular overlap. Sin auth (igual que el catálogo).
    """
    from reservas.disponibilidad import estado_diario_equipo

    hoy = _date.today()
    d_desde = desde or hoy.isoformat()
    d_hasta = hasta or (hoy + timedelta(days=90)).isoformat()
    # Cap defensivo del rango (≤ 180 días) para no abusar de la lectura.
    try:
        span = (_date.fromisoformat(d_hasta[:10]) - _date.fromisoformat(d_desde[:10])).days
    except ValueError:
        raise HTTPException(400, "Fechas inválidas (usar YYYY-MM-DD)")
    if span < 0:
        raise HTTPException(400, "El rango es inválido (hasta < desde)")
    if span > 180:
        raise HTTPException(400, "El rango no puede superar 180 días")

    with get_db() as conn:
        res = estado_diario_equipo(conn, id, d_desde, d_hasta)
    if res is None:
        raise HTTPException(404, "Equipo no encontrado")
    # Slim: solo días no-libres (libre = ausente).
    res["dias"] = {d: e for d, e in res["dias"].items() if e != "libre"}
    return res


# ── Historial de alquileres por equipo ───────────────────────────────────────

@router.get("/equipos/{id}/historial")
def get_equipo_historial(id: int):
    with get_db() as conn:
        if not conn.execute("SELECT id FROM equipos WHERE id=%s", (id,)).fetchone():
            raise HTTPException(404, "Equipo no encontrado")

        rows = conn.execute("""
            SELECT
                p.id, p.numero_pedido, p.estado,
                p.fecha_desde, p.fecha_hasta,
                COALESCE(c.nombre || ' ' || c.apellido, p.cliente_nombre) AS cliente,
                pi.cantidad, pi.precio_jornada AS precio_item,
                GREATEST(1, (p.fecha_hasta::date - p.fecha_desde::date))::INTEGER AS dias
            FROM alquiler_items pi
            JOIN alquileres p ON p.id = pi.pedido_id
            LEFT JOIN clientes c ON c.id = p.cliente_id
            WHERE pi.equipo_id = %s
            ORDER BY p.fecha_desde DESC
        """, (id,)).fetchall()

        items      = [row_to_dict(r) for r in rows]
        total_dias = sum(r["dias"] or 1 for r in items)
        total_rev  = sum((r["precio_item"] or 0) * (r["cantidad"] or 1) * (r["dias"] or 1) for r in items)

        return {
            "historial": items,
            "stats": {
                "total_alquileres": len(items),
                "total_dias":       total_dias,
                "total_revenue":    total_rev,
                "ultimo_alquiler":  items[0]["fecha_desde"] if items else None,
            },
        }


# ── Historial de precios ─────────────────────────────────────────────────────

@router.get("/equipos/{id}/precio-historial")
def get_precio_historial(id: int):
    with get_db() as conn:
        if not conn.execute("SELECT id FROM equipos WHERE id=%s", (id,)).fetchone():
            raise HTTPException(404, "Equipo no encontrado")
        rows = conn.execute("""
            SELECT precio_jornada, changed_at
            FROM equipo_precio_historial
            WHERE equipo_id = %s
            ORDER BY changed_at DESC
        """, (id,)).fetchall()
        return [row_to_dict(r) for r in rows]



@router.get("/equipos/{id}/calendario")
def get_equipo_calendario(id: int, year: int = Query(...), month: int = Query(...)):
    """Unidades libres por día de un equipo en un mes.

    Delega el conteo de "reservado" en el motor único `reservas.reservado_total`,
    que sube por TODO el grafo de composición (combos/kits anidados, a cualquier
    profundidad). Antes este endpoint reimplementaba el overlap a 1 solo nivel de
    kit (`directas` + `via_kit`) → mostraba un equipo como libre aunque estuviera
    reservado vía un compuesto anidado (#923; violaba la fuente única, MEMORIA
    2026-05-30 / 2026-05-31). El grafo inverso se calcula una vez y se reusa por día.
    Comportamiento por día = overlap a nivel timestamp (igual que el gate): un día
    en el que el alquiler sigue ocupado, aunque devuelva más tarde, cuenta como
    ocupado (la versión vieja, a fecha exclusiva, lo mostraba libre — optimista).
    """
    if not (1 <= month <= 12):
        raise HTTPException(400, "Mes inválido")

    with get_db() as conn:
        equipo = conn.execute(
            "SELECT id, cantidad FROM equipos WHERE id=%s", (id,)
        ).fetchone()
        if not equipo:
            raise HTTPException(404, "Equipo no encontrado")

        stock_total = equipo["cantidad"]
        _, days_in_month = _cal.monthrange(year, month)
        rev = parientes_de(conn)  # grafo inverso de composición — una vez (motor)

        result: dict[str, int] = {}
        for day_num in range(1, days_in_month + 1):
            d0 = _date(year, month, day_num)
            d1 = d0 + timedelta(days=1)
            # Reservado recursivo (directo + vía cualquier compuesto que lo
            # contenga) que se pisa con [d0, d1). excl=-1 → no excluir ningún
            # pedido (contar todos). Sin buffer (vista de día, no chequeo de gate).
            reservado = reservado_total(
                conn, id, -1, d1.isoformat(), d0.isoformat(), rev_graph=rev,
            )
            result[d0.isoformat()] = max(0, stock_total - reservado)

        return result
