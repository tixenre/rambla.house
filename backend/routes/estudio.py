"""
routes/estudio.py — CRUD del Estudio (singleton) + galería de fotos (E1)
                    + trabajos/producciones (galería "en acción").
"""

import json
import time
from collections import namedtuple
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from auth.guards import require_admin
from database import MARCA_SUBQUERY, get_db, now_ar, row_to_dict, to_datetime
from rate_limit import limiter, ADMIN_WRITE_LIMIT, ADMIN_UPLOAD_LIMIT, CLIENTE_WRITE_LIMIT
from clientes.queries.identidad import nombre_completo_cliente
from reservas import ESTADOS_RESERVADO, validar_stock as _check_stock, validar_stock_hipotetico
from routes.alquileres import (
    _dispatch_pedido_creado_emails,
    _enriquecer_pedidos_con_cliente,
    _get_alquiler_detail,
    _next_numero_pedido,
    get_disponibilidad,
)
from services.media.security import _download_image_bytes, _validate_ssrf_only
from services.media.storage import delete_object as _delete_from_r2
from services.media import (
    DISPLAY_KEEP_ASPECT,
    DISPLAY_KEEP_ASPECT_AVIF,
    DISPLAY_KEEP_ASPECT_SM,
    DISPLAY_KEEP_ASPECT_SM_AVIF,
    collect_asset_keys,
    purge_r2,
    store_upload,
)
from services.media_fastapi import media_http
from services.fechas import fmt_hhmm
from services.precios import precio_jornada_efectivo, resolver_descuento_uniforme

router = APIRouter()

# Stock sentinel de un equipo tipo='combo' (#635): su disponibilidad real se
# deriva de sus componentes, este valor nunca se lee para ese fin — mismo
# criterio que `COMBO_SENTINEL_STOCK` en `ComboBuilderDialog.tsx` (frontend).
_COMBO_STOCK_SENTINEL = 9999


# ── Helpers internos ─────────────────────────────────────────────────────────

def _foto_path_estudio() -> str:
    ts = int(time.time() * 1000)
    return f"estudio/{ts}.webp"


def _get_estudio_row(conn):
    cur = conn.execute("SELECT * FROM estudio WHERE id = 1")
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Fila estudio no encontrada — ejecutá init_db")
    return row


def _require_cliente(request):
    """Guard de cliente logueado (mismo que /api/cliente/pedidos). Import diferido
    para no acoplar el módulo a toda la cadena del portal; envuelto en helper para
    ser patcheable en tests."""
    from routes.cliente_portal import require_cliente
    return require_cliente(request)


