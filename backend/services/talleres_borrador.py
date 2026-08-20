"""Borradores de inscripción a un taller — mirror de `services/carrito/activos.py`
para el funnel de Talleres (2026-08-13, pedido del dueño).

A diferencia del carrito (una lista de ítems), acá el "estado a medio
completar" es lo que la persona tipeó en `WorkshopInscripcionForm` (nombre/
email/teléfono) antes de enviar — o de irse sin enviar. Mismo patrón: route =
transporte, service = lógica (funciones que reciben `conn`, no objetos con
estado).

Vive FUERA de `services/talleres/` a propósito: ese paquete deja "Inscripción/
seña" fuera de su alcance (Fase 1 acotada, ver su CLAUDE.md) — este módulo es
parte de esa misma familia (inscripción), así que respeta el mismo límite.
"""

import logging
from typing import Optional

from database import row_to_dict

logger = logging.getLogger(__name__)

# Mismo umbral que carritos_activos — sin actividad por más de esto se
# considera abandonado (se le estampa `abandonado_en` la primera vez que lo
# detectamos; un heartbeat nuevo lo limpia).
ABANDONO_HORAS = 24


def heartbeat_upsert(
    conn,
    session_id: str,
    edicion_id: int,
    nombre: Optional[str],
    email: Optional[str],
    telefono: Optional[str],
) -> None:
    """Persiste el estado del formulario vía upsert por session_id.

    `nombre`/`email`/`telefono` son lo que la persona tenga tipeado en ESE
    momento (pueden venir vacíos) — no se valida contenido acá, es un
    snapshot, no una inscripción real. El `conn` lo abre y commitea el route.
    """
    conn.execute(
        """
        INSERT INTO taller_inscripciones_borrador (
            session_id, edicion_id, nombre, email, telefono, updated_at
        ) VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (session_id) DO UPDATE SET
            edicion_id    = EXCLUDED.edicion_id,
            nombre        = EXCLUDED.nombre,
            email         = EXCLUDED.email,
            telefono      = EXCLUDED.telefono,
            abandonado_en = NULL,
            updated_at    = NOW()
        """,
        (session_id, edicion_id, nombre or None, email or None, telefono or None),
    )


def marcar_confirmado(
    conn,
    session_id: str,
    edicion_id: int,
    nombre: Optional[str] = None,
    email: Optional[str] = None,
    telefono: Optional[str] = None,
) -> None:
    """Cierra el funnel: marca el borrador como confirmado al crear la
    inscripción real. UPSERT, no un UPDATE plano: el heartbeat del form viaja
    por `fetch` sin `await` (fire-and-forget) — puede llegar a la base
    DESPUÉS de este commit (red lenta, WhatsApp in-app browser). Con un
    UPDATE simple, esa llegada tardía no encontraba fila (todavía no
    existía), y el heartbeat posterior insertaba una fila nueva
    `confirmado=FALSE` para alguien que YA se había inscripto — aparecía a
    la vez en "Confirmadas" y en "Empezaron el formulario y no lo enviaron"
    (bug real, 2026-08-20). El upsert garantiza `confirmado=TRUE` sin
    importar el orden de llegada: el heartbeat que llegue después solo
    actualiza nombre/email/teléfono, nunca toca `confirmado` (no está en su
    propio `SET`)."""
    conn.execute(
        """
        INSERT INTO taller_inscripciones_borrador (
            session_id, edicion_id, nombre, email, telefono, confirmado, updated_at
        ) VALUES (%s, %s, %s, %s, %s, TRUE, NOW())
        ON CONFLICT (session_id) DO UPDATE SET
            confirmado = TRUE,
            updated_at = NOW()
        """,
        (session_id, edicion_id, nombre or None, email or None, telefono or None),
    )


def _estampar_abandono(conn) -> None:
    """Idempotente (mismo patrón que carritos_activos): sin actividad por más
    de ABANDONO_HORAS se considera abandonado. Global — no filtra por
    edición, así que un heartbeat viejo queda estampado sin importar si
    después se lista scoped a una edición o cross-taller."""
    conn.execute(
        """
        UPDATE taller_inscripciones_borrador
        SET abandonado_en = NOW()
        WHERE NOT confirmado
          AND abandonado_en IS NULL
          AND updated_at < NOW() - (%s || ' hours')::interval
        """,
        (str(ABANDONO_HORAS),),
    )
    conn.commit()


def _borradores_resp(borradores: list[dict]) -> dict:
    con_contacto = sum(1 for b in borradores if b.get("email") or b.get("telefono"))
    abandonados = sum(1 for b in borradores if b["abandonado"])
    return {
        "borradores": borradores,
        "total": len(borradores),
        "con_contacto": con_contacto,
        "abandonados": abandonados,
    }


def listar_borradores_admin(conn, edicion_id: int, horas: int = 72) -> dict:
    """Lista borradores no confirmados de UNA edición + KPIs chicos del
    funnel, para la pestaña "Inscripciones" del admin.

    A diferencia de carritos_activos (una página propia, cross-catálogo),
    esto vive scoped a una edición puntual — un admin gestiona los borradores
    del taller que está mirando. El cross-taller vive en
    `listar_borradores_admin_global` (pestaña "Sin enviar" del sidebar).
    """
    _estampar_abandono(conn)

    rows = conn.execute(
        """
        SELECT id, session_id, nombre, email, telefono, abandonado_en, created_at, updated_at
        FROM taller_inscripciones_borrador
        WHERE edicion_id = %s
          AND NOT confirmado
          AND updated_at > NOW() - (%s || ' hours')::interval
        ORDER BY updated_at DESC
        LIMIT 200
        """,
        (edicion_id, str(horas)),
    ).fetchall()

    borradores = []
    for r in rows:
        d = row_to_dict(r)
        d["abandonado"] = d.pop("abandonado_en", None) is not None
        borradores.append(d)

    return _borradores_resp(borradores)


def listar_borradores_admin_global(conn, horas: int = 72) -> dict:
    """Vista "Sin enviar" (sidebar "Estudio y talleres", junto a
    Alumnos/Profesores) — borradores sin confirmar de TODOS los talleres,
    con el taller/edición al que pertenece cada uno, para no tener que
    entrar taller por taller a hacer seguimiento de quién no llegó a
    mandar el form. Mismo criterio que `listar_borradores_admin`."""
    _estampar_abandono(conn)

    rows = conn.execute(
        """
        SELECT b.id, b.session_id, b.nombre, b.email, b.telefono,
               b.abandonado_en, b.created_at, b.updated_at,
               e.id AS edicion_id, e.numero_edicion, e.slug AS edicion_slug,
               t.id AS taller_id, t.nombre AS taller_nombre, t.slug_base AS taller_slug
        FROM taller_inscripciones_borrador b
        JOIN ediciones_taller e ON e.id = b.edicion_id
        JOIN talleres t ON t.id = e.taller_id
        WHERE NOT b.confirmado
          AND b.updated_at > NOW() - (%s || ' hours')::interval
        ORDER BY b.updated_at DESC
        LIMIT 200
        """,
        (str(horas),),
    ).fetchall()

    borradores = []
    for r in rows:
        d = row_to_dict(r)
        d["abandonado"] = d.pop("abandonado_en", None) is not None
        borradores.append(d)

    return _borradores_resp(borradores)
