"""routes/dataio.py — Endpoints admin para export/import del catálogo y operacional.

Expone:
    GET /api/admin/dataio/entities
        Lista las entidades disponibles + a qué grupo pertenecen.

    GET /api/admin/dataio/export?entity=<name>|catalog-all|operacional-all|full
        Devuelve JSON individual (una entidad) o ZIP (grupos).
        - catalog-all: ZIP con las 8 entidades del catálogo.
        - operacional-all: ZIP con clientes + alquileres (datos privados).
        - full: ZIP con todo (catálogo + operacional).
        - equipos-csv|alquileres-csv|clientes-csv: planilla CSV plana.
        - csv-all: ZIP con las 3 planillas CSV.

    POST /api/admin/dataio/import?scope=operacional
        Sube un ZIP con clientes.json/alquileres.json para upsert. Solo
        operacional desde la UI (catálogo se importa al startup).
        Query param `dry_run=true` para simular.
"""

import io
import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from auth.guards import require_admin
from database import get_db
from dataio import orchestrator
from dataio.csv_exporters import CSV_EXPORTERS
from dataio.paths import BACKUP_GROUPS, CATALOG_ENTITIES, ENTITY_ORDER, OPERATIONAL_ENTITIES

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/admin/dataio/entities")
def list_entities(_admin: dict = Depends(require_admin)):
    """Lista las entidades disponibles agrupadas por scope."""
    return {
        "catalog": list(CATALOG_ENTITIES),
        "operacional": list(OPERATIONAL_ENTITIES),
        "all": list(ENTITY_ORDER),
    }


def _zip_response(zip_bytes: bytes, filename_prefix: str) -> StreamingResponse:
    ts = datetime.utcnow().strftime("%Y-%m-%d")
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename_prefix}-{ts}.zip"'
            )
        },
    )


@router.get("/admin/dataio/export")
def export_dataio(
    entity: str = Query("catalog-all", description="entidad o 'catalog-all'|'operacional-all'|'full'"),
    _admin: dict = Depends(require_admin),
):
    """Exporta una entidad como JSON, o un grupo como ZIP."""
    with get_db() as conn:
        # ── Grupos de backup de la UI: backup-<grupo> → un solo ZIP ──
        if entity.startswith("backup-"):
            grupo = entity[len("backup-"):]
            entities = BACKUP_GROUPS.get(grupo)
            if entities is None:
                raise HTTPException(
                    400,
                    f"Grupo de backup inválido: {grupo!r}. "
                    f"Válidos: {[f'backup-{g}' for g in BACKUP_GROUPS]}",
                )
            zip_bytes = orchestrator.export_to_zip_bytes(conn, list(entities))
            return _zip_response(zip_bytes, f"backup-{grupo}")

        if entity == "catalog-all":
            zip_bytes = orchestrator.export_to_zip_bytes(conn, list(CATALOG_ENTITIES))
            return _zip_response(zip_bytes, "catalogo")

        if entity == "operacional-all":
            zip_bytes = orchestrator.export_to_zip_bytes(conn, list(OPERATIONAL_ENTITIES))
            return _zip_response(zip_bytes, "backup")

        if entity == "full":
            zip_bytes = orchestrator.export_to_zip_bytes(conn, list(ENTITY_ORDER))
            return _zip_response(zip_bytes, "backup-full")

        # ── Planillas CSV planas (una hoja, lista para Excel) ──
        if entity == "csv-all":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, fn in CSV_EXPORTERS.items():
                    zf.writestr(f"{name}.csv", fn(conn))
            return _zip_response(buf.getvalue(), "planillas-csv")

        if entity.endswith("-csv"):
            name = entity[:-4]
            fn = CSV_EXPORTERS.get(name)
            if fn is None:
                raise HTTPException(
                    400,
                    f"Entidad CSV inválida: {entity!r}. "
                    f"Válidas: {[f'{k}-csv' for k in CSV_EXPORTERS] + ['csv-all']}",
                )
            ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            return Response(
                content=fn(conn),
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{name}-{ts}.csv"'
                },
            )

        if entity not in ENTITY_ORDER:
            raise HTTPException(
                400,
                f"Entidad inválida: {entity!r}. "
                f"Válidas: {list(ENTITY_ORDER) + ['catalog-all', 'operacional-all', 'full']}",
            )

        try:
            rows = orchestrator.export_entity(conn, entity)
        except Exception:
            logger.exception("export_entity falló para %r", entity)
            raise HTTPException(500, f"Export {entity} falló")

        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        return JSONResponse(
            content=rows,
            headers={
                "Content-Disposition": f'attachment; filename="{entity}-{ts}.json"'
            },
        )


