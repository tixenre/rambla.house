"""Endpoint público de media por entidad — variantes de fotos para el frontend.

GET /api/media/entity/{kind}/{entity_id}
  Devuelve los assets de media de una entidad con sus variantes completas
  (name, url, width, height, content_type). Público — las URLs de variantes
  ya son CDN públicas.

  Soporta: kind="equipo" (equipo_fotos) | kind="estudio" (estudio_fotos).
  Legacy fallback: fotos sin media_id (subidas antes de F0a) devuelven una
  variante sintética "display" con la url almacenada (cero rotura).

  El frontend usa este endpoint en `useEntityMedia(kind, entityId)` para
  construir srcset con width/height reales (anti-CLS) vía `<ResponsiveImage>`.
"""
from fastapi import APIRouter, HTTPException, Request

from auth.guards import require_admin
from database import get_db
from services.media.service import validate_kind
from services.media.errors import MediaError
from services.media.storage import presigned_url as _presigned_url

router = APIRouter()


def _load_variants(conn, media_id: int) -> list[dict]:
    """Carga las variantes de un media_asset desde media_variants."""
    rows = conn.execute(
        "SELECT name, url, width, height, content_type "
        "FROM media_variants WHERE asset_id = %s ORDER BY id",
        (media_id,),
    ).fetchall()
    return [
        {
            "name": r["name"],
            "url": r["url"],
            "width": r["width"] or 0,
            "height": r["height"] or 0,
            "content_type": r["content_type"] or "image/webp",
        }
        for r in rows
    ]


def _load_asset_meta(conn, media_id: int) -> dict:
    """Lee lqip y status del media_asset. Defaults seguros si faltan columnas."""
    row = conn.execute(
        "SELECT lqip, status FROM media_assets WHERE id = %s", (media_id,)
    ).fetchone()
    if not row:
        return {"lqip": None, "status": "ready"}
    try:
        lqip = row["lqip"]
    except (KeyError, IndexError):
        lqip = None
    try:
        status = row["status"] or "ready"
    except (KeyError, IndexError):
        status = "ready"
    return {"lqip": lqip, "status": status}


def _build_asset(conn, row) -> dict:
    """Construye un asset con variants, lqip y status. Fallback para fotos pre-F0a."""
    media_id = row["media_id"]
    variants = _load_variants(conn, media_id) if media_id else []
    meta = _load_asset_meta(conn, media_id) if media_id else {"lqip": None, "status": "ready"}

    if not variants and row["url"]:
        variants = [{
            "name": "display",
            "url": row["url"],
            "width": 0,
            "height": 0,
            "content_type": "image/webp",
        }]

    return {
        "id": row["id"],
        "media_id": media_id,
        "orden": row["orden"],
        "es_principal": bool(row["es_principal"]),
        "lqip": meta["lqip"],
        "status": meta["status"],
        "variants": variants,
    }


def _get_equipo_media(conn, entity_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, url, media_id, orden, es_principal "
        "FROM equipo_fotos WHERE equipo_id = %s ORDER BY orden, id",
        (entity_id,),
    ).fetchall()
    return [_build_asset(conn, r) for r in rows]


def _get_estudio_media(conn, entity_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, url, media_id, orden, es_principal "
        "FROM estudio_fotos WHERE estudio_id = %s ORDER BY orden, id",
        (entity_id,),
    ).fetchall()
    return [_build_asset(conn, r) for r in rows]


def _get_taller_clase_media(conn, entity_id: int) -> list[dict]:
    """Portada de una clase de taller (F2). entity_id = clase_id.
    Misma adaptación single-asset que `instructor` (el 'id' devuelto es el
    clase_id; el front no opera sobre ese campo)."""
    row = conn.execute(
        "SELECT id, portada_url, portada_media_id FROM clases_taller WHERE id = %s",
        (entity_id,),
    ).fetchone()
    if not row:
        return []
    media_id = row["portada_media_id"]
    url = row["portada_url"] or ""
    if not media_id and not url:
        return []
    adapted = {"id": row["id"], "media_id": media_id, "orden": 0, "es_principal": True, "url": url}
    return [_build_asset(conn, adapted)]


def _get_instructor_perfil_media(conn, entity_id: int) -> list[dict]:
    """Foto de un instructor-ENTIDAD (F3). entity_id = instructor_id — kind
    propio; el kind legacy "instructor" (entity_id=taller_id) se retiró en F6."""
    row = conn.execute(
        "SELECT id, foto_url, foto_media_id FROM instructores WHERE id = %s",
        (entity_id,),
    ).fetchone()
    if not row:
        return []
    media_id = row["foto_media_id"]
    url = row["foto_url"] or ""
    if not media_id and not url:
        return []
    adapted = {"id": row["id"], "media_id": media_id, "orden": 0, "es_principal": True, "url": url}
    return [_build_asset(conn, adapted)]


def _get_institucion_logo_media(conn, entity_id: int) -> list[dict]:
    """Logo de una institución co-presentadora (ej. "Rambla"/"Filmar").
    entity_id = institucion_id."""
    row = conn.execute(
        "SELECT id, logo_url, logo_media_id FROM instituciones WHERE id = %s",
        (entity_id,),
    ).fetchone()
    if not row:
        return []
    media_id = row["logo_media_id"]
    url = row["logo_url"] or ""
    if not media_id and not url:
        return []
    adapted = {"id": row["id"], "media_id": media_id, "orden": 0, "es_principal": True, "url": url}
    return [_build_asset(conn, adapted)]


_KIND_HANDLERS = {
    "equipo": _get_equipo_media,
    "estudio": _get_estudio_media,
    "taller-clase": _get_taller_clase_media,
    "instructor-perfil": _get_instructor_perfil_media,
    "institucion-logo": _get_institucion_logo_media,
}


@router.get("/media/entity/{kind}/{entity_id}")
def get_entity_media(kind: str, entity_id: int):
    """Variantes de fotos de una entidad. Público (URLs ya son CDN-públicas).

    Devuelve:
      {assets: [{id, media_id, orden, es_principal, variants: [{name, url, width, height, content_type}]}]}

    Fallback: fotos sin media_id (pre-F0a) devuelven variant sintética con url directa.
    """
    try:
        validate_kind(kind)
    except MediaError:
        raise HTTPException(400, f"kind inválido: {kind!r}")

    handler = _KIND_HANDLERS.get(kind)
    if handler is None:
        raise HTTPException(404, f"kind '{kind}' no soportado. Disponibles: {list(_KIND_HANDLERS)}")

    with get_db() as conn:
        assets = handler(conn, entity_id)

    return {"assets": assets}


@router.get("/admin/media/document/presigned")
def get_document_presigned(key: str, request: Request, expires: int = 3600):
    """Genera una URL prefirmada de acceso a un documento privado (comprobante, etc.).

    Solo admins. La key viene de comprobante_key en la BD.
    expires: segundos de validez (default 1h, máx 7 días = 604800).
    """
    require_admin(request)
    expires = max(60, min(expires, 604800))
    try:
        url = _presigned_url(key, expires, private=True)
    except MediaError as e:
        raise HTTPException(e.status, e.detail)
    return {"url": url, "expires_in": expires}
