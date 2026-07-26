"""Alta de una edición de taller — dedup de las 2 duplicaciones reales
encontradas en `routes/talleres.py`: el gate de conflicto con Estudio (antes
copiado inline 3 veces) y el INSERT de `ediciones_taller` (antes copiado
byte a byte entre `admin_create_taller` y `admin_create_edicion`)."""
from services.estudio.constants import _ADVISORY_NS_ESTUDIO
from services.estudio.queries.estudio import _get_estudio_row
from services.estudio.queries.disponibilidad import verificar_sesiones_disponibles

from services.talleres.commands.clases import _insert_clases
from services.talleres.commands.economia import _regenerar_pedidos_taller


def _gate_conflicto_estudio(conn, clases: list, *, exclude_taller_id: int | None = None) -> None:
    """Dedup de las 3 copias idénticas (antes inline en admin_create_taller,
    admin_create_edicion, admin_update_edicion). El CALLER decide CUÁNDO
    invocarlo — el trigger difiere entre "nace publicada" (create) y
    "transición a publicada" (update, con su propia condición más compleja);
    esta función solo encapsula el CÓMO. Lanza 409 (vía
    `verificar_sesiones_disponibles`) si hay conflicto."""
    estudio = _get_estudio_row(conn)
    if not estudio["equipo_id"]:
        return
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_ADVISORY_NS_ESTUDIO, 1))
    verificar_sesiones_disponibles(conn, estudio, clases, exclude_taller_id=exclude_taller_id)


def crear_edicion(
    conn, *, taller_id: int, ed_numero: int, slug_edicion: str, clases: list,
    campos: dict, taller_nombre: str, numero_pedido_fn,
) -> dict:
    """INSERT `ediciones_taller` + sus clases + regenerar economía — núcleo
    compartido por `admin_create_taller` (primera edición de un concepto
    nuevo) y `admin_create_edicion` (edición nueva de un concepto existente);
    antes 2 copias byte a byte del mismo INSERT de 20 columnas.

    El GATE de conflicto con Estudio NO está adentro a propósito — el caller
    lo invoca ANTES (mismo orden relativo que el código de origen en ambos
    call-sites: se verifica disponibilidad antes de tocar `talleres`/
    `ediciones_taller`).

    `campos` = dict ya armado por el caller (valores ya `.strip()`eados donde
    corresponde) con: tipo_taller, horario, cupos_total, precio_total,
    precio_sena, pago_alias, pago_cbu, pago_banco, direccion, activo,
    usa_estudio, valor_estudio, valor_estudio_modo, usa_equipos, valor_equipos,
    valor_equipos_modo. `fecha_inicio`/`fecha_fin` se derivan acá de `clases`
    (no los pide `campos` — evita que caller y función puedan desincronizarse).

    No commitea — responsabilidad del caller (route)."""
    fecha_inicio = min(c["fecha"] for c in clases)
    fecha_fin = max(c["fecha"] for c in clases)

    edicion_id = conn.insert_returning(
        """
        INSERT INTO ediciones_taller (
            taller_id, numero_edicion, slug, tipo_taller,
            fecha_inicio, fecha_fin, horario,
            cupos_total, precio_total, precio_sena,
            pago_alias, pago_cbu, pago_banco,
            direccion, activo,
            usa_estudio, valor_estudio, valor_estudio_modo,
            usa_equipos, valor_equipos, valor_equipos_modo
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            taller_id, ed_numero, slug_edicion, campos["tipo_taller"],
            fecha_inicio, fecha_fin, campos["horario"],
            campos["cupos_total"], campos["precio_total"], campos["precio_sena"],
            campos["pago_alias"], campos["pago_cbu"], campos["pago_banco"],
            campos["direccion"], campos["activo"],
            campos["usa_estudio"], campos["valor_estudio"], campos["valor_estudio_modo"],
            campos["usa_equipos"], campos["valor_equipos"], campos["valor_equipos_modo"],
        ),
    )
    _insert_clases(conn, edicion_id, clases)
    e_row = conn.execute(
        "SELECT * FROM ediciones_taller WHERE id = %s", (edicion_id,)
    ).fetchone()
    _regenerar_pedidos_taller(conn, e_row, taller_nombre, numero_pedido_fn=numero_pedido_fn)
    return e_row
