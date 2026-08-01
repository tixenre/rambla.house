"""dataio/exporters.py — DB → list[dict] por entidad.

Cada función `export_<entidad>(conn)` devuelve una lista de dicts validados
contra el modelo Pydantic correspondiente (definido en `schema.py`).

Convenciones:
- IDs SERIAL se reemplazan por la clave natural correspondiente.
- FKs se resuelven a nombres / paths legibles.
- Campos runtime (timestamps de auto-update, scores calculados,
  popularidad, etc.) se omiten — son estado local del ambiente, no
  configuración portable.
- Las filas se devuelven ordenadas por su clave natural para producir
  diffs estables en git.
"""

from __future__ import annotations

from typing import Any

from . import schema


def _to_iso(v: Any) -> str | None:
    """Convierte un datetime de psycopg2 a string ISO. None passthrough."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    iso = getattr(v, "isoformat", None)
    return iso() if callable(iso) else str(v)


# ─────────────────────────────────────────────────────────────────────────────
# marcas
# ─────────────────────────────────────────────────────────────────────────────


def export_marcas(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT nombre, logo_url, visible, orden,
               COALESCE(destacada, FALSE) AS destacada
        FROM marcas
        ORDER BY nombre
    """).fetchall()
    return [
        schema.Marca(
            nombre=r["nombre"],
            logo_url=r["logo_url"],
            visible=bool(r["visible"]),
            orden=int(r["orden"]),
            destacada=bool(r["destacada"]),
        ).model_dump()
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# categorias (con parent_path resuelto a nombre del padre)
# ─────────────────────────────────────────────────────────────────────────────


def export_categorias(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT c.nombre, c.prioridad, c.visible, c.grupo_visual,
               c.nombre_publico_template, p.nombre AS parent_nombre
        FROM categorias c
        LEFT JOIN categorias p ON p.id = c.parent_id
        ORDER BY c.nombre
    """).fetchall()
    return [
        schema.Categoria(
            nombre=r["nombre"],
            parent_path=r["parent_nombre"],
            prioridad=int(r["prioridad"]),
            visible=bool(r["visible"]),
            grupo_visual=r["grupo_visual"],
            nombre_publico_template=r["nombre_publico_template"],
        ).model_dump()
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# spec_definitions
# ─────────────────────────────────────────────────────────────────────────────


def export_spec_definitions(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT sd.spec_key, sd.label, sd.tipo, sd.unidad, sd.enum_options,
               sd.ayuda, sd.es_compatibilidad, sd.compatibilidad_modo,
               sd.rol_compatibilidad, sd.validado, sd.tabla_columnas,
               sd.output_config, sd.favorito, sd.en_nombre, sd.en_filtros,
               sd.prioridad, c.nombre AS categoria_raiz_nombre
        FROM spec_definitions sd
        LEFT JOIN categorias c ON c.id = sd.categoria_raiz_id
        ORDER BY COALESCE(c.nombre, ''), sd.spec_key
    """).fetchall()
    return [
        schema.SpecDefinition(
            categoria_raiz_nombre=r["categoria_raiz_nombre"],
            spec_key=r["spec_key"],
            label=r["label"],
            tipo=r["tipo"],
            unidad=r["unidad"],
            enum_options=r["enum_options"],
            ayuda=r["ayuda"],
            es_compatibilidad=bool(r["es_compatibilidad"]),
            compatibilidad_modo=r["compatibilidad_modo"] or "exacta",
            rol_compatibilidad=r["rol_compatibilidad"],
            validado=bool(r["validado"]),
            tabla_columnas=r["tabla_columnas"],
            output_config=r["output_config"],
            favorito=bool(r["favorito"]),
            en_nombre=bool(r["en_nombre"]),
            en_filtros=bool(r["en_filtros"]),
            prioridad=int(r["prioridad"]),
        ).model_dump()
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# categoria_spec_templates
# ─────────────────────────────────────────────────────────────────────────────


def export_categoria_spec_templates(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT cat.nombre AS categoria_nombre,
               sd.spec_key,
               raiz.nombre AS spec_categoria_raiz_nombre,
               cst.prioridad, cst.destacado, cst.obligatorio,
               cst.visible_en_card, cst.visible_en_filtros,
               cst.visible_en_nombre, cst.ayuda
        FROM categoria_spec_templates cst
        JOIN categorias cat ON cat.id = cst.categoria_id
        JOIN spec_definitions sd ON sd.id = cst.spec_def_id
        LEFT JOIN categorias raiz ON raiz.id = sd.categoria_raiz_id
        ORDER BY cat.nombre, sd.spec_key
    """).fetchall()
    return [
        schema.CategoriaSpecTemplate(
            categoria_nombre=r["categoria_nombre"],
            spec_ref=schema.SpecRef(
                categoria_raiz_nombre=r["spec_categoria_raiz_nombre"],
                spec_key=r["spec_key"],
            ),
            prioridad=int(r["prioridad"] or 100),
            destacado=bool(r["destacado"]),
            obligatorio=bool(r["obligatorio"]),
            visible_en_card=bool(r["visible_en_card"]),
            visible_en_filtros=bool(r["visible_en_filtros"]),
            visible_en_nombre=bool(r["visible_en_nombre"]),
            ayuda=r["ayuda"],
        ).model_dump()
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# equipos (con M2M categorias embebidas)
# ─────────────────────────────────────────────────────────────────────────────


def export_equipos(conn) -> list[dict]:
    """Exporta equipos con slug como clave natural.

    READ-ONLY por contrato (#922): el export NO crea columnas ni puebla slugs
    —antes lo hacía un self-heal acá, mutando esquema/datos en cada "bajar
    backup" (locks en prod, commit incondicional)—. El slug se garantiza por
    los caminos correctos: la columna/constraint en `init_db()` + migración, y
    el valor por el backfill (`dataio.slug.backfill_equipos_slug`) que corre en
    el bootstrap y en el alta de equipo. Si un equipo activo quedara sin slug
    (esquema sin migrar), se omite del export y se loguea — no se auto-cura.
    """
    from database import MARCA_SUBQUERY  # type: ignore

    sin_slug = conn.execute("""
        SELECT COUNT(*) AS n FROM equipos
        WHERE slug IS NULL AND eliminado_at IS NULL
    """).fetchone()["n"]
    if sin_slug:
        import logging
        logging.getLogger(__name__).warning(
            "export_equipos: %d equipo(s) activo(s) sin slug se omiten del export. "
            "Correr el backfill (init_db / migración) antes de exportar.",
            sin_slug,
        )
    rows = conn.execute(f"""
        SELECT e.slug, e.nombre, {MARCA_SUBQUERY}, e.modelo, e.cantidad,
               e.precio_jornada, e.precio_jornada_manual, e.precio_usd,
               e.roi_pct, e.valor_reposicion, e.foto_url, e.fecha_compra,
               e.serie, e.bh_url, e.dueno, e.visible_catalogo, e.estado,
               e.ficha_completa, e.eliminado_at, e.nombre_publico_override,
               e.nombre_publico_revisado, e.relevancia_manual,
               m.nombre AS marca_nombre
        FROM equipos e
        LEFT JOIN marcas m ON m.id = e.brand_id
        WHERE e.slug IS NOT NULL
        ORDER BY e.slug
    """).fetchall()
    if not rows:
        return []

    # Cargar M2M en batch para no hacer N+1 queries
    slug_by_id = {}
    id_rows = conn.execute("""
        SELECT id, slug FROM equipos WHERE slug IS NOT NULL
    """).fetchall()
    for ir in id_rows:
        slug_by_id[ir["id"]] = ir["slug"]

    cat_rows = conn.execute("""
        SELECT ec.equipo_id, c.nombre AS cat_nombre, ec.orden
        FROM equipo_categorias ec
        JOIN categorias c ON c.id = ec.categoria_id
        JOIN equipos e ON e.id = ec.equipo_id
        WHERE e.slug IS NOT NULL
        ORDER BY ec.equipo_id, ec.orden, c.nombre
    """).fetchall()
    cats_by_slug: dict[str, list[schema.EquipoCategoriaRef]] = {}
    for r in cat_rows:
        s = slug_by_id.get(r["equipo_id"])
        if not s:
            continue
        cats_by_slug.setdefault(s, []).append(
            schema.EquipoCategoriaRef(nombre=r["cat_nombre"], orden=int(r["orden"] or 0))
        )

    out: list[dict] = []
    for r in rows:
        slug = r["slug"]
        out.append(
            schema.Equipo(
                slug=slug,
                nombre=r["nombre"],
                marca=r["marca"],
                modelo=r["modelo"],
                marca_nombre=r["marca_nombre"],
                cantidad=int(r["cantidad"] or 1),
                precio_jornada=r["precio_jornada"],
                precio_jornada_manual=bool(r["precio_jornada_manual"]),
                precio_usd=r["precio_usd"],
                roi_pct=r["roi_pct"],
                valor_reposicion=r["valor_reposicion"],
                foto_url=r["foto_url"],
                fecha_compra=_to_iso(r["fecha_compra"]),
                serie=r["serie"],
                bh_url=r["bh_url"],
                dueno=r["dueno"],
                visible_catalogo=int(r["visible_catalogo"] or 0),
                estado=r["estado"] or "operativo",
                ficha_completa=bool(r["ficha_completa"]),
                eliminado_at=_to_iso(r["eliminado_at"]),
                nombre_publico_override=r["nombre_publico_override"],
                nombre_publico_revisado=bool(r["nombre_publico_revisado"]),
                relevancia_manual=int(r["relevancia_manual"] or 100),
                categorias=cats_by_slug.get(slug, []),
            ).model_dump()
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# equipo_specs
# ─────────────────────────────────────────────────────────────────────────────


def export_equipo_specs(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT e.slug AS equipo_slug,
               sd.spec_key,
               raiz.nombre AS spec_categoria_raiz_nombre,
               es.value
        FROM equipo_specs es
        JOIN equipos e ON e.id = es.equipo_id
        JOIN spec_definitions sd ON sd.id = es.spec_def_id
        LEFT JOIN categorias raiz ON raiz.id = sd.categoria_raiz_id
        WHERE e.slug IS NOT NULL
        ORDER BY e.slug, sd.spec_key
    """).fetchall()
    return [
        schema.EquipoSpec(
            equipo_slug=r["equipo_slug"],
            spec_ref=schema.SpecRef(
                categoria_raiz_nombre=r["spec_categoria_raiz_nombre"],
                spec_key=r["spec_key"],
            ),
            value=r["value"],
        ).model_dump()
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# equipo_fichas
# ─────────────────────────────────────────────────────────────────────────────


def export_equipo_fichas(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT e.slug AS equipo_slug, ef.*
        FROM equipo_fichas ef
        JOIN equipos e ON e.id = ef.equipo_id
        WHERE e.slug IS NOT NULL
        ORDER BY e.slug
    """).fetchall()
    out: list[dict] = []
    for r in rows:
        out.append(
            schema.EquipoFicha(
                equipo_slug=r["equipo_slug"],
                descripcion=r["descripcion"],
                notas=r["notas"],
                keywords_json=r["keywords_json"],
                nombre_publico_template=r["nombre_publico_template"],
                conectividad_json=r["conectividad_json"],
                compatible_con_json=r["compatible_con_json"],
                video_url=r["video_url"],
                precio_bh_usd=r["precio_bh_usd"],
                fuente_url=r["fuente_url"],
                fuente_titulo=r["fuente_titulo"],
                enriquecido_at=_to_iso(r["enriquecido_at"]),
                enriquecido_fuente=r["enriquecido_fuente"],
            ).model_dump()
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# OPERATIONAL — clientes, alquileres (con items/pagos embebidos)
# ─────────────────────────────────────────────────────────────────────────────


def export_clientes(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT email, nombre, apellido, telefono, direccion, direccion_maps_url,
               cuit, descuento, perfil_impuestos, razon_social, domicilio_fiscal,
               email_facturacion, notas, supabase_uid
        FROM clientes
        WHERE email IS NOT NULL
        ORDER BY LOWER(email)
    """).fetchall()
    out: list[dict] = []
    for r in rows:
        out.append(
            schema.Cliente(
                email=r["email"],
                nombre=r["nombre"],
                apellido=r["apellido"],
                telefono=r["telefono"],
                direccion=r["direccion"],
                direccion_maps_url=r["direccion_maps_url"],
                cuit=r["cuit"],
                descuento=float(r["descuento"] or 0.0),
                perfil_impuestos=r["perfil_impuestos"] or "consumidor_final",
                razon_social=r["razon_social"],
                domicilio_fiscal=r["domicilio_fiscal"],
                email_facturacion=r["email_facturacion"],
                notas=r["notas"],
                supabase_uid=str(r["supabase_uid"]) if r["supabase_uid"] else None,
            ).model_dump()
        )
    return out


def export_alquileres(conn) -> list[dict]:
    """Exporta alquileres con items y pagos embebidos.

    Filtra los que no tienen numero_pedido — no son re-importables sin clave
    natural. Eso deja afuera dos grupos, los dos a propósito:

    - **Legacy sin número** (importados viejos). Si los necesitás, generales un
      numero_pedido antes vía un script de mantenimiento.
    - **Borradores.** Un borrador nace SIN número por diseño (es un presupuesto
      rápido, no una venta — ver `create_pedido`), así que no entra al backup.
      **CONFIRMADO POR EL DUEÑO** ("no pasa nada si el borrador no entra en el
      back up"): es efímero y se borra de verdad (hard delete), no algo que
      haya que preservar. NO "arreglar" este filtro para incluirlos.
    """
    rows = conn.execute("""
        SELECT a.numero_pedido, a.cliente_nombre, a.cliente_telefono,
               a.estado, a.fecha_desde, a.fecha_hasta, a.monto_total,
               a.monto_pagado, a.descuento_pct, a.notas, a.fuente,
               a.tipo,
               pp.numero_pedido AS pedido_principal_numero,
               a.id AS alquiler_id,
               c.email AS cliente_email
        FROM alquileres a
        LEFT JOIN clientes c ON c.id = a.cliente_id
        LEFT JOIN alquileres pp ON pp.id = a.pedido_principal_id
        WHERE a.numero_pedido IS NOT NULL
        ORDER BY a.numero_pedido
    """).fetchall()
    if not rows:
        return []

    alquiler_ids = [r["alquiler_id"] for r in rows]

    # Turnos del Estudio EMBEBIDOS en batch (#1308) — ANTES de los items:
    # arma el índice (pedido_id, turno_id) → posición que los items necesitan
    # para referenciar "a cuál turno pertenezco" sin usar el id real (no
    # estable entre ambientes).
    turnos_by_alq: dict[int, list[schema.AlquilerTurnoEstudioRef]] = {}
    turno_index_por_id: dict[int, int] = {}
    turno_rows = conn.execute("""
        SELECT id, pedido_id, fecha_desde, fecha_hasta, descuento_pct,
               descuento_manual_tipo, descuento_manual_monto
        FROM alquiler_turnos_estudio
        WHERE pedido_id = ANY(%s)
        ORDER BY pedido_id, id
    """, (alquiler_ids,)).fetchall()
    for tr in turno_rows:
        lista = turnos_by_alq.setdefault(tr["pedido_id"], [])
        turno_index_por_id[tr["id"]] = len(lista)
        lista.append(
            schema.AlquilerTurnoEstudioRef(
                fecha_desde=_to_iso(tr["fecha_desde"]) or "",
                fecha_hasta=_to_iso(tr["fecha_hasta"]) or "",
                descuento_pct=float(tr["descuento_pct"] or 0.0),
                descuento_manual_tipo=tr["descuento_manual_tipo"] or "pct",
                descuento_manual_monto=int(tr["descuento_manual_monto"] or 0),
            )
        )

    # Items en batch — LEFT JOIN (no INNER): una línea personalizada (#805,
    # `equipo_id IS NULL`, ej. flete o la "Pintura reciente" de un turno del
    # Estudio) no tiene equipo que matchear y antes se perdía en silencio.
    # `ai.equipo_id` viaja aparte de `equipo_slug` para distinguir "sin equipo
    # a propósito" de "equipo sin slug" (anomalía real pero distinta —
    # ver el filtro de abajo, mismo comportamiento que el INNER JOIN de antes
    # para ESE caso puntual).
    items_by_alq: dict[int, list[schema.AlquilerItemRef]] = {}
    item_rows = conn.execute("""
        SELECT ai.pedido_id, ai.equipo_id, e.slug AS equipo_slug, ai.cantidad,
               ai.precio_jornada, ai.subtotal, ai.cobro_modo, ai.nombre_libre,
               ai.turno_estudio_id
        FROM alquiler_items ai
        LEFT JOIN equipos e ON e.id = ai.equipo_id
        WHERE ai.pedido_id = ANY(%s)
        ORDER BY ai.pedido_id, ai.id
    """, (alquiler_ids,)).fetchall()
    for ir in item_rows:
        if ir["equipo_id"] is not None and ir["equipo_slug"] is None:
            continue  # equipo sin slug (anomalía) — mismo drop que antes
        turno_id = ir["turno_estudio_id"]
        items_by_alq.setdefault(ir["pedido_id"], []).append(
            schema.AlquilerItemRef(
                equipo_slug=ir["equipo_slug"],
                cantidad=int(ir["cantidad"] or 1),
                precio_jornada=int(ir["precio_jornada"] or 0),
                subtotal=int(ir["subtotal"] or 0),
                cobro_modo=ir["cobro_modo"] or "jornada",
                nombre_libre=ir["nombre_libre"],
                turno_index=(
                    turno_index_por_id.get(turno_id) if turno_id is not None else None
                ),
            )
        )

    # Pagos en batch. Incluye `anulado` + columnas de auditoría (#1184/#1209):
    # un pago anulado es soft-delete y no debe "revivir" activo al reimportar
    # (antes se perdía en el viaje y el import lo reinsertaba con el default
    # de la columna, `anulado=FALSE`).
    pagos_by_alq: dict[int, list[schema.AlquilerPagoRef]] = {}
    pago_rows = conn.execute("""
        SELECT pedido_id, monto, concepto, fecha,
               COALESCE(anulado, FALSE) AS anulado,
               anulado_por, anulado_at, anulado_motivo
        FROM alquiler_pagos
        WHERE pedido_id = ANY(%s)
        ORDER BY pedido_id, fecha, id
    """, (alquiler_ids,)).fetchall()
    for pr in pago_rows:
        pagos_by_alq.setdefault(pr["pedido_id"], []).append(
            schema.AlquilerPagoRef(
                monto=int(pr["monto"]),
                concepto=pr["concepto"],
                fecha=_to_iso(pr["fecha"]) or "",
                anulado=bool(pr["anulado"]),
                anulado_por=pr["anulado_por"],
                anulado_at=_to_iso(pr["anulado_at"]),
                anulado_motivo=pr["anulado_motivo"],
            )
        )

    out: list[dict] = []
    for r in rows:
        alq_id = r["alquiler_id"]
        out.append(
            schema.Alquiler(
                numero_pedido=int(r["numero_pedido"]),
                cliente_email=r["cliente_email"],
                cliente_nombre=r["cliente_nombre"],
                cliente_telefono=r["cliente_telefono"],
                estado=r["estado"] or "solicitado",
                fecha_desde=_to_iso(r["fecha_desde"]) or "",
                fecha_hasta=_to_iso(r["fecha_hasta"]) or "",
                tipo=r["tipo"] or "diaria",
                pedido_principal_numero=(
                    int(r["pedido_principal_numero"])
                    if r["pedido_principal_numero"] is not None
                    else None
                ),
                monto_total=int(r["monto_total"] or 0),
                monto_pagado=int(r["monto_pagado"] or 0),
                descuento_pct=float(r["descuento_pct"] or 0.0),
                notas=r["notas"],
                fuente=r["fuente"] or "sistema",
                items=items_by_alq.get(alq_id, []),
                pagos=pagos_by_alq.get(alq_id, []),
                turnos_estudio=turnos_by_alq.get(alq_id, []),
            ).model_dump()
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# estudio (singleton + listas embebidas: fotos, pack, slots)
# ─────────────────────────────────────────────────────────────────────────────


def export_estudio(conn) -> list[dict]:
    """Exporta el estudio singleton (id=1) con fotos, pack y slots embebidos.

    Devuelve lista vacía si la fila aún no existe (estudio no configurado).
    Las FKs a equipos se resuelven a slug para portabilidad entre ambientes.
    """
    row = conn.execute("SELECT * FROM estudio WHERE id = 1").fetchone()
    if not row:
        return []

    # equipo_id → slug (centinela del espacio)
    equipo_slug: str | None = None
    if row["equipo_id"]:
        slug_row = conn.execute(
            "SELECT slug FROM equipos WHERE id = %s", (row["equipo_id"],)
        ).fetchone()
        equipo_slug = slug_row["slug"] if slug_row else None

    # Fotos
    foto_rows = conn.execute("""
        SELECT url, path, orden, es_principal
        FROM estudio_fotos
        WHERE estudio_id = 1
        ORDER BY orden, id
    """).fetchall()
    fotos = [
        schema.EstudioFoto(
            url=r["url"],
            path=r["path"],
            orden=int(r["orden"]),
            es_principal=bool(r["es_principal"]),
        ).model_dump()
        for r in foto_rows
    ]

    # Pack — equipo_id → slug
    pack_rows = conn.execute("""
        SELECT e.slug AS equipo_slug, pe.orden
        FROM estudio_pack_equipos pe
        JOIN equipos e ON e.id = pe.equipo_id
        WHERE pe.estudio_id = 1 AND e.slug IS NOT NULL
        ORDER BY pe.orden, pe.id
    """).fetchall()
    pack_equipos = [
        schema.EstudioPackEquipo(
            equipo_slug=r["equipo_slug"],
            orden=int(r["orden"]),
        ).model_dump()
        for r in pack_rows
    ]

    # Slots fijos
    slot_rows = conn.execute("""
        SELECT cliente, dia_semana, hora_desde, hora_hasta, valor_mensual,
               mes_desde, mes_hasta, activo
        FROM estudio_slots_fijos
        ORDER BY dia_semana, hora_desde, id
    """).fetchall()
    slots_fijos = [
        schema.EstudioSlotFijo(
            cliente=r["cliente"],
            dia_semana=int(r["dia_semana"]),
            hora_desde=int(r["hora_desde"]),
            hora_hasta=int(r["hora_hasta"]),
            valor_mensual=int(r["valor_mensual"] or 0),
            mes_desde=str(r["mes_desde"]),
            mes_hasta=str(r["mes_hasta"]),
            activo=bool(r["activo"]),
        ).model_dump()
        for r in slot_rows
    ]

    return [
        schema.Estudio(
            equipo_slug=equipo_slug,
            nombre=row["nombre"],
            tagline=row["tagline"] or "",
            descripcion=row["descripcion"] or "",
            precio_hora=int(row["precio_hora"] or 0),
            min_horas=int(row["min_horas"] or 2),
            open_hour=int(row["open_hour"] or 8),
            close_hour=int(row["close_hour"] or 22),
            buffer_horas=int(row["buffer_horas"] or 0),
            pack_activo=bool(row["pack_activo"]),
            pack_nombre=row["pack_nombre"] or "",
            pack_descripcion=row["pack_descripcion"] or "",
            pack_precio=int(row["pack_precio"] or 0),
            features_json=row["features_json"],
            faq_json=row["faq_json"],
            direccion=row["direccion"] or "",
            como_llegar=row["como_llegar"] or "",
            testimonios_json=row["testimonios_json"],
            anticipacion_min_horas=int(row["anticipacion_min_horas"] or 0),
            mapa_url=row["mapa_url"] or "",
            mapa_embed_url=row["mapa_embed_url"] or "",
            fotos=fotos,
            pack_equipos=pack_equipos,
            slots_fijos=slots_fijos,
        ).model_dump()
    ]


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — ajustes, plantillas de mail, descuentos
# ─────────────────────────────────────────────────────────────────────────────


def export_app_settings(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT key, value FROM app_settings ORDER BY key"
    ).fetchall()
    return [
        schema.AppSetting(key=r["key"], value=r["value"]).model_dump()
        for r in rows
    ]


def export_email_templates(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT key, subject, body_html, body_text FROM email_templates ORDER BY key"
    ).fetchall()
    return [
        schema.EmailTemplate(
            key=r["key"],
            subject=r["subject"],
            body_html=r["body_html"],
            body_text=r["body_text"],
        ).model_dump()
        for r in rows
    ]


def export_descuentos_jornada(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT jornadas, pct FROM descuentos_jornada ORDER BY jornadas"
    ).fetchall()
    return [
        schema.DescuentoJornada(jornadas=int(r["jornadas"]), pct=float(r["pct"])).model_dump()
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────────────────────

EXPORTERS = {
    "marcas": export_marcas,
    "categorias": export_categorias,
    "spec_definitions": export_spec_definitions,
    "categoria_spec_templates": export_categoria_spec_templates,
    "equipos": export_equipos,
    "equipo_specs": export_equipo_specs,
    "equipo_fichas": export_equipo_fichas,
    "estudio": export_estudio,
    "app_settings": export_app_settings,
    "email_templates": export_email_templates,
    "descuentos_jornada": export_descuentos_jornada,
    "clientes": export_clientes,
    "alquileres": export_alquileres,
}
