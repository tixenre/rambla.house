"""Única puerta de mutación de la promo (combo) de El Estudio (#1283 Fase 5)."""
from fastapi import HTTPException

from services.precios import resolver_descuento_uniforme

from services.estudio.queries.promo import _pack_equipo_ids

# Stock sentinel de un equipo tipo='combo' (#635): su disponibilidad real se
# deriva de sus componentes, este valor nunca se lee para ese fin — mismo
# criterio que `COMBO_SENTINEL_STOCK` en `ComboBuilderDialog.tsx` (frontend).
_COMBO_STOCK_SENTINEL = 9999


def crear_promo(conn, estudio, nombre: str | None, precio_objetivo: int | None) -> int:
    """Crea la promo (combo) del Estudio a partir del pack curado actual
    (`estudio_pack_equipos`): un equipo real `tipo='combo'`, `dueno='Rambla'`
    (no los dueños tradicionales — es plata de Rambla, no de terceros),
    `visible_catalogo=0` (oculto del catálogo público, solo se ofrece desde el
    Estudio/back-office). El precio objetivo (default = `pack_precio` actual)
    se clava vía un descuento % uniforme en sus componentes
    (`resolver_descuento_uniforme`, misma pieza que el endpoint de Equipos).

    Reemplaza al pack: apaga `pack_activo` y setea `estudio.promo_combo_id`.
    No commitea — eso es responsabilidad del caller (route). El pack/sus datos
    NO se borran (⏰ LEGACY hasta la Fase 8) — el combo creado es un equipo
    normal, editable después desde Equipos como cualquier otro combo."""
    if estudio["promo_combo_id"]:
        raise HTTPException(
            409, "Ya existe una promo — editala desde Equipos o borrala primero"
        )
    pack_ids = _pack_equipo_ids(conn)
    if not pack_ids:
        raise HTTPException(400, "El pack curado está vacío — agregá equipos primero")

    nombre_final = (nombre or estudio["pack_nombre"] or "Promo de equipos").strip()
    precio_final = (
        precio_objetivo if precio_objetivo is not None
        else (estudio["pack_precio"] or 0)
    )
    if precio_final <= 0:
        raise HTTPException(400, "El precio objetivo tiene que ser mayor a 0")

    combo_id = conn.insert_returning(
        """
        INSERT INTO equipos (nombre, tipo, cantidad, dueno, visible_catalogo,
                             es_recurso_interno, estado)
        VALUES (%s,'combo',%s,'Rambla',0,FALSE,'operativo')
        """,
        (nombre_final, _COMBO_STOCK_SENTINEL),
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
        descuento = resolver_descuento_uniforme(rows, precio_final)
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
    return combo_id
