"""dataio/importers.py — list[dict] → upsert DB.

Cada función `import_<entidad>(conn, rows, resolver)` valida cada row con
el modelo Pydantic correspondiente y aplica un upsert idempotente contra
la DB.

Política:
- Upsert por clave natural. Insertar si no existe, actualizar si existe.
- Campos del modelo siempre pisan (la fuente de verdad es el JSON).
- M2M (`equipo_categorias`): `asignar_categorias` siempre reemplaza el set
  completo del equipo por el del JSON (no es incremental, no preserva
  asignaciones custom que no estén en el JSON).

`dry-run` NO es responsabilidad de los importers — siempre escriben. El
orchestrator (orchestrator.import_all) es quien envuelve el batch en un
SAVEPOINT y hace ROLLBACK al final si `dry_run=True`. Si llamás a un
importer directo sin orchestrator, vas a escribir a la DB siempre.

Devuelve siempre un dict con stats: `{"inserted", "updated", "skipped"}`.
"""

from __future__ import annotations


from pydantic import ValidationError

from services.categorias import crear_si_no_existe, asignar_padre_si_no_tiene, asignar_categorias
from . import schema
from .natural_keys import KeyResolver


class ImportError_(Exception):
    """Error de importación con contexto de qué fila falló."""


def _validate_rows(rows: list[dict], model: type[schema._Base], entity: str) -> list:
    out = []
    for i, row in enumerate(rows):
        try:
            out.append(model(**row))
        except ValidationError as e:
            raise ImportError_(
                f"Validación falló en {entity}[{i}]: {e}"
            ) from e
    return out


# ─────────────────────────────────────────────────────────────────────────────
# marcas
# ─────────────────────────────────────────────────────────────────────────────