def _get_fotos(conn) -> list:
    cur = conn.execute(
        "SELECT id, url, url_sm, url_avif, url_sm_avif, path, orden, es_principal, created_at "
        "FROM estudio_fotos WHERE estudio_id = 1 ORDER BY orden, id",
        (),
    )
    rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "url": r["url"],
            "url_sm": r["url_sm"],
            "url_avif": r["url_avif"],
            "url_sm_avif": r["url_sm_avif"],
            "path": r["path"],
            "orden": r["orden"],
            "es_principal": bool(r["es_principal"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


def _parse_json_field(value) -> list | None:
    if not value:
        return None
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


def _build_response(row, fotos: list) -> dict:
    return {
        "id": row["id"],
        "equipo_id": row["equipo_id"],
        "nombre": row["nombre"],
        "tagline": row["tagline"],
        "descripcion": row["descripcion"],
        "precio_hora": row["precio_hora"],
        "min_horas": row["min_horas"],
        "open_hour": row["open_hour"],
        "close_hour": row["close_hour"],
        "buffer_horas": row["buffer_horas"],
        "anticipacion_min_horas": row["anticipacion_min_horas"],
        "pack_activo": bool(row["pack_activo"]),
        "pack_nombre": row["pack_nombre"],
        "pack_descripcion": row["pack_descripcion"],
        "pack_precio": row["pack_precio"],
        "promo_combo_id": row["promo_combo_id"],
        "features": _parse_json_field(row["features_json"]),
        "faq": _parse_json_field(row["faq_json"]),
        "direccion": row["direccion"],
        "como_llegar": row["como_llegar"],
        "testimonios": _parse_json_field(row["testimonios_json"]),
        "mapa_url": row["mapa_url"],
        "mapa_embed_url": row["mapa_embed_url"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "fotos": fotos,
    }


def _promo_info(conn, estudio_row, fecha_desde=None, fecha_hasta=None,
                exclude_pedido_id: int | None = None) -> dict | None:
    """Info de la promo (combo) del Estudio: nombre/foto/precio — `None` si
    todavía no se creó (#1283 Fase 5). El precio sale de `precio_jornada_efectivo`
    (fuente única, sigue en vivo el precio de los componentes). `descripcion` reusa
    `pack_descripcion` (texto libre ya editable desde el back-office, no se agrega
    un campo nuevo). Si se pasa una franja (`fecha_desde`/`fecha_hasta`, ambos
    `datetime`), suma `disponible` (deriva de `get_disponibilidad`, que expande
    los componentes del combo igual que cualquier compuesto — sin lógica nueva)."""
    combo_id = estudio_row["promo_combo_id"]
    if not combo_id:
        return None
    combo = conn.execute(
        "SELECT nombre, foto_url FROM equipos WHERE id = %s AND eliminado_at IS NULL",
        (combo_id,),
    ).fetchone()
    if not combo:
        return None
    out = {
        "equipo_id": combo_id,
        "nombre": combo["nombre"],
        "descripcion": estudio_row["pack_descripcion"],
        "foto_url": combo["foto_url"],
        "precio": precio_jornada_efectivo(conn, combo_id) or 0,
    }
    if fecha_desde is not None:
        disp = get_disponibilidad(fecha_desde.isoformat(), fecha_hasta.isoformat(), exclude_pedido_id)
        out["disponible"] = disp.get(str(combo_id), 0) >= 1
    return out


def _insert_foto(
    conn,
    url: str,
    path: str,
    media_id: int | None = None,
    url_sm: str | None = None,
    url_avif: str | None = None,
    url_sm_avif: str | None = None,
) -> dict:
    cur = conn.execute(
        "SELECT COALESCE(MAX(orden), -1) + 1 AS next_orden FROM estudio_fotos WHERE estudio_id = 1",
        (),
    )
    orden = cur.fetchone()["next_orden"]

    cur2 = conn.execute("SELECT COUNT(*) AS cnt FROM estudio_fotos WHERE estudio_id = 1", ())
    is_first = cur2.fetchone()["cnt"] == 0

    conn.execute(
        "INSERT INTO estudio_fotos "
        "(estudio_id, url, url_sm, url_avif, url_sm_avif, path, orden, es_principal, media_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (1, url, url_sm, url_avif, url_sm_avif, path, orden, is_first, media_id),
    )
    conn.commit()

    cur3 = conn.execute(
        "SELECT id, url, url_sm, url_avif, url_sm_avif, path, orden, es_principal, created_at "
        "FROM estudio_fotos WHERE path = %s AND estudio_id = 1",
        (path,),
    )
    r = cur3.fetchone()
    return {
        "id": r["id"],
        "url": r["url"],
        "url_sm": r["url_sm"],
        "url_avif": r["url_avif"],
        "url_sm_avif": r["url_sm_avif"],
        "path": r["path"],
        "orden": r["orden"],
        "es_principal": bool(r["es_principal"]),
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


# ── Endpoint público ─────────────────────────────────────────────────────────

import re as _re


def _extract_ig_shortcode(url_or_code: str) -> tuple[str, str] | None:
    """Retorna (shortcode, post_type) donde post_type es 'reel', 'p' o 'tv'."""
    if not url_or_code:
        return None
    m = _re.search(r"instagram\.com/(reel|p|tv)/([A-Za-z0-9_-]+)", url_or_code)
    if m:
        return (m.group(2), m.group(1))
    if _re.match(r"^[A-Za-z0-9_-]{8,}$", url_or_code):
        return (url_or_code, "reel")
    return None


def _extract_og_tag(html_text: str, prop: str) -> str | None:
    """Extrae el content de un og:meta tag, tolerando orden de atributos."""
    for pat in (
        rf'<meta[^>]+property="{_re.escape(prop)}"[^>]+content="([^"]+)"',
        rf'<meta[^>]+content="([^"]+)"[^>]+property="{_re.escape(prop)}"',
    ):
        m = _re.search(pat, html_text)
        if m:
            return m.group(1).replace("\\u0026", "&").replace("&amp;", "&")
    return None


def _fetch_og_meta(url: str) -> dict:
    """Descarga una URL y extrae og:title/image/description (best-effort)."""
    import httpx
    try:
        headers = {
            "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        }
        resp = httpx.get(url, headers=headers, timeout=8.0, follow_redirects=True)
        if resp.status_code != 200:
            return {}
        html = resp.text
        return {
            "title": _extract_og_tag(html, "og:title"),
            "image": _extract_og_tag(html, "og:image"),
            "description": _extract_og_tag(html, "og:description"),
        }
    except Exception:
        return {}


# ── Medios externos (links YouTube/Instagram) ─────────────────────────────────
#
# Un trabajo es una lista ordenada de medios: links externos (YouTube/Instagram)
# + fotos subidas. Los thumbnails de los links NO se hotlinkean crudos — las URLs
# del CDN de Instagram expiran y se bloquean por referrer; las de YouTube son
# estables pero igual las pasamos por el motor para tener una copia permanente +
# AVIF. `_process_remote_thumbnail` baja la imagen y la guarda en R2 vía el motor
# (dedup por hash → no reprocesa la misma imagen).


def _detect_link_tipo(url: str) -> str | None:
    """Clasifica una URL externa. None si no es un proveedor soportado."""
    if not url:
        return None
    if "youtu" in url:
        return "youtube"
    if "instagram.com" in url:
        return "instagram"
    return None


def _extract_yt_id(url: str) -> str | None:
    m = _re.search(
        r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/|live/))([A-Za-z0-9_-]{11})",
        url,
    )
    return m.group(1) if m else None


def _process_remote_thumbnail(url: str | None) -> str | None:
    """Baja una imagen remota (og:image de IG, thumb de YT) y la guarda permanente
    en R2 vía el motor de medios. Devuelve la URL de display (webp). Best-effort:
    None ante cualquier fallo (la card cae a un placeholder)."""
    if not url:
        return None
    try:
        with media_http():
            _validate_ssrf_only(url)
            raw, _ct = _download_image_bytes(url)
        with get_db() as conn:
            with media_http():
                asset = store_upload(
                    raw,
                    kind="estudio",
                    derive_specs=[
                        DISPLAY_KEEP_ASPECT,
                        DISPLAY_KEEP_ASPECT_SM,
                        DISPLAY_KEEP_ASPECT_AVIF,
                        DISPLAY_KEEP_ASPECT_SM_AVIF,
                    ],
                    conn=conn,
                )
            conn.commit()
        v = asset.variant("display")
        return {"url": v.url, "w": v.width or None, "h": v.height or None}
    except Exception:
        return None


def _resolve_link_thumbnail(tipo: str, url: str) -> dict | None:
    """Obtiene un thumbnail permanente {url, w, h} para un link, según el proveedor."""
    if tipo == "youtube":
        vid = _extract_yt_id(url)
        if not vid:
            return None
        for quality in ("maxresdefault", "hqdefault"):
            thumb = _process_remote_thumbnail(
                f"https://img.youtube.com/vi/{vid}/{quality}.jpg"
            )
            if thumb:
                return thumb
        return None
    if tipo == "instagram":
        ig = _extract_ig_shortcode(url)
        if not ig:
            return None
        og = _fetch_og_meta(f"https://www.instagram.com/{ig[1]}/{ig[0]}/")
        return _process_remote_thumbnail(og.get("image"))
    return None


def _resolve_links(incoming: list, existing: list | None) -> list:
    """Normaliza la lista de links entrante a [{tipo, url, thumbnail_url, w, h}].

    Reusa el thumbnail ya procesado (url + dimensiones) de un link cuya URL no
    cambió (evita re-bajar y re-procesar en cada edición). El `tipo` lo decide el
    server (ignora lo que mande el front).

    Si el link trae `thumbnail_url` (override del admin), lo descarga y lo usa
    en lugar del og:image auto-detectado — permite corregir la miniatura de
    carruseles de IG donde og:image no es el primer slide."""
    existing_by_url = {l.get("url"): l for l in (existing or []) if l.get("url")}
    out: list = []
    seen: set = set()
    for link in incoming:
        url = (link.get("url") or "").strip()
        if not url or url in seen:
            continue
        tipo = _detect_link_tipo(url)
        if not tipo:
            continue
        seen.add(url)
        prev = existing_by_url.get(url)
        # Override: el admin mandó una URL de miniatura personalizada.
        override = (link.get("thumbnail_url") or "").strip()
        if override:
            thumb = _process_remote_thumbnail(override)
            out.append({
                "tipo": tipo, "url": url,
                "thumbnail_url": thumb["url"] if thumb else (prev or {}).get("thumbnail_url"),
                "thumbnail_w": thumb["w"] if thumb else (prev or {}).get("thumbnail_w"),
                "thumbnail_h": thumb["h"] if thumb else (prev or {}).get("thumbnail_h"),
            })
            continue
        if prev and prev.get("thumbnail_url"):
            out.append({
                "tipo": tipo, "url": url,
                "thumbnail_url": prev.get("thumbnail_url"),
                "thumbnail_w": prev.get("thumbnail_w"),
                "thumbnail_h": prev.get("thumbnail_h"),
            })
            continue
        thumb = _resolve_link_thumbnail(tipo, url)
        out.append({
            "tipo": tipo, "url": url,
            "thumbnail_url": thumb["url"] if thumb else None,
            "thumbnail_w": thumb["w"] if thumb else None,
            "thumbnail_h": thumb["h"] if thumb else None,
        })
    return out


def _build_media(links: list, fotos: list) -> list:
    """Une links + fotos en la lista `media` ordenada que consume el carrusel del
    front. Links primero (el medio 'titular'), después las fotos subidas. `w`/`h`
    = dimensiones del thumbnail, para que la card use la proporción real."""
    media: list = []
    for link in links or []:
        media.append({
            "kind": link.get("tipo"),
            "url": link.get("url"),
            "thumbnail": link.get("thumbnail_url"),
            "w": link.get("thumbnail_w"),
            "h": link.get("thumbnail_h"),
        })
    for foto in fotos or []:
        media.append({
            "kind": "foto",
            "url": foto.get("url"),
            "url_sm": foto.get("url_sm"),
            "url_avif": foto.get("url_avif"),
            "url_sm_avif": foto.get("url_sm_avif"),
            "w": foto.get("w"),
            "h": foto.get("h"),
        })
    return media


def _trabajo_links(row) -> list:
    """Lee los links de un trabajo: links_json, con fallback a las columnas
    sueltas legacy (youtube_url/instagram_reel_url) para filas no migradas.

    ⏰ LEGACY: el fallback a youtube_url/instagram_reel_url/thumbnail_url (acá +
    en el UPDATE que las vacía) se remueve cuando todos los trabajos existentes
    pasaron por links_json (editar y guardar cada uno migra on-write). Una vez
    que no quede ninguna fila con esas columnas pobladas, dropear las 3 columnas
    y este bloque."""
    links = _parse_json_field(row["links_json"]) or []
    if links:
        return links
    legacy: list = []
    if row["youtube_url"]:
        legacy.append({
            "tipo": "youtube", "url": row["youtube_url"],
            "thumbnail_url": row["thumbnail_url"],
        })
    if row["instagram_reel_url"]:
        legacy.append({
            "tipo": "instagram", "url": row["instagram_reel_url"],
            "thumbnail_url": row["thumbnail_url"],
        })
    return legacy


def _clean_categorias(cats: list | None) -> list:
    """Normaliza tags: trim, descarta vacíos, deduplica case-insensitive
    preservando el orden y la capitalización de la primera aparición."""
    out: list = []
    seen: set = set()
    for c in cats or []:
        c = (c or "").strip()
        if not c:
            continue
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _trabajo_categorias(row) -> list:
    """Lee los tags de un trabajo: categorias_json, con fallback legacy a la
    columna `categoria` (singular) para filas no migradas."""
    cats = _parse_json_field(row["categorias_json"]) or []
    if cats:
        return cats
    return [row["categoria"]] if row["categoria"] else []


def _get_trabajos(conn, solo_activos: bool = True) -> list:
    q = (
        "SELECT id, titulo, realizador, realizador_logo_url, "
        "realizador_instagram, realizador_web, categoria, categorias_json, descripcion, "
        "tipo, youtube_url, instagram_reel_url, thumbnail_url, "
        "links_json, fotos_json, orden, activo, created_at, updated_at "
        "FROM estudio_trabajos "
    )
    q += "WHERE activo = TRUE " if solo_activos else ""
    q += "ORDER BY orden, id"
    cur = conn.execute(q)
    rows = cur.fetchall()
    out = []
    for r in rows:
        links = _trabajo_links(r)
        fotos = _parse_json_field(r["fotos_json"]) or []
        cats = _trabajo_categorias(r)
        out.append({
            "id": r["id"],
            "titulo": r["titulo"],
            "realizador": r["realizador"],
            "realizador_logo_url": r["realizador_logo_url"],
            "realizador_instagram": r["realizador_instagram"],
            "realizador_web": r["realizador_web"],
            # `categoria` (singular) = primer tag, legacy; `categorias` = fuente única.
            "categoria": cats[0] if cats else "",
            "categorias": cats,
            "descripcion": r["descripcion"] or "",
            "tipo": r["tipo"],
            # Fuente única para el front: lista ordenada de medios (links + fotos).
            "media": _build_media(links, fotos),
            # Links crudos para que el admin pueda editarlos.
            "links": links,
            "fotos": fotos,
            "orden": r["orden"],
            "activo": bool(r["activo"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        })
    return out


@router.get("/estudio")
def get_estudio(response: Response):
    """Devuelve la configuración pública del estudio + fotos + pack curado + trabajos."""
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=30"
    with get_db() as conn:
        row = _get_estudio_row(conn)
        fotos = _get_fotos(conn)
        resp = _build_response(row, fotos)
        resp["pack_equipos"] = _pack_curado(conn)
        resp["promo"] = _promo_info(conn, row)
        resp["trabajos"] = _get_trabajos(conn, solo_activos=True)
        return resp


# ── Endpoints admin ──────────────────────────────────────────────────────────

@router.get("/admin/estudio")
def get_estudio_admin(request: Request):
    """Versión admin del GET /estudio — sin Cache-Control público (el endpoint
    público está cacheado 5min en Cloudflare, lo que causaba que subir/borrar
    fotos no se reflejara hasta que el caché expirara)."""
    require_admin(request)
    with get_db() as conn:
        row = _get_estudio_row(conn)
        fotos = _get_fotos(conn)
        resp = _build_response(row, fotos)
        resp["pack_equipos"] = _pack_curado(conn)
        resp["promo"] = _promo_info(conn, row)
        resp["trabajos"] = _get_trabajos(conn, solo_activos=False)
        return resp

class EstudioUpdate(BaseModel):
    nombre: Optional[str] = None
    tagline: Optional[str] = None
    descripcion: Optional[str] = None
    precio_hora: Optional[int] = None
    min_horas: Optional[int] = None
    open_hour: Optional[int] = None
    close_hour: Optional[int] = None
    buffer_horas: Optional[int] = None
    anticipacion_min_horas: Optional[int] = None
    pack_activo: Optional[bool] = None
    pack_nombre: Optional[str] = None
    pack_descripcion: Optional[str] = None
    pack_precio: Optional[int] = None
    features_json: Optional[str] = None
    faq_json: Optional[str] = None
    direccion: Optional[str] = None
    como_llegar: Optional[str] = None
    testimonios_json: Optional[str] = None
    # Link de Google Maps que pega el dueño (shortlink, URL larga o iframe HTML).
    # El backend lo parsea/resuelve y deriva `mapa_embed_url`.
    mapa_url: Optional[str] = None


@router.patch("/admin/estudio")
@limiter.limit(ADMIN_WRITE_LIMIT)
def patch_estudio(body: EstudioUpdate, request: Request):
    require_admin(request)

    updates = {k: v for k, v in body.dict().items() if v is not None}

    # Si el dueño cambió `mapa_url`, derivamos `mapa_embed_url`. Si lo dejó vacío,
    # vaciamos ambos.
    if "mapa_url" in updates:
        from services.maps_url import MapsParseError, parse_maps_input

        raw = (updates["mapa_url"] or "").strip()
        if not raw:
            updates["mapa_url"] = ""
            updates["mapa_embed_url"] = ""
        else:
            try:
                parsed = parse_maps_input(raw)
            except MapsParseError as e:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"No pude leer ese link de Google Maps: {e}. "
                        "Probá copiar 'Compartir → Insertar mapa' (código iframe) "
                        "o el link que da 'Compartir' en la app de Maps."
                    ),
                ) from e
            updates["mapa_url"] = parsed.raw_url
            updates["mapa_embed_url"] = parsed.embed_url

    with get_db() as conn:
        if updates:
            set_parts = [f"{k} = %s" for k in updates]
            set_parts.append("updated_at = %s")
            values = list(updates.values())
            values.append(datetime.now(tz=timezone.utc))
            values.append(1)
            conn.execute(
                f"UPDATE estudio SET {', '.join(set_parts)} WHERE id = %s",
                tuple(values),
            )
            conn.commit()
        row = _get_estudio_row(conn)
        fotos = _get_fotos(conn)
        return _build_response(row, fotos)


@router.post("/admin/estudio/upload-foto")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
async def upload_foto(request: Request):
    """Sube un archivo (multipart, campo 'file') a R2 y lo registra en estudio_fotos."""
    require_admin(request)

    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise HTTPException(400, "Falta el campo 'file' en el form-data")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Archivo vacío")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "Archivo muy grande (máx 20 MB)")

    with get_db() as conn:
        try:
            with media_http():
                asset = store_upload(
                    raw,
                    kind="estudio",
                    derive_specs=[
                        DISPLAY_KEEP_ASPECT,
                        DISPLAY_KEEP_ASPECT_SM,
                        DISPLAY_KEEP_ASPECT_AVIF,
                        DISPLAY_KEEP_ASPECT_SM_AVIF,
                    ],
                    conn=conn,
                )
            display = asset.variant("display")
            display_sm = asset.variant("display-sm")
            display_avif = asset.variant("display-avif")
            display_sm_avif = asset.variant("display-sm-avif")
            foto = _insert_foto(
                conn,
                url=display.url,
                path=display.key,
                media_id=asset.id,
                url_sm=display_sm.url if display_sm else None,
                url_avif=display_avif.url if display_avif else None,
                url_sm_avif=display_sm_avif.url if display_sm_avif else None,
            )
        except Exception:
            conn.rollback()
            raise

    return {
        "id": foto["id"],
        "public_url": display.url,
        "path": display.key,
        "size": display.bytes,
        "size_original": len(raw),
        "content_type": display.content_type,
        "width": display.width or None,
        "height": display.height or None,
    }


class UploadFromUrlBody(BaseModel):
    url: str


@router.post("/admin/estudio/upload-foto-from-url")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
def upload_foto_from_url(body: UploadFromUrlBody, request: Request):
    """Descarga URL externa, optimiza y sube a R2. SSRF-safe."""
    require_admin(request)

    url = (body.url or "").strip()
    if not url:
        raise HTTPException(400, "URL vacía")

    with media_http():
        _validate_ssrf_only(url)
        raw, _raw_ctype = _download_image_bytes(url)

    with get_db() as conn:
        try:
            with media_http():
                asset = store_upload(
                    raw,
                    kind="estudio",
                    derive_specs=[
                        DISPLAY_KEEP_ASPECT,
                        DISPLAY_KEEP_ASPECT_SM,
                        DISPLAY_KEEP_ASPECT_AVIF,
                        DISPLAY_KEEP_ASPECT_SM_AVIF,
                    ],
                    conn=conn,
                )
            display = asset.variant("display")
            display_sm = asset.variant("display-sm")
            display_avif = asset.variant("display-avif")
            display_sm_avif = asset.variant("display-sm-avif")
            foto = _insert_foto(
                conn,
                url=display.url,
                path=display.key,
                media_id=asset.id,
                url_sm=display_sm.url if display_sm else None,
                url_avif=display_avif.url if display_avif else None,
                url_sm_avif=display_sm_avif.url if display_sm_avif else None,
            )
        except Exception:
            conn.rollback()
            raise

    return {
        "id": foto["id"],
        "public_url": display.url,
        "path": display.key,
        "size": display.bytes,
        "size_original": len(raw),
        "content_type": display.content_type,
        "width": display.width or None,
        "height": display.height or None,
    }


@router.delete("/admin/estudio/fotos/{foto_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def delete_foto(foto_id: int, request: Request):
    require_admin(request)

    with get_db() as conn:
        cur = conn.execute(
            "SELECT path, media_id FROM estudio_fotos WHERE id = %s AND estudio_id = 1",
            (foto_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Foto no encontrada")
        path = row["path"]
        media_id = row["media_id"]

        # Recolectar keys R2 ANTES del DELETE (cascade borrará las filas de variants)
        r2_keys: list[str] = []
        if media_id:
            r2_keys = collect_asset_keys(conn, media_id)

        conn.execute("DELETE FROM estudio_fotos WHERE id = %s", (foto_id,))
        if media_id:
            conn.execute("DELETE FROM media_assets WHERE id = %s", (media_id,))
        conn.commit()

    # Best-effort R2 cleanup (después del commit — la DB es la fuente de verdad)
    if r2_keys:
        purge_r2(r2_keys)
    elif path:
        _delete_from_r2(path)  # fallback legacy (fotos sin media_id)

    return {"ok": True}


class FotoOrdenItem(BaseModel):
    id: int
    orden: int
    es_principal: bool


class ReorderBody(BaseModel):
    fotos: list[FotoOrdenItem]


@router.patch("/admin/estudio/fotos/orden")
@limiter.limit(ADMIN_WRITE_LIMIT)
def reorder_fotos(body: ReorderBody, request: Request):
    require_admin(request)

    with get_db() as conn:
        for f in body.fotos:
            # El array llega completo en cada drag — el guard evita reescribir
            # las fotos que no se movieron (antes: 1 foto movida = N updates).
            conn.execute(
                "UPDATE estudio_fotos SET orden = %s, es_principal = %s "
                "WHERE id = %s AND estudio_id = 1 "
                "AND (orden IS DISTINCT FROM %s OR es_principal IS DISTINCT FROM %s)",
                (f.orden, f.es_principal, f.id, f.orden, f.es_principal),
            )
        conn.commit()
        fotos = _get_fotos(conn)

    return {"fotos": fotos}


# ── Trabajos / producciones (galería "en acción") ────────────────────────────

def _trabajo_path(suffix: str) -> str:
    ts = int(time.time() * 1000)
    return f"estudio/trabajos/{ts}_{suffix}.webp"


@router.get("/admin/estudio/trabajos")
def admin_list_trabajos(request: Request):
    require_admin(request)
    with get_db() as conn:
        return {"trabajos": _get_trabajos(conn, solo_activos=False)}


@router.post("/admin/estudio/trabajos/fetch-meta")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
async def fetch_trabajo_meta(request: Request):
    """Dado un link de YouTube o Instagram, retorna metadata (titulo, realizador, thumbnail).
    YouTube usa oEmbed oficial. Instagram usa og:tags (best-effort)."""
    require_admin(request)
    import httpx
    body = await request.json()
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url requerida")

    # YouTube — oEmbed oficial, muy confiable
    if "youtu" in url:
        try:
            resp = httpx.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
                timeout=8.0,
            )
            if resp.status_code == 200:
                d = resp.json()
                return {
                    "titulo": d.get("title"),
                    "realizador": d.get("author_name"),
                    "thumbnail_url": d.get("thumbnail_url"),
                    "fuente": "youtube",
                }
        except Exception:
            pass

    # Instagram / cualquier otro — og:tags (best-effort)
    meta = _fetch_og_meta(url)
    if meta:
        # og:title de IG: "Nombre (@handle) • Fotos y videos de Instagram"
        raw_title = meta.get("title") or ""
        realizador = None
        m = _re.match(r"^(.+?)\s*[•·(@]", raw_title)
        if m:
            realizador = m.group(1).strip()
        return {
            "titulo": None,
            "realizador": realizador,
            "thumbnail_url": meta.get("image"),
            "descripcion": meta.get("description"),
            "fuente": "og",
        }

    return {"fuente": "desconocido"}


class TrabajoLinkInput(BaseModel):
    url: str
    # `tipo` lo decide el server (`_resolve_links`); se acepta pero se ignora.
    tipo: Optional[str] = None
    thumbnail_url: Optional[str] = None


class TrabajoCreate(BaseModel):
    titulo: str = ""
    realizador: str = ""
    realizador_instagram: Optional[str] = None
    realizador_web: Optional[str] = None
    categorias: list[str] = []
    descripcion: str = ""
    links: list[TrabajoLinkInput] = []
    activo: bool = True


@router.post("/admin/estudio/trabajos")
@limiter.limit(ADMIN_WRITE_LIMIT)
def admin_create_trabajo(body: TrabajoCreate, request: Request):
    require_admin(request)
    # Resolver links (baja + procesa thumbnails) ANTES de abrir la conexión del
    # insert — `_process_remote_thumbnail` usa su propia conexión corta.
    links = _resolve_links([l.dict() for l in body.links], existing=[])
    tipo = "video" if links else "fotos"
    cats = _clean_categorias(body.categorias)
    with get_db() as conn:
        cur = conn.execute(
            "SELECT COALESCE(MAX(orden), -1) + 1 AS next FROM estudio_trabajos"
        )
        orden = cur.fetchone()["next"]
        cur2 = conn.execute(
            "INSERT INTO estudio_trabajos "
            "(titulo, realizador, realizador_instagram, realizador_web, "
            "categoria, categorias_json, descripcion, tipo, links_json, orden, activo) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (body.titulo, body.realizador, body.realizador_instagram, body.realizador_web,
             cats[0] if cats else "", json.dumps(cats), body.descripcion, tipo,
             json.dumps(links), orden, body.activo),
        )
        new_id = cur2.fetchone()["id"]
        conn.commit()
        rows = _get_trabajos(conn, solo_activos=False)
        return next(r for r in rows if r["id"] == new_id)


class TrabajoUpdate(BaseModel):
    titulo: Optional[str] = None
    realizador: Optional[str] = None
    realizador_instagram: Optional[str] = None
    realizador_web: Optional[str] = None
    categorias: Optional[list[str]] = None
    descripcion: Optional[str] = None
    links: Optional[list[TrabajoLinkInput]] = None
    activo: Optional[bool] = None


class TrabajoOrdenItem(BaseModel):
    id: int
    orden: int


class TrabajoReorderBody(BaseModel):
    trabajos: list[TrabajoOrdenItem]


# OJO: la ruta literal `/orden` va ANTES que la dinámica `/{trabajo_id}` — si no,
# FastAPI matchea `PATCH /trabajos/orden` contra `{trabajo_id}` con "orden" y
# falla la conversión a int (422). Static-before-dynamic.
@router.patch("/admin/estudio/trabajos/orden")
@limiter.limit(ADMIN_WRITE_LIMIT)
def admin_reorder_trabajos(body: TrabajoReorderBody, request: Request):
    require_admin(request)
    with get_db() as conn:
        for t in body.trabajos:
            conn.execute(
                "UPDATE estudio_trabajos SET orden = %s WHERE id = %s",
                (t.orden, t.id),
            )
        conn.commit()
        return {"trabajos": _get_trabajos(conn, solo_activos=False)}


@router.patch("/admin/estudio/trabajos/{trabajo_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def admin_update_trabajo(trabajo_id: int, body: TrabajoUpdate, request: Request):
    require_admin(request)
    updates = {
        k: v for k, v in body.dict(exclude={"links", "categorias"}).items() if v is not None
    }
    # Tags: `categorias is not None` distingue "no tocar" de "vaciar". Escribe la
    # fuente única (categorias_json) + la columna legacy `categoria` (primer tag).
    if body.categorias is not None:
        cats = _clean_categorias(body.categorias)
        updates["categorias_json"] = json.dumps(cats)
        updates["categoria"] = cats[0] if cats else ""
    # Los links se manejan aparte: `links is not None` distingue "no tocar"
    # (None) de "vaciar" ([]). Se resuelven antes de abrir la conexión del UPDATE.
    if body.links is not None:
        with get_db() as conn:
            cur = conn.execute(
                "SELECT links_json, youtube_url, instagram_reel_url, thumbnail_url "
                "FROM estudio_trabajos WHERE id = %s",
                (trabajo_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Trabajo no encontrado")
            existing = _trabajo_links(row)
        resolved = _resolve_links([l.dict() for l in body.links], existing=existing)
        updates["links_json"] = json.dumps(resolved)
        updates["tipo"] = "video" if resolved else "fotos"
        # Migración on-write: las columnas legacy quedan vacías una vez que la
        # fila pasó por links_json.
        updates["youtube_url"] = None
        updates["instagram_reel_url"] = None
        updates["thumbnail_url"] = None
    if not updates:
        raise HTTPException(400, "Nada que actualizar")
    with get_db() as conn:
        set_parts = [f"{k} = %s" for k in updates]
        set_parts.append("updated_at = %s")
        vals = list(updates.values()) + [datetime.now(tz=timezone.utc), trabajo_id]
        conn.execute(
            f"UPDATE estudio_trabajos SET {', '.join(set_parts)} WHERE id = %s",
            vals,
        )
        conn.commit()
        rows = _get_trabajos(conn, solo_activos=False)
        match = next((r for r in rows if r["id"] == trabajo_id), None)
        if not match:
            raise HTTPException(404, "Trabajo no encontrado")
        return match


@router.delete("/admin/estudio/trabajos/{trabajo_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def admin_delete_trabajo(trabajo_id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        conn.execute("DELETE FROM estudio_trabajos WHERE id = %s", (trabajo_id,))
        conn.commit()
    return {"ok": True}


@router.post("/admin/estudio/trabajos/{trabajo_id}/upload-foto")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
async def admin_upload_trabajo_foto(
    trabajo_id: int, request: Request, background_tasks: BackgroundTasks
):
    require_admin(request)
    path = _trabajo_path(f"foto_{trabajo_id}")
    result = await media_http(
        request,
        background_tasks,
        path=path,
        presets=[
            DISPLAY_KEEP_ASPECT,
            DISPLAY_KEEP_ASPECT_SM,
            DISPLAY_KEEP_ASPECT_AVIF,
            DISPLAY_KEEP_ASPECT_SM_AVIF,
        ],
    )
    nueva_foto = {
        "url": result[DISPLAY_KEEP_ASPECT]["url"],
        "url_sm": result[DISPLAY_KEEP_ASPECT_SM]["url"],
        "url_avif": result[DISPLAY_KEEP_ASPECT_AVIF]["url"],
        "url_sm_avif": result[DISPLAY_KEEP_ASPECT_SM_AVIF]["url"],
        "path": path,
    }
    with get_db() as conn:
        cur = conn.execute(
            "SELECT fotos_json FROM estudio_trabajos WHERE id = %s", (trabajo_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Trabajo no encontrado")
        fotos = _parse_json_field(row["fotos_json"]) or []
        fotos.append(nueva_foto)
        conn.execute(
            "UPDATE estudio_trabajos SET fotos_json = %s, updated_at = %s WHERE id = %s",
            (json.dumps(fotos), datetime.now(tz=timezone.utc), trabajo_id),
        )
        conn.commit()
        rows = _get_trabajos(conn, solo_activos=False)
        return next(r for r in rows if r["id"] == trabajo_id)


@router.delete("/admin/estudio/trabajos/{trabajo_id}/fotos/{foto_idx}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def admin_delete_trabajo_foto(trabajo_id: int, foto_idx: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        cur = conn.execute(
            "SELECT fotos_json FROM estudio_trabajos WHERE id = %s", (trabajo_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Trabajo no encontrado")
        fotos = _parse_json_field(row["fotos_json"]) or []
        if foto_idx < 0 or foto_idx >= len(fotos):
            raise HTTPException(400, f"Índice de foto inválido: {foto_idx}")
        fotos.pop(foto_idx)
        conn.execute(
            "UPDATE estudio_trabajos SET fotos_json = %s, updated_at = %s WHERE id = %s",
            (json.dumps(fotos), datetime.now(tz=timezone.utc), trabajo_id),
        )
        conn.commit()
        rows = _get_trabajos(conn, solo_activos=False)
        return next(r for r in rows if r["id"] == trabajo_id)


@router.post("/admin/estudio/trabajos/{trabajo_id}/upload-logo")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
async def admin_upload_trabajo_logo(
    trabajo_id: int, request: Request, background_tasks: BackgroundTasks
):
    require_admin(request)
    path = _trabajo_path(f"logo_{trabajo_id}")
    result = await media_http(
        request,
        background_tasks,
        path=path,
        presets=[DISPLAY_KEEP_ASPECT, DISPLAY_KEEP_ASPECT_SM],
    )
    logo_url = result[DISPLAY_KEEP_ASPECT]["url"]
    with get_db() as conn:
        conn.execute(
            "UPDATE estudio_trabajos SET realizador_logo_url = %s, updated_at = %s WHERE id = %s",
            (logo_url, datetime.now(tz=timezone.utc), trabajo_id),
        )
        conn.commit()
        rows = _get_trabajos(conn, solo_activos=False)
        match = next((r for r in rows if r["id"] == trabajo_id), None)
        if not match:
            raise HTTPException(404, "Trabajo no encontrado")
        return match


# ── Reserva del estudio por horas (E2 / E2.1) ─────────────────────────────────
#
# REGLA SAGRADA: el motor de reservas (_check_stock / get_disponibilidad /
# _rango_con_buffer) NO se modifica ni se reusa para el espacio. La reserva del
# estudio es un pedido normal (tipo='estudio') con UN ítem: el equipo centinela
# (estudio.equipo_id, cantidad=1, recurso único).
#
# E2.1 — el solapamiento del centinela se chequea con una query DEDICADA (no vía
# _check_stock), para que el espacio use SOLO su buffer propio (estudio.buffer_horas)
# y nunca el buffer global de equipos (buffer_horas_alquiler, que es el prep de
# equipos del pack — eso es E3). Al ser stock=1, un overlap directo alcanza.


def _franja_estudio(estudio, fecha: str, start: str, horas: int) -> tuple[datetime, datetime]:
    """Valida y arma la franja [fecha_desde, fecha_hasta] de una reserva.

    - `horas` debe ser >= min_horas del estudio.
    - La franja [start, start+horas] debe caer dentro de [open_hour, close_hour].

    Devuelve (fecha_desde, fecha_hasta) como datetimes. Lanza HTTPException 400
    si algo no valida.
    """
    min_horas = estudio["min_horas"]
    if horas < min_horas:
        raise HTTPException(400, f"El mínimo de reserva es de {min_horas} horas")
    try:
        hh, mm = (int(x) for x in start.split(":"))
        dia = datetime.strptime(fecha, "%Y-%m-%d")
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(400, "Fecha u hora inválida (esperado fecha=YYYY-MM-DD, start=HH:MM)")

    inicio_min = hh * 60 + mm
    fin_min = inicio_min + horas * 60
    open_h, close_h = estudio["open_hour"], estudio["close_hour"]
    if inicio_min < open_h * 60 or fin_min > close_h * 60:
        raise HTTPException(
            400,
            f"La franja debe estar entre las {open_h:02d}:00 y las {close_h:02d}:00",
        )

    fecha_desde = dia.replace(hour=hh, minute=mm, second=0, microsecond=0)
    fecha_hasta = fecha_desde + timedelta(hours=horas)
    return fecha_desde, fecha_hasta


def _viola_anticipacion(estudio, fecha_desde) -> bool:
    """¿La franja arranca antes de la anticipación mínima exigida por el estudio?
    Solo aplica al estudio (no a equipos). anticipacion_min_horas <= 0 → sin tope."""
    horas = estudio["anticipacion_min_horas"] or 0
    if horas <= 0:
        return False
    return fecha_desde < now_ar() + timedelta(hours=horas)


def _centinela_libre(conn, equipo_id: int, fecha_desde, fecha_hasta,
                     buffer_horas: int, exclude_pedido_id: int | None = None,
                     exclude_slot_id: int | None = None) -> bool:
    """True si el centinela del estudio está libre en [fecha_desde, fecha_hasta],
    aplicando SOLO el buffer propio del estudio (expande el rango por
    `buffer_horas` a cada lado). Query dedicada — NO usa el motor sagrado, así
    el buffer global de equipos no interviene.

    El centinela es un recurso único (stock=1): cualquier reserva activa que se
    pise con la franja expandida (half-open: fecha_desde < hi AND fecha_hasta > lo)
    significa ocupado. `exclude_pedido_id` excluye el propio pedido en el POST.

    `exclude_slot_id`: los pedidos `estudio_fijo` llevan su propio ítem
    centinela (Fase 2, ítems veraces) — sin esto, revalidar la disponibilidad
    de un slot fijo (`actualizar_slot`, ANTES de regenerar sus pedidos)
    chocaría contra los pedidos YA EXISTENTES del propio slot para ese mismo
    día/hora, bloqueándose a sí mismo.
    """
    lo = fecha_desde - timedelta(hours=max(0, buffer_horas or 0))
    hi = fecha_hasta + timedelta(hours=max(0, buffer_horas or 0))
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS cnt
        FROM alquiler_items pi
        JOIN alquileres p ON p.id = pi.pedido_id
        WHERE pi.equipo_id = %s
          AND p.estado IN {ESTADOS_RESERVADO}
          AND (%s IS NULL OR p.id != %s)
          AND (%s IS NULL OR p.estudio_slot_id IS DISTINCT FROM %s)
          AND p.fecha_desde < %s
          AND p.fecha_hasta > %s
        """,
        (equipo_id, exclude_pedido_id, exclude_pedido_id,
         exclude_slot_id, exclude_slot_id, hi, lo),
    ).fetchone()
    return (row["cnt"] or 0) == 0


# ── Pack curado (v2-C) ──────────────────────────────────────────────────────────
#
# El pack es una lista CURADA de equipos elegidos a mano por el admin (tabla
# `estudio_pack_equipos`), no "todo lo de unas categorías". De esos equipos, en
# cada franja se ofrecen SOLO los DISPONIBLES (best-effort: un ocupado no se
# ofrece, pero tampoco bloquea la reserva). Son equipos reales → se rigen por el
# motor sagrado (get_disponibilidad / _check_stock con el buffer GLOBAL de
# equipos). Esto es distinto del espacio (centinela), que usa su propio buffer vía
# _centinela_libre. NO mezclar: espacio = query dedicada; pack = motor.


def _pack_equipo_ids(conn) -> list[int]:
    """IDs de los equipos curados del pack (tabla `estudio_pack_equipos`), en su
    orden. Excluye el centinela y los eliminados (por si quedó alguno colgado)."""
    rows = conn.execute(
        """
        SELECT e.id
        FROM estudio_pack_equipos pe
        JOIN equipos e ON e.id = pe.equipo_id
        WHERE pe.estudio_id = 1
          AND e.es_recurso_interno = FALSE
          AND e.eliminado_at IS NULL
        ORDER BY pe.orden, pe.id
        """,
    ).fetchall()
    return [r["id"] for r in rows]


def _pack_disponible(conn, fecha_desde, fecha_hasta, exclude_pedido_id: int | None = None) -> list[dict]:
    """Equipos curados del pack con >= 1 unidad disponible en la franja. La
    disponibilidad sale del motor sagrado (get_disponibilidad aplica el buffer
    global de equipos), así que lo ya reservado no aparece. Devuelve
    [{id, nombre, marca, foto_url, cantidad}]."""
    pack_ids = _pack_equipo_ids(conn)
    if not pack_ids:
        return []
    disp = get_disponibilidad(
        fecha_desde.isoformat(), fecha_hasta.isoformat(), exclude_pedido_id
    )
    libres = {eid: disp.get(str(eid), 0) for eid in pack_ids if disp.get(str(eid), 0) >= 1}
    if not libres:
        return []
    rows = conn.execute(
        f"""
        SELECT e.id, e.nombre, e.foto_url, {MARCA_SUBQUERY}
        FROM equipos e
        WHERE e.id = ANY(%s)
        ORDER BY e.nombre
        """,
        (list(libres.keys()),),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "nombre": r["nombre"],
            "marca": r["marca"],
            "foto_url": r["foto_url"],
            "cantidad": libres[r["id"]],
        }
        for r in rows
    ]


def _pack_curado(conn) -> list[dict]:
    """Lista curada del pack (en orden), con nombre/marca/foto y `cantidad` =
    stock total del equipo en el Rental (lo que muestra la ficha pública como
    "5× C-stand"). Sin filtrar por disponibilidad de franja (eso es del público
    en `_pack_disponible`). Sirve al admin y a la ficha pública."""
    rows = conn.execute(
        f"""
        SELECT pe.equipo_id AS id, pe.orden, e.nombre, e.foto_url, e.cantidad,
               {MARCA_SUBQUERY}
        FROM estudio_pack_equipos pe
        JOIN equipos e ON e.id = pe.equipo_id
        WHERE pe.estudio_id = 1
          AND e.eliminado_at IS NULL
        ORDER BY pe.orden, pe.id
        """,
    ).fetchall()
    return [
        {
            "id": r["id"],
            "nombre": r["nombre"],
            "marca": r["marca"],
            "foto_url": r["foto_url"],
            "cantidad": r["cantidad"],
            "orden": r["orden"],
        }
        for r in rows
    ]


# ── Admin: CRUD del pack curado (v2-C) ──────────────────────────────────────────

@router.get("/admin/estudio/pack")
def listar_pack(request: Request):
    require_admin(request)
    with get_db() as conn:
        return {"pack": _pack_curado(conn)}


class PackEquipoCreate(BaseModel):
    equipo_id: int


@router.post("/admin/estudio/pack", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
def agregar_pack_equipo(body: PackEquipoCreate, request: Request):
    require_admin(request)
    with get_db() as conn:
        try:
            eq = conn.execute(
                "SELECT id, es_recurso_interno, eliminado_at FROM equipos WHERE id = %s",
                (body.equipo_id,),
            ).fetchone()
            if not eq or eq["eliminado_at"] is not None:
                raise HTTPException(404, "Equipo no encontrado")
            if eq["es_recurso_interno"]:
                raise HTTPException(400, "No se puede agregar un recurso interno al pack")
            orden = conn.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 AS next FROM estudio_pack_equipos WHERE estudio_id = 1"
            ).fetchone()["next"]
            conn.execute(
                "INSERT INTO estudio_pack_equipos (estudio_id, equipo_id, orden) "
                "VALUES (1, %s, %s) ON CONFLICT (estudio_id, equipo_id) DO NOTHING",
                (body.equipo_id, orden),
            )
            conn.commit()
            return {"pack": _pack_curado(conn)}
        except Exception:
            conn.rollback()
            raise


@router.delete("/admin/estudio/pack/{equipo_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def quitar_pack_equipo(equipo_id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        try:
            conn.execute(
                "DELETE FROM estudio_pack_equipos WHERE estudio_id = 1 AND equipo_id = %s",
                (equipo_id,),
            )
            conn.commit()
            return {"pack": _pack_curado(conn)}
        except Exception:
            conn.rollback()
            raise


# ── Admin: promo combo (#1283 Fase 5 — reemplaza al pack) ───────────────────────


class PromoCrearBody(BaseModel):
    nombre: Optional[str] = None
    precio_objetivo: Optional[int] = None


@router.post("/admin/estudio/promo/crear-desde-pack", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
def crear_promo_desde_pack(body: PromoCrearBody, request: Request):
    """Crea la promo (combo) del Estudio a partir del pack curado actual
    (`estudio_pack_equipos`): un equipo real `tipo='combo'`, `dueno='Rambla'`
    (no los dueños tradicionales — es plata de Rambla, no de terceros),
    `visible_catalogo=0` (oculto del catálogo público, solo se ofrece desde el
    Estudio/back-office). El precio objetivo (default = `pack_precio` actual)
    se clava vía un descuento % uniforme en sus componentes
    (`resolver_descuento_uniforme`, misma pieza que el endpoint de Equipos).

    Reemplaza al pack: apaga `pack_activo` y setea `estudio.promo_combo_id`.
    Una sola transacción. El pack/sus datos NO se borran (⏰ LEGACY hasta la
    Fase 8) — el combo creado es un equipo normal, editable después desde
    Equipos como cualquier otro combo."""
    require_admin(request)
    with get_db() as conn:
        try:
            estudio = _get_estudio_row(conn)
            if estudio["promo_combo_id"]:
                raise HTTPException(
                    409, "Ya existe una promo — editala desde Equipos o borrala primero"
                )
            pack_ids = _pack_equipo_ids(conn)
            if not pack_ids:
                raise HTTPException(400, "El pack curado está vacío — agregá equipos primero")

            nombre = (body.nombre or estudio["pack_nombre"] or "Promo de equipos").strip()
            precio_objetivo = (
                body.precio_objetivo if body.precio_objetivo is not None
                else (estudio["pack_precio"] or 0)
            )
            if precio_objetivo <= 0:
                raise HTTPException(400, "El precio objetivo tiene que ser mayor a 0")

            combo_id = conn.insert_returning(
                """
                INSERT INTO equipos (nombre, tipo, cantidad, dueno, visible_catalogo,
                                     es_recurso_interno, estado)
                VALUES (%s,'combo',%s,'Rambla',0,FALSE,'operativo')
                """,
                (nombre, _COMBO_STOCK_SENTINEL),
            )
            for eid in pack_ids:
                conn.execute(
                    "INSERT INTO kit_componentes (equipo_id, componente_id, cantidad, esencial) "
                    "VALUES (%s,%s,1,TRUE)",
                    (combo_id, eid),
                )
            rows = conn.execute(
                "SELECT e.precio_jornada, kc.cantidad "
                "FROM kit_componentes kc JOIN equipos e ON e.id = kc.componente_id "
                "WHERE kc.equipo_id = %s AND e.eliminado_at IS NULL",
                (combo_id,),
            ).fetchall()
            try:
                descuento = resolver_descuento_uniforme(rows, precio_objetivo)
            except ValueError as e:
                raise HTTPException(400, str(e))
            conn.execute(
                "UPDATE kit_componentes SET descuento_pct = %s WHERE equipo_id = %s",
                (descuento, combo_id),
            )
            conn.execute(
                "UPDATE estudio SET promo_combo_id = %s, pack_activo = FALSE WHERE id = 1",
                (combo_id,),
            )
            conn.commit()
            row = _get_estudio_row(conn)
            resp = _build_response(row, _get_fotos(conn))
            resp["promo"] = _promo_info(conn, row)
            return resp
        except Exception:
            conn.rollback()
            raise


# ── Slots fijos recurrentes mensuales (E4) ─────────────────────────────────────
#
# Un slot fijo (ej. "miércoles 8-20 Filmar $X jun-dic") cumple DOS roles:
#   (a) bloquea su franja para el público mientras el rango de meses esté activo
#       → regla propia (`_slot_bloqueante`), NO usa el motor ni el centinela.
#   (b) genera un pedido por mes (tipo='estudio_fijo') para estadísticas + pagos
#       → registro de facturación, SIN ítem del centinela para no doble-bloquear
#       (el bloqueo ya lo hace (a)).


def _slot_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "cliente": row["cliente"],
        "dia_semana": row["dia_semana"],
        "hora_desde": row["hora_desde"],
        "hora_hasta": row["hora_hasta"],
        "valor_mensual": row["valor_mensual"],
        "mes_desde": row["mes_desde"],
        "mes_hasta": row["mes_hasta"],
        "activo": bool(row["activo"]),
    }


def _mes_actual_ar() -> str:
    n = now_ar()
    return f"{n.year:04d}-{n.month:02d}"


def _iter_meses(mes_desde: str, mes_hasta: str):
    """Itera (year, month) inclusive entre dos 'YYYY-MM'."""
    y0, m0 = int(mes_desde[:4]), int(mes_desde[5:7])
    y1, m1 = int(mes_hasta[:4]), int(mes_hasta[5:7])
    cur = (y0, m0)
    while cur <= (y1, m1):
        yield cur
        y, m = cur
        cur = (y + 1, 1) if m == 12 else (y, m + 1)


def _primer_dia_semana(year: int, month: int, dia_semana: int) -> datetime:
    """Primera fecha del mes cuyo weekday() == dia_semana (0=Lun..6=Dom)."""
    base = datetime(year, month, 1)
    offset = (dia_semana - base.weekday()) % 7
    return base + timedelta(days=offset)


# Namespace del advisory lock para operaciones que validan+escriben en el estudio
# (slots y talleres). Privado de este flujo; evita colisión con el NS de pedidos.
_ADVISORY_NS_ESTUDIO = 5390413


def _sesiones_de_slot(slot: dict) -> list:
    """Genera todas las fechas con `dia_semana` en el rango de meses del slot,
    como lista de dicts {fecha, hora_inicio_min, hora_fin_min}. Usada para validar
    disponibilidad antes de crear o editar un slot.

    OJO unidades: `estudio_slots_fijos.hora_desde/hasta` siguen en HORAS enteras
    (su tabla no cambió); las sesiones se emiten en MINUTOS (contrato de
    `verificar_sesiones_disponibles` desde Escuela v2 F1) → conversión ×60 acá."""
    y0, m0 = int(slot["mes_desde"][:4]), int(slot["mes_desde"][5:7])
    y1, m1 = int(slot["mes_hasta"][:4]), int(slot["mes_hasta"][5:7])
    import calendar as _cal
    sesiones = []
    cur = (y0, m0)
    while cur <= (y1, m1):
        y, m = cur
        _, last_day = _cal.monthrange(y, m)
        d = _primer_dia_semana(y, m, slot["dia_semana"]).date()
        while d.month == m:
            sesiones.append({
                "fecha": d,
                "hora_inicio_min": slot["hora_desde"] * 60,
                "hora_fin_min": slot["hora_hasta"] * 60,
            })
            d = d + timedelta(weeks=1)
        cur = (y + 1, 1) if m == 12 else (y, m + 1)
    return sesiones


def _slot_bloqueante(conn, fecha_desde, fecha_hasta,
                     exclude_slot_id: Optional[int] = None) -> Optional[str]:
    """Si la franja cae en un slot fijo activo (mismo día de semana, dentro del
    rango de meses y con solape horario), devuelve el `cliente` del slot. Regla
    del slot — NO usa el motor de reservas."""
    dia = fecha_desde.weekday()
    mes = f"{fecha_desde.year:04d}-{fecha_desde.month:02d}"
    # Minutos relativos al día de inicio (no `.hour`): una franja que cierra a
    # medianoche tiene fecha_hasta = 00:00 del día siguiente, y `.hour` daría 0,
    # rompiendo el solape. La resta sí da 1440.
    dia_base = fecha_desde.replace(hour=0, minute=0, second=0, microsecond=0)
    ini = int((fecha_desde - dia_base).total_seconds() // 60)
    fin = int((fecha_hasta - dia_base).total_seconds() // 60)
    rows = conn.execute(
        """
        SELECT id, cliente, hora_desde, hora_hasta
        FROM estudio_slots_fijos
        WHERE activo = TRUE AND dia_semana = %s
          AND mes_desde <= %s AND mes_hasta >= %s
          AND (%s IS NULL OR id != %s)
        """,
        (dia, mes, mes, exclude_slot_id, exclude_slot_id),
    ).fetchall()
    for r in rows:
        if ini < r["hora_hasta"] * 60 and fin > r["hora_desde"] * 60:
            return r["cliente"]
    return None


def _taller_bloqueante(conn, fecha_desde, fecha_hasta,
                       exclude_taller_id: Optional[int] = None) -> Optional[str]:
    """Si la franja solapa una clase de un taller PUBLICADO (concepto Y edición
    activos), devuelve el nombre del taller. Compara contra la fecha literal — no
    deriva weekday ni rango. `hora_*_min` ya está en minutos desde medianoche
    (Escuela v2 F1) — misma unidad que `ini`/`fin`, sin conversión.
    Consulta clases_taller (modelo vigente; taller_sesiones era el modelo anterior).

    `AND e.activo`: fix del bloqueo fantasma (Escuela v2 F1, decisión del dueño) —
    una edición desactivada/borrador NO bloquea el estudio; antes solo se miraba
    `t.activo` (concepto) y una edición dada de baja seguía reservando la franja."""
    dia = fecha_desde.date()
    dia_base = fecha_desde.replace(hour=0, minute=0, second=0, microsecond=0)
    ini = int((fecha_desde - dia_base).total_seconds() // 60)
    fin = int((fecha_hasta - dia_base).total_seconds() // 60)
    rows = conn.execute(
        """
        SELECT t.nombre, c.hora_inicio_min, c.hora_fin_min
        FROM clases_taller c
        JOIN ediciones_taller e ON e.id = c.edicion_id
        JOIN talleres t ON t.id = e.taller_id
        WHERE t.activo = TRUE
          AND e.activo = TRUE
          AND c.fecha = %s
          AND (%s IS NULL OR t.id != %s)
        """,
        (dia, exclude_taller_id, exclude_taller_id),
    ).fetchall()
    for r in rows:
        if ini < r["hora_fin_min"] and fin > r["hora_inicio_min"]:
            return r["nombre"]
    return None


def _estudio_disponible(conn, estudio, fecha_desde, fecha_hasta,
                        exclude_pedido_id: Optional[int] = None,
                        exclude_taller_id: Optional[int] = None,
                        exclude_slot_id: Optional[int] = None) -> tuple:
    """Engine de lectura unificada. Orden: slot → taller → centinela.
    Devuelve (True, None) si libre; (False, motivo) si ocupado."""
    s = _slot_bloqueante(conn, fecha_desde, fecha_hasta, exclude_slot_id=exclude_slot_id)
    if s:
        return False, f"slot fijo «{s}»"
    t = _taller_bloqueante(conn, fecha_desde, fecha_hasta, exclude_taller_id=exclude_taller_id)
    if t:
        return False, f"taller «{t}»"
    if not _centinela_libre(conn, estudio["equipo_id"], fecha_desde, fecha_hasta,
                            estudio["buffer_horas"], exclude_pedido_id=exclude_pedido_id,
                            exclude_slot_id=exclude_slot_id):
        return False, "ya reservado en esa franja"
    return True, None


def revalidar_disponibilidad_estudio(conn, pedido) -> list[str]:
    """Re-valida un pedido del Estudio YA EXISTENTE (turno o slot fijo) al
    transicionar de estado — la usa `transiciones.cambiar_estado` EN VEZ DEL
    `_check_stock` genérico (bug encontrado auditando la economía del
    Estudio: ese gate leería el ítem centinela como un equipo más y lo
    validaría con el buffer GLOBAL, no con el buffer propio del espacio).

    ESPACIO (centinela): por `_estudio_disponible` (buffer propio), excluyendo
    el propio pedido y —si es un `estudio_fijo`— su propio slot (para no
    chocar contra sí mismo). EQUIPOS reales (pack/sueltos, si los hay): por el
    motor sagrado `validar_stock_hipotetico`, excluyendo el centinela (que no
    es un equipo real).

    `pedido` es la fila de `alquileres` (dict o `PGRow`) ya leída `FOR UPDATE`
    por el caller — esta función no relockea nada."""
    estudio = _get_estudio_row(conn)
    errores: list[str] = []

    fd, fh = to_datetime(pedido["fecha_desde"]), to_datetime(pedido["fecha_hasta"])
    libre, motivo = _estudio_disponible(
        conn, estudio, fd, fh,
        exclude_pedido_id=pedido["id"],
        exclude_slot_id=pedido["estudio_slot_id"],
    )
    if not libre:
        errores.append(f"El espacio no está disponible: {motivo}")

    items = conn.execute(
        "SELECT equipo_id, cantidad FROM alquiler_items "
        "WHERE pedido_id=%s AND equipo_id IS NOT NULL AND equipo_id != %s",
        (pedido["id"], estudio["equipo_id"]),
    ).fetchall()
    if items:
        _Item = namedtuple("_Item", ["equipo_id", "cantidad"])
        sin_stock = validar_stock_hipotetico(
            conn, pedido["id"], pedido["fecha_desde"], pedido["fecha_hasta"],
            [_Item(it["equipo_id"], it["cantidad"]) for it in items],
        )
        errores.extend(f"Sin stock suficiente: {s}" for s in sin_stock)

    return errores


def verificar_sesiones_disponibles(conn, estudio, sesiones: list,
                                   exclude_pedido_id: Optional[int] = None,
                                   exclude_taller_id: Optional[int] = None,
                                   exclude_slot_id: Optional[int] = None) -> None:
    """Valida cada sesión futura contra _estudio_disponible. Lanza 409 al primer
    conflicto. Usada por talleres (clases explícitas) y slots (sesiones generadas).
    Contrato: sesiones = [{fecha, hora_inicio_min, hora_fin_min}] en MINUTOS desde
    medianoche (Escuela v2 F1) — timedelta(minutes) representa 1440 = medianoche
    sin el caso especial que `datetime.time` no banca (`replace(hour=24)` rompe)."""
    hoy = now_ar().date()
    for s in sesiones:
        if s["fecha"] < hoy:
            continue
        base = datetime(s["fecha"].year, s["fecha"].month, s["fecha"].day)
        desde = base + timedelta(minutes=s["hora_inicio_min"])
        hasta = base + timedelta(minutes=s["hora_fin_min"])
        libre, motivo = _estudio_disponible(
            conn, estudio, desde, hasta,
            exclude_pedido_id=exclude_pedido_id,
            exclude_taller_id=exclude_taller_id,
            exclude_slot_id=exclude_slot_id,
        )
        if not libre:
            raise HTTPException(
                409,
                f"El estudio no está libre el "
                f"{s['fecha'].strftime('%d/%m/%Y')} de {fmt_hhmm(s['hora_inicio_min'])} "
                f"a {fmt_hhmm(s['hora_fin_min'])} hs: {motivo}",
            )


def _regenerar_pedidos_slot(conn, estudio, slot: dict) -> None:
    """(Re)genera un pedido `estudio_fijo` por mes del rango del slot. Preserva
    los pasados y los que ya tienen pagos; borra y recrea los futuros impagos.
    Fecha representativa = primer `dia_semana` del mes a [hora_desde, hora_hasta].

    Cada pedido lleva su ítem centinela con el monto real (Fase 2, ítems
    veraces: `cobro_modo='fijo'`, `precio_jornada=subtotal=valor_mensual`) —
    antes el pedido no tenía NINGÚN ítem y quedaba invisible para la
    liquidación (`filas_atribucion` hace INNER JOIN a `alquiler_items`), sin
    atribuirse a nadie pese a cobrarse. El BLOQUEO del slot lo sigue haciendo
    `_slot_bloqueante` (la regla, no el ítem) — el ítem acá es solo para que
    la plata se vea y se atribuya (dueño del centinela = 'Estudio')."""
    slot_id = slot["id"]
    mes_actual = _mes_actual_ar()
    existentes = conn.execute(
        "SELECT id, fecha_desde, monto_pagado FROM alquileres WHERE estudio_slot_id = %s",
        (slot_id,),
    ).fetchall()

    conservados: set[str] = set()
    for e in existentes:
        fd = to_datetime(e["fecha_desde"])
        mes_e = f"{fd.year:04d}-{fd.month:02d}"
        if mes_e < mes_actual or (e["monto_pagado"] or 0) > 0:
            conservados.add(mes_e)  # pasado o con pagos → intocable
        else:
            conn.execute("DELETE FROM alquileres WHERE id = %s", (e["id"],))

    if not slot["activo"]:
        return

    for (y, m) in _iter_meses(slot["mes_desde"], slot["mes_hasta"]):
        mes = f"{y:04d}-{m:02d}"
        if mes < mes_actual or mes in conservados:
            continue
        rep = _primer_dia_semana(y, m, slot["dia_semana"])
        # `timedelta` desde medianoche (no `.replace(hour=...)`): hora_hasta=24
        # (cierre a medianoche, válido) caería en las 00:00 del día siguiente sin
        # romper, mientras que replace(hour=24) lanza ValueError.
        base = rep.replace(hour=0, minute=0, second=0, microsecond=0)
        fd = base + timedelta(hours=slot["hora_desde"])
        fh = base + timedelta(hours=slot["hora_hasta"])
        num = _next_numero_pedido(conn)
        pedido_id = conn.insert_returning(
            """
            INSERT INTO alquileres (cliente_nombre, fecha_desde, fecha_hasta, monto_total,
                                    estado, fuente, tipo, numero_pedido, estudio_slot_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (slot["cliente"], fd, fh, slot["valor_mensual"], "confirmado",
             "estudio", "estudio_fijo", num, slot_id),
        )
        conn.execute(
            """
            INSERT INTO alquiler_items
                (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
            VALUES (%s,%s,1,%s,%s,'fijo')
            """,
            (pedido_id, estudio["equipo_id"], slot["valor_mensual"], slot["valor_mensual"]),
        )


def _borrar_pedidos_futuros_impagos(conn, slot_id: int) -> None:
    """Borra los pedidos del slot que son de un mes actual-o-futuro y no tienen
    pagos. Los pasados/pagados quedan (su estudio_slot_id se va a NULL al borrar
    el slot, vía FK ON DELETE SET NULL)."""
    mes_actual = _mes_actual_ar()
    rows = conn.execute(
        "SELECT id, fecha_desde, monto_pagado FROM alquileres WHERE estudio_slot_id = %s",
        (slot_id,),
    ).fetchall()
    for e in rows:
        fd = to_datetime(e["fecha_desde"])
        mes_e = f"{fd.year:04d}-{fd.month:02d}"
        if mes_e >= mes_actual and (e["monto_pagado"] or 0) == 0:
            conn.execute("DELETE FROM alquileres WHERE id = %s", (e["id"],))


@router.get("/estudio/disponibilidad")
def estudio_disponibilidad(
    fecha: str = Query(..., description="YYYY-MM-DD"),
    start: str = Query(..., description="HH:MM"),
    horas: int = Query(..., description="Duración en horas (>= min_horas)"),
):
    """¿El estudio está libre en [fecha start, +horas]? Aplica el buffer propio
    del estudio (no el global) y la anticipación mínima. Devuelve {libre, motivo}."""
    with get_db() as conn:
        estudio = _get_estudio_row(conn)

        if not estudio["equipo_id"]:
            raise HTTPException(409, "El estudio todavía no tiene un recurso asociado")

        fecha_desde, fecha_hasta = _franja_estudio(estudio, fecha, start, horas)

        if _viola_anticipacion(estudio, fecha_desde):
            return {
                "libre": False,
                "motivo": f"Necesitás reservar con al menos {estudio['anticipacion_min_horas']} h de anticipación",
                "pack": [],
                "promo": None,
            }

        libre, motivo = _estudio_disponible(conn, estudio, fecha_desde, fecha_hasta)
        if not libre:
            return {"libre": False, "motivo": motivo, "pack": [], "promo": None}

        # Pack: equipos disponibles en la franja (solo si el pack está activo).
        # ⏰ LEGACY — el pack sigue funcionando hasta que la Fase 8 lo retire.
        pack = (
            _pack_disponible(conn, fecha_desde, fecha_hasta)
            if estudio["pack_activo"]
            else []
        )
        # Promo: reemplaza al pack (#1283 Fase 5) — misma franja, disponibilidad
        # derivada de sus componentes vía get_disponibilidad (compuesto genérico).
        promo = _promo_info(conn, estudio, fecha_desde, fecha_hasta)
        return {"libre": True, "motivo": None, "pack": pack, "promo": promo}


class EstudioReservaCreate(BaseModel):
    fecha: str
    start: str
    horas: int
    con_pack: bool = False   # ⏰ LEGACY — reemplazado por con_promo (Fase 5, #1283)
    con_promo: bool = False
    # Los datos del cliente NO vienen del body: salen de la sesión + tabla clientes
    # (reserva con login obligatorio, igual que el portal /api/cliente/pedidos).


def _agregar_items_pack(conn, pedido_id: int, fecha_desde, fecha_hasta, pack_ids: list[int]) -> None:
    """Inserta un alquiler_item por cada equipo del pack con stock disponible en
    la franja (cantidad = lo disponible, precio 0 — el pack es valor fijo). Asume
    que las filas de `pack_ids` ya están lockeadas (FOR UPDATE) por el caller."""
    disp = get_disponibilidad(fecha_desde.isoformat(), fecha_hasta.isoformat(), pedido_id)
    for eid in pack_ids:
        qty = disp.get(str(eid), 0)
        if qty >= 1:
            conn.execute(
                """
                INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (pedido_id, eid, qty, 0, 0),
            )


class SueltoItem(BaseModel):
    """Equipo suelto agregado a mano a una reserva del Estudio — solo desde el
    back-office (#1283 Fase 6): el flujo público no ofrece sueltos arbitrarios,
    solo pack ⏰/promo. Mismo tratamiento de plata que el pack/promo: cargo FIJO
    (no por jornada) — la reserva se mide en horas, no en días."""
    equipo_id: int
    cantidad: int = Field(default=1, ge=1, le=9999)


def _crear_pedido_estudio(
    conn, *, estudio, fecha_desde, fecha_hasta,
    cliente_id, cliente_nombre, cliente_email, cliente_telefono,
    con_pack: bool, con_promo: bool, sueltos: list | None,
    espacio_monto: int | None, estado: str, numero_pedido: int,
) -> int:
    """Núcleo de creación de un pedido del Estudio (#1283 Fase 6 — extraído de
    `crear_reserva_estudio`, que ahora es un wrapper: sesión+Didit+anticipación
    +'solicitado'). Arma los ítems (pack ⏰ best-effort / promo+sueltos DUROS /
    centinela DURO) y el pedido, todo en la transacción del `conn` del caller
    (no commitea — eso es responsabilidad del caller). Devuelve `pedido_id`.

    NO valida identidad ni anticipación — son gates del CALLER, distintos entre
    el flujo público y el admin. SÍ valida slot/taller (conflicto estructural,
    aplica a cualquier origen) y todo el stock/disponibilidad.

    `espacio_monto`: si es `None`, se calcula `precio_hora × horas` como
    siempre; si viene, es un override manual del admin (ej. tarifa
    negociada) — el pedido lo persiste tal cual, sin recalcularlo.
    """
    slot_cliente = _slot_bloqueante(conn, fecha_desde, fecha_hasta)
    if slot_cliente:
        raise HTTPException(409, f"Esa franja está reservada de forma fija ({slot_cliente})")

    taller_nombre = _taller_bloqueante(conn, fecha_desde, fecha_hasta)
    if taller_nombre:
        raise HTTPException(409, f"Esa franja está reservada para el taller «{taller_nombre}»")

    con_pack = bool(con_pack) and bool(estudio["pack_activo"])
    # La promo reemplaza al pack (#1283 Fase 5): en la práctica son
    # mutuamente excluyentes (crear la promo apaga pack_activo), pero no
    # se fuerza acá — cada flag depende solo de que SU mecanismo siga vigente.
    con_promo = bool(con_promo) and bool(estudio["promo_combo_id"])
    sueltos = sueltos or []

    # `espacio_monto` es la plata REAL del espacio (va al ítem centinela,
    # Fase 2 — ítems veraces); `monto_total` sigue siendo espacio + pack/promo/
    # sueltos, como siempre. El precio de la promo/sueltos se resuelve UNA vez
    # acá y queda congelado en el ítem (como cualquier otra plata de pedido) —
    # si el combo/equipo cambia de precio después, este pedido ya cobrado no
    # se mueve.
    horas = int(round((fecha_hasta - fecha_desde).total_seconds() / 3600))
    espacio_monto_final = (
        espacio_monto if espacio_monto is not None else (estudio["precio_hora"] or 0) * horas
    )
    monto_total = espacio_monto_final
    if con_pack:
        monto_total += estudio["pack_precio"] or 0
    promo_precio = precio_jornada_efectivo(conn, estudio["promo_combo_id"]) or 0 if con_promo else 0
    if con_promo:
        monto_total += promo_precio
    precios_sueltos: dict[int, int] = {}
    for s in sueltos:
        precio = precio_jornada_efectivo(conn, s.equipo_id) or 0
        precios_sueltos[s.equipo_id] = precio
        monto_total += precio * s.cantidad

    pedido_id = conn.insert_returning(
        """
        INSERT INTO alquileres (cliente_id, cliente_nombre, cliente_email, cliente_telefono,
                                fecha_desde, fecha_hasta, monto_total, estado,
                                fuente, tipo, estudio_con_pack, numero_pedido)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            cliente_id, cliente_nombre, cliente_email, cliente_telefono,
            fecha_desde, fecha_hasta, monto_total, estado,
            "estudio", "estudio", con_pack, numero_pedido,
        ),
    )

    # ── Pack PRIMERO (antes del ítem centinela) ─────────────────────────────
    # Así _check_stock solo ve los equipos reales del pack y nunca el
    # centinela → no se mezcla el buffer global con el propio del espacio.
    if con_pack:
        pack_ids = _pack_equipo_ids(conn)
        if pack_ids:
            # Lock de las filas del pack: serializa contra otras reservas que
            # toquen estos equipos (su _check_stock también las lockea).
            conn.execute("SELECT id FROM equipos WHERE id = ANY(%s) FOR UPDATE", (pack_ids,))
            _agregar_items_pack(conn, pedido_id, fecha_desde, fecha_hasta, pack_ids)
            # Gate del motor (FOR UPDATE). Best-effort: si algo se lo llevó
            # otro entre el snapshot y el lock, re-snapshoteamos bajo el lock
            # (ya refleja a los competidores commiteados) en vez de fallar
            # toda la reserva. El espacio sí es requisito duro (abajo).
            fd_iso, fh_iso = fecha_desde.isoformat(), fecha_hasta.isoformat()
            if _check_stock(conn, pedido_id, fd_iso, fh_iso):
                conn.execute(
                    "DELETE FROM alquiler_items WHERE pedido_id = %s AND equipo_id = ANY(%s)",
                    (pedido_id, pack_ids),
                )
                _agregar_items_pack(conn, pedido_id, fecha_desde, fecha_hasta, pack_ids)

        # Línea personalizada con el precio FIJO del pack (Fase 2, ítems
        # veraces): antes el pack no tenía NINGÚN ítem con plata propia —
        # el prorrateo de la liquidación (que reparte `monto_total` por
        # `subtotal` de ítem) caía al fallback "partes iguales" entre el
        # centinela y los equipos del pack (todos a $0), derramando valor
        # del espacio hacia los DUEÑOS de esos equipos. `equipo_id=NULL`
        # → dueño 'Rambla' por default en la liquidación (`COALESCE`) —
        # coherente con que la promo es plata de Rambla, no de los
        # dueños tradicionales. Se cobra el precio fijo del pack pase lo
        # que pase con la disponibilidad de sus equipos (best-effort de
        # arriba: lo que no entró, no entró — el precio no cambia).
        pack_precio = estudio["pack_precio"] or 0
        conn.execute(
            """
            INSERT INTO alquiler_items
                (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, nombre_libre, cobro_modo)
            VALUES (%s,NULL,1,%s,%s,%s,'fijo')
            """,
            (pedido_id, pack_precio, pack_precio, estudio["pack_nombre"] or "Pack de equipos"),
        )

    # ── Promo (combo) + sueltos: requisito DURO, sin best-effort ────────────
    # A diferencia del pack (equipos sueltos best-effort, valor fijo pase lo
    # que pase), la promo y los sueltos son equipos/combos a precio fijo YA
    # comprometido con el cliente: si algún componente/equipo no tiene stock,
    # la reserva falla entera (409) en vez de servir una versión parcial
    # silenciosa. Se valida ANTES de insertar (`validar_stock_hipotetico`,
    # como en `revalidar_disponibilidad_estudio`) — NO insertar-y-recién-
    # chequear: el gate toma sus propios `FOR UPDATE` (expande combos con la
    # MISMA pieza que cualquier compuesto, `_expandir_mult`), y si el INSERT
    # fuera antes, el lock implícito FOR KEY SHARE del propio insert quedaría
    # en el camino del FOR UPDATE del gate — mismo deadlock que el centinela
    # (ver comentario abajo), aplicado acá por las dudas.
    _Item = namedtuple("_Item", ["equipo_id", "cantidad"])
    items_a_validar = []
    if con_promo:
        items_a_validar.append(_Item(estudio["promo_combo_id"], 1))
    items_a_validar.extend(_Item(s.equipo_id, s.cantidad) for s in sueltos)
    if items_a_validar:
        errores = validar_stock_hipotetico(
            conn, pedido_id, fecha_desde.isoformat(), fecha_hasta.isoformat(), items_a_validar
        )
        if errores:
            raise HTTPException(409, f"Sin stock suficiente: {'; '.join(errores)}")

    if con_promo:
        conn.execute(
            """
            INSERT INTO alquiler_items
                (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
            VALUES (%s,%s,1,%s,%s,'fijo')
            """,
            (pedido_id, estudio["promo_combo_id"], promo_precio, promo_precio),
        )
    for s in sueltos:
        precio = precios_sueltos[s.equipo_id]
        conn.execute(
            """
            INSERT INTO alquiler_items
                (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
            VALUES (%s,%s,%s,%s,%s,'fijo')
            """,
            (pedido_id, s.equipo_id, s.cantidad, precio, precio * s.cantidad),
        )

    # ── Espacio (centinela): requisito DURO ─────────────────────────────────
    # Lock PRIMERO, INSERT después — a propósito, en ese orden. Un INSERT que
    # referencia `equipo_id` (FK) toma un lock implícito FOR KEY SHARE sobre esa
    # fila; si esto insertara ANTES de pedir el FOR UPDATE, dos altas
    # concurrentes de la MISMA franja quedarían cada una con FOR KEY SHARE de
    # su propio insert (compatibles entre sí) y las dos bloqueadas pidiendo
    # FOR UPDATE sobre la fila del otro — deadlock simétrico (encontrado con
    # `test_concurrencia_admin_dos_altas_misma_franja_solo_una_pasa`). Lockeando
    # ANTES de insertar, la 2da transacción espera acá, nunca llega a insertar
    # su propia fila en conflicto. Mismo criterio que el pack (arriba: lockea
    # `pack_ids` antes de `_agregar_items_pack`).
    conn.execute("SELECT id FROM equipos WHERE id = %s FOR UPDATE", (estudio["equipo_id"],))
    if not _centinela_libre(conn, estudio["equipo_id"], fecha_desde, fecha_hasta,
                            estudio["buffer_horas"], exclude_pedido_id=pedido_id):
        raise HTTPException(409, "El estudio no está disponible en esa franja")
    # `cobro_modo='fijo'` con el monto real (Fase 2, ítems veraces): antes
    # este ítem iba a $0 (la plata vivía solo en el header) — sin esto,
    # cualquier recálculo/desglose/reconciliación que sume por ítem daba
    # $0 en vez del total real (bugs vivos arreglados en la Fase 1/2).
    conn.execute(
        """
        INSERT INTO alquiler_items
            (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
        VALUES (%s,%s,1,%s,%s,'fijo')
        """,
        (pedido_id, estudio["equipo_id"], espacio_monto_final, espacio_monto_final),
    )

    return pedido_id


@router.post("/estudio/reservas", status_code=201)
@limiter.limit(CLIENTE_WRITE_LIMIT)
def crear_reserva_estudio(body: EstudioReservaCreate, request: Request, background: BackgroundTasks):
    """Reserva real del estudio por horas. Entra como solicitud
    (estado='solicitado'), en UNA transacción.

    Requiere CLIENTE LOGUEADO (igual que /api/cliente/pedidos): el cliente_id sale
    de la sesión y nombre/email/teléfono del registro de `clientes` — nunca del body.
    Wrapper del núcleo `_crear_pedido_estudio` (#1283 Fase 6): acá viven los gates
    específicos del público (identidad, anticipación) que el admin no necesita."""
    # Import diferido (mismo motivo que `_require_cliente`): evita acoplar el
    # módulo a toda la cadena del portal en import-time y romper ciclos.
    from routes.cliente_portal import cliente_verificado, IDENTIDAD_NO_VERIFICADA_MSG

    session = _require_cliente(request)
    cliente_id = session["cliente_id"]

    with get_db() as conn:
        try:
            estudio = _get_estudio_row(conn)
            if not estudio["equipo_id"]:
                raise HTTPException(409, "El estudio todavía no tiene un recurso asociado")

            # Datos del cliente desde la cuenta (no del body), mismo formato que create_pedido.
            cli = conn.execute(
                "SELECT nombre, apellido, email, telefono FROM clientes WHERE id = %s",
                (cliente_id,),
            ).fetchone()
            if not cli:
                raise HTTPException(401, "Sesión de cliente inválida")
            # Gate de identidad: mismo criterio que /api/cliente/pedidos, vía la
            # fuente única `cliente_verificado` (no se duplica el chequeo de dni).
            if not cliente_verificado(conn, cliente_id):
                raise HTTPException(403, IDENTIDAD_NO_VERIFICADA_MSG)
            cliente_nombre = nombre_completo_cliente(cli["nombre"], cli["apellido"])
            cliente_email = cli["email"]
            cliente_telefono = cli["telefono"]

            fecha_desde, fecha_hasta = _franja_estudio(
                estudio, body.fecha, body.start, body.horas
            )
            hoy = now_ar().replace(hour=0, minute=0, second=0, microsecond=0)
            if fecha_desde < hoy:
                raise HTTPException(400, "La fecha no puede ser en el pasado")
            if _viola_anticipacion(estudio, fecha_desde):
                raise HTTPException(
                    400,
                    f"Necesitás reservar con al menos {estudio['anticipacion_min_horas']} h de anticipación",
                )

            pedido_id = _crear_pedido_estudio(
                conn, estudio=estudio, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
                cliente_id=cliente_id, cliente_nombre=cliente_nombre,
                cliente_email=cliente_email, cliente_telefono=cliente_telefono,
                con_pack=body.con_pack, con_promo=body.con_promo, sueltos=None,
                espacio_monto=None, estado="solicitado",
                numero_pedido=_next_numero_pedido(conn),
            )

            conn.commit()
            pedido = _get_alquiler_detail(conn, pedido_id)
        except Exception:
            conn.rollback()
            raise

    _dispatch_pedido_creado_emails(background, pedido)
    return pedido


# ── Admin: alta/gestión de reservas + agenda (#1283 Fase 6) ─────────────────────
#
# El admin puede cargar/reprogramar un turno sin pasar por el flujo público
# (sin login/Didit/anticipación — "el admin carga urgencias a mano", mismo
# criterio que el lead-time de #1126). Reusa el núcleo `_crear_pedido_estudio`
# — nunca reimplementa la validación de stock/disponibilidad.

# Estados con los que se puede CREAR una reserva desde el back-office (mismo
# universo que reserva stock — `reservas.ESTADOS_RESERVADO`, acá como tupla
# Python para validar el body; 'cancelado' no aplica a una alta).
_ESTADOS_ADMIN_CREACION = ("solicitado", "confirmado", "retirado")


def _resolver_cliente_admin(conn, cliente_id: Optional[int], cliente_nombre: Optional[str]):
    """Admin: cliente REAL (cliente_id, con contacto de la ficha) o texto libre
    (cliente_nombre, sin cuenta — ej. alguien que llamó por teléfono). Exactamente
    uno de los dos. Devuelve (cliente_id, cliente_nombre, cliente_email, cliente_telefono)."""
    if cliente_id and cliente_nombre:
        raise HTTPException(400, "Mandá cliente_id O cliente_nombre, no los dos")
    if cliente_id:
        cli = conn.execute(
            "SELECT nombre, apellido, email, telefono FROM clientes WHERE id = %s", (cliente_id,)
        ).fetchone()
        if not cli:
            raise HTTPException(404, "Cliente no encontrado")
        return (
            cliente_id, nombre_completo_cliente(cli["nombre"], cli["apellido"]),
            cli["email"], cli["telefono"],
        )
    nombre = (cliente_nombre or "").strip()
    if not nombre:
        raise HTTPException(400, "Mandá cliente_id o cliente_nombre")
    return None, nombre, None, None


def _reserva_estudio_admin_dict(conn, pedido_id: int) -> dict:
    """Detalle liviano de una reserva para el admin — reusa la puerta única de
    detalle de pedido (contacto en vivo, ítems reales) en vez de reimplementar
    un SELECT paralelo."""
    return _get_alquiler_detail(conn, pedido_id)


@router.get("/admin/estudio/reservas")
def listar_reservas_estudio(
    request: Request, desde: Optional[str] = None, hasta: Optional[str] = None,
):
    """Turnos del estudio (tipo='estudio'; NO incluye estudio_fijo — esos son
    slots recurrentes, ver /admin/estudio/slots) — para la lista del back-office."""
    require_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.numero_pedido, a.cliente_id, a.cliente_nombre,
                   a.fecha_desde, a.fecha_hasta, a.monto_total, a.monto_pagado,
                   a.estado, a.estudio_con_pack
            FROM alquileres a
            WHERE a.tipo = 'estudio'
              AND (%s::date IS NULL OR a.fecha_hasta >= %s::date)
              AND (%s::date IS NULL OR a.fecha_desde < %s::date + interval '1 day')
            ORDER BY a.fecha_desde DESC
            """,
            (desde, desde, hasta, hasta),
        ).fetchall()
        pedidos = [row_to_dict(r) for r in rows]
        _enriquecer_pedidos_con_cliente(conn, pedidos)
        return {"reservas": pedidos}


@router.get("/admin/estudio/agenda")
def agenda_estudio(request: Request, desde: str = Query(...), hasta: str = Query(...)):
    """Bloques de ocupación del estudio en [desde, hasta] (YYYY-MM-DD): turnos
    reales + slots fijos recurrentes (expandidos a fechas concretas) + talleres.
    Solo lectura — no toca disponibilidad de ningún equipo, es la vista de
    "qué ocupa el ESPACIO" (mismas fuentes que _estudio_disponible)."""
    require_admin(request)
    try:
        desde_d = datetime.strptime(desde, "%Y-%m-%d").date()
        hasta_d = datetime.strptime(hasta, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "desde/hasta deben tener formato YYYY-MM-DD")
    if desde_d > hasta_d:
        raise HTTPException(400, "desde no puede ser posterior a hasta")

    with get_db() as conn:
        bloques = []

        rows = conn.execute(
            f"""
            SELECT id, numero_pedido, cliente_nombre, fecha_desde, fecha_hasta, estado
            FROM alquileres
            WHERE tipo = 'estudio' AND estado IN {ESTADOS_RESERVADO}
              AND fecha_desde < %s AND fecha_hasta > %s
            ORDER BY fecha_desde
            """,
            (hasta_d + timedelta(days=1), desde_d),
        ).fetchall()
        for r in rows:
            bloques.append({
                "tipo": "turno",
                "id": r["id"],
                "numero_pedido": r["numero_pedido"],
                "titulo": r["cliente_nombre"] or "Reserva",
                "fecha_desde": r["fecha_desde"].isoformat(),
                "fecha_hasta": r["fecha_hasta"].isoformat(),
                "estado": r["estado"],
            })

        slots = conn.execute("SELECT * FROM estudio_slots_fijos WHERE activo = TRUE").fetchall()
        for slot_row in slots:
            slot = _slot_to_dict(slot_row)
            for s in _sesiones_de_slot(slot):
                if not (desde_d <= s["fecha"] <= hasta_d):
                    continue
                base = datetime(s["fecha"].year, s["fecha"].month, s["fecha"].day)
                bloques.append({
                    "tipo": "slot",
                    "id": slot["id"],
                    "numero_pedido": None,
                    "titulo": slot["cliente"],
                    "fecha_desde": (base + timedelta(minutes=s["hora_inicio_min"])).isoformat(),
                    "fecha_hasta": (base + timedelta(minutes=s["hora_fin_min"])).isoformat(),
                    "estado": "confirmado",
                })

        rows = conn.execute(
            """
            SELECT t.id, t.nombre, c.fecha, c.hora_inicio_min, c.hora_fin_min
            FROM clases_taller c
            JOIN ediciones_taller e ON e.id = c.edicion_id
            JOIN talleres t ON t.id = e.taller_id
            WHERE t.activo = TRUE AND e.activo = TRUE
              AND c.fecha BETWEEN %s AND %s
            ORDER BY c.fecha
            """,
            (desde_d, hasta_d),
        ).fetchall()
        for r in rows:
            base = datetime(r["fecha"].year, r["fecha"].month, r["fecha"].day)
            bloques.append({
                "tipo": "taller",
                "id": r["id"],
                "numero_pedido": None,
                "titulo": r["nombre"],
                "fecha_desde": (base + timedelta(minutes=r["hora_inicio_min"])).isoformat(),
                "fecha_hasta": (base + timedelta(minutes=r["hora_fin_min"])).isoformat(),
                "estado": "confirmado",
            })

        bloques.sort(key=lambda b: b["fecha_desde"])
        return {"bloques": bloques}


@router.get("/admin/estudio/reservas/cotizar")
def cotizar_reserva_estudio(
    request: Request,
    fecha: str = Query(...), start: str = Query(...), horas: int = Query(...),
    con_pack: bool = False, con_promo: bool = False,
    sueltos_json: str = Query("[]"),
):
    """Desglose de plata de una reserva ANTES de crearla — no muta nada (el
    front no calcula plata, MEMORIA 2026-06-29). `sueltos_json` es
    `[{"equipo_id":N,"cantidad":N}]` codificado."""
    require_admin(request)
    try:
        sueltos_raw = json.loads(sueltos_json)
        sueltos = [SueltoItem(**s) for s in sueltos_raw]
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"sueltos_json inválido: {e}")

    with get_db() as conn:
        estudio = _get_estudio_row(conn)
        if not estudio["equipo_id"]:
            raise HTTPException(409, "El estudio todavía no tiene un recurso asociado")
        fecha_desde, fecha_hasta = _franja_estudio(estudio, fecha, start, horas)

        con_pack = bool(con_pack) and bool(estudio["pack_activo"])
        con_promo = bool(con_promo) and bool(estudio["promo_combo_id"])
        espacio_monto = (estudio["precio_hora"] or 0) * horas
        desglose = {"espacio": espacio_monto, "pack": 0, "promo": 0, "sueltos": []}
        total = espacio_monto
        if con_pack:
            desglose["pack"] = estudio["pack_precio"] or 0
            total += desglose["pack"]
        if con_promo:
            promo_precio = precio_jornada_efectivo(conn, estudio["promo_combo_id"]) or 0
            desglose["promo"] = promo_precio
            total += promo_precio
        for s in sueltos:
            precio = precio_jornada_efectivo(conn, s.equipo_id) or 0
            subtotal = precio * s.cantidad
            desglose["sueltos"].append(
                {"equipo_id": s.equipo_id, "cantidad": s.cantidad, "precio_jornada": precio,
                 "subtotal": subtotal}
            )
            total += subtotal
        desglose["monto_total"] = total

        libre, motivo = _estudio_disponible(conn, estudio, fecha_desde, fecha_hasta)
        desglose["espacio_disponible"] = libre
        desglose["espacio_motivo"] = motivo
        return desglose


class EstudioReservaAdminCreate(BaseModel):
    fecha: str
    start: str
    horas: int
    cliente_id: Optional[int] = None
    cliente_nombre: Optional[str] = None
    con_pack: bool = False
    con_promo: bool = False
    sueltos: list[SueltoItem] = []
    espacio_monto: Optional[int] = None
    estado: str = "confirmado"


@router.post("/admin/estudio/reservas", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
def crear_reserva_estudio_admin(body: EstudioReservaAdminCreate, request: Request):
    """Alta de una reserva del estudio desde el back-office: sin sesión de
    cliente ni Didit ni anticipación mínima (el admin la carga a mano),
    con equipos sueltos + override del precio del espacio si hace falta.
    Reusa el mismo núcleo (`_crear_pedido_estudio`) que el flujo público —
    la validación de stock/disponibilidad no se reimplementa."""
    require_admin(request)
    if body.estado not in _ESTADOS_ADMIN_CREACION:
        raise HTTPException(
            400, f"estado debe ser uno de {', '.join(_ESTADOS_ADMIN_CREACION)}"
        )

    with get_db() as conn:
        try:
            estudio = _get_estudio_row(conn)
            if not estudio["equipo_id"]:
                raise HTTPException(409, "El estudio todavía no tiene un recurso asociado")

            cliente_id, cliente_nombre, cliente_email, cliente_telefono = _resolver_cliente_admin(
                conn, body.cliente_id, body.cliente_nombre
            )
            fecha_desde, fecha_hasta = _franja_estudio(estudio, body.fecha, body.start, body.horas)

            pedido_id = _crear_pedido_estudio(
                conn, estudio=estudio, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
                cliente_id=cliente_id, cliente_nombre=cliente_nombre,
                cliente_email=cliente_email, cliente_telefono=cliente_telefono,
                con_pack=body.con_pack, con_promo=body.con_promo, sueltos=body.sueltos,
                espacio_monto=body.espacio_monto, estado=body.estado,
                numero_pedido=_next_numero_pedido(conn),
            )
            conn.commit()
            return _reserva_estudio_admin_dict(conn, pedido_id)
        except Exception:
            conn.rollback()
            raise


class EstudioReservaAdminUpdate(BaseModel):
    fecha: Optional[str] = None
    start: Optional[str] = None
    horas: Optional[int] = None
    con_pack: Optional[bool] = None
    con_promo: Optional[bool] = None
    sueltos: Optional[list[SueltoItem]] = None
    espacio_monto: Optional[int] = None


@router.patch("/admin/estudio/reservas/{pedido_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def editar_reserva_estudio_admin(pedido_id: int, body: EstudioReservaAdminUpdate, request: Request):
    """Reprograma/edita una reserva del estudio YA EXISTENTE. Reemplaza TODOS
    los ítems no-centinela (pack/promo/sueltos) según el payload — mismo
    criterio "reemplazo completo" que el PUT de ítems del editor genérico,
    adaptado al Estudio (que el editor genérico bloquea, Fase 1: #1283).
    Un `estudio_fijo` no se edita acá — lo gobierna su slot (editar el slot
    regenera sus pedidos)."""
    require_admin(request)
    with get_db() as conn:
        try:
            pedido = conn.execute(
                "SELECT * FROM alquileres WHERE id = %s FOR UPDATE", (pedido_id,)
            ).fetchone()
            if not pedido:
                raise HTTPException(404, "Pedido no encontrado")
            if pedido["tipo"] == "estudio_fijo":
                raise HTTPException(
                    409, "Los turnos de un slot fijo se editan desde el slot, no acá"
                )
            if pedido["tipo"] != "estudio":
                raise HTTPException(400, "Este pedido no es del Estudio")

            estudio = _get_estudio_row(conn)

            fecha_desde = to_datetime(pedido["fecha_desde"])
            fecha_hasta = to_datetime(pedido["fecha_hasta"])
            reprograma = body.fecha is not None or body.start is not None or body.horas is not None
            if reprograma:
                horas_actuales = int(round((fecha_hasta - fecha_desde).total_seconds() / 3600))
                fecha_desde, fecha_hasta = _franja_estudio(
                    estudio,
                    body.fecha or fecha_desde.strftime("%Y-%m-%d"),
                    body.start or fecha_desde.strftime("%H:%M"),
                    body.horas if body.horas is not None else horas_actuales,
                )

            libre, motivo = _estudio_disponible(
                conn, estudio, fecha_desde, fecha_hasta, exclude_pedido_id=pedido_id,
            )
            if not libre:
                raise HTTPException(409, f"El espacio no está disponible: {motivo}")

            items_actuales = conn.execute(
                "SELECT equipo_id, cantidad, precio_jornada, subtotal, nombre_libre, cobro_modo "
                "FROM alquiler_items WHERE pedido_id = %s AND equipo_id != %s",
                (pedido_id, estudio["equipo_id"]),
            ).fetchall()
            pack_actual = any(it["equipo_id"] is None for it in items_actuales)
            promo_actual = any(it["equipo_id"] == estudio["promo_combo_id"] for it in items_actuales)

            con_pack = body.con_pack if body.con_pack is not None else pack_actual
            con_promo = body.con_promo if body.con_promo is not None else promo_actual
            if body.sueltos is not None:
                sueltos = body.sueltos
            else:
                ids_conocidos = {estudio["promo_combo_id"]}
                sueltos = [
                    SueltoItem(equipo_id=it["equipo_id"], cantidad=it["cantidad"])
                    for it in items_actuales
                    if it["equipo_id"] is not None and it["equipo_id"] not in ids_conocidos
                ]
            espacio_monto = (
                body.espacio_monto if body.espacio_monto is not None
                else (estudio["precio_hora"] or 0)
                * int(round((fecha_hasta - fecha_desde).total_seconds() / 3600))
            )

            # Reemplazo completo de los ítems no-centinela: se recalcula todo
            # desde cero contra la franja (nueva o la misma) en vez de parchear
            # fila por fila — más simple y sin estado intermedio inconsistente.
            conn.execute(
                "DELETE FROM alquiler_items WHERE pedido_id = %s AND equipo_id != %s",
                (pedido_id, estudio["equipo_id"]),
            )

            con_pack = bool(con_pack) and bool(estudio["pack_activo"])
            con_promo = bool(con_promo) and bool(estudio["promo_combo_id"])
            monto_total = espacio_monto
            if con_pack:
                pack_ids = _pack_equipo_ids(conn)
                if pack_ids:
                    conn.execute("SELECT id FROM equipos WHERE id = ANY(%s) FOR UPDATE", (pack_ids,))
                    _agregar_items_pack(conn, pedido_id, fecha_desde, fecha_hasta, pack_ids)
                monto_total += estudio["pack_precio"] or 0
                conn.execute(
                    """INSERT INTO alquiler_items
                           (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, nombre_libre, cobro_modo)
                       VALUES (%s,NULL,1,%s,%s,%s,'fijo')""",
                    (pedido_id, estudio["pack_precio"] or 0, estudio["pack_precio"] or 0,
                     estudio["pack_nombre"] or "Pack de equipos"),
                )
            # Validar ANTES de insertar (mismo motivo que `_crear_pedido_estudio`:
            # insertar primero dejaría el lock implícito FOR KEY SHARE del
            # propio insert en el camino del FOR UPDATE que toma el gate).
            _Item = namedtuple("_Item", ["equipo_id", "cantidad"])
            items_a_validar = []
            if con_promo:
                items_a_validar.append(_Item(estudio["promo_combo_id"], 1))
            items_a_validar.extend(_Item(s.equipo_id, s.cantidad) for s in sueltos)
            if items_a_validar:
                errores = validar_stock_hipotetico(
                    conn, pedido_id, fecha_desde.isoformat(), fecha_hasta.isoformat(),
                    items_a_validar,
                )
                if errores:
                    raise HTTPException(409, f"Sin stock suficiente: {'; '.join(errores)}")

            if con_promo:
                promo_precio = precio_jornada_efectivo(conn, estudio["promo_combo_id"]) or 0
                monto_total += promo_precio
                conn.execute(
                    """INSERT INTO alquiler_items
                           (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
                       VALUES (%s,%s,1,%s,%s,'fijo')""",
                    (pedido_id, estudio["promo_combo_id"], promo_precio, promo_precio),
                )
            for s in sueltos:
                precio = precio_jornada_efectivo(conn, s.equipo_id) or 0
                subtotal = precio * s.cantidad
                monto_total += subtotal
                conn.execute(
                    """INSERT INTO alquiler_items
                           (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
                       VALUES (%s,%s,%s,%s,%s,'fijo')""",
                    (pedido_id, s.equipo_id, s.cantidad, precio, subtotal),
                )

            conn.execute(
                "UPDATE alquiler_items SET precio_jornada = %s, subtotal = %s "
                "WHERE pedido_id = %s AND equipo_id = %s",
                (espacio_monto, espacio_monto, pedido_id, estudio["equipo_id"]),
            )
            conn.execute(
                "UPDATE alquileres SET fecha_desde = %s, fecha_hasta = %s, monto_total = %s, "
                "estudio_con_pack = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (fecha_desde, fecha_hasta, monto_total, con_pack, pedido_id),
            )

            conn.commit()
            return _reserva_estudio_admin_dict(conn, pedido_id)
        except Exception:
            conn.rollback()
            raise


# ── Admin: ocupación real del estudio para el calendario del dashboard ─────────
#
# `GET /admin/calendario` (routes/dashboard.py) lista pedidos — una reserva de
# estudio confirmada/solicitada YA aparece ahí (es un alquiler normal sobre el
# centinela). Lo que ese endpoint NO puede ver son los bloqueos que no son
# pedidos: los slots fijos (el pedido mensual que genera `_regenerar_pedidos_slot`
# es solo un marcador de facturación, sin `alquiler_items` — el INNER JOIN de
# `get_calendario` lo excluye a propósito, y aunque no lo excluyera solo mostraría
# UN día representativo por mes, no cada ocurrencia semanal real) y las clases de
# taller publicadas. Mismas reglas que `_slot_bloqueante`/`_taller_bloqueante`
# (una sola forma de decidir "¿está ocupado?"), en forma de lista para un rango
# en vez de un chequeo puntual.

def _ocupacion_estudio_rango(conn, desde: date, hasta: date) -> list[dict]:
    """Slots fijos + clases de taller que ocupan el estudio en [desde, hasta].
    Deliberadamente NO incluye reservas del centinela (ya las cubre el
    calendario de pedidos) — si un futuro consumidor las necesita también
    (ej. un selector de fecha del cliente), que las pida aparte vía
    `_centinela_libre`, no que se dupliquen acá."""
    mes_desde = f"{desde.year:04d}-{desde.month:02d}"
    mes_hasta = f"{hasta.year:04d}-{hasta.month:02d}"
    out: list[dict] = []

    slots = conn.execute(
        """
        SELECT cliente, dia_semana, hora_desde, hora_hasta, mes_desde, mes_hasta
        FROM estudio_slots_fijos
        WHERE activo = TRUE AND mes_desde <= %s AND mes_hasta >= %s
        """,
        (mes_hasta, mes_desde),
    ).fetchall()
    for slot in slots:
        for s in _sesiones_de_slot(slot):
            if not (desde <= s["fecha"] <= hasta):
                continue
            base = datetime(s["fecha"].year, s["fecha"].month, s["fecha"].day)
            out.append({
                "tipo": "slot_fijo",
                "label": f"Slot fijo · {slot['cliente']}",
                "fecha_desde": base + timedelta(minutes=s["hora_inicio_min"]),
                "fecha_hasta": base + timedelta(minutes=s["hora_fin_min"]),
            })

    clases = conn.execute(
        """
        SELECT t.nombre, c.fecha, c.hora_inicio_min, c.hora_fin_min
        FROM clases_taller c
        JOIN ediciones_taller e ON e.id = c.edicion_id
        JOIN talleres t ON t.id = e.taller_id
        WHERE t.activo = TRUE AND e.activo = TRUE
          AND c.fecha BETWEEN %s AND %s
        """,
        (desde, hasta),
    ).fetchall()
    for c in clases:
        base = datetime(c["fecha"].year, c["fecha"].month, c["fecha"].day)
        out.append({
            "tipo": "taller",
            "label": f"Taller · {c['nombre']}",
            "fecha_desde": base + timedelta(minutes=c["hora_inicio_min"]),
            "fecha_hasta": base + timedelta(minutes=c["hora_fin_min"]),
        })

    return out


@router.get("/admin/estudio/ocupacion")
def estudio_ocupacion_admin(
    request: Request,
    desde: str = Query(..., description="YYYY-MM-DD"),
    hasta: str = Query(..., description="YYYY-MM-DD"),
):
    """Bloqueos no-pedido del estudio en [desde, hasta], para overlay en el
    calendario del dashboard admin. Ver nota de sección arriba."""
    require_admin(request)
    try:
        d0 = datetime.strptime(desde, "%Y-%m-%d").date()
        d1 = datetime.strptime(hasta, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Fecha inválida (esperado YYYY-MM-DD)")
    if d1 < d0:
        raise HTTPException(400, "hasta no puede ser anterior a desde")
    with get_db() as conn:
        return {"bloqueos": _ocupacion_estudio_rango(conn, d0, d1)}


# ── Admin: CRUD de slots fijos (E4) ────────────────────────────────────────────

class SlotFijoCreate(BaseModel):
    cliente: str
    dia_semana: int
    hora_desde: int
    hora_hasta: int
    valor_mensual: int = 0
    mes_desde: str
    mes_hasta: str
    activo: bool = True


class SlotFijoUpdate(BaseModel):
    cliente: Optional[str] = None
    dia_semana: Optional[int] = None
    hora_desde: Optional[int] = None
    hora_hasta: Optional[int] = None
    valor_mensual: Optional[int] = None
    mes_desde: Optional[str] = None
    mes_hasta: Optional[str] = None
    activo: Optional[bool] = None


_MES_RE = __import__("re").compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validar_slot(d: dict) -> None:
    """Valida los campos de un slot (los que estén presentes). Lanza 400."""
    if "dia_semana" in d and not (0 <= d["dia_semana"] <= 6):
        raise HTTPException(400, "dia_semana debe estar entre 0 (Lun) y 6 (Dom)")
    for k in ("hora_desde", "hora_hasta"):
        if k in d and not (0 <= d[k] <= 24):
            raise HTTPException(400, f"{k} debe estar entre 0 y 24")
    if "hora_desde" in d and "hora_hasta" in d and d["hora_desde"] >= d["hora_hasta"]:
        raise HTTPException(400, "hora_hasta debe ser posterior a hora_desde")
    for k in ("mes_desde", "mes_hasta"):
        if k in d and not _MES_RE.match(d[k] or ""):
            raise HTTPException(400, f"{k} debe tener formato YYYY-MM")
    if "mes_desde" in d and "mes_hasta" in d and d["mes_desde"] > d["mes_hasta"]:
        raise HTTPException(400, "mes_hasta no puede ser anterior a mes_desde")


def _get_slot(conn, slot_id: int) -> dict:
    row = conn.execute("SELECT * FROM estudio_slots_fijos WHERE id = %s", (slot_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Slot no encontrado")
    return _slot_to_dict(row)


@router.get("/admin/estudio/slots")
def listar_slots(request: Request):
    require_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM estudio_slots_fijos ORDER BY activo DESC, dia_semana, hora_desde"
        ).fetchall()
        return {"slots": [_slot_to_dict(r) for r in rows]}


@router.post("/admin/estudio/slots", status_code=201)
@limiter.limit(ADMIN_WRITE_LIMIT)
def crear_slot(body: SlotFijoCreate, request: Request):
    require_admin(request)
    data = body.dict()
    _validar_slot(data)
    with get_db() as conn:
        try:
            estudio = _get_estudio_row(conn)
            if not estudio["equipo_id"]:
                raise HTTPException(409, "El estudio todavía no tiene un recurso asociado")
            conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_ADVISORY_NS_ESTUDIO, 1))
            if data.get("activo", True):
                verificar_sesiones_disponibles(conn, estudio, _sesiones_de_slot(data))
            slot_id = conn.insert_returning(
                """
                INSERT INTO estudio_slots_fijos
                    (cliente, dia_semana, hora_desde, hora_hasta, valor_mensual,
                     mes_desde, mes_hasta, activo)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (data["cliente"], data["dia_semana"], data["hora_desde"], data["hora_hasta"],
                 data["valor_mensual"], data["mes_desde"], data["mes_hasta"], data["activo"]),
            )
            slot = _get_slot(conn, slot_id)
            _regenerar_pedidos_slot(conn, estudio, slot)
            conn.commit()
            return slot
        except Exception:
            conn.rollback()
            raise


@router.patch("/admin/estudio/slots/{slot_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def actualizar_slot(slot_id: int, body: SlotFijoUpdate, request: Request):
    require_admin(request)
    updates = {k: v for k, v in body.dict().items() if v is not None}
    with get_db() as conn:
        try:
            actual = _get_slot(conn, slot_id)
            merged = {**actual, **updates}
            _validar_slot(merged)
            estudio = _get_estudio_row(conn)
            if not estudio["equipo_id"]:
                raise HTTPException(409, "El estudio todavía no tiene un recurso asociado")
            conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_ADVISORY_NS_ESTUDIO, 1))
            if merged.get("activo", True):
                verificar_sesiones_disponibles(
                    conn, estudio, _sesiones_de_slot(merged),
                    exclude_slot_id=slot_id,
                )
            if updates:
                updates["updated_at"] = now_ar()
                set_parts = ", ".join(f"{k} = %s" for k in updates)
                conn.execute(
                    f"UPDATE estudio_slots_fijos SET {set_parts} WHERE id = %s",
                    (*updates.values(), slot_id),
                )
            slot = _get_slot(conn, slot_id)
            _regenerar_pedidos_slot(conn, estudio, slot)
            conn.commit()
            return slot
        except Exception:
            conn.rollback()
            raise


@router.delete("/admin/estudio/slots/{slot_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def borrar_slot(slot_id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        try:
            _get_slot(conn, slot_id)  # 404 si no existe
            # Borra los pedidos futuros impagos; los pasados/pagados quedan (su
            # estudio_slot_id pasa a NULL por la FK ON DELETE SET NULL).
            _borrar_pedidos_futuros_impagos(conn, slot_id)
            conn.execute("DELETE FROM estudio_slots_fijos WHERE id = %s", (slot_id,))
            conn.commit()
            return {"ok": True}
        except Exception:
            conn.rollback()
            raise