# Scopes de import expuestos por la UI. Cada uno mapea a una lista de
# entidades. "operacional" se mantiene por compatibilidad (clientes+pedidos).
_IMPORT_SCOPES: dict[str, tuple[str, ...]] = {
    **BACKUP_GROUPS,  # configuracion, clientes, pedidos
    "operacional": OPERATIONAL_ENTITIES,
}


@router.post("/admin/dataio/import")
async def import_dataio(
    file: UploadFile = File(...),
    scope: str = Query(
        "configuracion",
        description="Grupo a restaurar: configuracion | clientes | pedidos.",
    ),
    dry_run: bool = Query(False, description="Simular sin commitear."),
    _admin: dict = Depends(require_admin),
):
    """Restaura (upsert) un ZIP con los JSONs de un grupo de backup.

    Scopes: `configuracion` (catálogo + specs + ajustes + mails + descuentos),
    `clientes`, `pedidos`. El upsert es por clave natural (no borra lo que no
    esté en el ZIP). Probar siempre con `dry_run=true` primero.
    """
    entities = _IMPORT_SCOPES.get(scope)
    if entities is None:
        raise HTTPException(
            400,
            f"Scope inválido: {scope!r}. Válidos: {list(_IMPORT_SCOPES)}",
        )
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Solo archivos .zip permitidos")
    content = await file.read()
    if not content:
        raise HTTPException(400, "Archivo vacío")

    with get_db() as conn:
        try:
            # Hook para imports de migracion (ej. Booqable). Si el ZIP trae
            # un `placeholders_equipos.json`, creamos esos equipos antes
            # de importar alquileres para que las FKs resuelvan. Idempotente.
            placeholders_created = _create_placeholder_equipos(conn, content)

            stats = orchestrator.import_from_zip_bytes(
                conn,
                content,
                only=list(entities),
                dry_run=dry_run,
            )

            # Bumpear secuencias operacionales post-import para que nuevos pedidos
            # manuales no colisionen con los importados. Idempotente. Solo si se
            # tocaron clientes o pedidos.
            sequences_bumped = []
            toco_operacional = (
                stats.get("alquileres", {}).get("inserted", 0) > 0
                or stats.get("clientes", {}).get("inserted", 0) > 0
            )
            if not dry_run and toco_operacional:
                sequences_bumped = _bump_operacional_sequences(conn)

            if not dry_run:
                conn.commit()
            return {
                "ok": True,
                "dry_run": dry_run,
                "stats": stats,
                "total_inserted": sum(s.get("inserted", 0) for s in stats.values()),
                "total_updated": sum(s.get("updated", 0) for s in stats.values()),
                "placeholders_creados": placeholders_created,
                "sequences_bumped": sequences_bumped,
            }
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise HTTPException(400, f"Import falló: {e}")


def _create_placeholder_equipos(conn, zip_bytes: bytes) -> int:
    """Si el ZIP trae `placeholders_equipos.json`, inserta esos equipos
    como historicos (cantidad=0, visible_catalogo=0, estado='historico').
    Idempotente: ON CONFLICT (slug) DO NOTHING.

    Pensado para wipe-and-reimport desde sistemas externos (ej. Booqable)
    donde hay items historicos sin equivalente en el catalogo activo.
    """
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if Path(name).name != "placeholders_equipos.json":
                    continue
                placeholders = json.loads(zf.read(name).decode("utf-8"))
                break
            else:
                return 0
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError):
        return 0

    if not isinstance(placeholders, list):
        return 0

    # El UNIQUE de equipos.slug puede ser un constraint completo (migracion
    # f5b8d2e4a9c1) o un partial index "WHERE slug IS NOT NULL" (migracion
    # e4a7c1f8d6b2 sin la siguiente, o el self-heal de export_equipos).
    # ON CONFLICT con partial index requiere WHERE explicito que coincida.
    # Probamos primero con WHERE; si falla, fallback al constraint completo.
    created = 0
    for p in placeholders:
        slug = (p.get("slug") or "").strip()
        nombre = (p.get("nombre") or "").strip()
        if not slug or not nombre:
            continue
        # Idempotencia manual: chequear antes de insertar. Es 2 queries por
        # placeholder, pero los datasets son chicos (<100) y evita el
        # quilombo del ON CONFLICT con partial vs full index.
        exists = conn.execute(
            "SELECT 1 FROM equipos WHERE slug = %s LIMIT 1", (slug,)
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """
            INSERT INTO equipos (slug, nombre, cantidad, visible_catalogo, estado)
            VALUES (%s, %s, 0, 0, 'historico')
            """,
            (slug, nombre),
        )
        created += 1
    return created