def import_marcas(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    items = _validate_rows(rows, schema.Marca, "marcas")
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    for m in items:
        cur = conn.execute(
            """
            INSERT INTO marcas (nombre, logo_url, visible, orden, destacada)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (nombre) DO UPDATE SET
                logo_url = EXCLUDED.logo_url,
                visible = EXCLUDED.visible,
                orden = EXCLUDED.orden,
                destacada = EXCLUDED.destacada,
                updated_at = CURRENT_TIMESTAMP
            WHERE (marcas.logo_url, marcas.visible, marcas.orden, marcas.destacada)
               IS DISTINCT FROM (EXCLUDED.logo_url, EXCLUDED.visible, EXCLUDED.orden, EXCLUDED.destacada)
            RETURNING (xmax = 0) AS inserted
            """,
            (m.nombre, m.logo_url, m.visible, m.orden, m.destacada),
        )
        row = cur.fetchone()
        # row es None cuando el WHERE de arriba no matcheó (fila ya idéntica):
        # el import re-corre el JSON entero cada vez (export→import de
        # staging/prod), así que sin este guard cada re-import reescribía las
        # 66 marcas aunque no hubieran cambiado.
        if row is None:
            stats["skipped"] += 1
        elif row["inserted"]:
            stats["inserted"] += 1
        else:
            stats["updated"] += 1
    resolver.refresh_marcas()
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# categorias (con resolución de parent_path en pases por nivel)
# ─────────────────────────────────────────────────────────────────────────────


def import_categorias(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    items = _validate_rows(rows, schema.Categoria, "categorias")
    stats = {"inserted": 0, "updated": 0, "skipped": 0}

    pending: list[schema.Categoria] = []
    for c in items:
        _, was_inserted = crear_si_no_existe(
            conn, c.nombre, prioridad=c.prioridad,
            visible=c.visible, grupo_visual=c.grupo_visual,
            nombre_publico_template=c.nombre_publico_template,
        )
        if was_inserted:
            stats["inserted"] += 1
        else:
            stats["skipped"] += 1
        if c.parent_path:
            pending.append(c)

    resolver.refresh_categorias()
    for c in pending:
        parent_id = resolver.categoria_id(c.parent_path)
        if parent_id is None:
            raise ImportError_(
                f"categorias: '{c.nombre}' referencia parent_path='{c.parent_path}' "
                f"que no existe (debe estar en el mismo JSON)"
            )
        asignar_padre_si_no_tiene(conn, c.nombre, parent_id)
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# spec_definitions
# ─────────────────────────────────────────────────────────────────────────────


def import_spec_definitions(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    items = _validate_rows(rows, schema.SpecDefinition, "spec_definitions")
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    import json as _json

    for sd in items:
        cat_raiz_id = resolver.categoria_id(sd.categoria_raiz_nombre)
        if sd.categoria_raiz_nombre and cat_raiz_id is None:
            raise ImportError_(
                f"spec_definitions: spec_key='{sd.spec_key}' referencia "
                f"categoria_raiz_nombre='{sd.categoria_raiz_nombre}' que no existe"
            )

        enum_json = (
            _json.dumps(sd.enum_options, ensure_ascii=False)
            if sd.enum_options is not None
            else None
        )
        tabla_cols = (
            _json.dumps(sd.tabla_columnas, ensure_ascii=False)
            if sd.tabla_columnas is not None
            else None
        )
        output_cfg = (
            _json.dumps(sd.output_config, ensure_ascii=False)
            if sd.output_config is not None
            else None
        )

        # ON CONFLICT distinto según si tiene categoria_raiz_id o es global.
        # Las UNIQUEs son: (categoria_raiz_id, spec_key) para las con cat;
        # idx_spec_def_global_unique partial para las sin cat (WHERE categoria_raiz_id IS NULL).
        if cat_raiz_id is not None:
            cur = conn.execute(
                """
                INSERT INTO spec_definitions
                    (categoria_raiz_id, spec_key, label, tipo, unidad, enum_options,
                     ayuda, es_compatibilidad, compatibilidad_modo, rol_compatibilidad,
                     validado, tabla_columnas, output_config, favorito, en_nombre,
                     en_filtros, prioridad)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (categoria_raiz_id, spec_key) DO UPDATE SET
                    label = EXCLUDED.label,
                    tipo = EXCLUDED.tipo,
                    unidad = EXCLUDED.unidad,
                    enum_options = EXCLUDED.enum_options,
                    ayuda = EXCLUDED.ayuda,
                    es_compatibilidad = EXCLUDED.es_compatibilidad,
                    compatibilidad_modo = EXCLUDED.compatibilidad_modo,
                    rol_compatibilidad = EXCLUDED.rol_compatibilidad,
                    validado = EXCLUDED.validado,
                    tabla_columnas = EXCLUDED.tabla_columnas,
                    output_config = EXCLUDED.output_config,
                    favorito = EXCLUDED.favorito,
                    en_nombre = EXCLUDED.en_nombre,
                    en_filtros = EXCLUDED.en_filtros,
                    prioridad = EXCLUDED.prioridad,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING (xmax = 0) AS inserted
                """,
                (
                    cat_raiz_id, sd.spec_key, sd.label, sd.tipo, sd.unidad,
                    enum_json, sd.ayuda, sd.es_compatibilidad,
                    sd.compatibilidad_modo, sd.rol_compatibilidad, sd.validado,
                    tabla_cols, output_cfg, sd.favorito, sd.en_nombre,
                    sd.en_filtros, sd.prioridad,
                ),
            )
        else:
            # Global spec (sin categoria_raiz): manual lookup + insert/update,
            # porque el ON CONFLICT no aplica al partial index.
            existing = conn.execute(
                "SELECT id FROM spec_definitions "
                "WHERE categoria_raiz_id IS NULL AND spec_key = %s",
                (sd.spec_key,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE spec_definitions SET
                        label = %s, tipo = %s, unidad = %s, enum_options = %s,
                        ayuda = %s, es_compatibilidad = %s, compatibilidad_modo = %s,
                        rol_compatibilidad = %s, validado = %s, tabla_columnas = %s,
                        output_config = %s, favorito = %s, en_nombre = %s,
                        en_filtros = %s, prioridad = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        sd.label, sd.tipo, sd.unidad, enum_json, sd.ayuda,
                        sd.es_compatibilidad, sd.compatibilidad_modo,
                        sd.rol_compatibilidad, sd.validado, tabla_cols, output_cfg,
                        sd.favorito, sd.en_nombre, sd.en_filtros, sd.prioridad,
                        existing["id"],
                    ),
                )
                cur = None
            else:
                cur = conn.execute(
                    """
                    INSERT INTO spec_definitions
                        (categoria_raiz_id, spec_key, label, tipo, unidad, enum_options,
                         ayuda, es_compatibilidad, compatibilidad_modo, rol_compatibilidad,
                         validado, tabla_columnas, output_config, favorito, en_nombre,
                         en_filtros, prioridad)
                    VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        sd.spec_key, sd.label, sd.tipo, sd.unidad, enum_json,
                        sd.ayuda, sd.es_compatibilidad, sd.compatibilidad_modo,
                        sd.rol_compatibilidad, sd.validado, tabla_cols, output_cfg,
                        sd.favorito, sd.en_nombre, sd.en_filtros, sd.prioridad,
                    ),
                )

        if cur is not None:
            row = cur.fetchone()
            if row and row["inserted"]:
                stats["inserted"] += 1
            else:
                stats["updated"] += 1
        else:
            stats["updated"] += 1

    resolver.refresh_spec_defs()
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# categoria_spec_templates
# ─────────────────────────────────────────────────────────────────────────────


def import_categoria_spec_templates(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    items = _validate_rows(
        rows, schema.CategoriaSpecTemplate, "categoria_spec_templates"
    )
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    for t in items:
        cat_id = resolver.categoria_id(t.categoria_nombre)
        if cat_id is None:
            raise ImportError_(
                f"categoria_spec_templates: categoria_nombre='{t.categoria_nombre}' "
                "no existe"
            )
        spec_id = resolver.spec_def_id(
            t.spec_ref.categoria_raiz_nombre, t.spec_ref.spec_key
        )
        if spec_id is None:
            raise ImportError_(
                f"categoria_spec_templates: spec_ref={t.spec_ref!r} no existe"
            )
        cur = conn.execute(
            """
            INSERT INTO categoria_spec_templates
                (categoria_id, spec_def_id, prioridad, destacado, obligatorio,
                 visible_en_card, visible_en_filtros, visible_en_nombre, ayuda)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (categoria_id, spec_def_id) DO UPDATE SET
                prioridad = EXCLUDED.prioridad,
                destacado = EXCLUDED.destacado,
                obligatorio = EXCLUDED.obligatorio,
                visible_en_card = EXCLUDED.visible_en_card,
                visible_en_filtros = EXCLUDED.visible_en_filtros,
                visible_en_nombre = EXCLUDED.visible_en_nombre,
                ayuda = EXCLUDED.ayuda
            RETURNING (xmax = 0) AS inserted
            """,
            (
                cat_id, spec_id, t.prioridad, t.destacado, t.obligatorio,
                t.visible_en_card, t.visible_en_filtros, t.visible_en_nombre,
                t.ayuda,
            ),
        )
        row = cur.fetchone()
        if row and row["inserted"]:
            stats["inserted"] += 1
        else:
            stats["updated"] += 1
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# equipos (con M2M categorias)
# ─────────────────────────────────────────────────────────────────────────────


def import_equipos(
    conn,
    rows: list[dict],
    resolver: KeyResolver,
) -> dict[str, int]:
    """Upsert de equipos por slug + sync de M2M categorias (siempre
    reemplaza — asignar_categorias no es incremental)."""
    items = _validate_rows(rows, schema.Equipo, "equipos")
    stats = {"inserted": 0, "updated": 0, "skipped": 0}

    for eq in items:
        # marca_nombre → brand_id (marcas.nombre es la fuente única). Si la
        # marca no existe aún, la creamos para no perder el dato.
        brand_id = resolver.marca_id(eq.marca_nombre)
        if brand_id is None and (eq.marca_nombre or eq.marca):
            nombre_marca = (eq.marca_nombre or eq.marca).strip()
            conn.execute(
                "INSERT INTO marcas (nombre) VALUES (%s) ON CONFLICT (nombre) DO NOTHING",
                (nombre_marca,),
            )
            resolver.refresh_marcas()
            brand_id = resolver.marca_id(nombre_marca)

        cur = conn.execute(
            """
            INSERT INTO equipos (
                slug, nombre, modelo, brand_id, cantidad,
                precio_jornada, precio_jornada_manual, precio_usd, roi_pct,
                valor_reposicion, foto_url, fecha_compra, serie, bh_url,
                dueno, visible_catalogo, estado, ficha_completa, eliminado_at,
                nombre_publico_override, nombre_publico_revisado, relevancia_manual
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                nombre = EXCLUDED.nombre,
                modelo = EXCLUDED.modelo,
                brand_id = EXCLUDED.brand_id,
                cantidad = EXCLUDED.cantidad,
                precio_jornada = EXCLUDED.precio_jornada,
                precio_jornada_manual = EXCLUDED.precio_jornada_manual,
                precio_usd = EXCLUDED.precio_usd,
                roi_pct = EXCLUDED.roi_pct,
                valor_reposicion = EXCLUDED.valor_reposicion,
                foto_url = EXCLUDED.foto_url,
                fecha_compra = EXCLUDED.fecha_compra,
                serie = EXCLUDED.serie,
                bh_url = EXCLUDED.bh_url,
                dueno = EXCLUDED.dueno,
                visible_catalogo = EXCLUDED.visible_catalogo,
                estado = EXCLUDED.estado,
                ficha_completa = EXCLUDED.ficha_completa,
                eliminado_at = EXCLUDED.eliminado_at,
                nombre_publico_override = EXCLUDED.nombre_publico_override,
                nombre_publico_revisado = EXCLUDED.nombre_publico_revisado,
                relevancia_manual = EXCLUDED.relevancia_manual,
                updated_at = CURRENT_TIMESTAMP
            WHERE (
                equipos.nombre, equipos.modelo, equipos.brand_id, equipos.cantidad,
                equipos.precio_jornada, equipos.precio_jornada_manual, equipos.precio_usd,
                equipos.roi_pct, equipos.valor_reposicion, equipos.foto_url,
                equipos.fecha_compra, equipos.serie, equipos.bh_url, equipos.dueno,
                equipos.visible_catalogo, equipos.estado, equipos.ficha_completa,
                equipos.eliminado_at, equipos.nombre_publico_override,
                equipos.nombre_publico_revisado, equipos.relevancia_manual
            ) IS DISTINCT FROM (
                EXCLUDED.nombre, EXCLUDED.modelo, EXCLUDED.brand_id, EXCLUDED.cantidad,
                EXCLUDED.precio_jornada, EXCLUDED.precio_jornada_manual, EXCLUDED.precio_usd,
                EXCLUDED.roi_pct, EXCLUDED.valor_reposicion, EXCLUDED.foto_url,
                EXCLUDED.fecha_compra, EXCLUDED.serie, EXCLUDED.bh_url, EXCLUDED.dueno,
                EXCLUDED.visible_catalogo, EXCLUDED.estado, EXCLUDED.ficha_completa,
                EXCLUDED.eliminado_at, EXCLUDED.nombre_publico_override,
                EXCLUDED.nombre_publico_revisado, EXCLUDED.relevancia_manual
            )
            RETURNING id, (xmax = 0) AS inserted
            """,
            (
                eq.slug, eq.nombre, eq.modelo, brand_id, eq.cantidad,
                eq.precio_jornada, eq.precio_jornada_manual, eq.precio_usd,
                eq.roi_pct, eq.valor_reposicion, eq.foto_url, eq.fecha_compra,
                eq.serie, eq.bh_url, eq.dueno, eq.visible_catalogo, eq.estado,
                eq.ficha_completa, eq.eliminado_at, eq.nombre_publico_override,
                eq.nombre_publico_revisado, eq.relevancia_manual,
            ),
        )
        row = cur.fetchone()
        # row es None cuando el WHERE de arriba no matcheó (fila ya idéntica
        # — el import re-corre el JSON entero cada vez, ver import_marcas):
        # el equipo YA existía antes de este batch, así que su id ya está en
        # el cache lazy del resolver (cargado desde la DB al primer acceso).
        if row is None:
            equipo_id = resolver.equipo_id(eq.slug)
            stats["skipped"] += 1
        else:
            equipo_id = row["id"]
            if row["inserted"]:
                stats["inserted"] += 1
            else:
                stats["updated"] += 1

        # Refresh equipo cache para el resto del batch
        if resolver._equipos is not None:
            resolver._equipos[eq.slug] = equipo_id

        # ── M2M: categorias ──────────────────────────────────────────────
        cat_ids = []
        for cat_ref in eq.categorias:
            cat_id = resolver.categoria_id(cat_ref.nombre)
            if cat_id is None:
                raise ImportError_(
                    f"equipos[{eq.slug}].categorias: '{cat_ref.nombre}' no existe"
                )
            cat_ids.append(cat_id)
        asignar_categorias(conn, equipo_id, cat_ids)
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# equipo_specs
# ─────────────────────────────────────────────────────────────────────────────


def import_equipo_specs(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    items = _validate_rows(rows, schema.EquipoSpec, "equipo_specs")
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    for es in items:
        equipo_id = resolver.equipo_id(es.equipo_slug)
        if equipo_id is None:
            raise ImportError_(
                f"equipo_specs: equipo_slug='{es.equipo_slug}' no existe"
            )
        spec_id = resolver.spec_def_id(
            es.spec_ref.categoria_raiz_nombre, es.spec_ref.spec_key
        )
        if spec_id is None:
            raise ImportError_(
                f"equipo_specs: spec_ref={es.spec_ref!r} no existe "
                f"(equipo_slug={es.equipo_slug})"
            )
        cur = conn.execute(
            """
            INSERT INTO equipo_specs (equipo_id, spec_def_id, value)
            VALUES (%s, %s, %s)
            ON CONFLICT (equipo_id, spec_def_id) DO UPDATE SET
                value = EXCLUDED.value
            RETURNING (xmax = 0) AS inserted
            """,
            (equipo_id, spec_id, es.value),
        )
        row = cur.fetchone()
        if row and row["inserted"]:
            stats["inserted"] += 1
        else:
            stats["updated"] += 1
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# equipo_fichas
# ─────────────────────────────────────────────────────────────────────────────


def import_equipo_fichas(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    items = _validate_rows(rows, schema.EquipoFicha, "equipo_fichas")
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    for f in items:
        equipo_id = resolver.equipo_id(f.equipo_slug)
        if equipo_id is None:
            raise ImportError_(
                f"equipo_fichas: equipo_slug='{f.equipo_slug}' no existe"
            )
        cur = conn.execute(
            """
            INSERT INTO equipo_fichas (
                equipo_id, descripcion, notas,
                keywords_json, nombre_publico_template,
                conectividad_json,
                compatible_con_json, video_url, precio_bh_usd, fuente_url,
                fuente_titulo, enriquecido_at, enriquecido_fuente
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (equipo_id) DO UPDATE SET
                descripcion = EXCLUDED.descripcion,
                notas = EXCLUDED.notas,
                keywords_json = EXCLUDED.keywords_json,
                nombre_publico_template = EXCLUDED.nombre_publico_template,
                conectividad_json = EXCLUDED.conectividad_json,
                compatible_con_json = EXCLUDED.compatible_con_json,
                video_url = EXCLUDED.video_url,
                precio_bh_usd = EXCLUDED.precio_bh_usd,
                fuente_url = EXCLUDED.fuente_url,
                fuente_titulo = EXCLUDED.fuente_titulo,
                enriquecido_at = EXCLUDED.enriquecido_at,
                enriquecido_fuente = EXCLUDED.enriquecido_fuente,
                updated_at = CURRENT_TIMESTAMP
            RETURNING (xmax = 0) AS inserted
            """,
            (
                equipo_id, f.descripcion, f.notas,
                f.keywords_json, f.nombre_publico_template,
                f.conectividad_json,
                f.compatible_con_json, f.video_url, f.precio_bh_usd,
                f.fuente_url, f.fuente_titulo, f.enriquecido_at,
                f.enriquecido_fuente,
            ),
        )
        row = cur.fetchone()
        if row and row["inserted"]:
            stats["inserted"] += 1
        else:
            stats["updated"] += 1
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# OPERATIONAL — clientes, alquileres (con items y pagos embebidos)
# ─────────────────────────────────────────────────────────────────────────────


def import_clientes(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    """Upsert clientes por email (UNIQUE, case-insensitive en queries).

    Si supabase_uid viene seteado, se aplica — pero recordá que UIDs no
    son portables entre proyectos Supabase. Si falla por UNIQUE
    (ya hay otro cliente con ese uid), se ignora el conflicto.
    """
    items = _validate_rows(rows, schema.Cliente, "clientes")
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    for c in items:
        # Pre-check: ¿existe por email? Email case-insensitive
        # (el índice idx_clientes_email_lower lo permite).
        existing = conn.execute(
            "SELECT id FROM clientes WHERE LOWER(email) = LOWER(%s) LIMIT 1",
            (c.email,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE clientes SET
                    nombre = %s, apellido = %s, telefono = %s, direccion = %s,
                    direccion_maps_url = %s, cuit = %s, descuento = %s,
                    perfil_impuestos = %s, razon_social = %s, domicilio_fiscal = %s,
                    email_facturacion = %s, notas = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (c.nombre, c.apellido, c.telefono, c.direccion,
                 c.direccion_maps_url, c.cuit, c.descuento, c.perfil_impuestos,
                 c.razon_social, c.domicilio_fiscal, c.email_facturacion,
                 c.notas, existing["id"]),
            )
            stats["updated"] += 1
        else:
            conn.execute(
                """
                INSERT INTO clientes (
                    email, nombre, apellido, telefono, direccion,
                    direccion_maps_url, cuit, descuento, perfil_impuestos,
                    razon_social, domicilio_fiscal, email_facturacion, notas
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (c.email, c.nombre, c.apellido, c.telefono, c.direccion,
                 c.direccion_maps_url, c.cuit, c.descuento, c.perfil_impuestos,
                 c.razon_social, c.domicilio_fiscal, c.email_facturacion, c.notas),
            )
            stats["inserted"] += 1

        # supabase_uid: SET solo si viene y no genera conflicto. UPDATE
        # separado para no bloquear el insert principal si choca.
        if c.supabase_uid:
            try:
                conn.execute("SAVEPOINT sp_uid")
                conn.execute(
                    "UPDATE clientes SET supabase_uid = %s::uuid "
                    "WHERE LOWER(email) = LOWER(%s)",
                    (c.supabase_uid, c.email),
                )
                conn.execute("RELEASE SAVEPOINT sp_uid")
            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT sp_uid")
                conn.execute("RELEASE SAVEPOINT sp_uid")
                # Conflicto con otro cliente que ya tenía ese uid — ignoramos.
    resolver.refresh_clientes()
    return stats


def import_alquileres(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    """Upsert alquileres por numero_pedido + reemplaza items/pagos.

    Política sobre M2M-like (items, pagos): REPLACE — borra todos los
    existentes del alquiler y reinserta los del JSON. Esto es lo correcto
    porque un pedido no acumula items entre imports.
    """
    items = _validate_rows(rows, schema.Alquiler, "alquileres")
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    # (id_local, numero_del_principal) — se resuelve al final: el principal
    # puede venir DESPUÉS que su turno en el archivo (#1308).
    vinculos_pendientes: list[tuple[int, int]] = []
    # Nota: alquileres.numero_pedido NO tiene UNIQUE constraint (es una
    # secuencia generada por la app), así que NO podemos usar ON CONFLICT.
    # Pre-check + insert/update manual. El import es single-threaded por
    # entidad, así que no hay race condition relevante.
    for a in items:
        cliente_id = resolver.cliente_id(a.cliente_email)
        # cliente_id puede ser None: cliente fue eliminado pero el pedido
        # se preserva con los campos cliente_* denormalizados (snapshot).

        existing = conn.execute(
            "SELECT id FROM alquileres WHERE numero_pedido = %s LIMIT 1",
            (a.numero_pedido,),
        ).fetchone()

        # Compat: un backup PRE-rename (2026-07-15) trae el viejo estado
        # `presupuesto` → mapearlo a `solicitado` al importar, para que las filas
        # restauradas queden dentro del gate de reservas (ESTADOS_RESERVADO).
        estado = "solicitado" if a.estado == "presupuesto" else a.estado

        if existing:
            alq_id = existing["id"]
            conn.execute(
                """
                UPDATE alquileres SET
                    cliente_id = %s, cliente_nombre = %s, cliente_email = %s,
                    cliente_telefono = %s, notas = %s, estado = %s,
                    fecha_desde = %s, fecha_hasta = %s, monto_total = %s,
                    monto_pagado = %s, descuento_pct = %s, fuente = %s,
                    tipo = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (cliente_id, a.cliente_nombre, a.cliente_email, a.cliente_telefono,
                 a.notas, estado, a.fecha_desde, a.fecha_hasta, a.monto_total,
                 a.monto_pagado, a.descuento_pct, a.fuente, a.tipo,
                 alq_id),
            )
            stats["updated"] += 1
        else:
            cur = conn.execute(
                """
                INSERT INTO alquileres (
                    numero_pedido, cliente_id, cliente_nombre, cliente_email,
                    cliente_telefono, notas, estado, fecha_desde, fecha_hasta,
                    monto_total, monto_pagado, descuento_pct, fuente, tipo
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (a.numero_pedido, cliente_id, a.cliente_nombre, a.cliente_email,
                 a.cliente_telefono, a.notas, estado, a.fecha_desde, a.fecha_hasta,
                 a.monto_total, a.monto_pagado, a.descuento_pct, a.fuente, a.tipo),
            )
            alq_id = cur.fetchone()["id"]
            stats["inserted"] += 1

        if a.pedido_principal_numero is not None:
            vinculos_pendientes.append((alq_id, a.pedido_principal_numero))

        # Items + turnos del Estudio embebidos (#1308): replace completo, mismo
        # criterio que items/pagos ("un pedido no acumula entre imports"). Los
        # ítems se borran ANTES de los turnos — el cascade de
        # `alquiler_turnos_estudio` ya no tiene nada que arrastrar, y así el
        # DELETE de turnos no depende de en qué orden corra.
        conn.execute(
            "DELETE FROM alquiler_items WHERE pedido_id = %s", (alq_id,)
        )
        conn.execute(
            "DELETE FROM alquiler_turnos_estudio WHERE pedido_id = %s", (alq_id,)
        )
        # `turno_ids[i]` = id REAL del turno que estaba en la posición `i` del
        # JSON — los ítems lo resuelven vía `it.turno_index`.
        turno_ids: list[int] = []
        for t in a.turnos_estudio:
            cur = conn.execute(
                """
                INSERT INTO alquiler_turnos_estudio
                    (pedido_id, fecha_desde, fecha_hasta, descuento_pct,
                     descuento_manual_tipo, descuento_manual_monto)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (alq_id, t.fecha_desde, t.fecha_hasta, t.descuento_pct,
                 t.descuento_manual_tipo, t.descuento_manual_monto),
            )
            turno_ids.append(cur.fetchone()["id"])

        for it in a.items:
            if it.equipo_slug is not None:
                equipo_id = resolver.equipo_id(it.equipo_slug)
                if equipo_id is None:
                    raise ImportError_(
                        f"alquileres[{a.numero_pedido}].items: equipo_slug="
                        f"{it.equipo_slug!r} no existe"
                    )
            else:
                equipo_id = None  # línea personalizada (#805) — sin FK
            turno_estudio_id = (
                turno_ids[it.turno_index] if it.turno_index is not None else None
            )
            conn.execute(
                """
                INSERT INTO alquiler_items
                    (pedido_id, equipo_id, cantidad, precio_jornada, subtotal,
                     cobro_modo, nombre_libre, turno_estudio_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (alq_id, equipo_id, it.cantidad, it.precio_jornada, it.subtotal,
                 it.cobro_modo, it.nombre_libre, turno_estudio_id),
            )

        # Pagos: replace. Idem. `anulado`+auditoría viajan tal cual (#1184/
        # #1209) — un pago anulado (soft-delete) NO debe reinsertarse activo
        # con el default de la columna.
        conn.execute(
            "DELETE FROM alquiler_pagos WHERE pedido_id = %s", (alq_id,)
        )
        for p in a.pagos:
            conn.execute(
                """
                INSERT INTO alquiler_pagos
                    (pedido_id, monto, concepto, fecha,
                     anulado, anulado_por, anulado_at, anulado_motivo)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (alq_id, p.monto, p.concepto, p.fecha,
                 p.anulado, p.anulado_por, p.anulado_at, p.anulado_motivo),
            )

    # Segunda pasada: atar cada turno del Estudio a su pedido principal (#1308).
    # Va acá, no en el loop, porque el principal puede aparecer DESPUÉS que su
    # turno en el archivo. Si el principal no vino en el backup, queda NULL (el
    # turno sobrevive como pedido suelto en vez de romper el import).
    for alq_id, principal_numero in vinculos_pendientes:
        principal = conn.execute(
            "SELECT id FROM alquileres WHERE numero_pedido = %s LIMIT 1",
            (principal_numero,),
        ).fetchone()
        conn.execute(
            "UPDATE alquileres SET pedido_principal_id = %s WHERE id = %s",
            (principal["id"] if principal else None, alq_id),
        )

    resolver.refresh_alquileres()
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# estudio (singleton upsert WHERE id=1 + replace de listas hijas)
# ─────────────────────────────────────────────────────────────────────────────


def import_estudio(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    """Upsert del singleton estudio (id=1) + replace de fotos, pack y slots.

    Política de listas hijas: DELETE + reinsert (replace completo).
    - fotos: sin clave natural propia — replace es lo correcto.
    - pack_equipos: curado por el admin — replace mantiene el orden del JSON.
    - slots_fijos: configuración recurrente — replace. Nota: si hay alquileres
      con estudio_slot_id, esas FKs quedarán NULL hasta que se restaure también
      el backup de pedidos (el ON DELETE SET NULL de la FK lo maneja el motor).
    """
    if not rows:
        return {"inserted": 0, "updated": 0, "skipped": 0}
    items = _validate_rows(rows, schema.Estudio, "estudio")
    s = items[0]  # singleton — solo se procesa el primer elemento
    stats = {"inserted": 0, "updated": 0, "skipped": 0}

    # Resolver equipo centinela slug → id
    equipo_id = resolver.equipo_id(s.equipo_slug) if s.equipo_slug else None

    existing = conn.execute("SELECT id FROM estudio WHERE id = 1").fetchone()
    if existing:
        conn.execute(
            """
            UPDATE estudio SET
                equipo_id = %s, nombre = %s, tagline = %s, descripcion = %s,
                precio_hora = %s, min_horas = %s, open_hour = %s, close_hour = %s,
                buffer_horas = %s, pack_activo = %s, pack_nombre = %s,
                pack_descripcion = %s, pack_precio = %s, features_json = %s,
                faq_json = %s, direccion = %s, como_llegar = %s,
                testimonios_json = %s, anticipacion_min_horas = %s,
                mapa_url = %s, mapa_embed_url = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (
                equipo_id, s.nombre, s.tagline, s.descripcion,
                s.precio_hora, s.min_horas, s.open_hour, s.close_hour,
                s.buffer_horas, s.pack_activo, s.pack_nombre,
                s.pack_descripcion, s.pack_precio, s.features_json,
                s.faq_json, s.direccion, s.como_llegar,
                s.testimonios_json, s.anticipacion_min_horas,
                s.mapa_url, s.mapa_embed_url,
            ),
        )
        stats["updated"] += 1
    else:
        conn.execute(
            """
            INSERT INTO estudio (
                id, equipo_id, nombre, tagline, descripcion,
                precio_hora, min_horas, open_hour, close_hour, buffer_horas,
                pack_activo, pack_nombre, pack_descripcion, pack_precio,
                features_json, faq_json, direccion, como_llegar,
                testimonios_json, anticipacion_min_horas, mapa_url, mapa_embed_url
            ) VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                equipo_id, s.nombre, s.tagline, s.descripcion,
                s.precio_hora, s.min_horas, s.open_hour, s.close_hour,
                s.buffer_horas, s.pack_activo, s.pack_nombre,
                s.pack_descripcion, s.pack_precio, s.features_json,
                s.faq_json, s.direccion, s.como_llegar,
                s.testimonios_json, s.anticipacion_min_horas,
                s.mapa_url, s.mapa_embed_url,
            ),
        )
        stats["inserted"] += 1

    # ── Fotos: replace ───────────────────────────────────────────────────────
    conn.execute("DELETE FROM estudio_fotos WHERE estudio_id = 1")
    for f in s.fotos:
        conn.execute(
            """
            INSERT INTO estudio_fotos (estudio_id, url, path, orden, es_principal)
            VALUES (1, %s, %s, %s, %s)
            """,
            (f.url, f.path, f.orden, f.es_principal),
        )

    # ── Pack equipos: replace ────────────────────────────────────────────────
    conn.execute("DELETE FROM estudio_pack_equipos WHERE estudio_id = 1")
    for pe in s.pack_equipos:
        eq_id = resolver.equipo_id(pe.equipo_slug)
        if eq_id is None:
            raise ImportError_(
                f"estudio.pack_equipos: equipo_slug='{pe.equipo_slug}' no existe"
            )
        conn.execute(
            """
            INSERT INTO estudio_pack_equipos (estudio_id, equipo_id, orden)
            VALUES (1, %s, %s)
            ON CONFLICT (estudio_id, equipo_id) DO UPDATE SET orden = EXCLUDED.orden
            """,
            (eq_id, pe.orden),
        )

    # ── Slots fijos: replace ─────────────────────────────────────────────────
    # ON DELETE SET NULL en alquileres.estudio_slot_id maneja la FK automáticamente.
    conn.execute("DELETE FROM estudio_slots_fijos")
    for sl in s.slots_fijos:
        conn.execute(
            """
            INSERT INTO estudio_slots_fijos
                (cliente, dia_semana, hora_desde, hora_hasta, valor_mensual,
                 mes_desde, mes_hasta, activo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                sl.cliente, sl.dia_semana, sl.hora_desde, sl.hora_hasta,
                sl.valor_mensual, sl.mes_desde, sl.mes_hasta, sl.activo,
            ),
        )

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — ajustes, plantillas de mail, descuentos (upsert por clave natural)
# ─────────────────────────────────────────────────────────────────────────────


def import_app_settings(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    items = _validate_rows(rows, schema.AppSetting, "app_settings")
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    for s in items:
        cur = conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_by)
            VALUES (%s, %s, 'dataio-import')
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = CURRENT_TIMESTAMP,
                updated_by = 'dataio-import'
            RETURNING (xmax = 0) AS inserted
            """,
            (s.key, s.value),
        )
        row = cur.fetchone()
        stats["inserted" if row and row["inserted"] else "updated"] += 1
    return stats


def import_email_templates(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    items = _validate_rows(rows, schema.EmailTemplate, "email_templates")
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    for t in items:
        cur = conn.execute(
            """
            INSERT INTO email_templates (key, subject, body_html, body_text, updated_by)
            VALUES (%s, %s, %s, %s, 'dataio-import')
            ON CONFLICT (key) DO UPDATE SET
                subject = EXCLUDED.subject,
                body_html = EXCLUDED.body_html,
                body_text = EXCLUDED.body_text,
                updated_at = CURRENT_TIMESTAMP,
                updated_by = 'dataio-import'
            RETURNING (xmax = 0) AS inserted
            """,
            (t.key, t.subject, t.body_html, t.body_text),
        )
        row = cur.fetchone()
        stats["inserted" if row and row["inserted"] else "updated"] += 1
    return stats


def import_descuentos_jornada(
    conn, rows: list[dict], resolver: KeyResolver
) -> dict[str, int]:
    items = _validate_rows(rows, schema.DescuentoJornada, "descuentos_jornada")
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    for d in items:
        cur = conn.execute(
            """
            INSERT INTO descuentos_jornada (jornadas, pct)
            VALUES (%s, %s)
            ON CONFLICT (jornadas) DO UPDATE SET pct = EXCLUDED.pct
            RETURNING (xmax = 0) AS inserted
            """,
            (d.jornadas, d.pct),
        )
        row = cur.fetchone()
        stats["inserted" if row and row["inserted"] else "updated"] += 1
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────────────────────

IMPORTERS = {
    "marcas": import_marcas,
    "categorias": import_categorias,
    "spec_definitions": import_spec_definitions,
    "categoria_spec_templates": import_categoria_spec_templates,
    "equipos": import_equipos,
    "equipo_specs": import_equipo_specs,
    "equipo_fichas": import_equipo_fichas,
    "estudio": import_estudio,
    "app_settings": import_app_settings,
    "email_templates": import_email_templates,
    "descuentos_jornada": import_descuentos_jornada,
    "clientes": import_clientes,
    "alquileres": import_alquileres,
}
