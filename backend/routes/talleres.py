"""
routes/talleres.py — Workshops públicos: listing, detalle, inscripción + notificaciones.
Vista admin: conceptos de taller con ediciones anidadas, upload comprobante/foto.

Modelo de tres capas (F3):
  talleres          = concepto (datos estables: nombre, bio, programa)
  ediciones_taller  = una fila por edición (fechas, precios, cupos, freeze)
  clases_taller     = clases de cada edición (reemplaza taller_sesiones)
  interesados_taller= leads cuando no hay cupos disponibles
"""

import csv
import io
import logging
import time
import uuid
import json as _json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pydantic import BaseModel, EmailStr, Field

from auth.guards import require_admin
from config import SITE_URL, settings
from database import get_db, now_ar
from rate_limit import limiter, ADMIN_WRITE_LIMIT, ADMIN_UPLOAD_LIMIT
from dataio.slug import slugify, slug_unico
from routes.alquileres import _next_numero_pedido
from services.email import Attachment, send_email
from services.fechas import fmt_fecha_es as _fmt_fecha_es
from services.email.service import get_admin_tos
from services.ical import clases_taller_to_ics
from services.media.models import DeriveSpec
from services.media.errors import MediaError
from services.media.service import store_upload, store_raw_document
from services.media.youtube import extract_video_id, youtube_nocookie_url, store_youtube_poster
from services.media import (
    DISPLAY_KEEP_ASPECT,
    DISPLAY_KEEP_ASPECT_AVIF,
    DISPLAY_KEEP_ASPECT_SM,
    DISPLAY_KEEP_ASPECT_SM_AVIF,
    collect_asset_keys,
    purge_r2,
)
from services.media_fastapi import media_http
from services import telefono as telefono_svc
# Lógica de decisión duplicada/compartida extraída a services/talleres/
# (CQRS-lite): gate de conflicto con Estudio, creación de edición, validación
# de clases/modalidades, economía. Este route queda como transporte fino para
# esa porción — perfil/lectura/serialización, instructores/instituciones/
# trabajos/portada e inscripción/seña (Fase 2, diferida) siguen acá. Ver
# services/talleres/CLAUDE.md.
from services.talleres.queries.clases import (
    _row_get,
    _validar_clases,
    _validar_cuentas_pago,
    _validar_modalidades,
    clases_de_edicion as _get_clases,
)
from services.talleres.commands.clases import (
    _upsert_clases,
    _upsert_cuentas_pago,
    _upsert_modalidades,
)
from services.talleres.commands.ediciones import _gate_conflicto_estudio, crear_edicion
from services.talleres.commands.economia import _regenerar_pedidos_taller
from services.talleres.queries.economia import _revenue_inscriptos, _valor_efectivo
from services.talleres_borrador import (
    heartbeat_upsert as _borrador_heartbeat_upsert,
    listar_borradores_admin as _listar_borradores_admin,
    marcar_confirmado as _borrador_marcar_confirmado,
)

logger = logging.getLogger(__name__)

router = APIRouter()

COMPROBANTE_MAX_MB = 10
FOTO_MAX_MB = 8

# F4b: link de "completá tu seña" tras ofrecer un cupo liberado. NO es un
# nonce single-use en tabla aparte (patrón auth/commands/magic.py) — el gate
# real es el ESTADO de la inscripción (`estado == 'cupo_ofrecido'`): una vez
# reclamado, el estado cambia y el mismo token ya no sirve, sin necesitar una
# tabla de challenges. `max_age` es un techo de higiene, no el control de
# negocio — "sin expiración automática" (el admin re-ofrece a mano) sigue
# siendo cierto porque el admin puede re-ofrecer mucho antes de este techo.
_CUPO_TOKEN_MAX_AGE = 60 * 60 * 24 * 30  # 30 días
_cupo_signer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="taller-cupo-ofrecido")


def _generar_token_cupo(inscripcion_id: int) -> str:
    return _cupo_signer.dumps({"insid": inscripcion_id})


