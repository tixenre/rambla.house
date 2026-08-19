"""
routes/marcas.py — CRUD de marcas (brands).
"""

import logging
import re
import time
import unicodedata
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from database import get_db, row_to_dict
from auth.guards import require_admin
from rate_limit import limiter, ADMIN_WRITE_LIMIT, ADMIN_UPLOAD_LIMIT

logger = logging.getLogger(__name__)
router = APIRouter()


def _logo_path(marca_id: int, nombre: str, ext: str) -> str:
    """Genera path R2 para el logo: marcas/{id}_{slug}/logo-{ts}.{ext}.

    El timestamp en el nombre del archivo evita el problema del cache
    inmutable: R2 sirve los assets con `Cache-Control: immutable max-age=1y`,
    así que si dos uploads usan el mismo path el navegador sigue mostrando
    el viejo durante un año. Con timestamp cada upload tiene URL nueva.
    El archivo anterior queda como huérfano en R2 (cleanup futuro si pesa).
    """
    slug = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")[:50]
    folder = f"{marca_id}_{slug}" if slug else str(marca_id)
    ts = int(time.time())
    return f"marcas/{folder}/logo-{ts}.{ext}"


# ── Pydantic Models ──────────────────────────────────────────────────────────

class MarcaAdmin(BaseModel):
    id: int
    nombre: str
    logo_url: Optional[str] = None
    visible: bool
    destacada: bool = False
    orden: int
    total: int


class MarcaPatch(BaseModel):
    nombre: Optional[str] = None
    logo_url: Optional[str] = None
    visible: Optional[bool] = None
    destacada: Optional[bool] = None
    orden: Optional[int] = None


class MarcasReorderRequest(BaseModel):
    marcas: list[dict]  # [{"id": 1, "orden": 2}, ...]


class MarcaMergeRequest(BaseModel):
    source_id: int  # marca a eliminar (sus equipos van a target)
    target_id: int  # marca destino (recibe los equipos de source)


# ── Public API ───────────────────────────────────────────────────────────────

@router.get("/marcas")
def list_marcas():
    """Lista marcas visibles ordenadas por orden manual, después por
    popularidad automática (#131), después alfabético.

    El `orden` manual (default 100) sigue siendo override — el admin
    puede forzar marcas específicas arriba bajándole el número. Si
    todas tienen orden=100, gana la popularidad real (cant_pedidos +
    ingreso, calculado por el ranking service).

    El campo `destacada` (issue #288) lo lee el frontend para curar el
    BrandCarousel del home: si hay marcas con destacada=true las muestra,
    sino fallback al algoritmo automático de top N por count."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, nombre, logo_url, logo_url_sm, destacada, orden,
                   popularidad_score, created_at, updated_at
            FROM marcas
            WHERE visible = TRUE
            ORDER BY orden ASC, popularidad_score DESC, nombre ASC
        """).fetchall()
        marcas = [row_to_dict(r) for r in rows]
        return {"items": marcas}


# ── Admin API ────────────────────────────────────────────────────────────────