def _bump_operacional_sequences(conn) -> list[str]:
    """Despues de un import masivo, sube las secuencias al MAX actual.

    Sin esto, nuevos pedidos manuales agarrarian numero_pedido=1 y
    colisionarian con los importados. Idempotente.
    """
    bumped = []
    for seq, table, col in (
        ("alquileres_id_seq", "alquileres", "id"),
        ("alquiler_items_id_seq", "alquiler_items", "id"),
        ("alquiler_pagos_id_seq", "alquiler_pagos", "id"),
        ("clientes_id_seq", "clientes", "id"),
        ("numero_pedido_seq", "alquileres", "numero_pedido"),
    ):
        try:
            conn.execute(
                f"SELECT setval('{seq}', GREATEST(1, "
                f"(SELECT COALESCE(MAX({col}), 0) FROM {table})), true)"
            )
            bumped.append(seq)
        except Exception as e:
            logger.warning("setval %s fallo (no critico): %s", seq, e)
    return bumped


RESET_CONFIRMATION = "BORRAR TODO"

# Secuencias a resetear despues del wipe operacional. Sin reset, los IDs
# de la siguiente import continuarian desde el MAX previo (ej. importar
# desde Booqable arrancaria en id=500 en vez de 1).
_OPERACIONAL_SEQUENCES = (
    "clientes_id_seq",
    "alquileres_id_seq",
    "alquiler_items_id_seq",
    "alquiler_pagos_id_seq",
    "numero_pedido_seq",
)


@router.post("/admin/dataio/reset-operacional")
def reset_operacional(
    payload: dict = Body(...),
    _admin: dict = Depends(require_admin),
):
    """Borra TODOS los clientes y alquileres (incluidos items/pagos via CASCADE).

    Pensado para hacer un wipe-and-reimport limpio. Requiere que el body
    incluya exactamente {"confirm": "BORRAR TODO"} para evitar disparos
    accidentales. La operacion no es reversible — hacer backup antes.

    Tambien resetea las secuencias de IDs operacionales a 1 para que la
    siguiente import arranque desde cero (clientes, alquileres y sus
    tablas hijas, mas numero_pedido_seq).
    """
    if payload.get("confirm") != RESET_CONFIRMATION:
        raise HTTPException(
            400,
            f"Confirmacion requerida. Enviar {{'confirm': '{RESET_CONFIRMATION}'}}",
        )

    with get_db() as conn:
        try:
            clientes_before = conn.execute("SELECT COUNT(*) AS n FROM clientes").fetchone()["n"]
            alquileres_before = conn.execute("SELECT COUNT(*) AS n FROM alquileres").fetchone()["n"]

            # alquileres primero: CASCADE limpia items y pagos.
            conn.execute("DELETE FROM alquileres")
            conn.execute("DELETE FROM clientes")

            for seq in _OPERACIONAL_SEQUENCES:
                conn.execute(f"ALTER SEQUENCE IF EXISTS {seq} RESTART WITH 1")

            conn.commit()

            return {
                "ok": True,
                "deleted": {
                    "clientes": clientes_before,
                    "alquileres": alquileres_before,
                },
                "sequences_reset": list(_OPERACIONAL_SEQUENCES),
            }
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("Reset de la base operacional falló")
            raise HTTPException(500, "Reset falló")