def _leer_token_cupo(token: str) -> int | None:
    try:
        data = _cupo_signer.loads(token, max_age=_CUPO_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    insid = data.get("insid") if isinstance(data, dict) else None
    return insid if isinstance(insid, int) else None


def _fmt_pesos(n: int) -> str:
    return "$" + f"{n:,}".replace(",", ".")


def _monto_por_cuota(monto_total: int, n_cuotas: int) -> int:
    """Monto de UNA cuota — derivado de `monto_total`/`n_cuotas`, redondeado
    al peso. Es texto informativo ("N cuotas de $X"), no una cobranza real
    (la seña/comprobante siguen siendo el mecanismo de pago) — por eso
    redondeo simple en vez del reparto con remanente-en-la-última-cuota que
    usa `services/talleres/commands/economia.py::_partes` para plata real."""
    return round(monto_total / n_cuotas)


# ── Helpers de lectura ────────────────────────────────────────────────────────

_EDICION_JOIN_SELECT = """
    SELECT e.*, t.nombre, t.subtitulo, t.descripcion, t.resumen,
           t.publico_objetivo, t.notif_email,
           t.slug_base, t.terminos, t.beneficios, t.pregunta_experiencia,
           t.mensaje_confirmacion, t.video_url, t.video_poster_url, t.faqs
    FROM ediciones_taller e
    JOIN talleres t ON t.id = e.taller_id
"""


def _get_edicion_row(conn, slug: str, incluir_borrador: bool = False):
    """Busca una edición activa por slug. Lanza 404 si no existe.
    `incluir_borrador=True` (SOLO preview admin, F2): también sirve ediciones
    despublicadas — el caller es responsable de haber verificado la sesión."""
    filtro_activo = "" if incluir_borrador else "AND e.activo = TRUE"
    row = conn.execute(
        f"{_EDICION_JOIN_SELECT} WHERE e.slug = %s {filtro_activo}",
        (slug,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Taller no encontrado")
    return row


def _instructor_dict(row) -> dict:
    return {
        "id": row["id"],
        "nombre": row["nombre"],
        "rol": row["rol"],
        "descripcion": row["descripcion"],
        "instagram": row["instagram"],
        "web": row["web"],
        "foto_url": row["foto_url"] or "",
        "foto_media_id": row["foto_media_id"],
        # F6: "Trabajó con" — reemplaza el legacy `talleres.instructor_proyectos`
        # (1 por taller); ahora es propio de cada instructor.
        "proyectos": _row_get(row, "proyectos", ""),
    }


def _get_instructores_taller(conn, taller_id: int) -> list[dict]:
    """Instructores de un taller (F3), ordenados. Fuente única desde F6 (los
    campos legacy `talleres.instructor_*` que precedían a esto ya no existen)."""
    rows = conn.execute(
        "SELECT i.* FROM instructores i "
        "JOIN taller_instructores ti ON ti.instructor_id = i.id "
        "WHERE ti.taller_id = %s ORDER BY ti.orden, i.id",
        (taller_id,),
    ).fetchall()
    return [_instructor_dict(r) for r in rows]


def _institucion_dict(row) -> dict:
    return {
        "id": row["id"],
        "nombre": row["nombre"],
        "descripcion": row["descripcion"],
        "instagram": row["instagram"],
        "web": row["web"],
        "logo_url": row["logo_url"] or "",
        "logo_media_id": row["logo_media_id"],
    }


def _get_instituciones_taller(conn, taller_id: int) -> list[dict]:
    """Instituciones co-presentadoras de un taller (ej. "Rambla" + "Filmar"),
    ordenadas. Mismo patrón que _get_instructores_taller."""
    rows = conn.execute(
        "SELECT ins.* FROM instituciones ins "
        "JOIN taller_instituciones ti ON ti.institucion_id = ins.id "
        "WHERE ti.taller_id = %s ORDER BY ti.orden, ins.id",
        (taller_id,),
    ).fetchall()
    return [_institucion_dict(r) for r in rows]


def _trabajo_dict(row) -> dict:
    return {
        "id": row["id"],
        "titulo": row["titulo"],
        "youtube_url": row["youtube_url"],
        "poster_url": row["poster_url"] or "",
        "poster_media_id": row["poster_media_id"],
    }


def _get_trabajos_taller(conn, taller_id: int) -> list[dict]:
    """Trabajos pasados (F4c) — solo links de YouTube, sin testimonios/
    reseñas (decisión del dueño). Prueba social de una escuela de cine."""
    rows = conn.execute(
        "SELECT * FROM taller_trabajos WHERE taller_id = %s ORDER BY orden, id",
        (taller_id,),
    ).fetchall()
    return [_trabajo_dict(r) for r in rows]


def _modalidad_dict(row) -> dict:
    """F4a: una modalidad de pago (row de DB o dict normalizado de
    _validar_modalidades). `monto_total_str` resuelto acá — el front no
    formatea plata a mano. `monto_cuota`/`monto_cuota_str` = `monto_total`
    derivado por `n_cuotas` (default 1, pago único) — el público nunca ve
    un monto por cuota tipeado a mano, solo el calculado."""
    monto = _row_get(row, "monto_total", 0) or 0
    n_cuotas = _row_get(row, "n_cuotas", 1) or 1
    monto_cuota = _monto_por_cuota(monto, n_cuotas)
    return {
        "id": _row_get(row, "id"),
        "codigo": row["codigo"],
        "label": row["label"],
        "nota": _row_get(row, "nota", ""),
        "monto_total": monto,
        "monto_total_str": _fmt_pesos(monto),
        "n_cuotas": n_cuotas,
        "monto_cuota": monto_cuota,
        "monto_cuota_str": _fmt_pesos(monto_cuota),
    }


def _get_modalidades(conn, edicion_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, codigo, label, nota, monto_total, n_cuotas FROM edicion_modalidades_pago "
        "WHERE edicion_id = %s ORDER BY orden, id",
        (edicion_id,),
    ).fetchall()
    return [_modalidad_dict(r) for r in rows]


def _modalidades_publicas(modalidades: list[dict] | None, precio_total: int) -> list[dict]:
    """Shape público de las modalidades: sin ninguna configurada, sintetiza 1
    sola opción ("Pago total" = precio_total) — cero ruptura para ediciones
    que nunca las configuran (Jime)."""
    if modalidades:
        return modalidades
    return [_modalidad_dict({"codigo": "total", "label": "Pago total", "nota": "", "monto_total": precio_total})]


def _cuenta_pago_dict(row) -> dict:
    """Una cuenta de cobro (row de DB o dict normalizado de
    _validar_cuentas_pago) — sin plata derivada, passthrough directo."""
    return {
        "id": _row_get(row, "id"),
        "alias": _row_get(row, "alias", ""),
        "cbu": _row_get(row, "cbu", ""),
        "banco": _row_get(row, "banco", ""),
    }


def _get_cuentas_pago(conn, edicion_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, alias, cbu, banco FROM edicion_cuentas_pago "
        "WHERE edicion_id = %s ORDER BY orden, id",
        (edicion_id,),
    ).fetchall()
    return [_cuenta_pago_dict(r) for r in rows]


def _cuentas_pago_para_mail(cuentas: list[dict]) -> tuple[str, str]:
    """Fragmentos (HTML + texto plano) de "Datos de pago" para el mail de
    inscripción (`taller_inscripcion_cliente`) — inyectados con `{{
    cuentas_pago_html|safe }}`/`{{ cuentas_pago_text }}`, mismo patrón que
    `items_html`/`items_text` en `services/comunicacion/despacho.py` (evita
    loopear en Jinja: sin `trim_blocks`, un `{% for %}` en el body de texto
    plano deja saltos de línea sueltos que sí se ven en un mail).

    Mismo criterio que `DatosPago`/`UnaCuenta` del frontend
    (`frontend/src/components/talleres/WorkshopInscripcionForm.tsx`): salta
    los campos vacíos (nunca un separador colgando) — con 1 sola cuenta (el
    caso común) el render queda igual al de siempre; con 2+, un bloque por
    cuenta. Values escapados a mano (mismo patrón que
    `services/comunicacion/despacho.py`) — el HTML se inyecta con `|safe`,
    así que no pasa por el autoescape de Jinja."""
    from markupsafe import escape

    con_datos = [c for c in cuentas if c.get("alias") or c.get("cbu") or c.get("banco")]
    if not con_datos:
        return "", ""

    bloques_html, bloques_text = [], []
    for c in con_datos:
        campos = [
            (label, valor)
            for label, valor in (("Alias", c.get("alias")), ("CBU", c.get("cbu")), ("Banco", c.get("banco")))
            if valor
        ]
        bloques_html.append(
            "<br>".join(f"<strong>{label}:</strong> {escape(valor)}" for label, valor in campos)
        )
        bloques_text.append("\n".join(f"  {label}: {valor}" for label, valor in campos))

    html = "".join(f'<p style="margin:0 0 4px;">{b}</p>' for b in bloques_html)
    text = "\n\n".join(bloques_text)
    return html, text


def _cuentas_pago_efectivas(
    cuentas: list[dict], *, pago_alias: str, pago_cbu: str, pago_banco: str
) -> list[dict]:
    """`cuentas` (de `_get_cuentas_pago`) si trae algo; si no, una sintetizada
    desde los 3 campos viejos — defensa en profundidad para una edición que,
    por lo que sea, no pasó por el traspaso de `crear_edicion`/la migración
    `cu3nt4sp4g0`. No debería hacer falta en el camino normal."""
    if cuentas:
        return cuentas
    if pago_alias or pago_cbu or pago_banco:
        return [{"alias": pago_alias, "cbu": pago_cbu, "banco": pago_banco}]
    return []


def _video_dict(row) -> dict | None:
    """Shape público del video hero: None si no hay URL o no se pudo extraer
    un video_id (URL mal pegada) — la landing no debe romper por esto."""
    url = _row_get(row, "video_url", "")
    if not url:
        return None
    vid = extract_video_id(url)
    if not vid:
        return None
    return {
        "youtube_id": vid,
        "embed_url": youtube_nocookie_url(vid),
        "poster": _row_get(row, "video_poster_url", "") or None,
    }


def _edicion_lite(row) -> dict:
    """Datos mínimos de una edición para mostrar en el contexto de otra."""
    return {
        "slug": row["slug"],
        "numero_edicion": row["numero_edicion"],
        "fecha_inicio": str(row["fecha_inicio"]),
        "fecha_fin": str(row["fecha_fin"]),
        "horario": row["horario"],
        "cupos_total": row["cupos_total"],
        "cupos_confirmados": row["cupos_confirmados"],
        "cupos_disponibles": max(0, row["cupos_total"] - row["cupos_confirmados"]),
        "precio_total": row["precio_total"],
        "precio_sena": row["precio_sena"],
        "pago_alias": row["pago_alias"],
        "pago_cbu": row["pago_cbu"],
        "pago_banco": row["pago_banco"],
        "direccion": row["direccion"],
    }


def _edicion_to_public_dict(
    row, clases=None, instructores=None, modalidades=None, trabajos=None, instituciones=None,
    fotos=None, cuentas_pago=None,
) -> dict:
    """Convierte edicion_row (JOIN talleres) al shape plano del API público."""
    return {
        "id": row["id"],
        "taller_id": row["taller_id"],
        "slug": row["slug"],
        "nombre": row["nombre"],
        "subtitulo": row["subtitulo"],
        "descripcion": row["descripcion"],
        # F7: resumen corto para la tarjeta del listado (mezcla "para quién" +
        # "de qué trata" — la descripción completa no sirve truncada, arranca
        # dirigiéndose al lector en vez de explicar el taller). '' = el front
        # cae a la descripción truncada (cero ruptura para talleres viejos que
        # nunca lo cargaron).
        "resumen": _row_get(row, "resumen", ""),
        "publico_objetivo": row["publico_objetivo"],
        "fecha_inicio": str(row["fecha_inicio"]),
        "fecha_fin": str(row["fecha_fin"]),
        "horario": row["horario"],
        "cupos_total": row["cupos_total"],
        "cupos_confirmados": row["cupos_confirmados"],
        "cupos_disponibles": max(0, row["cupos_total"] - row["cupos_confirmados"]),
        "precio_total": row["precio_total"],
        "precio_sena": row["precio_sena"],
        "pago_alias": row["pago_alias"],
        "pago_cbu": row["pago_cbu"],
        "pago_banco": row["pago_banco"],
        "direccion": row["direccion"],
        "activo": bool(row["activo"]),
        "tipo_taller": row["tipo_taller"],
        "numero_edicion": row["numero_edicion"],
        "frozen_at": row["frozen_at"].isoformat() if row["frozen_at"] else None,
        # F2: textos del concepto que consume la landing/form
        "terminos": _row_get(row, "terminos", ""),
        "beneficios": _row_get(row, "beneficios", ""),
        "pregunta_experiencia": _row_get(row, "pregunta_experiencia", ""),
        "mensaje_confirmacion": _row_get(row, "mensaje_confirmacion", ""),
        # F2 preview admin: True cuando se sirve una edición despublicada
        "borrador": not bool(row["activo"]),
        # F3: instructores como entidad (además de los campos legacy arriba,
        # servidos en paralelo hasta F6).
        "instructores": instructores if instructores is not None else [],
        # Instituciones co-presentadoras (ej. "Rambla" + "Filmar") — mismo
        # patrón que instructores.
        "instituciones": instituciones if instituciones is not None else [],
        # sesiones = backward compat con el frontend (lee de clases_taller)
        "sesiones": clases if clases is not None else [],
        # F4a: video hero del concepto + modalidades de pago (con fallback
        # sintético — ver _modalidades_publicas).
        "video": _video_dict(row),
        "modalidades": _modalidades_publicas(modalidades, row["precio_total"]),
        # Cuentas de cobro (alias/cbu/banco) — lista, independiente de la
        # modalidad de pago (el público ve todas, elige a cuál transferir).
        # Sin fallback sintético: [] = sin cuentas cargadas.
        "cuentas_pago": cuentas_pago if cuentas_pago is not None else [],
        # F4c: FAQ del concepto + cierre de inscripciones de ESTA edición +
        # trabajos pasados del concepto (solo YouTube, sin testimonios —
        # antes solo se servían al admin; F5 los muestra públicamente).
        "faqs": _row_get(row, "faqs", []) or [],
        "fecha_cierre_inscripcion": (
            str(row["fecha_cierre_inscripcion"]) if _row_get(row, "fecha_cierre_inscripcion") else None
        ),
        "trabajos": trabajos if trabajos is not None else [],
        # Portada + galería de ESTA edición (no del concepto) — confirmado con
        # el dueño: cada edición tiene su propia tanda de fotos.
        "fotos": fotos if fotos is not None else [],
    }


def _edicion_to_admin_dict(
    edicion_row, clases=None, modalidades=None, fotos=None, cuentas_pago=None,
    inscriptos_revenue: int = 0,
) -> dict:
    """Convierte una fila de ediciones_taller al shape de admin (anidado en concepto)."""
    return {
        "id": edicion_row["id"],
        "taller_id": edicion_row["taller_id"],
        "numero_edicion": edicion_row["numero_edicion"],
        "slug": edicion_row["slug"],
        "tipo_taller": edicion_row["tipo_taller"],
        "fecha_inicio": str(edicion_row["fecha_inicio"]),
        "fecha_fin": str(edicion_row["fecha_fin"]),
        "horario": edicion_row["horario"],
        "cupos_total": edicion_row["cupos_total"],
        "cupos_confirmados": edicion_row["cupos_confirmados"],
        "cupos_disponibles": max(0, edicion_row["cupos_total"] - edicion_row["cupos_confirmados"]),
        "precio_total": edicion_row["precio_total"],
        "precio_sena": edicion_row["precio_sena"],
        "pago_alias": edicion_row["pago_alias"],
        "pago_cbu": edicion_row["pago_cbu"],
        "pago_banco": edicion_row["pago_banco"],
        "direccion": edicion_row["direccion"],
        "activo": bool(edicion_row["activo"]),
        "frozen_at": edicion_row["frozen_at"].isoformat() if edicion_row["frozen_at"] else None,
        "clases": clases if clases is not None else [],
        # F4a: modalidades RAW (sin fallback sintético — el admin ve el
        # estado real: lista vacía = "no configuradas todavía").
        "modalidades": modalidades if modalidades is not None else [],
        # Cuentas de cobro RAW — mismo criterio que modalidades arriba.
        "cuentas_pago": cuentas_pago if cuentas_pago is not None else [],
        # F4c: NULL = sin cierre (default, siempre abierto).
        "fecha_cierre_inscripcion": (
            str(edicion_row["fecha_cierre_inscripcion"])
            if _row_get(edicion_row, "fecha_cierre_inscripcion") else None
        ),
        "usa_estudio": bool(edicion_row["usa_estudio"]),
        "valor_estudio": edicion_row["valor_estudio"],
        "valor_estudio_modo": edicion_row["valor_estudio_modo"],
        "valor_estudio_tipo": edicion_row["valor_estudio_tipo"],
        "valor_estudio_pct": edicion_row["valor_estudio_pct"],
        "usa_equipos": bool(edicion_row["usa_equipos"]),
        "valor_equipos": edicion_row["valor_equipos"],
        "valor_equipos_modo": edicion_row["valor_equipos_modo"],
        "valor_equipos_tipo": edicion_row["valor_equipos_tipo"],
        "valor_equipos_pct": edicion_row["valor_equipos_pct"],
        # Preview resuelto por el backend (nunca el front): cuánto pagan HOY
        # los inscriptos no en lista de espera + el valor efectivo que
        # `_regenerar_pedidos_taller` aplicaría con la config actual — en
        # 'fijo' es un espejo de `valor_estudio`/`valor_equipos`, en
        # 'porcentaje' es `revenue * pct / 100` ya calculado.
        "inscriptos_revenue": inscriptos_revenue,
        "valor_estudio_efectivo": _valor_efectivo(
            edicion_row["valor_estudio_tipo"], edicion_row["valor_estudio"],
            edicion_row["valor_estudio_pct"], inscriptos_revenue,
        ),
        "valor_equipos_efectivo": _valor_efectivo(
            edicion_row["valor_equipos_tipo"], edicion_row["valor_equipos"],
            edicion_row["valor_equipos_pct"], inscriptos_revenue,
        ),
        "fotos": fotos if fotos is not None else [],
    }


def _concepto_to_admin_dict(
    taller_row, ediciones=None, instructores=None, trabajos=None, instituciones=None,
) -> dict:
    """Convierte una fila de talleres (concepto) al shape admin con ediciones anidadas."""
    return {
        "id": taller_row["id"],
        "slug_base": taller_row["slug_base"] or taller_row["slug"],
        "nombre": taller_row["nombre"],
        "subtitulo": taller_row["subtitulo"],
        "descripcion": taller_row["descripcion"],
        "resumen": _row_get(taller_row, "resumen", ""),
        "publico_objetivo": taller_row["publico_objetivo"],
        "notif_email": taller_row["notif_email"],
        "terminos": _row_get(taller_row, "terminos", ""),
        "beneficios": _row_get(taller_row, "beneficios", ""),
        "pregunta_experiencia": _row_get(taller_row, "pregunta_experiencia", ""),
        "mensaje_confirmacion": _row_get(taller_row, "mensaje_confirmacion", ""),
        "video_url": _row_get(taller_row, "video_url", ""),
        "video_poster_url": _row_get(taller_row, "video_poster_url", ""),
        "instructores": instructores if instructores is not None else [],
        "instituciones": instituciones if instituciones is not None else [],
        "ediciones": ediciones if ediciones is not None else [],
        # F4c: FAQ del concepto + trabajos pasados (solo YouTube, sin testimonios).
        "faqs": _row_get(taller_row, "faqs", []) or [],
        "trabajos": trabajos if trabajos is not None else [],
    }


# ── Endpoints públicos ────────────────────────────────────────────────────────

@router.get("/talleres")
def list_talleres():
    """Lista todas las ediciones activas de talleres (una card por edición)."""
    with get_db() as conn:
        rows = conn.execute(
            f"{_EDICION_JOIN_SELECT} WHERE e.activo = TRUE ORDER BY e.fecha_inicio",
        ).fetchall()
        return [
            _edicion_to_public_dict(
                r, _get_clases(conn, r["id"]), _get_instructores_taller(conn, r["taller_id"]),
                _get_modalidades(conn, r["id"]),
                instituciones=_get_instituciones_taller(conn, r["taller_id"]),
                fotos=_get_edicion_fotos(conn, r["id"]),
                cuentas_pago=_get_cuentas_pago(conn, r["id"]),
            )
            for r in rows
        ]


@router.get("/talleres/{slug}")
def get_taller(slug: str, request: Request):
    """Detalle de una edición de taller. Incluye proxima_edicion y edicion_anterior.

    F2 borradores: una edición despublicada da 404 al público, pero se sirve a
    una SESIÓN ADMIN (preview del "ver en web" mientras se arma el taller) con
    `borrador: true` — el front muestra el banner "solo visible para vos"."""
    from auth.guards import is_admin_email
    from auth.session import dev_bypass_enabled, get_session

    session = get_session(request)
    es_admin = dev_bypass_enabled() or bool(session and is_admin_email(session.get("email")))
    with get_db() as conn:
        row = _get_edicion_row(conn, slug, incluir_borrador=es_admin)
        d = _edicion_to_public_dict(
            row, _get_clases(conn, row["id"]), _get_instructores_taller(conn, row["taller_id"]),
            _get_modalidades(conn, row["id"]), _get_trabajos_taller(conn, row["taller_id"]),
            instituciones=_get_instituciones_taller(conn, row["taller_id"]),
            fotos=_get_edicion_fotos(conn, row["id"]),
            cuentas_pago=_get_cuentas_pago(conn, row["id"]),
        )

        # Próxima edición: misma concepto (taller_id), numero_edicion mayor
        pr = conn.execute(
            """
            SELECT * FROM ediciones_taller
            WHERE taller_id = %s AND numero_edicion > %s AND activo = TRUE
            ORDER BY numero_edicion ASC LIMIT 1
            """,
            (row["taller_id"], row["numero_edicion"]),
        ).fetchone()
        d["proxima_edicion"] = _edicion_lite(pr) if pr else None

        # Edición anterior: mismo concepto, numero_edicion menor
        ant = conn.execute(
            """
            SELECT * FROM ediciones_taller
            WHERE taller_id = %s AND numero_edicion < %s AND activo = TRUE
            ORDER BY numero_edicion DESC LIMIT 1
            """,
            (row["taller_id"], row["numero_edicion"]),
        ).fetchone()
        d["edicion_anterior"] = _edicion_lite(ant) if ant else None
    return d


async def _procesar_upload_comprobante(request: Request, ref: str) -> dict:
    """Recibe el comprobante de pago (multipart, campo 'file') y lo sube a R2
    privado. Compartido por el upload del form de inscripción (slug) y el de
    la página de seña (token) — misma validación, distinto `ref` de storage."""
    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise HTTPException(400, "Falta el campo 'file' en el form-data")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Archivo vacío")
    if len(raw) > COMPROBANTE_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"Archivo muy grande (máx {COMPROBANTE_MAX_MB} MB)")

    content_type = getattr(file, "content_type", None) or "application/octet-stream"

    try:
        key, url = store_raw_document(raw, kind="comprobante-taller", ref=ref, content_type=content_type)
    except MediaError as e:
        raise HTTPException(e.status, e.detail)
    except Exception as e:
        logger.error("_procesar_upload_comprobante: error inesperado: %s", e, exc_info=True)
        raise HTTPException(502, "No se pudo subir el archivo. Intentá de nuevo.")

    return {"url": url, "key": key}


@router.post("/talleres/{slug}/upload-comprobante")
@limiter.limit("20/minute")
async def upload_comprobante(slug: str, request: Request):
    """Recibe el comprobante de pago del form de inscripción normal."""
    with get_db() as conn:
        _get_edicion_row(conn, slug)
    ts = int(time.time() * 1000)
    uid = uuid.uuid4().hex[:8]
    return await _procesar_upload_comprobante(request, ref=f"{slug}-{ts}-{uid}")


class InscripcionBody(BaseModel):
    nombre: str
    email: EmailStr
    telefono: str
    experiencia: str | None = None
    comprobante_url: str | None = None
    comprobante_key: str | None = None
    # F2: checkbox "Acepto los términos" del form v2. CABLEADO-APAGADO: se
    # registra si viene, pero NO se exige hasta que el form nuevo (F5) mande
    # el campo — exigirlo hoy rompería el form actual (patrón #1125/#1126).
    acepta_terminos: bool = False
    # F4a: modalidad de pago elegida (código de edicion_modalidades_pago).
    # CABLEADO-APAGADO: el form v1 no manda el campo — default a la primera
    # modalidad configurada (o al fallback sintético "Pago total").
    modalidad_codigo: str | None = None
    # session_id del heartbeat de borrador (services.talleres_borrador) — si
    # viene, cierra ese funnel al confirmarse la inscripción real. Opcional:
    # un front viejo sin el heartbeat wireado sigue funcionando igual.
    session_id: str | None = None


class InscripcionBorradorBody(BaseModel):
    session_id: str
    nombre: str | None = None
    email: str | None = None
    telefono: str | None = None


def _comprobante_url_fresca(key: str | None, fallback_url: str | None) -> str:
    """Re-firma la URL del comprobante AL MOMENTO de servirla — la que devuelve
    `store_raw_document` al subir vence a las 24hs (`presign_expires`) y NO se
    puede guardar tal cual para acceso futuro (bug real: la lista de
    inscripciones del admin devolvía `comprobante_url` crudo de la base,
    rompiendo con `ExpiredRequest` apenas pasaban 24hs desde la subida). La
    key SÍ es estable — se re-firma desde ahí cada vez que hace falta mostrar
    el comprobante (acá, en el mail de confirmación, o donde surja después)."""
    if key:
        try:
            from services.media.storage import presigned_url as _presigned
            return _presigned(key, expires_seconds=86400, private=True)
        except Exception as e:
            logger.warning("_comprobante_url_fresca: no se pudo generar presigned: %s", e)
    return fallback_url or ""


def _ics_adjunto_taller(
    *, taller_nombre: str, direccion: str | None, slug: str, clases: list[dict],
) -> list[Attachment] | None:
    """Adjunto `.ics` del mail de inscripción confirmada — reemplaza el botón
    "Agregar a mi calendario" que vivía en la landing pública (pedido del
    dueño: solo tiene sentido una vez inscripto, no antes). Best-effort: si
    falla o no hay clases cargadas, devuelve `None` y el mail sale igual."""
    try:
        ics = clases_taller_to_ics(clases, taller_nombre=taller_nombre, location=direccion or "")
        if not ics:
            return None
        return [
            Attachment(
                filename=f"{slug}.ics",
                content=ics.encode("utf-8"),
                mimetype="text/calendar; method=PUBLISH; charset=utf-8",
            )
        ]
    except Exception:
        logger.warning("No se pudo generar el .ics del taller %s", slug, exc_info=True)
        return None


@router.post("/talleres/{slug}/inscripcion/heartbeat")
@limiter.limit("60/minute")
def inscripcion_heartbeat(slug: str, body: InscripcionBorradorBody, request: Request):
    """Persiste lo que la persona lleva tipeado en WorkshopInscripcionForm
    (services.talleres_borrador — mirror de POST /cart/heartbeat). Anónimo,
    sin auth: mismo criterio que el resto de los endpoints públicos de
    talleres. Silencioso ante slug/edición inválida (404 no aporta nada acá
    — es telemetría, no una acción del usuario) en vez de romper el form."""
    with get_db() as conn:
        try:
            edicion_row = _get_edicion_row(conn, slug)
        except HTTPException:
            return {"ok": True}
        _borrador_heartbeat_upsert(
            conn,
            session_id=body.session_id,
            edicion_id=edicion_row["id"],
            nombre=body.nombre,
            email=body.email,
            telefono=body.telefono,
        )
        conn.commit()
    return {"ok": True}


@router.get("/admin/ediciones/{edicion_id}/borradores")
def admin_listar_borradores(edicion_id: int, request: Request, horas: int = 72):
    """Borradores de inscripción sin enviar de una edición — quién estuvo por
    anotarse y no llegó, para que el admin pueda hacer seguimiento."""
    require_admin(request)
    with get_db() as conn:
        return _listar_borradores_admin(conn, edicion_id, horas)


@router.post("/talleres/{slug}/inscripcion")
@limiter.limit("10/minute")
def crear_inscripcion(slug: str, body: InscripcionBody, request: Request):
    """Crea una inscripción a una edición de taller. Cupos llenos → lista de espera."""
    nombre = body.nombre.strip()
    email = body.email.strip().lower()
    telefono_raw = body.telefono.strip()
    if not nombre or not email or not telefono_raw:
        raise HTTPException(400, "Nombre, email y teléfono son obligatorios")
    # Teléfono normalizado a E.164 (puerta única services.telefono → listo para
    # WhatsApp). Si no parsea, conservamos lo que cargó la persona: no bloqueamos
    # la inscripción por un formato raro.
    telefono = telefono_svc.formatear_para_guardar(telefono_raw) or telefono_raw

    with get_db() as conn:
        try:
            edicion_row = _get_edicion_row(conn, slug)
            edicion_id = edicion_row["id"]
            taller_id = edicion_row["taller_id"]
            # Clases reales (para el adjunto .ics del mail — ver más abajo).
            clases = _get_clases(conn, edicion_id)
            # Cuentas de cobro (para el mail — ver ctx_cliente más abajo).
            # Fetch DENTRO del `with`, mismo motivo que `clases`: se usa
            # después de que el context manager cierra la conexión.
            cuentas_pago_ctx = _get_cuentas_pago(conn, edicion_id)

            # F4c: cierre de inscripciones por fecha (NULL = siempre abierto).
            cierre = edicion_row["fecha_cierre_inscripcion"]
            if cierre and now_ar().date() > cierre:
                raise HTTPException(400, "Las inscripciones a este taller ya cerraron.")

            # FOR UPDATE serializa el conteo de cupos de esta edición
            locked = conn.execute(
                "SELECT cupos_total, cupos_confirmados FROM ediciones_taller "
                "WHERE id = %s FOR UPDATE",
                (edicion_id,),
            ).fetchone()
            en_lista = locked["cupos_confirmados"] >= locked["cupos_total"]
            estado = "en_espera" if en_lista else "pendiente_sena"

            # Dedup: una persona no se inscribe dos veces a la MISMA edición. La
            # clave es el email (ya normalizado a lowercase). Corre bajo el
            # FOR UPDATE de la edición → race-safe (dos envíos concurrentes del
            # mismo email quedan serializados, el segundo ve al primero).
            # `eliminado_at IS NULL`: una inscripción soft-deleted no cuenta
            # como "ya inscripto" — si no, un borrado (accidental o no) bloquea
            # para siempre volver a anotar a esa persona.
            ya_inscripto = conn.execute(
                "SELECT 1 FROM taller_inscripciones "
                "WHERE edicion_id = %s AND LOWER(email) = %s AND eliminado_at IS NULL LIMIT 1",
                (edicion_id, email),
            ).fetchone()
            if ya_inscripto:
                raise HTTPException(
                    409,
                    "Ya hay una inscripción con ese email para esta edición del taller.",
                )

            # F4a: snapshot de la modalidad elegida (mismo criterio que el
            # precio de línea de un pedido: congelado al inscribirse, no en
            # vivo — ver _modalidades_publicas para el fallback sintético).
            modalidades_edicion = _modalidades_publicas(
                _get_modalidades(conn, edicion_id), edicion_row["precio_total"]
            )
            if body.modalidad_codigo:
                elegida = next(
                    (m for m in modalidades_edicion if m["codigo"] == body.modalidad_codigo), None
                )
                if elegida is None:
                    raise HTTPException(400, "Modalidad de pago inválida")
            else:
                elegida = modalidades_edicion[0]

            cur = conn.execute(
                """
                INSERT INTO taller_inscripciones
                    (taller_id, edicion_id, nombre, email, telefono, experiencia,
                     comprobante_url, comprobante_key, en_lista_espera, estado,
                     tyc_aceptado_at, modalidad_codigo, modalidad_label, modalidad_monto)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CASE WHEN %s THEN NOW() ELSE NULL END, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    taller_id,
                    edicion_id,
                    nombre, email, telefono,
                    body.experiencia or None,
                    body.comprobante_url or None,
                    body.comprobante_key or None,
                    en_lista,
                    estado,
                    body.acepta_terminos,
                    elegida["codigo"], elegida["label"], elegida["monto_total"],
                ),
            )
            row = cur.fetchone()
            inscripcion_id = row["id"]

            if not en_lista:
                conn.execute(
                    "UPDATE ediciones_taller "
                    "SET cupos_confirmados = cupos_confirmados + 1, updated_at = NOW() "
                    "WHERE id = %s",
                    (edicion_id,),
                )
            if body.session_id:
                _borrador_marcar_confirmado(conn, body.session_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    nombre_pila = nombre.split()[0]
    fecha_str = now_ar().strftime("%-d de %B de %Y, %H:%M hs")
    admin_tos = [edicion_row["notif_email"]] if edicion_row["notif_email"] else get_admin_tos()

    ctx_admin = {
        "taller_nombre": edicion_row["nombre"],
        "nombre": nombre,
        "email": email,
        "telefono": telefono,
        "experiencia": body.experiencia or "",
        "comprobante_url": _comprobante_url_fresca(body.comprobante_key, body.comprobante_url),
        "en_lista_espera": en_lista,
        "fecha": fecha_str,
    }
    # El .ics solo tiene sentido con el cupo confirmado — a alguien en lista
    # de espera no le mandamos un calendario para clases a las que todavía no
    # sabemos si va a entrar.
    attachments = None
    if not en_lista:
        attachments = _ics_adjunto_taller(
            taller_nombre=edicion_row["nombre"], direccion=edicion_row["direccion"],
            slug=edicion_row["slug"], clases=clases,
        )
    # `cuentas_pago_ctx` es la fuente real (0+ cuentas, lo que edita el admin
    # desde "Precios y forma de pago"); `_cuentas_pago_efectivas` cae a los 3
    # campos viejos SOLO si esa lista vino vacía (defensa en profundidad —
    # no debería pasar tras el fix de `crear_edicion`).
    cuentas_pago_html, cuentas_pago_text = _cuentas_pago_para_mail(
        _cuentas_pago_efectivas(
            cuentas_pago_ctx,
            pago_alias=edicion_row["pago_alias"], pago_cbu=edicion_row["pago_cbu"],
            pago_banco=edicion_row["pago_banco"],
        )
    )
    ctx_cliente = {
        "taller_nombre": edicion_row["nombre"],
        "nombre_pila": nombre_pila,
        "en_lista_espera": en_lista,
        "fecha_inicio_str": _fmt_fecha_es(edicion_row["fecha_inicio"]),
        "fecha_fin_str": _fmt_fecha_es(edicion_row["fecha_fin"]),
        "horario": edicion_row["horario"],
        "direccion": edicion_row["direccion"],
        "precio_sena_str": _fmt_pesos(edicion_row["precio_sena"]),
        "cuentas_pago_html": cuentas_pago_html,
        "cuentas_pago_text": cuentas_pago_text,
        "tipo_taller": edicion_row["tipo_taller"],
        "tiene_ics": bool(attachments),
    }

    for to in admin_tos:
        send_email("taller_inscripcion_admin", to, ctx_admin)
    send_email("taller_inscripcion_cliente", email, ctx_cliente, attachments=attachments)

    cupos_disponibles = max(0, locked["cupos_total"] - locked["cupos_confirmados"] - (0 if en_lista else 1))
    return {
        "id": inscripcion_id,
        "en_lista_espera": en_lista,
        "cupos_disponibles": cupos_disponibles,
    }


class InteresadoBody(BaseModel):
    nombre: str
    email: EmailStr
    telefono: str = ""


@router.post("/talleres/{slug}/interesado", status_code=201)
@limiter.limit("5/minute")
def crear_interesado(slug: str, body: InteresadoBody, request: Request):
    """Registra un interesado en el workshop cuando no hay cupos disponibles."""
    nombre = body.nombre.strip()
    email = body.email.strip().lower()
    if not nombre or not email:
        raise HTTPException(400, "Nombre y email son obligatorios")
    # Teléfono (opcional) normalizado a E.164 por la misma puerta única; vacío queda "".
    telefono = telefono_svc.formatear_para_guardar(body.telefono) or body.telefono.strip()

    with get_db() as conn:
        edicion_row = _get_edicion_row(conn, slug)
        taller_id = edicion_row["taller_id"]
        try:
            conn.execute(
                """
                INSERT INTO interesados_taller (taller_id, nombre, email, telefono)
                VALUES (%s, %s, %s, %s)
                """,
                (taller_id, nombre, email, telefono),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True}


@router.get("/talleres/sena/{token}")
@limiter.limit("30/minute")
def get_oferta_cupo(token: str, request: Request):
    """Contexto público de una oferta de cupo vigente ("completá tu seña").
    404 si el token es inválido/venció; 410 si esta inscripción particular ya
    no está en estado `cupo_ofrecido` (ya la reclamó, o nunca fue ofrecida)."""
    insid = _leer_token_cupo(token)
    if insid is None:
        raise HTTPException(404, "Este link no es válido o venció.")
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT ti.id, ti.nombre, ti.estado, e.id AS edicion_id,
                   e.fecha_inicio, e.fecha_fin, e.horario,
                   e.direccion, e.precio_sena, e.pago_alias, e.pago_cbu, e.pago_banco,
                   t.nombre AS taller_nombre
            FROM taller_inscripciones ti
            JOIN ediciones_taller e ON e.id = ti.edicion_id
            JOIN talleres t ON t.id = ti.taller_id
            WHERE ti.id = %s AND ti.eliminado_at IS NULL
            """,
            (insid,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Este link no es válido o venció.")
        if row["estado"] != "cupo_ofrecido":
            raise HTTPException(410, "Esta oferta ya no está disponible.")
        # Efectivas (fallback a los 3 campos viejos si la lista vino vacía —
        # mismo criterio defensivo que el mail, ver _cuentas_pago_efectivas):
        # el front (`DatosPago`) solo lee `cuentas_pago`, sin fallback propio.
        cuentas_pago = _cuentas_pago_efectivas(
            _get_cuentas_pago(conn, row["edicion_id"]),
            pago_alias=row["pago_alias"], pago_cbu=row["pago_cbu"], pago_banco=row["pago_banco"],
        )
    return {
        "taller_nombre": row["taller_nombre"],
        "nombre_pila": row["nombre"].split()[0],
        "fecha_inicio_str": _fmt_fecha_es(row["fecha_inicio"]),
        "fecha_fin_str": _fmt_fecha_es(row["fecha_fin"]),
        "horario": row["horario"],
        "direccion": row["direccion"],
        "precio_sena_str": _fmt_pesos(row["precio_sena"]),
        "cuentas_pago": cuentas_pago,
    }


@router.post("/talleres/sena/{token}/upload-comprobante")
@limiter.limit("20/minute")
async def upload_comprobante_sena(token: str, request: Request):
    """Comprobante de la página "completá tu seña" (F5) — mismo procesamiento
    que el form normal, sin necesitar el slug (todo resuelve por token)."""
    insid = _leer_token_cupo(token)
    if insid is None:
        raise HTTPException(404, "Este link no es válido o venció.")
    ts = int(time.time() * 1000)
    uid = uuid.uuid4().hex[:8]
    return await _procesar_upload_comprobante(request, ref=f"sena-{insid}-{ts}-{uid}")


class ClaimCupoBody(BaseModel):
    comprobante_url: str | None = None
    comprobante_key: str | None = None


@router.post("/talleres/sena/{token}")
@limiter.limit("10/minute")
def claim_oferta_cupo(token: str, body: ClaimCupoBody, request: Request):
    """Reclama un cupo ofrecido: sube el comprobante y pasa a pendiente_sena.
    Re-chequea cupos disponibles bajo lock — si alguien más ya lo tomó (u otro
    cupo_ofrecido en carrera ganó primero), 409 con mensaje claro en vez de
    sobrevender. No es un login: cualquiera con el link puede reclamar (mismo
    modelo de confianza que un magic-link de invitación)."""
    if not (body.comprobante_url or body.comprobante_key):
        raise HTTPException(400, "Falta el comprobante de la seña")
    insid = _leer_token_cupo(token)
    if insid is None:
        raise HTTPException(404, "Este link no es válido o venció.")

    with get_db() as conn:
        try:
            ins = conn.execute(
                "SELECT id, taller_id, edicion_id, estado, nombre, email, telefono "
                "FROM taller_inscripciones WHERE id = %s AND eliminado_at IS NULL FOR UPDATE",
                (insid,),
            ).fetchone()
            if ins is None:
                raise HTTPException(404, "Este link no es válido o venció.")
            if ins["estado"] != "cupo_ofrecido":
                raise HTTPException(410, "Esta oferta ya no está disponible.")

            edicion = conn.execute(
                "SELECT * FROM ediciones_taller WHERE id = %s FOR UPDATE",
                (ins["edicion_id"],),
            ).fetchone()
            if edicion["cupos_confirmados"] >= edicion["cupos_total"]:
                raise HTTPException(409, "Ese cupo ya fue tomado. Escribinos y vemos si se libera otro.")

            conn.execute(
                "UPDATE taller_inscripciones SET en_lista_espera = FALSE, estado = 'pendiente_sena', "
                "comprobante_url = %s, comprobante_key = %s, confirmed_at = NOW() WHERE id = %s",
                (body.comprobante_url, body.comprobante_key, insid),
            )
            conn.execute(
                "UPDATE ediciones_taller SET cupos_confirmados = cupos_confirmados + 1, "
                "updated_at = NOW() WHERE id = %s",
                (edicion["id"],),
            )
            conn.commit()
            # Contexto de mail resuelto DENTRO del `with` (mismo criterio que
            # crear_inscripcion): el JOIN a talleres da nombre/notif_email.
            edicion_row = conn.execute(
                "SELECT e.*, t.nombre AS taller_nombre, t.notif_email FROM ediciones_taller e "
                "JOIN talleres t ON t.id = e.taller_id WHERE e.id = %s",
                (ins["edicion_id"],),
            ).fetchone()
            # Clases reales (para el adjunto .ics del mail — ver más abajo).
            clases = _get_clases(conn, ins["edicion_id"])
            # Cuentas de cobro (para el mail — mismo criterio que crear_inscripcion).
            cuentas_pago_ctx = _get_cuentas_pago(conn, ins["edicion_id"])
        except Exception:
            conn.rollback()
            raise

    nombre_pila = ins["nombre"].split()[0]
    attachments = _ics_adjunto_taller(
        taller_nombre=edicion_row["taller_nombre"], direccion=edicion_row["direccion"],
        slug=edicion_row["slug"], clases=clases,
    )
    cuentas_pago_html, cuentas_pago_text = _cuentas_pago_para_mail(
        _cuentas_pago_efectivas(
            cuentas_pago_ctx,
            pago_alias=edicion_row["pago_alias"], pago_cbu=edicion_row["pago_cbu"],
            pago_banco=edicion_row["pago_banco"],
        )
    )
    ctx_cliente = {
        "taller_nombre": edicion_row["taller_nombre"],
        "nombre_pila": nombre_pila,
        "en_lista_espera": False,
        "fecha_inicio_str": _fmt_fecha_es(edicion_row["fecha_inicio"]),
        "fecha_fin_str": _fmt_fecha_es(edicion_row["fecha_fin"]),
        "horario": edicion_row["horario"],
        "direccion": edicion_row["direccion"],
        "precio_sena_str": _fmt_pesos(edicion_row["precio_sena"]),
        "cuentas_pago_html": cuentas_pago_html,
        "cuentas_pago_text": cuentas_pago_text,
        "tipo_taller": edicion_row["tipo_taller"],
        "tiene_ics": bool(attachments),
    }
    admin_tos = [edicion_row["notif_email"]] if edicion_row["notif_email"] else get_admin_tos()
    ctx_admin = {
        "taller_nombre": edicion_row["taller_nombre"],
        "nombre": ins["nombre"],
        "email": ins["email"],
        "telefono": ins["telefono"] or "",
        "experiencia": "",
        "comprobante_url": _comprobante_url_fresca(body.comprobante_key, body.comprobante_url),
        "en_lista_espera": False,
        "fecha": now_ar().strftime("%-d de %B de %Y, %H:%M hs"),
    }
    for to in admin_tos:
        send_email("taller_inscripcion_admin", to, ctx_admin)
    send_email("taller_inscripcion_cliente", ins["email"], ctx_cliente, attachments=attachments)

    return {"ok": True}


# ── Endpoints admin ───────────────────────────────────────────────────────────

class ModalidadPagoBody(BaseModel):
    # `id` presente = actualizar esa modalidad; ausente = nueva. `orden` es
    # la posición en la lista recibida (no viaja como campo propio).
    id: int | None = None
    codigo: str
    label: str
    nota: str = ""
    monto_total: int = Field(..., gt=0)
    # Default 1 = pago único. El monto POR cuota se deriva de monto_total/
    # n_cuotas en `_modalidad_dict` — nunca se manda ni se guarda a mano.
    n_cuotas: int = Field(default=1, ge=1)


class CuentaPagoBody(BaseModel):
    # `id` presente = actualizar esa cuenta; ausente = nueva. `orden` es la
    # posición en la lista recibida (no viaja como campo propio). Sin plata
    # ni codigo — independiente de la modalidad de pago.
    id: int | None = None
    alias: str = ""
    cbu: str = ""
    banco: str = ""


class ClaseBody(BaseModel):
    fecha: str  # YYYY-MM-DD
    hora_inicio_min: int = Field(..., ge=0, le=1440)  # minutos desde medianoche (510 = 8:30)
    hora_fin_min: int = Field(..., ge=0, le=1440)
    # Contenido rico (F2). `id` presente = actualizar esa clase (preserva su
    # portada); ausente = clase nueva. `portada_*` solo se honra en INSERT
    # (caso "copiar clases de otra edición") — el cambio de portada de una
    # clase existente va por sus endpoints dedicados.
    id: int | None = None
    titulo: str = ""
    descripcion: str = ""
    nota: str = ""
    portada_media_id: int | None = None
    portada_url: str = ""


# Body usado en POST /admin/talleres y POST /admin/talleres/{id}/ediciones
class EdicionCreateBody(BaseModel):
    tipo_taller: str = "intensivo"
    clases: list[ClaseBody]
    cupos_total: int = 12
    precio_total: int = 0
    precio_sena: int = 0
    horario: str = ""
    pago_alias: str = ""
    pago_cbu: str = ""
    pago_banco: str = ""
    direccion: str = ""
    # F2 borradores: una edición NACE despublicada ("ir armándolo sin que esté
    # en la web") — el Switch "Publicado" del admin es la puerta. Publicar
    # re-verifica la disponibilidad del estudio.
    activo: bool = False
    numero_edicion: int = 1
    # Economía del taller (ver `_regenerar_pedidos_taller`): si la edición usa
    # el espacio del Estudio y/o equipos de alquiler, con un valor — 'mensual'
    # (mismo valor cada mes) o 'total' (se reparte en partes iguales entre los
    # meses de la edición). `_tipo` decide CÓMO se determina ese valor: 'fijo'
    # = lo tipea el admin (`valor_estudio`/`valor_equipos`, comportamiento de
    # siempre); 'porcentaje' = un % (`valor_estudio_pct`/`valor_equipos_pct`,
    # 0-100) sobre lo que van a pagar los inscriptos no en lista de espera.
    usa_estudio: bool = False
    valor_estudio: int = 0
    valor_estudio_modo: str = "mensual"
    valor_estudio_tipo: str = "fijo"
    valor_estudio_pct: int = 0
    usa_equipos: bool = False
    valor_equipos: int = 0
    valor_equipos_modo: str = "mensual"
    valor_equipos_tipo: str = "fijo"
    valor_equipos_pct: int = 0


class TallerConceptoCreateBody(BaseModel):
    nombre: str
    # F6: ya no se persiste en `talleres` — resuelve por find-or-create contra
    # la entidad `instructores` (mismo dedup exacto-por-nombre del backfill de
    # F3) + link vía `taller_instructores`. Mantiene la UX de 1 solo campo al
    # crear; el admin ajusta rol/bio/foto después en la pestaña "Instructores".
    instructor_nombre: str
    subtitulo: str = ""
    descripcion: str = ""
    resumen: str = ""
    publico_objetivo: str = ""
    notif_email: str = ""
    terminos: str = ""
    beneficios: str = ""
    pregunta_experiencia: str = ""
    mensaje_confirmacion: str = ""
    # Primera edición (requerida al crear el concepto)
    edicion: EdicionCreateBody


class InstructorBody(BaseModel):
    nombre: str
    rol: str = ""
    descripcion: str = ""
    instagram: str = ""
    web: str = ""
    # F6: "Trabajó con" — reemplaza `talleres.instructor_proyectos` (legacy,
    # 1 por taller); ahora es propio de cada instructor. Texto separado por coma.
    proyectos: str = ""


class InstructorUpdateBody(BaseModel):
    nombre: str | None = None
    rol: str | None = None
    descripcion: str | None = None
    instagram: str | None = None
    web: str | None = None
    proyectos: str | None = None
    activo: bool | None = None


class TallerInstructoresBody(BaseModel):
    instructor_ids: list[int]


class InstitucionBody(BaseModel):
    nombre: str
    descripcion: str = ""
    instagram: str = ""
    web: str = ""


class InstitucionUpdateBody(BaseModel):
    nombre: str | None = None
    descripcion: str | None = None
    instagram: str | None = None
    web: str | None = None


class TallerInstitucionesBody(BaseModel):
    institucion_ids: list[int]


class FaqItemBody(BaseModel):
    pregunta: str
    respuesta: str = ""


class TallerConceptoUpdateBody(BaseModel):
    nombre: str | None = None
    subtitulo: str | None = None
    descripcion: str | None = None
    resumen: str | None = None
    publico_objetivo: str | None = None
    notif_email: str | None = None
    terminos: str | None = None
    beneficios: str | None = None
    pregunta_experiencia: str | None = None
    mensaje_confirmacion: str | None = None
    # F4a: video hero (YouTube). '' → borra el video (y su poster).
    video_url: str | None = None
    # F4c: FAQ del concepto — [{pregunta, respuesta}]. Ninguna es obligatoria.
    faqs: list[FaqItemBody] | None = None


class EdicionUpdateBody(BaseModel):
    tipo_taller: str | None = None
    horario: str | None = None
    precio_total: int | None = None
    precio_sena: int | None = None
    cupos_total: int | None = None
    pago_alias: str | None = None
    pago_cbu: str | None = None
    pago_banco: str | None = None
    direccion: str | None = None
    activo: bool | None = None
    clases: list[ClaseBody] | None = None
    modalidades: list[ModalidadPagoBody] | None = None
    # Cuentas de cobro (alias/cbu/banco) — lista, independiente de
    # `modalidades`. Reemplaza a pago_alias/pago_cbu/pago_banco de arriba
    # como lo que el admin edita; esos 3 campos quedan sin tocar por
    # compatibilidad pero ya no los escribe la UI (ver PreciosSection).
    cuentas_pago: list[CuentaPagoBody] | None = None
    # F4c: cierre de inscripciones. '' → borra el cierre (siempre abierto).
    fecha_cierre_inscripcion: str | None = None
    # Corrige el número de edición (ej. al cargar un taller con historia previa
    # fuera de Rambla — nace #1 y hay que pasarlo a la #5 real). NO toca el
    # slug (queda fijo desde la creación, no se re-deriva del número nuevo).
    numero_edicion: int | None = None
    # Economía del taller — ver comentario gemelo en EdicionCreateBody.
    usa_estudio: bool | None = None
    valor_estudio: int | None = None
    valor_estudio_modo: str | None = None
    valor_estudio_tipo: str | None = None
    valor_estudio_pct: int | None = None
    usa_equipos: bool | None = None
    valor_equipos: int | None = None
    valor_equipos_modo: str | None = None
    valor_equipos_tipo: str | None = None
    valor_equipos_pct: int | None = None


@router.get("/admin/talleres")
def admin_list_talleres(request: Request):
    """Lista todos los conceptos de taller con sus ediciones y clases anidadas."""
    require_admin(request)
    with get_db() as conn:
        # Conceptos: talleres que tienen al menos una edición
        conceptos = conn.execute(
            """
            SELECT DISTINCT t.*
            FROM talleres t
            JOIN ediciones_taller e ON e.taller_id = t.id
            ORDER BY t.id DESC
            """
        ).fetchall()

        result = []
        for t in conceptos:
            edicion_rows = conn.execute(
                "SELECT * FROM ediciones_taller WHERE taller_id = %s ORDER BY numero_edicion",
                (t["id"],),
            ).fetchall()
            ediciones = [
                _edicion_to_admin_dict(
                    e, _get_clases(conn, e["id"]), _get_modalidades(conn, e["id"]),
                    fotos=_get_edicion_fotos(conn, e["id"]),
                    cuentas_pago=_get_cuentas_pago(conn, e["id"]),
                    inscriptos_revenue=_revenue_inscriptos(conn, e["id"]),
                )
                for e in edicion_rows
            ]
            result.append(
                _concepto_to_admin_dict(
                    t, ediciones, _get_instructores_taller(conn, t["id"]),
                    _get_trabajos_taller(conn, t["id"]),
                    instituciones=_get_instituciones_taller(conn, t["id"]),
                )
            )
    return result


def _find_or_create_instructor(conn, nombre: str) -> int:
    """Dedup EXACTO por nombre — mismo criterio que el backfill de F3
    (esc3n4t5r6u7): dos talleres con el mismo nombre de instructor comparten
    la misma fila de `instructores`."""
    row = conn.execute("SELECT id FROM instructores WHERE nombre = %s", (nombre,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO instructores (nombre) VALUES (%s) RETURNING id", (nombre,))
    return cur.fetchone()["id"]


@router.post("/admin/talleres", status_code=201)
def admin_create_taller(body: TallerConceptoCreateBody, request: Request):
    """Crea un nuevo concepto de taller con su primera edición."""
    require_admin(request)
    ed = body.edicion
    clases = _validar_clases(ed.clases)
    if ed.precio_sena > ed.precio_total:
        raise HTTPException(400, "La seña no puede superar el precio total")
    if ed.cupos_total < 1:
        raise HTTPException(400, "cupos_total debe ser al menos 1")
    if ed.tipo_taller not in ("intensivo", "semanal"):
        raise HTTPException(400, "tipo_taller debe ser 'intensivo' o 'semanal'")
    if ed.valor_estudio_modo not in ("mensual", "total"):
        raise HTTPException(400, "valor_estudio_modo debe ser 'mensual' o 'total'")
    if ed.valor_equipos_modo not in ("mensual", "total"):
        raise HTTPException(400, "valor_equipos_modo debe ser 'mensual' o 'total'")
    if ed.valor_estudio_tipo not in ("fijo", "porcentaje"):
        raise HTTPException(400, "valor_estudio_tipo debe ser 'fijo' o 'porcentaje'")
    if not (0 <= ed.valor_estudio_pct <= 100):
        raise HTTPException(400, "valor_estudio_pct debe estar entre 0 y 100")
    if ed.valor_equipos_tipo not in ("fijo", "porcentaje"):
        raise HTTPException(400, "valor_equipos_tipo debe ser 'fijo' o 'porcentaje'")
    if not (0 <= ed.valor_equipos_pct <= 100):
        raise HTTPException(400, "valor_equipos_pct debe estar entre 0 y 100")

    with get_db() as conn:
        try:
            # Slug base del concepto (único en talleres)
            nombre_base = body.nombre.strip()
            ocupados_t = {r["slug"] for r in conn.execute("SELECT slug FROM talleres").fetchall()}
            slug_base = slug_unico(slugify(nombre_base), ocupados_t)

            # Slug de la primera edición (único en ediciones_taller)
            ocupados_e = {r["slug"] for r in conn.execute("SELECT slug FROM ediciones_taller").fetchall()}
            ed_numero = max(1, ed.numero_edicion)
            slug_edicion = slug_unico(slug_base, ocupados_e) if ed_numero == 1 else slug_unico(
                f"{slug_base}-{ed_numero}", ocupados_e
            )

            # F2 borradores: un borrador no bloquea el estudio (fix e.activo de
            # F1), así que solo se verifica disponibilidad si nace PUBLICADA.
            # El chequeo de un borrador corre al publicarlo (PATCH activo=true).
            if ed.activo:
                _gate_conflicto_estudio(conn, clases)

            # Crear concepto en talleres. OJO: `activo` del CONCEPTO queda TRUE
            # (kill-switch general, no la puerta de publicación) — la puerta es
            # el `activo` de la EDICIÓN: sin edición activa no aparece nada
            # público, así el concepto se arma en borrador igual.
            cur = conn.execute(
                """
                INSERT INTO talleres (
                    slug, nombre, subtitulo, descripcion, resumen, publico_objetivo,
                    notif_email, activo, slug_base,
                    terminos, beneficios, pregunta_experiencia, mensaje_confirmacion
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s, %s
                ) RETURNING id
                """,
                (
                    slug_base, nombre_base, body.subtitulo.strip(),
                    body.descripcion.strip(), body.resumen.strip(), body.publico_objetivo.strip(),
                    body.notif_email.strip(), slug_base,
                    body.terminos.strip(), body.beneficios.strip(),
                    body.pregunta_experiencia.strip(), body.mensaje_confirmacion.strip(),
                ),
            )
            taller_id = cur.fetchone()["id"]

            # F6: instructor por find-or-create (entidad `instructores`) + link
            # — reemplaza el UPDATE directo a columnas legacy de `talleres`.
            # Vacío → el concepto nace sin instructor (se agrega después desde
            # la pestaña "Instructores"), en vez de crear una fila basura "".
            instructor_nombre = body.instructor_nombre.strip()
            if instructor_nombre:
                instructor_id = _find_or_create_instructor(conn, instructor_nombre)
                conn.execute(
                    "INSERT INTO taller_instructores (taller_id, instructor_id, orden) "
                    "VALUES (%s, %s, 0)",
                    (taller_id, instructor_id),
                )

            # Crear primera edición — núcleo compartido con admin_create_edicion.
            e_row = crear_edicion(
                conn, taller_id=taller_id, ed_numero=ed_numero, slug_edicion=slug_edicion,
                clases=clases, taller_nombre=nombre_base, numero_pedido_fn=_next_numero_pedido,
                campos={
                    "tipo_taller": ed.tipo_taller, "horario": ed.horario.strip(),
                    "cupos_total": ed.cupos_total, "precio_total": ed.precio_total,
                    "precio_sena": ed.precio_sena,
                    "pago_alias": ed.pago_alias.strip(), "pago_cbu": ed.pago_cbu.strip(),
                    "pago_banco": ed.pago_banco.strip(), "direccion": ed.direccion.strip(),
                    "activo": ed.activo,
                    "usa_estudio": ed.usa_estudio, "valor_estudio": ed.valor_estudio,
                    "valor_estudio_modo": ed.valor_estudio_modo,
                    "valor_estudio_tipo": ed.valor_estudio_tipo, "valor_estudio_pct": ed.valor_estudio_pct,
                    "usa_equipos": ed.usa_equipos, "valor_equipos": ed.valor_equipos,
                    "valor_equipos_modo": ed.valor_equipos_modo,
                    "valor_equipos_tipo": ed.valor_equipos_tipo, "valor_equipos_pct": ed.valor_equipos_pct,
                },
            )
            conn.commit()

            t_row = conn.execute("SELECT * FROM talleres WHERE id = %s", (taller_id,)).fetchone()
            # Re-leer de la DB: las clases recién insertadas tienen id (el admin
            # lo necesita para subir portadas / upsert sin refetch). DEBE ir
            # DENTRO del `with` — usar `conn` después de que el context manager
            # lo devuelve al pool deja una transacción implícita abierta que
            # bloquea el próximo `ALTER TABLE`/lock de otra sesión (candado:
            # test_talleres_f2_db.py, se colgaba justo por esto).
            clases_out = _get_clases(conn, e_row["id"])
            # `_get_cuentas_pago`, no `[]`: `crear_edicion` puede haber
            # sembrado una fila desde pago_alias/cbu/banco (ver su docstring)
            # — devolver `[]` a ciegas le mentiría al admin sobre lo que
            # realmente quedó guardado.
            cuentas_pago_out = _get_cuentas_pago(conn, e_row["id"])
            instructores_out = _get_instructores_taller(conn, taller_id)
            instituciones_out = _get_instituciones_taller(conn, taller_id)
        except Exception:
            conn.rollback()
            raise

    return _concepto_to_admin_dict(
        t_row,
        [_edicion_to_admin_dict(
            e_row, clases_out, fotos=[], cuentas_pago=cuentas_pago_out, inscriptos_revenue=0,
        )],
        instructores_out,
        instituciones=instituciones_out,
    )


@router.post("/admin/talleres/{taller_id}/ediciones", status_code=201)
def admin_create_edicion(taller_id: int, body: EdicionCreateBody, request: Request):
    """Agrega una nueva edición a un concepto de taller existente."""
    require_admin(request)
    clases = _validar_clases(body.clases)
    if body.precio_sena > body.precio_total:
        raise HTTPException(400, "La seña no puede superar el precio total")
    if body.cupos_total < 1:
        raise HTTPException(400, "cupos_total debe ser al menos 1")
    if body.tipo_taller not in ("intensivo", "semanal"):
        raise HTTPException(400, "tipo_taller debe ser 'intensivo' o 'semanal'")
    if body.valor_estudio_modo not in ("mensual", "total"):
        raise HTTPException(400, "valor_estudio_modo debe ser 'mensual' o 'total'")
    if body.valor_equipos_modo not in ("mensual", "total"):
        raise HTTPException(400, "valor_equipos_modo debe ser 'mensual' o 'total'")
    if body.valor_estudio_tipo not in ("fijo", "porcentaje"):
        raise HTTPException(400, "valor_estudio_tipo debe ser 'fijo' o 'porcentaje'")
    if not (0 <= body.valor_estudio_pct <= 100):
        raise HTTPException(400, "valor_estudio_pct debe estar entre 0 y 100")
    if body.valor_equipos_tipo not in ("fijo", "porcentaje"):
        raise HTTPException(400, "valor_equipos_tipo debe ser 'fijo' o 'porcentaje'")
    if not (0 <= body.valor_equipos_pct <= 100):
        raise HTTPException(400, "valor_equipos_pct debe estar entre 0 y 100")

    with get_db() as conn:
        try:
            t_row = conn.execute(
                "SELECT * FROM talleres WHERE id = %s", (taller_id,)
            ).fetchone()
            if t_row is None:
                raise HTTPException(404, "Taller no encontrado")

            slug_base = t_row["slug_base"] or t_row["slug"]
            ed_numero = max(1, body.numero_edicion)

            # Verificar que el numero_edicion no está tomado
            existing = conn.execute(
                "SELECT id FROM ediciones_taller WHERE taller_id = %s AND numero_edicion = %s",
                (taller_id, ed_numero),
            ).fetchone()
            if existing:
                raise HTTPException(409, f"Ya existe la edición #{ed_numero} de este taller")

            # Slug único para la edición
            ocupados = {r["slug"] for r in conn.execute("SELECT slug FROM ediciones_taller").fetchall()}
            slug_edicion = slug_unico(
                slug_base if ed_numero == 1 else f"{slug_base}-{ed_numero}",
                ocupados,
            )

            # F2 borradores: solo verificar el estudio si nace PUBLICADA (el
            # chequeo de un borrador corre al publicar).
            if body.activo:
                _gate_conflicto_estudio(conn, clases)

            e_row = crear_edicion(
                conn, taller_id=taller_id, ed_numero=ed_numero, slug_edicion=slug_edicion,
                clases=clases, taller_nombre=t_row["nombre"], numero_pedido_fn=_next_numero_pedido,
                campos={
                    "tipo_taller": body.tipo_taller, "horario": body.horario.strip(),
                    "cupos_total": body.cupos_total, "precio_total": body.precio_total,
                    "precio_sena": body.precio_sena,
                    "pago_alias": body.pago_alias.strip(), "pago_cbu": body.pago_cbu.strip(),
                    "pago_banco": body.pago_banco.strip(), "direccion": body.direccion.strip(),
                    "activo": body.activo,
                    "usa_estudio": body.usa_estudio, "valor_estudio": body.valor_estudio,
                    "valor_estudio_modo": body.valor_estudio_modo,
                    "valor_estudio_tipo": body.valor_estudio_tipo, "valor_estudio_pct": body.valor_estudio_pct,
                    "usa_equipos": body.usa_equipos, "valor_equipos": body.valor_equipos,
                    "valor_equipos_modo": body.valor_equipos_modo,
                    "valor_equipos_tipo": body.valor_equipos_tipo, "valor_equipos_pct": body.valor_equipos_pct,
                },
            )
            conn.commit()
            # Re-leer de la DB: las clases recién insertadas tienen id (el admin
            # lo necesita para subir portadas / upsert sin refetch). DENTRO del
            # `with` — ver comentario gemelo en admin_create_taller.
            clases_out = _get_clases(conn, e_row["id"])
            # `_get_cuentas_pago`, no `[]` — ver comentario gemelo en
            # admin_create_taller (`crear_edicion` puede haber sembrado una
            # fila desde pago_alias/cbu/banco).
            cuentas_pago_out = _get_cuentas_pago(conn, e_row["id"])
        except Exception:
            conn.rollback()
            raise

    return _edicion_to_admin_dict(
        e_row, clases_out, fotos=[], cuentas_pago=cuentas_pago_out, inscriptos_revenue=0,
    )


@router.patch("/admin/talleres/{taller_id}")
def admin_update_concepto(taller_id: int, body: TallerConceptoUpdateBody, request: Request):
    """Actualiza los campos estables del concepto (nombre, descripción, T&C, etc.)."""
    require_admin(request)
    sets = []
    params: list = []
    if body.nombre is not None:
        sets.append("nombre = %s"); params.append(body.nombre.strip())
    if body.subtitulo is not None:
        sets.append("subtitulo = %s"); params.append(body.subtitulo.strip())
    if body.descripcion is not None:
        sets.append("descripcion = %s"); params.append(body.descripcion.strip())
    if body.resumen is not None:
        sets.append("resumen = %s"); params.append(body.resumen.strip())
    if body.publico_objetivo is not None:
        sets.append("publico_objetivo = %s"); params.append(body.publico_objetivo.strip())
    if body.notif_email is not None:
        sets.append("notif_email = %s"); params.append(body.notif_email.strip())
    if body.terminos is not None:
        sets.append("terminos = %s"); params.append(body.terminos.strip())
    if body.beneficios is not None:
        sets.append("beneficios = %s"); params.append(body.beneficios.strip())
    if body.pregunta_experiencia is not None:
        sets.append("pregunta_experiencia = %s"); params.append(body.pregunta_experiencia.strip())
    if body.mensaje_confirmacion is not None:
        sets.append("mensaje_confirmacion = %s"); params.append(body.mensaje_confirmacion.strip())
    if body.faqs is not None:
        faqs_limpio = [
            {"pregunta": f.pregunta.strip(), "respuesta": f.respuesta.strip()}
            for f in body.faqs if f.pregunta.strip()
        ]
        sets.append("faqs = %s::jsonb"); params.append(_json.dumps(faqs_limpio, ensure_ascii=False))

    video_url_provisto = body.video_url is not None

    if not sets and not video_url_provisto:
        raise HTTPException(400, "No hay campos para actualizar")

    with get_db() as conn:
        try:
            existing = conn.execute("SELECT id FROM talleres WHERE id = %s", (taller_id,)).fetchone()
            if existing is None:
                raise HTTPException(404, "Taller no encontrado")

            if video_url_provisto:
                nuevo_video = body.video_url.strip()
                if not nuevo_video:
                    # '' borra el video (y desengancha el poster — el asset
                    # queda en media_assets, no se purga R2, mismo criterio
                    # que la portada de una clase / la foto de instructor).
                    sets.append("video_url = %s"); params.append("")
                    sets.append("video_poster_media_id = NULL")
                    sets.append("video_poster_url = %s"); params.append("")
                else:
                    vid = extract_video_id(nuevo_video)
                    if vid is None:
                        raise HTTPException(400, "URL de YouTube inválida")
                    try:
                        asset = store_youtube_poster(vid, kind="taller", conn=conn)
                    except MediaError as e:
                        raise HTTPException(e.status, e.detail)
                    display = asset.variant("display") or (asset.variants[0] if asset.variants else None)
                    sets.append("video_url = %s"); params.append(nuevo_video)
                    sets.append("video_poster_media_id = %s"); params.append(asset.id)
                    sets.append("video_poster_url = %s"); params.append(display.url if display else "")

            sets.append("updated_at = NOW()")
            params.append(taller_id)
            conn.execute(f"UPDATE talleres SET {', '.join(sets)} WHERE id = %s", params)
            conn.commit()
            t_row = conn.execute("SELECT * FROM talleres WHERE id = %s", (taller_id,)).fetchone()
            edicion_rows = conn.execute(
                "SELECT * FROM ediciones_taller WHERE taller_id = %s ORDER BY numero_edicion",
                (taller_id,),
            ).fetchall()
            ediciones = [
                _edicion_to_admin_dict(
                    e, _get_clases(conn, e["id"]), _get_modalidades(conn, e["id"]),
                    fotos=_get_edicion_fotos(conn, e["id"]),
                    cuentas_pago=_get_cuentas_pago(conn, e["id"]),
                    inscriptos_revenue=_revenue_inscriptos(conn, e["id"]),
                )
                for e in edicion_rows
            ]
            instructores_out = _get_instructores_taller(conn, taller_id)
            trabajos_out = _get_trabajos_taller(conn, taller_id)
            instituciones_out = _get_instituciones_taller(conn, taller_id)
        except Exception:
            conn.rollback()
            raise
    return _concepto_to_admin_dict(
        t_row, ediciones, instructores_out, trabajos_out, instituciones=instituciones_out,
    )


@router.patch("/admin/ediciones/{edicion_id}")
def admin_update_edicion(edicion_id: int, body: EdicionUpdateBody, request: Request):
    """Actualiza campos de una edición específica (fechas, precios, cupos, clases)."""
    require_admin(request)

    sets = []
    params: list = []
    if body.tipo_taller is not None:
        if body.tipo_taller not in ("intensivo", "semanal"):
            raise HTTPException(400, "tipo_taller debe ser 'intensivo' o 'semanal'")
        sets.append("tipo_taller = %s"); params.append(body.tipo_taller)
    if body.horario is not None:
        sets.append("horario = %s"); params.append(body.horario.strip())
    if body.precio_total is not None:
        sets.append("precio_total = %s"); params.append(body.precio_total)
    if body.precio_sena is not None:
        sets.append("precio_sena = %s"); params.append(body.precio_sena)
    if body.cupos_total is not None:
        sets.append("cupos_total = %s"); params.append(body.cupos_total)
    if body.pago_alias is not None:
        sets.append("pago_alias = %s"); params.append(body.pago_alias.strip())
    if body.pago_cbu is not None:
        sets.append("pago_cbu = %s"); params.append(body.pago_cbu.strip())
    if body.pago_banco is not None:
        sets.append("pago_banco = %s"); params.append(body.pago_banco.strip())
    if body.direccion is not None:
        sets.append("direccion = %s"); params.append(body.direccion.strip())
    if body.activo is not None:
        sets.append("activo = %s"); params.append(body.activo)
    if body.numero_edicion is not None:
        if body.numero_edicion < 1:
            raise HTTPException(400, "numero_edicion debe ser un entero positivo")
        sets.append("numero_edicion = %s"); params.append(body.numero_edicion)
    if body.fecha_cierre_inscripcion is not None:
        if body.fecha_cierre_inscripcion == "":
            sets.append("fecha_cierre_inscripcion = NULL")
        else:
            from datetime import date as _dt_date
            try:
                _dt_date.fromisoformat(body.fecha_cierre_inscripcion)
            except ValueError:
                raise HTTPException(400, f"Fecha inválida: {body.fecha_cierre_inscripcion}")
            sets.append("fecha_cierre_inscripcion = %s")
            params.append(body.fecha_cierre_inscripcion)
    if body.usa_estudio is not None:
        sets.append("usa_estudio = %s"); params.append(body.usa_estudio)
    if body.valor_estudio is not None:
        sets.append("valor_estudio = %s"); params.append(body.valor_estudio)
    if body.valor_estudio_modo is not None:
        if body.valor_estudio_modo not in ("mensual", "total"):
            raise HTTPException(400, "valor_estudio_modo debe ser 'mensual' o 'total'")
        sets.append("valor_estudio_modo = %s"); params.append(body.valor_estudio_modo)
    if body.valor_estudio_tipo is not None:
        if body.valor_estudio_tipo not in ("fijo", "porcentaje"):
            raise HTTPException(400, "valor_estudio_tipo debe ser 'fijo' o 'porcentaje'")
        sets.append("valor_estudio_tipo = %s"); params.append(body.valor_estudio_tipo)
    if body.valor_estudio_pct is not None:
        if not (0 <= body.valor_estudio_pct <= 100):
            raise HTTPException(400, "valor_estudio_pct debe estar entre 0 y 100")
        sets.append("valor_estudio_pct = %s"); params.append(body.valor_estudio_pct)
    if body.usa_equipos is not None:
        sets.append("usa_equipos = %s"); params.append(body.usa_equipos)
    if body.valor_equipos is not None:
        sets.append("valor_equipos = %s"); params.append(body.valor_equipos)
    if body.valor_equipos_modo is not None:
        if body.valor_equipos_modo not in ("mensual", "total"):
            raise HTTPException(400, "valor_equipos_modo debe ser 'mensual' o 'total'")
        sets.append("valor_equipos_modo = %s"); params.append(body.valor_equipos_modo)
    if body.valor_equipos_tipo is not None:
        if body.valor_equipos_tipo not in ("fijo", "porcentaje"):
            raise HTTPException(400, "valor_equipos_tipo debe ser 'fijo' o 'porcentaje'")
        sets.append("valor_equipos_tipo = %s"); params.append(body.valor_equipos_tipo)
    if body.valor_equipos_pct is not None:
        if not (0 <= body.valor_equipos_pct <= 100):
            raise HTTPException(400, "valor_equipos_pct debe estar entre 0 y 100")
        sets.append("valor_equipos_pct = %s"); params.append(body.valor_equipos_pct)

    new_clases = None
    if body.clases is not None:
        new_clases = _validar_clases(body.clases)

    new_modalidades = None
    if body.modalidades is not None:
        new_modalidades = _validar_modalidades(body.modalidades)

    new_cuentas_pago = None
    if body.cuentas_pago is not None:
        new_cuentas_pago = _validar_cuentas_pago(body.cuentas_pago)

    if (
        not sets
        and new_clases is None
        and new_modalidades is None
        and new_cuentas_pago is None
    ):
        raise HTTPException(400, "No hay campos para actualizar")

    with get_db() as conn:
        try:
            existing = conn.execute(
                "SELECT e.taller_id, e.cupos_total, e.cupos_confirmados, e.activo, "
                "       t.nombre AS taller_nombre "
                "FROM ediciones_taller e JOIN talleres t ON t.id = e.taller_id "
                "WHERE e.id = %s FOR UPDATE",
                (edicion_id,),
            ).fetchone()
            if existing is None:
                raise HTTPException(404, "Edición no encontrada")

            if body.numero_edicion is not None:
                conflicto = conn.execute(
                    "SELECT id FROM ediciones_taller WHERE taller_id = %s AND numero_edicion = %s "
                    "AND id != %s",
                    (existing["taller_id"], body.numero_edicion, edicion_id),
                ).fetchone()
                if conflicto:
                    raise HTTPException(
                        409, f"Ya existe la edición #{body.numero_edicion} de este taller"
                    )

            new_cupos = body.cupos_total if body.cupos_total is not None else existing["cupos_total"]
            if new_cupos < existing["cupos_confirmados"]:
                raise HTTPException(
                    400,
                    f"No se puede bajar cupos a {new_cupos}: hay {existing['cupos_confirmados']} confirmados",
                )

            # F2 borradores: el estudio se verifica cuando el estado RESULTANTE
            # es publicado — al editar clases de una edición activa, o al
            # PUBLICAR (activo false→true; un borrador no bloqueó su franja, así
            # que puede haber aparecido una reserva → 409 claro acá, no choque
            # silencioso). Editar un borrador no chequea nada.
            resultara_activa = body.activo if body.activo is not None else existing["activo"]
            publicando = bool(body.activo) and not existing["activo"]
            clases_a_verificar = new_clases
            if publicando and clases_a_verificar is None:
                from datetime import date as _dt_date
                clases_a_verificar = [
                    {"fecha": _dt_date.fromisoformat(c["fecha"]),
                     "hora_inicio_min": c["hora_inicio_min"],
                     "hora_fin_min": c["hora_fin_min"]}
                    for c in _get_clases(conn, edicion_id)
                ]
            if resultara_activa and clases_a_verificar and (new_clases is not None or publicando):
                # Excluir este taller del chequeo (sus propias clases activas)
                _gate_conflicto_estudio(
                    conn, clases_a_verificar, exclude_taller_id=existing["taller_id"],
                )

            if new_clases is not None:
                fechas = [c["fecha"] for c in new_clases]
                sets.append("fecha_inicio = %s"); params.append(min(fechas))
                sets.append("fecha_fin = %s"); params.append(max(fechas))
                # Upsert (F2): preserva la portada de las clases existentes —
                # el delete+insert ciego de antes la perdía en cada edición.
                _upsert_clases(conn, edicion_id, new_clases)

            if new_modalidades is not None:
                _upsert_modalidades(conn, edicion_id, new_modalidades)

            if new_cuentas_pago is not None:
                _upsert_cuentas_pago(conn, edicion_id, new_cuentas_pago)

            if sets:
                sets.append("updated_at = NOW()")
                params.append(edicion_id)
                conn.execute(
                    f"UPDATE ediciones_taller SET {', '.join(sets)} WHERE id = %s",
                    params,
                )

            e_row = conn.execute(
                "SELECT * FROM ediciones_taller WHERE id = %s", (edicion_id,)
            ).fetchone()
            _regenerar_pedidos_taller(
                conn, e_row, existing["taller_nombre"], numero_pedido_fn=_next_numero_pedido,
            )
            conn.commit()
            # DENTRO del `with` — ver comentario gemelo en admin_create_taller.
            clases_out = _get_clases(conn, edicion_id)
            modalidades_out = _get_modalidades(conn, edicion_id)
            cuentas_pago_out = _get_cuentas_pago(conn, edicion_id)
            fotos_out = _get_edicion_fotos(conn, edicion_id)
            inscriptos_revenue_out = _revenue_inscriptos(conn, edicion_id)
        except Exception:
            conn.rollback()
            raise
    return _edicion_to_admin_dict(
        e_row, clases_out, modalidades_out, fotos=fotos_out, cuentas_pago=cuentas_pago_out,
        inscriptos_revenue=inscriptos_revenue_out,
    )


@router.delete("/admin/talleres/{taller_id}", status_code=200)
def admin_delete_taller(taller_id: int, request: Request):
    """Elimina un concepto y todas sus ediciones. Falla si hay inscriptos confirmados."""
    require_admin(request)
    with get_db() as conn:
        try:
            row = conn.execute(
                "SELECT id FROM talleres WHERE id = %s", (taller_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Taller no encontrado")

            # Verificar que no haya inscripciones confirmadas en ninguna edición
            confirmed = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM taller_inscripciones ti
                JOIN ediciones_taller e ON e.id = ti.edicion_id
                WHERE e.taller_id = %s AND ti.en_lista_espera = FALSE
                  AND ti.eliminado_at IS NULL
                """,
                (taller_id,),
            ).fetchone()["cnt"]
            if confirmed > 0:
                raise HTTPException(
                    409,
                    f"No se puede eliminar: hay {confirmed} inscripto(s) confirmado(s) en sus ediciones",
                )
            # CASCADE borra ediciones_taller, clases_taller, taller_inscripciones
            conn.execute("DELETE FROM talleres WHERE id = %s", (taller_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True}


@router.delete("/admin/ediciones/{edicion_id}", status_code=200)
def admin_delete_edicion(edicion_id: int, request: Request):
    """Elimina una edición específica. Falla si hay inscriptos confirmados."""
    require_admin(request)
    with get_db() as conn:
        try:
            edicion = conn.execute(
                "SELECT id, cupos_confirmados FROM ediciones_taller WHERE id = %s",
                (edicion_id,),
            ).fetchone()
            if edicion is None:
                raise HTTPException(404, "Edición no encontrada")
            if edicion["cupos_confirmados"] > 0:
                raise HTTPException(
                    409,
                    f"No se puede eliminar: hay {edicion['cupos_confirmados']} inscripto(s) confirmado(s)",
                )
            conn.execute("DELETE FROM ediciones_taller WHERE id = %s", (edicion_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True}


# ── Instructores: entidad propia + mini-CRUD (F3) ────────────────────────────
# Un taller puede tener varios instructores; un instructor puede dar varios
# talleres (Filmar: mismo instructor en Principiante y Avanzado). Fuente única
# desde F6 (reemplazó a los campos legacy `talleres.instructor_*`, retirados).
# Kind de media PROPIO ("instructor-perfil", entity_id=instructor.id) — el kind
# legacy "instructor" (entity_id=taller_id) se retiró junto con el resto en F6.

_INSTRUCTOR_PERFIL_SPECS = [
    DeriveSpec(name="display", square=False, max_width=400),
    DeriveSpec(name="display-sm", square=False, max_width=200),
]


@router.get("/admin/instructores")
def admin_list_instructores(request: Request):
    """Lista todos los instructores (para el selector del taller)."""
    require_admin(request)
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM instructores ORDER BY nombre").fetchall()
        return [_instructor_dict(r) for r in rows]


@router.post("/admin/instructores", status_code=201)
def admin_create_instructor(body: InstructorBody, request: Request):
    require_admin(request)
    if not body.nombre.strip():
        raise HTTPException(400, "El nombre es obligatorio")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO instructores (nombre, rol, descripcion, instagram, web, proyectos) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (body.nombre.strip(), body.rol.strip(), body.descripcion.strip(),
             body.instagram.strip(), body.web.strip(), body.proyectos.strip()),
        )
        instructor_id = cur.fetchone()["id"]
        conn.commit()
        row = conn.execute("SELECT * FROM instructores WHERE id = %s", (instructor_id,)).fetchone()
    return _instructor_dict(row)


@router.patch("/admin/instructores/{instructor_id}")
def admin_update_instructor(instructor_id: int, body: InstructorUpdateBody, request: Request):
    require_admin(request)
    sets = []
    params: list = []
    if body.nombre is not None:
        if not body.nombre.strip():
            raise HTTPException(400, "El nombre es obligatorio")
        sets.append("nombre = %s"); params.append(body.nombre.strip())
    if body.rol is not None:
        sets.append("rol = %s"); params.append(body.rol.strip())
    if body.descripcion is not None:
        sets.append("descripcion = %s"); params.append(body.descripcion.strip())
    if body.instagram is not None:
        sets.append("instagram = %s"); params.append(body.instagram.strip())
    if body.web is not None:
        sets.append("web = %s"); params.append(body.web.strip())
    if body.proyectos is not None:
        sets.append("proyectos = %s"); params.append(body.proyectos.strip())
    if body.activo is not None:
        sets.append("activo = %s"); params.append(body.activo)
    if not sets:
        raise HTTPException(400, "No hay campos para actualizar")
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM instructores WHERE id = %s", (instructor_id,)
        ).fetchone()
        if existing is None:
            raise HTTPException(404, "Instructor no encontrado")
        sets.append("updated_at = NOW()")
        params.append(instructor_id)
        conn.execute(f"UPDATE instructores SET {', '.join(sets)} WHERE id = %s", params)
        conn.commit()
        row = conn.execute("SELECT * FROM instructores WHERE id = %s", (instructor_id,)).fetchone()
    return _instructor_dict(row)


@router.delete("/admin/instructores/{instructor_id}", status_code=200)
def admin_delete_instructor(instructor_id: int, request: Request):
    """Borra un instructor. 409 si está vinculado a algún taller (desvincular
    primero) — más simple y seguro que distinguir por taller/edición activa."""
    require_admin(request)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM instructores WHERE id = %s", (instructor_id,)
        ).fetchone()
        if existing is None:
            raise HTTPException(404, "Instructor no encontrado")
        vinculado = conn.execute(
            "SELECT 1 FROM taller_instructores WHERE instructor_id = %s LIMIT 1",
            (instructor_id,),
        ).fetchone()
        if vinculado:
            raise HTTPException(409, "Desvinculalo de sus talleres antes de borrarlo")
        conn.execute("DELETE FROM instructores WHERE id = %s", (instructor_id,))
        conn.commit()
    return {"ok": True}


@router.post("/admin/instructores/{instructor_id}/upload-foto")
async def admin_upload_foto_instructor_perfil(instructor_id: int, request: Request):
    """Sube la foto de un instructor (entidad F3) a R2 vía el motor de media."""
    require_admin(request)
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM instructores WHERE id = %s", (instructor_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Instructor no encontrado")

    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise HTTPException(400, "Falta el campo 'file' en el form-data")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Archivo vacío")
    if len(raw) > FOTO_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"Archivo muy grande (máx {FOTO_MAX_MB} MB)")

    try:
        with get_db() as conn:
            asset = store_upload(
                raw, kind="instructor-perfil", derive_specs=_INSTRUCTOR_PERFIL_SPECS, conn=conn
            )
            display = asset.variant("display") or (asset.variants[0] if asset.variants else None)
            url = display.url if display else ""
            conn.execute(
                "UPDATE instructores SET foto_media_id = %s, foto_url = %s, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (asset.id, url, instructor_id),
            )
            conn.commit()
    except MediaError as e:
        raise HTTPException(e.status, e.detail)
    except Exception as e:
        logger.error("upload_foto_instructor_perfil: error inesperado: %s", e, exc_info=True)
        raise HTTPException(502, "No se pudo subir la foto. Intentá de nuevo.")

    return {"ok": True, "url": url, "media_id": asset.id}


@router.put("/admin/talleres/{taller_id}/instructores")
def admin_set_taller_instructores(taller_id: int, body: TallerInstructoresBody, request: Request):
    """Reemplaza la lista (ordenada) de instructores de un taller."""
    require_admin(request)
    with get_db() as conn:
        t = conn.execute("SELECT id FROM talleres WHERE id = %s", (taller_id,)).fetchone()
        if t is None:
            raise HTTPException(404, "Taller no encontrado")
        if body.instructor_ids:
            existentes = {
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM instructores WHERE id = ANY(%s)", (body.instructor_ids,)
                ).fetchall()
            }
            faltantes = set(body.instructor_ids) - existentes
            if faltantes:
                raise HTTPException(400, f"Instructor(es) inexistente(s): {sorted(faltantes)}")
        conn.execute("DELETE FROM taller_instructores WHERE taller_id = %s", (taller_id,))
        for orden, instructor_id in enumerate(body.instructor_ids):
            conn.execute(
                "INSERT INTO taller_instructores (taller_id, instructor_id, orden) "
                "VALUES (%s, %s, %s)",
                (taller_id, instructor_id, orden),
            )
        conn.commit()
        instructores_out = _get_instructores_taller(conn, taller_id)
    return {"instructores": instructores_out}


# ── Instituciones co-presentadoras (ej. "Rambla" + "Filmar") ────────────────────
# Mismo patrón que instructores: entidad propia + N↔N con talleres.

_INSTITUCION_LOGO_SPECS = [
    DeriveSpec(name="display", square=False, max_width=400),
    DeriveSpec(name="display-sm", square=False, max_width=200),
]


@router.get("/admin/instituciones")
def admin_list_instituciones(request: Request):
    """Lista todas las instituciones (para el selector del taller)."""
    require_admin(request)
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM instituciones ORDER BY nombre").fetchall()
        return [_institucion_dict(r) for r in rows]


@router.post("/admin/instituciones", status_code=201)
def admin_create_institucion(body: InstitucionBody, request: Request):
    require_admin(request)
    if not body.nombre.strip():
        raise HTTPException(400, "El nombre es obligatorio")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO instituciones (nombre, descripcion, instagram, web) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (body.nombre.strip(), body.descripcion.strip(),
             body.instagram.strip(), body.web.strip()),
        )
        institucion_id = cur.fetchone()["id"]
        conn.commit()
        row = conn.execute(
            "SELECT * FROM instituciones WHERE id = %s", (institucion_id,)
        ).fetchone()
    return _institucion_dict(row)


@router.patch("/admin/instituciones/{institucion_id}")
def admin_update_institucion(institucion_id: int, body: InstitucionUpdateBody, request: Request):
    require_admin(request)
    sets = []
    params: list = []
    if body.nombre is not None:
        if not body.nombre.strip():
            raise HTTPException(400, "El nombre es obligatorio")
        sets.append("nombre = %s"); params.append(body.nombre.strip())
    if body.descripcion is not None:
        sets.append("descripcion = %s"); params.append(body.descripcion.strip())
    if body.instagram is not None:
        sets.append("instagram = %s"); params.append(body.instagram.strip())
    if body.web is not None:
        sets.append("web = %s"); params.append(body.web.strip())
    if not sets:
        raise HTTPException(400, "No hay campos para actualizar")
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM instituciones WHERE id = %s", (institucion_id,)
        ).fetchone()
        if existing is None:
            raise HTTPException(404, "Institución no encontrada")
        sets.append("updated_at = NOW()")
        params.append(institucion_id)
        conn.execute(f"UPDATE instituciones SET {', '.join(sets)} WHERE id = %s", params)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM instituciones WHERE id = %s", (institucion_id,)
        ).fetchone()
    return _institucion_dict(row)


@router.delete("/admin/instituciones/{institucion_id}", status_code=200)
def admin_delete_institucion(institucion_id: int, request: Request):
    """Borra una institución. 409 si está vinculada a algún taller (desvincular
    primero) — mismo criterio que instructores."""
    require_admin(request)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM instituciones WHERE id = %s", (institucion_id,)
        ).fetchone()
        if existing is None:
            raise HTTPException(404, "Institución no encontrada")
        vinculada = conn.execute(
            "SELECT 1 FROM taller_instituciones WHERE institucion_id = %s LIMIT 1",
            (institucion_id,),
        ).fetchone()
        if vinculada:
            raise HTTPException(409, "Desvinculala de sus talleres antes de borrarla")
        conn.execute("DELETE FROM instituciones WHERE id = %s", (institucion_id,))
        conn.commit()
    return {"ok": True}


@router.post("/admin/instituciones/{institucion_id}/upload-logo")
async def admin_upload_logo_institucion(institucion_id: int, request: Request):
    """Sube el logo de una institución a R2 vía el motor de media."""
    require_admin(request)
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM instituciones WHERE id = %s", (institucion_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Institución no encontrada")

    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise HTTPException(400, "Falta el campo 'file' en el form-data")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Archivo vacío")
    if len(raw) > FOTO_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"Archivo muy grande (máx {FOTO_MAX_MB} MB)")

    try:
        with get_db() as conn:
            asset = store_upload(
                raw, kind="institucion-logo", derive_specs=_INSTITUCION_LOGO_SPECS, conn=conn
            )
            display = asset.variant("display") or (asset.variants[0] if asset.variants else None)
            url = display.url if display else ""
            conn.execute(
                "UPDATE instituciones SET logo_media_id = %s, logo_url = %s, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (asset.id, url, institucion_id),
            )
            conn.commit()
    except MediaError as e:
        raise HTTPException(e.status, e.detail)
    except Exception as e:
        logger.error("upload_logo_institucion: error inesperado: %s", e, exc_info=True)
        raise HTTPException(502, "No se pudo subir el logo. Intentá de nuevo.")

    return {"ok": True, "url": url, "media_id": asset.id}


@router.put("/admin/talleres/{taller_id}/instituciones")
def admin_set_taller_instituciones(taller_id: int, body: TallerInstitucionesBody, request: Request):
    """Reemplaza la lista (ordenada) de instituciones co-presentadoras de un taller."""
    require_admin(request)
    with get_db() as conn:
        t = conn.execute("SELECT id FROM talleres WHERE id = %s", (taller_id,)).fetchone()
        if t is None:
            raise HTTPException(404, "Taller no encontrado")
        if body.institucion_ids:
            existentes = {
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM instituciones WHERE id = ANY(%s)", (body.institucion_ids,)
                ).fetchall()
            }
            faltantes = set(body.institucion_ids) - existentes
            if faltantes:
                raise HTTPException(400, f"Institución(es) inexistente(s): {sorted(faltantes)}")
        conn.execute("DELETE FROM taller_instituciones WHERE taller_id = %s", (taller_id,))
        for orden, institucion_id in enumerate(body.institucion_ids):
            conn.execute(
                "INSERT INTO taller_instituciones (taller_id, institucion_id, orden) "
                "VALUES (%s, %s, %s)",
                (taller_id, institucion_id, orden),
            )
        conn.commit()
        instituciones_out = _get_instituciones_taller(conn, taller_id)
    return {"instituciones": instituciones_out}


# ── Trabajos pasados (F4c) ─────────────────────────────────────────────────────
# Solo links de YouTube (sin testimonios/reseñas, decisión del dueño). Mismo
# patrón de poster que el video hero del concepto (F4a): se descarga y guarda
# en R2, no se depende de img.youtube.com en cada visita.

class TrabajoBody(BaseModel):
    titulo: str = ""
    youtube_url: str


class TrabajoUpdateBody(BaseModel):
    titulo: str | None = None
    youtube_url: str | None = None
    orden: int | None = None


def _procesar_youtube_poster(youtube_url: str, conn) -> tuple[int, str]:
    """Valida la URL de YouTube y descarga+guarda el poster. 400 si la URL no
    es de YouTube. Devuelve (media_id, poster_url)."""
    vid = extract_video_id(youtube_url)
    if vid is None:
        raise HTTPException(400, "URL de YouTube inválida")
    try:
        asset = store_youtube_poster(vid, kind="taller", conn=conn)
    except MediaError as e:
        raise HTTPException(e.status, e.detail)
    display = asset.variant("display") or (asset.variants[0] if asset.variants else None)
    return asset.id, (display.url if display else "")


@router.post("/admin/talleres/{taller_id}/trabajos", status_code=201)
def admin_crear_trabajo(taller_id: int, body: TrabajoBody, request: Request):
    """Agrega un trabajo pasado (link de YouTube) al taller."""
    require_admin(request)
    with get_db() as conn:
        try:
            existing = conn.execute("SELECT id FROM talleres WHERE id = %s", (taller_id,)).fetchone()
            if existing is None:
                raise HTTPException(404, "Taller no encontrado")
            media_id, poster_url = _procesar_youtube_poster(body.youtube_url, conn)
            next_orden = conn.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 AS next FROM taller_trabajos "
                "WHERE taller_id = %s",
                (taller_id,),
            ).fetchone()["next"]
            row = conn.execute(
                "INSERT INTO taller_trabajos "
                "(taller_id, titulo, youtube_url, poster_media_id, poster_url, orden) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                (taller_id, body.titulo.strip(), body.youtube_url.strip(), media_id, poster_url, next_orden),
            ).fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return _trabajo_dict(row)


@router.patch("/admin/trabajos/{trabajo_id}")
def admin_editar_trabajo(trabajo_id: int, body: TrabajoUpdateBody, request: Request):
    """Edita un trabajo. Cambiar `youtube_url` re-descarga el poster."""
    require_admin(request)
    sets = []
    params: list = []
    if body.titulo is not None:
        sets.append("titulo = %s"); params.append(body.titulo.strip())
    if body.orden is not None:
        sets.append("orden = %s"); params.append(body.orden)

    with get_db() as conn:
        try:
            existing = conn.execute(
                "SELECT id FROM taller_trabajos WHERE id = %s", (trabajo_id,)
            ).fetchone()
            if existing is None:
                raise HTTPException(404, "Trabajo no encontrado")
            if body.youtube_url is not None:
                media_id, poster_url = _procesar_youtube_poster(body.youtube_url, conn)
                sets.append("youtube_url = %s"); params.append(body.youtube_url.strip())
                sets.append("poster_media_id = %s"); params.append(media_id)
                sets.append("poster_url = %s"); params.append(poster_url)
            if not sets:
                raise HTTPException(400, "No hay campos para actualizar")
            params.append(trabajo_id)
            row = conn.execute(
                f"UPDATE taller_trabajos SET {', '.join(sets)} WHERE id = %s RETURNING *",
                params,
            ).fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return _trabajo_dict(row)


@router.delete("/admin/trabajos/{trabajo_id}", status_code=200)
def admin_eliminar_trabajo(trabajo_id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        row = conn.execute(
            "DELETE FROM taller_trabajos WHERE id = %s RETURNING id", (trabajo_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Trabajo no encontrado")
        conn.commit()
    return {"ok": True}


# ── Portada por clase (F2) ────────────────────────────────────────────────────
# La portada es la imagen de marketing de una clase (se ve en la card colapsable
# de la landing). Solo clases YA GUARDADAS (necesitan id); el upsert de clases
# NO la toca — cambia únicamente por estos dos endpoints.

_PORTADA_SPECS = [
    DeriveSpec(name="display", square=False, max_width=1200),
    DeriveSpec(name="display-sm", square=False, max_width=480),
]


@router.post("/admin/clases/{clase_id}/portada")
@limiter.limit("20/minute")
async def admin_upload_portada_clase(clase_id: int, request: Request):
    """Sube la portada de una clase a R2 vía el motor de media."""
    require_admin(request)
    with get_db() as conn:
        row = conn.execute("SELECT id FROM clases_taller WHERE id = %s", (clase_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Clase no encontrada")

    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise HTTPException(400, "Falta el campo 'file' en el form-data")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Archivo vacío")
    if len(raw) > FOTO_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"Archivo muy grande (máx {FOTO_MAX_MB} MB)")

    try:
        with get_db() as conn:
            asset = store_upload(raw, kind="taller", derive_specs=_PORTADA_SPECS, conn=conn)
            display = asset.variant("display") or (asset.variants[0] if asset.variants else None)
            url = display.url if display else ""
            conn.execute(
                "UPDATE clases_taller SET portada_media_id = %s, portada_url = %s WHERE id = %s",
                (asset.id, url, clase_id),
            )
            conn.commit()
    except MediaError as e:
        raise HTTPException(e.status, e.detail)
    except Exception as e:
        logger.error("upload_portada_clase: error inesperado: %s", e, exc_info=True)
        raise HTTPException(502, "No se pudo subir la portada. Intentá de nuevo.")

    return {"ok": True, "url": url, "media_id": asset.id}


@router.delete("/admin/clases/{clase_id}/portada")
@limiter.limit("30/minute")
def admin_delete_portada_clase(clase_id: int, request: Request):
    """Quita la portada de una clase (el asset queda en media_assets; el
    SET NULL del FK lo desengancha — no se purga R2 acá, mismo criterio que
    la foto de instructor)."""
    require_admin(request)
    with get_db() as conn:
        row = conn.execute("SELECT id FROM clases_taller WHERE id = %s", (clase_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Clase no encontrada")
        conn.execute(
            "UPDATE clases_taller SET portada_media_id = NULL, portada_url = '' WHERE id = %s",
            (clase_id,),
        )
        conn.commit()
    return {"ok": True}


# ── Galería de fotos por EDICIÓN (portada + galería pública) ────────────────
# Espejo exacto de la galería del Estudio (`routes/estudio.py::_get_fotos` /
# `_insert_foto` / upload / delete / reorder), scoped a `edicion_id` en vez
# del singleton Estudio — por decisión del dueño, portada+galería son por
# EDICIÓN, no por taller (a diferencia de `video_url`, que sí es del taller).


def _get_edicion_fotos(conn, edicion_id: int) -> list:
    cur = conn.execute(
        "SELECT id, url, url_sm, url_avif, url_sm_avif, path, orden, es_principal, created_at "
        "FROM edicion_fotos WHERE edicion_id = %s ORDER BY orden, id",
        (edicion_id,),
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


def _insert_edicion_foto(
    conn,
    edicion_id: int,
    url: str,
    path: str,
    media_id: int | None = None,
    url_sm: str | None = None,
    url_avif: str | None = None,
    url_sm_avif: str | None = None,
) -> dict:
    cur = conn.execute(
        "SELECT COALESCE(MAX(orden), -1) + 1 AS next_orden FROM edicion_fotos WHERE edicion_id = %s",
        (edicion_id,),
    )
    orden = cur.fetchone()["next_orden"]

    cur2 = conn.execute(
        "SELECT COUNT(*) AS cnt FROM edicion_fotos WHERE edicion_id = %s", (edicion_id,)
    )
    is_first = cur2.fetchone()["cnt"] == 0

    conn.execute(
        "INSERT INTO edicion_fotos "
        "(edicion_id, url, url_sm, url_avif, url_sm_avif, path, orden, es_principal, media_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (edicion_id, url, url_sm, url_avif, url_sm_avif, path, orden, is_first, media_id),
    )
    conn.commit()

    cur3 = conn.execute(
        "SELECT id, url, url_sm, url_avif, url_sm_avif, path, orden, es_principal, created_at "
        "FROM edicion_fotos WHERE path = %s AND edicion_id = %s",
        (path, edicion_id),
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


@router.post("/admin/ediciones/{edicion_id}/upload-foto")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
async def admin_upload_foto_edicion(edicion_id: int, request: Request):
    """Sube un archivo (multipart, campo 'file') a R2 y lo registra en edicion_fotos."""
    require_admin(request)

    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM ediciones_taller WHERE id = %s", (edicion_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Edición no encontrada")

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
                    kind="taller",
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
            foto = _insert_edicion_foto(
                conn,
                edicion_id,
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


@router.delete("/admin/ediciones/fotos/{foto_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def admin_delete_foto_edicion(foto_id: int, request: Request):
    require_admin(request)

    with get_db() as conn:
        cur = conn.execute(
            "SELECT path, media_id FROM edicion_fotos WHERE id = %s", (foto_id,)
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

        conn.execute("DELETE FROM edicion_fotos WHERE id = %s", (foto_id,))
        if media_id:
            conn.execute("DELETE FROM media_assets WHERE id = %s", (media_id,))
        conn.commit()

    # Best-effort R2 cleanup (después del commit — la DB es la fuente de verdad)
    if r2_keys:
        purge_r2(r2_keys)

    return {"ok": True}


class EdicionFotoOrdenItem(BaseModel):
    id: int
    orden: int
    es_principal: bool


class EdicionReorderFotosBody(BaseModel):
    fotos: list[EdicionFotoOrdenItem]


@router.patch("/admin/ediciones/{edicion_id}/fotos/orden")
@limiter.limit(ADMIN_WRITE_LIMIT)
def admin_reorder_fotos_edicion(edicion_id: int, body: EdicionReorderFotosBody, request: Request):
    require_admin(request)

    with get_db() as conn:
        for f in body.fotos:
            # El array llega completo en cada drag — el guard evita reescribir
            # las fotos que no se movieron (mismo patrón que estudio_fotos).
            conn.execute(
                "UPDATE edicion_fotos SET orden = %s, es_principal = %s "
                "WHERE id = %s AND edicion_id = %s "
                "AND (orden IS DISTINCT FROM %s OR es_principal IS DISTINCT FROM %s)",
                (f.orden, f.es_principal, f.id, edicion_id, f.orden, f.es_principal),
            )
        conn.commit()
        fotos = _get_edicion_fotos(conn, edicion_id)

    return {"fotos": fotos}


# ── Inscripciones (admin) ─────────────────────────────────────────────────────

@router.get("/admin/talleres/{taller_id}/inscripciones")
def admin_list_inscripciones(taller_id: int, request: Request):
    """Lista todas las inscripciones del concepto (todas sus ediciones)."""
    require_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT ti.*, e.numero_edicion, e.slug AS edicion_slug
            FROM taller_inscripciones ti
            LEFT JOIN ediciones_taller e ON e.id = ti.edicion_id
            WHERE ti.taller_id = %s AND ti.eliminado_at IS NULL
            ORDER BY ti.en_lista_espera, ti.created_at
            """,
            (taller_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "nombre": r["nombre"],
            "email": r["email"],
            "telefono": r["telefono"],
            "experiencia": r["experiencia"],
            "comprobante_url": _comprobante_url_fresca(r["comprobante_key"], r["comprobante_url"]),
            "en_lista_espera": r["en_lista_espera"],
            "estado": r["estado"],
            "edicion_id": r["edicion_id"],
            "numero_edicion": r["numero_edicion"],
            "edicion_slug": r["edicion_slug"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "tyc_aceptado_at": r["tyc_aceptado_at"].isoformat() if r["tyc_aceptado_at"] else None,
            "modalidad_codigo": r["modalidad_codigo"],
            "modalidad_label": r["modalidad_label"],
            "modalidad_monto": r["modalidad_monto"],
        }
        for r in rows
    ]


@router.get("/admin/ediciones/{edicion_id}/inscripciones")
def admin_list_inscripciones_edicion(edicion_id: int, request: Request):
    """Lista inscripciones de una edición específica."""
    require_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT ti.*, e.numero_edicion, e.slug AS edicion_slug
            FROM taller_inscripciones ti
            LEFT JOIN ediciones_taller e ON e.id = ti.edicion_id
            WHERE ti.edicion_id = %s AND ti.eliminado_at IS NULL
            ORDER BY ti.en_lista_espera, ti.created_at
            """,
            (edicion_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "nombre": r["nombre"],
            "email": r["email"],
            "telefono": r["telefono"],
            "experiencia": r["experiencia"],
            "comprobante_url": _comprobante_url_fresca(r["comprobante_key"], r["comprobante_url"]),
            "en_lista_espera": r["en_lista_espera"],
            "estado": r["estado"],
            "edicion_id": r["edicion_id"],
            "numero_edicion": r["numero_edicion"],
            "edicion_slug": r["edicion_slug"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "tyc_aceptado_at": r["tyc_aceptado_at"].isoformat() if r["tyc_aceptado_at"] else None,
            "modalidad_codigo": r["modalidad_codigo"],
            "modalidad_label": r["modalidad_label"],
            "modalidad_monto": r["modalidad_monto"],
        }
        for r in rows
    ]


@router.get("/admin/ediciones/{edicion_id}/kpis")
def admin_edicion_kpis(edicion_id: int, request: Request):
    """Mini-KPIs de una edición: señas verificadas/pendientes/en espera + plata
    señada esperada (comprobante subido, sin verificar) vs recibida (verificada).
    `precio_sena` es un monto plano de la edición (no una regla de precio/combo/
    descuento): la plata acá es cantidad × ese monto, resuelta en el backend —
    el front solo la muestra (regla "el front no calcula plata", MEMORIA
    2026-06-29)."""
    require_admin(request)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT e.precio_sena,
                   COUNT(*) FILTER (WHERE ti.estado = 'confirmada') AS senas_verificadas,
                   COUNT(*) FILTER (WHERE ti.estado = 'pendiente_sena') AS senas_pendientes,
                   COUNT(*) FILTER (WHERE ti.estado = 'en_espera') AS en_espera,
                   COUNT(*) FILTER (WHERE ti.estado = 'cupo_ofrecido') AS cupo_ofrecido
            FROM ediciones_taller e
            LEFT JOIN taller_inscripciones ti
                   ON ti.edicion_id = e.id AND ti.eliminado_at IS NULL
            WHERE e.id = %s
            GROUP BY e.id
            """,
            (edicion_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Edición no encontrada")
    return {
        "senas_verificadas": row["senas_verificadas"],
        "senas_pendientes": row["senas_pendientes"],
        "en_espera": row["en_espera"],
        "cupo_ofrecido": row["cupo_ofrecido"],
        "plata_recibida_str": _fmt_pesos(row["precio_sena"] * row["senas_verificadas"]),
        "plata_esperada_str": _fmt_pesos(row["precio_sena"] * row["senas_pendientes"]),
    }


@router.get("/admin/ediciones/{edicion_id}/pedidos")
def admin_list_pedidos_edicion(edicion_id: int, request: Request):
    """Pedidos mensuales que `_regenerar_pedidos_taller` generó para esta
    edición (`taller_edicion_id`) — el puente Talleres → Pedidos (Fase 1,
    #1308): antes había que buscarlos a mano en /admin/pedidos, sin ver de un
    vistazo qué meses ya están pagados. Ordenados por mes; el front linkea
    cada uno a `/admin/pedidos/{id}`."""
    require_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, numero_pedido, estado, fecha_desde, fecha_hasta,
                   monto_total, monto_pagado
            FROM alquileres
            WHERE taller_edicion_id = %s
            ORDER BY fecha_desde
            """,
            (edicion_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "numero_pedido": r["numero_pedido"],
            "estado": r["estado"],
            "fecha_desde": r["fecha_desde"].isoformat() if r["fecha_desde"] else None,
            "fecha_hasta": r["fecha_hasta"].isoformat() if r["fecha_hasta"] else None,
            "monto_total": r["monto_total"],
            "monto_pagado": r["monto_pagado"],
        }
        for r in rows
    ]


@router.get("/admin/talleres/{taller_id}/inscripciones/export-csv")
def admin_export_inscripciones_csv(taller_id: int, request: Request):
    """Descarga CSV de inscriptos de un concepto de taller."""
    require_admin(request)
    with get_db() as conn:
        taller_row = conn.execute(
            "SELECT nombre, slug_base FROM talleres WHERE id = %s", (taller_id,)
        ).fetchone()
        if taller_row is None:
            raise HTTPException(404, "Taller no encontrado")
        rows = conn.execute(
            """
            SELECT ti.nombre, ti.email, ti.telefono, ti.experiencia,
                   ti.en_lista_espera, ti.created_at, e.numero_edicion,
                   ti.modalidad_label, ti.tyc_aceptado_at
            FROM taller_inscripciones ti
            LEFT JOIN ediciones_taller e ON e.id = ti.edicion_id
            WHERE ti.taller_id = %s AND ti.eliminado_at IS NULL
            ORDER BY ti.en_lista_espera, ti.created_at
            """,
            (taller_id,),
        ).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "nombre", "email", "telefono", "experiencia", "edicion", "estado",
        "modalidad_pago", "acepto_terminos", "inscripto_at",
    ])
    for r in rows:
        estado = "lista espera" if r["en_lista_espera"] else "confirmado"
        w.writerow([
            r["nombre"], r["email"], r["telefono"],
            r["experiencia"] or "",
            r["numero_edicion"] or "",
            estado,
            r["modalidad_label"] or "",
            "sí" if r["tyc_aceptado_at"] else "no",
            r["created_at"].isoformat() if r["created_at"] else "",
        ])
    csv_bytes = buf.getvalue().encode("utf-8-sig")
    filename = f"inscriptos-{taller_row['slug_base'] or 'taller'}.csv"
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/admin/talleres/{taller_id}/inscripciones/{ins_id}", status_code=200)
def admin_delete_inscripcion(taller_id: int, ins_id: int, request: Request):
    """Da de baja una inscripción (soft-delete). Si era confirmada, decrementa
    cupos en la edición.

    Soft, no DELETE real (2026-08-13, pedido del dueño): toda persona que se
    inscribe sirve como dataset de interesados — se saca de las vistas/listas/
    conteos normales, pero la fila (nombre/mail/teléfono) no se pierde.

    `FOR UPDATE`: sin el lock, un reclamo de cupo concurrente
    (POST /talleres/sena/{token}, que también toma FOR UPDATE sobre esta
    misma fila) podía commitear `en_lista_espera=False` justo entre este
    SELECT y la baja — el admin daba de baja la fila leyendo el
    `en_lista_espera` viejo (True) y se saltaba el decremento, dejando
    `cupos_confirmados` contando de más para siempre (hallazgo del
    supervisor, reproducido con dos conexiones reales)."""
    # `or {}`: algunos tests llaman a esta función directo (sin HTTP) con
    # require_admin mockeado a `lambda r: None` — nunca antes hacía falta su
    # valor de retorno en este archivo, así que ningún test lo cubría.
    session = require_admin(request) or {}
    with get_db() as conn:
        try:
            ins = conn.execute(
                "SELECT id, en_lista_espera, edicion_id FROM taller_inscripciones "
                "WHERE id = %s AND taller_id = %s AND eliminado_at IS NULL FOR UPDATE",
                (ins_id, taller_id),
            ).fetchone()
            if ins is None:
                raise HTTPException(404, "Inscripción no encontrada")
            conn.execute(
                "UPDATE taller_inscripciones SET eliminado_at = NOW(), eliminado_por = %s "
                "WHERE id = %s",
                (session.get("email", "unknown"), ins_id),
            )
            if not ins["en_lista_espera"] and ins["edicion_id"]:
                conn.execute(
                    "UPDATE ediciones_taller "
                    "SET cupos_confirmados = GREATEST(0, cupos_confirmados - 1), updated_at = NOW() "
                    "WHERE id = %s",
                    (ins["edicion_id"],),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True}


@router.post("/admin/talleres/{taller_id}/inscripciones/{ins_id}/confirmar", status_code=200)
def admin_confirmar_inscripcion(taller_id: int, ins_id: int, request: Request):
    """Pasa una inscripción de lista de espera a confirmada."""
    require_admin(request)
    with get_db() as conn:
        try:
            ins = conn.execute(
                "SELECT id, en_lista_espera, edicion_id FROM taller_inscripciones "
                "WHERE id = %s AND taller_id = %s AND eliminado_at IS NULL",
                (ins_id, taller_id),
            ).fetchone()
            if ins is None:
                raise HTTPException(404, "Inscripción no encontrada")
            if not ins["en_lista_espera"]:
                raise HTTPException(400, "La inscripción ya está confirmada")

            if ins["edicion_id"]:
                edicion = conn.execute(
                    "SELECT cupos_total, cupos_confirmados FROM ediciones_taller "
                    "WHERE id = %s FOR UPDATE",
                    (ins["edicion_id"],),
                ).fetchone()
                if edicion["cupos_confirmados"] >= edicion["cupos_total"]:
                    raise HTTPException(400, "No hay cupos disponibles para confirmar")
                conn.execute(
                    "UPDATE ediciones_taller "
                    "SET cupos_confirmados = cupos_confirmados + 1, updated_at = NOW() "
                    "WHERE id = %s",
                    (ins["edicion_id"],),
                )

            conn.execute(
                "UPDATE taller_inscripciones "
                "SET en_lista_espera = FALSE, estado = 'pendiente_sena', confirmed_at = NOW() "
                "WHERE id = %s",
                (ins_id,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True}


@router.post("/admin/talleres/{taller_id}/inscripciones/{ins_id}/verificar-sena", status_code=200)
def admin_verificar_sena(taller_id: int, ins_id: int, request: Request):
    """Verifica la seña de una inscripción `pendiente_sena` → `confirmada`.
    Manda mail al inscripto ("tu lugar está confirmado")."""
    require_admin(request)
    with get_db() as conn:
        try:
            ins = conn.execute(
                "SELECT id, estado, nombre, email, edicion_id FROM taller_inscripciones "
                "WHERE id = %s AND taller_id = %s AND eliminado_at IS NULL",
                (ins_id, taller_id),
            ).fetchone()
            if ins is None:
                raise HTTPException(404, "Inscripción no encontrada")
            if ins["estado"] != "pendiente_sena":
                raise HTTPException(400, "La inscripción no está pendiente de seña")
            conn.execute(
                "UPDATE taller_inscripciones SET sena_verificada_at = NOW(), estado = 'confirmada' "
                "WHERE id = %s",
                (ins_id,),
            )
            conn.commit()
            edicion_row = conn.execute(
                "SELECT e.*, t.nombre AS taller_nombre FROM ediciones_taller e "
                "JOIN talleres t ON t.id = e.taller_id WHERE e.id = %s",
                (ins["edicion_id"],),
            ).fetchone()
        except Exception:
            conn.rollback()
            raise

    send_email("taller_sena_confirmada", ins["email"], {
        "taller_nombre": edicion_row["taller_nombre"],
        "nombre_pila": ins["nombre"].split()[0],
        "fecha_inicio_str": _fmt_fecha_es(edicion_row["fecha_inicio"]),
        "fecha_fin_str": _fmt_fecha_es(edicion_row["fecha_fin"]),
        "horario": edicion_row["horario"],
        "direccion": edicion_row["direccion"],
    })
    return {"ok": True}


@router.post("/admin/talleres/{taller_id}/inscripciones/{ins_id}/ofrecer-cupo", status_code=200)
def admin_ofrecer_cupo(taller_id: int, ins_id: int, request: Request):
    """Ofrece el cupo liberado a alguien en lista de espera: manda un mail con
    link tokenizado a "completá tu seña". NO reserva el cupo todavía — se
    reserva recién cuando la persona lo reclama (POST /talleres/sena/{token});
    así el admin puede re-ofrecer a otra persona si esta no responde, sin
    tener que "devolver" nada primero."""
    require_admin(request)
    with get_db() as conn:
        try:
            ins = conn.execute(
                "SELECT id, en_lista_espera, nombre, email, edicion_id FROM taller_inscripciones "
                "WHERE id = %s AND taller_id = %s AND eliminado_at IS NULL",
                (ins_id, taller_id),
            ).fetchone()
            if ins is None:
                raise HTTPException(404, "Inscripción no encontrada")
            if not ins["en_lista_espera"]:
                raise HTTPException(400, "Esta inscripción no está en lista de espera")
            conn.execute(
                "UPDATE taller_inscripciones SET estado = 'cupo_ofrecido', cupo_ofrecido_at = NOW() "
                "WHERE id = %s",
                (ins_id,),
            )
            conn.commit()
            edicion_row = conn.execute(
                "SELECT e.*, t.nombre AS taller_nombre FROM ediciones_taller e "
                "JOIN talleres t ON t.id = e.taller_id WHERE e.id = %s",
                (ins["edicion_id"],),
            ).fetchone()
        except Exception:
            conn.rollback()
            raise

    token = _generar_token_cupo(ins_id)
    send_email("taller_cupo_ofrecido", ins["email"], {
        "taller_nombre": edicion_row["taller_nombre"],
        "nombre_pila": ins["nombre"].split()[0],
        "precio_sena_str": _fmt_pesos(edicion_row["precio_sena"]),
        "link_sena": f"{SITE_URL}/escuelas/sena/{token}",
    })
    return {"ok": True}


class NotificarCambiosBody(BaseModel):
    mensaje: str | None = None


@router.post("/admin/talleres/{taller_id}/notificar-cambios", status_code=200)
def admin_notificar_cambios(taller_id: int, body: NotificarCambiosBody, request: Request):
    """Envía email de cambios a todos los inscriptos confirmados del concepto."""
    require_admin(request)
    with get_db() as conn:
        taller = conn.execute(
            "SELECT nombre FROM talleres WHERE id = %s", (taller_id,)
        ).fetchone()
        if taller is None:
            raise HTTPException(404, "Taller no encontrado")
        inscriptos = conn.execute(
            "SELECT nombre, email FROM taller_inscripciones "
            "WHERE taller_id = %s AND en_lista_espera = FALSE AND eliminado_at IS NULL",
            (taller_id,),
        ).fetchall()

    enviados, fallidos = [], []
    for ins in inscriptos:
        nombre_pila = ins["nombre"].split()[0]
        ctx = {
            "taller_nombre": taller["nombre"],
            "nombre_pila": nombre_pila,
            "mensaje": body.mensaje or "",
        }
        try:
            send_email("taller_cambio_datos", ins["email"], ctx)
            enviados.append(ins["email"])
        except Exception as e:
            logger.warning("notificar_cambios: error enviando a %s: %s", ins["email"], e)
            fallidos.append(ins["email"])

    return {"enviados": len(enviados), "fallidos": len(fallidos)}


@router.get("/admin/talleres/{taller_id}/interesados")
def admin_list_interesados(taller_id: int, request: Request):
    """Lista los interesados (leads sin cupo en su momento) de un concepto —
    hoy `interesados_taller` era write-only, nadie la veía desde el admin."""
    require_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, nombre, email, telefono, created_at, notificado_at "
            "FROM interesados_taller WHERE taller_id = %s ORDER BY created_at DESC",
            (taller_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "nombre": r["nombre"],
            "email": r["email"],
            "telefono": r["telefono"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "notificado_at": r["notificado_at"].isoformat() if r["notificado_at"] else None,
        }
        for r in rows
    ]


@router.post("/admin/talleres/{taller_id}/interesados/{interesado_id}/notificar", status_code=200)
def admin_notificar_interesado(taller_id: int, interesado_id: int, request: Request):
    """Avisa a un interesado que hay una nueva edición abierta. Setea la
    dormida `notificado_at` — no reintenta si ya se avisó, pero no lo bloquea
    (el admin puede re-avisar a propósito si hace falta)."""
    require_admin(request)
    with get_db() as conn:
        row = conn.execute(
            "SELECT i.nombre, i.email, t.nombre AS taller_nombre, t.slug_base "
            "FROM interesados_taller i JOIN talleres t ON t.id = i.taller_id "
            "WHERE i.id = %s AND i.taller_id = %s",
            (interesado_id, taller_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Interesado no encontrado")
        conn.execute(
            "UPDATE interesados_taller SET notificado_at = NOW() WHERE id = %s",
            (interesado_id,),
        )
        conn.commit()

    send_email("taller_interesado_nueva_edicion", row["email"], {
        "taller_nombre": row["taller_nombre"],
        "nombre_pila": row["nombre"].split()[0],
        "taller_url": f"{SITE_URL}/escuelas/{row['slug_base']}",
    })
    return {"ok": True}