@router.get("/admin/marcas")
def admin_list_marcas(request: Request):
    """Lista todas las marcas (visible/invisible) con count de equipos y flag `destacada`."""
    require_admin(request)
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                m.id, m.nombre, m.logo_url, m.visible, m.destacada, m.orden,
                COUNT(e.id) as total
            FROM marcas m
            LEFT JOIN equipos e ON e.brand_id = m.id
            GROUP BY m.id, m.nombre, m.logo_url, m.visible, m.destacada, m.orden
            ORDER BY m.orden ASC, m.nombre ASC
        """).fetchall()
        marcas = [dict(row) for row in rows]
        return {"items": marcas}


@router.patch("/admin/marcas/{marca_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def admin_update_marca(marca_id: int, patch: MarcaPatch, request: Request):
    """Actualiza una marca (nombre, logo_url, visible, orden)."""
    require_admin(request)
    with get_db() as conn:
        # Verificar que existe
        existing = conn.execute("SELECT id FROM marcas WHERE id = %s", (marca_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Marca no encontrada")

        # Construir SET dinámico
        updates = {}
        if patch.nombre is not None:
            updates["nombre"] = patch.nombre
        if patch.logo_url is not None:
            updates["logo_url"] = patch.logo_url
        if patch.visible is not None:
            updates["visible"] = patch.visible
        if patch.destacada is not None:
            updates["destacada"] = patch.destacada
        if patch.orden is not None:
            updates["orden"] = patch.orden

        if not updates:
            raise HTTPException(status_code=400, detail="No hay campos para actualizar")

        updates["updated_at"] = "NOW()"

        set_clause = ", ".join([f"{k} = %s" if k != 'updated_at' else f"{k} = NOW()" for k in updates.keys()])
        values = [v for k, v in updates.items() if k != "updated_at"]
        values.append(marca_id)

        conn.execute(f"""
            UPDATE marcas SET {set_clause} WHERE id = %s
        """, values)

        # brand_id (FK) es la fuente única del nombre de marca; renombrar la
        # fila en `marcas` ya se refleja en todos los equipos vía el join.

        # Devolver la marca actualizada
        row = conn.execute("""
            SELECT
                m.id, m.nombre, m.logo_url, m.visible, m.destacada, m.orden,
                COUNT(e.id) as total
            FROM marcas m
            LEFT JOIN equipos e ON e.brand_id = m.id
            WHERE m.id = %s
            GROUP BY m.id, m.nombre, m.logo_url, m.visible, m.destacada, m.orden
        """, (marca_id,)).fetchone()

        conn.commit()
        return dict(row) if row else {}


@router.post("/admin/marcas/merge")
@limiter.limit(ADMIN_WRITE_LIMIT)
def admin_merge_marcas(req: MarcaMergeRequest, request: Request):
    """Fusiona dos marcas duplicadas: reasigna todos los equipos de
    `source_id` a `target_id` (vía `brand_id` y `marca` TEXT) y borra source.
    Útil para consolidar "Red" + "RED DIGITAL CINEMA" → una sola marca.
    """
    require_admin(request)
    if req.source_id == req.target_id:
        raise HTTPException(400, "source_id y target_id no pueden ser iguales")
    with get_db() as conn:
        try:
            # Validar que ambas existen
            rows = conn.execute(
                "SELECT id, nombre FROM marcas WHERE id IN (%s, %s)",
                (req.source_id, req.target_id),
            ).fetchall()
            existing = {r["id"]: r["nombre"] for r in rows}
            if req.source_id not in existing:
                raise HTTPException(404, f"Marca source {req.source_id} no encontrada")
            if req.target_id not in existing:
                raise HTTPException(404, f"Marca target {req.target_id} no encontrada")

            target_nombre = existing[req.target_id]

            # Reasignar brand_id (FK) — único campo necesario. La columna
            # legacy `equipos.marca` (TEXT) fue dropeada por la migración
            # d5a8f2c4b6e9; el nombre se resuelve por subquery contra
            # `marcas.nombre` (ver MARCA_SUBQUERY en database.py).
            conn.execute(
                "UPDATE equipos SET brand_id = %s WHERE brand_id = %s",
                (req.target_id, req.source_id),
            )
            # Borrar la source
            conn.execute("DELETE FROM marcas WHERE id = %s", (req.source_id,))
            conn.commit()
            return {"ok": True, "merged_into": target_nombre}
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            logger.exception("Error al fusionar marcas")
            raise HTTPException(500, "No se pudieron fusionar las marcas")


@router.post("/admin/marcas/reorder")
@limiter.limit(ADMIN_WRITE_LIMIT)
def admin_reorder_marcas(req: MarcasReorderRequest, request: Request):
    """Actualiza el orden de múltiples marcas."""
    require_admin(request)
    with get_db() as conn:
        try:
            for item in req.marcas:
                marca_id = item.get("id")
                orden = item.get("orden")
                if marca_id is None or orden is None:
                    raise HTTPException(status_code=400, detail="Items deben tener 'id' y 'orden'")
                conn.execute("""
                    UPDATE marcas SET orden = %s, updated_at = NOW() WHERE id = %s
                """, (orden, marca_id))
            conn.commit()
            return {"ok": True}
        except Exception as e:
            conn.rollback()
            raise HTTPException(status_code=500, detail=str(e))


@router.delete("/admin/marcas/{marca_id}", status_code=204)
@limiter.limit(ADMIN_WRITE_LIMIT)
def admin_delete_marca(marca_id: int, request: Request):
    """Borra una marca. Rechaza si tiene equipos asociados — primero hay que
    fusionar (POST /admin/marcas/merge) o reasignar los equipos."""
    require_admin(request)
    with get_db() as conn:
        try:
            existing = conn.execute(
                "SELECT id, nombre FROM marcas WHERE id = %s", (marca_id,)
            ).fetchone()
            if not existing:
                raise HTTPException(404, "Marca no encontrada")

            count_row = conn.execute(
                "SELECT COUNT(*) AS n FROM equipos WHERE brand_id = %s", (marca_id,)
            ).fetchone()
            n = int(count_row["n"] if isinstance(count_row, dict) else count_row[0])
            if n > 0:
                raise HTTPException(
                    409,
                    f"La marca tiene {n} equipos asociados. Fusionala con otra o reasigná los equipos antes de borrar.",
                )

            conn.execute("DELETE FROM marcas WHERE id = %s", (marca_id,))
            conn.commit()
        except HTTPException:
            conn.rollback()
            raise


@router.post("/admin/marcas/{marca_id}/upload-logo")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
async def admin_upload_marca_logo(marca_id: int, request: Request):
    """Sube un logo (multipart/form-data, campo `file`) a R2 y persiste
    `logo_url` en la marca.

    - SVG: se sube tal cual (con sanitize defensivo de <script> y on*).
      Se sirve con `Content-Type: image/svg+xml`. El frontend puede
      inlinearlo para teñirlo via `currentColor`.
    - Raster (PNG/JPEG/WebP): pipeline no-destructivo — guarda original
      + variante display vía `store_upload`; actualiza `logo_url` y `media_id`.
    """
    require_admin(request)

    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise HTTPException(400, "Falta el campo 'file' en el form-data")

    raw_content = await file.read()
    if not raw_content:
        raise HTTPException(400, "Archivo vacío")
    if len(raw_content) > 5 * 1024 * 1024:
        raise HTTPException(413, "Logo muy grande (máx 5MB)")

    from services.media.svg import is_svg as _is_svg, sanitize_svg as _sanitize_svg

    filename = getattr(file, "filename", None)
    is_svg = _is_svg(raw_content, filename)

    with get_db() as conn:
        try:
            marca = conn.execute(
                "SELECT id, nombre FROM marcas WHERE id = %s", (marca_id,)
            ).fetchone()
            if not marca:
                raise HTTPException(404, "Marca no encontrada")
            nombre = marca["nombre"]

            if is_svg:
                from services.media.storage import put as _r2_put
                from services.media_fastapi import media_http
                content = _sanitize_svg(raw_content)
                path = _logo_path(marca_id, nombre, "svg")
                with media_http():
                    public_url = _r2_put(path, content, "image/svg+xml")
                conn.execute(
                    "UPDATE marcas SET logo_url = %s, updated_at = NOW() WHERE id = %s",
                    (public_url, marca_id),
                )
                conn.commit()
                return {
                    "public_url": public_url,
                    "path": path,
                    "size": len(content),
                    "size_original": len(raw_content),
                    "content_type": "image/svg+xml",
                    "width": None,
                    "height": None,
                }
            else:
                from services.media import DISPLAY_KEEP_ASPECT, DISPLAY_KEEP_ASPECT_SM, store_upload
                from services.media_fastapi import media_http
                with media_http():
                    asset = store_upload(
                        raw_content, kind="marca",
                        derive_specs=[DISPLAY_KEEP_ASPECT, DISPLAY_KEEP_ASPECT_SM],
                        conn=conn,
                    )
                display = asset.variant("display")
                display_sm = asset.variant("display-sm")
                conn.execute(
                    "UPDATE marcas SET logo_url = %s, logo_url_sm = %s, media_id = %s, "
                    "updated_at = NOW() WHERE id = %s",
                    (display.url, display_sm.url if display_sm else None, asset.id, marca_id),
                )
                conn.commit()
                return {
                    "public_url": display.url,
                    "public_url_sm": display_sm.url if display_sm else None,
                    "path": display.key,
                    "size": display.bytes,
                    "size_original": len(raw_content),
                    "content_type": display.content_type,
                    "width": display.width,
                    "height": display.height,
                }
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
