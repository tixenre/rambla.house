"""Unifica los dos equipos legacy del Estudio (pre-centinela) con el sistema
actual — corrige el bug de id-hardcodeado de `unifestlegacy` matcheando por
NOMBRE en vez de id.

Contexto: `unifestlegacy` (2026-07-24) buscaba los equipos legacy por ID
HARDCODEADO (327/266 — los ids reales del ambiente contra el que se escribió
la migración). En otro ambiente con el MISMO historial legítimo pero un id
distinto para las mismas filas (producción real: 156 "Rambla Estudio" / 157
"Estudio Equipos Promo"), el guard `if not existe: return` de esa migración
interpretó "no matchea el id" como "este ambiente nunca tuvo el legacy" —
no-op silencioso, dejando los dos duplicados vivos y visibles en el buscador
de equipos (encontrado por el dueño post-deploy, #1322).

A diferencia de `unifestlegacy`, esta migración NO crea un combo nuevo: el
dueño ya tiene uno armado (`estudio.promo_combo_id`) — si existe, se reusa
como destino de "Estudio Equipos Promo"; si no existe todavía, esa mitad se
salta (mismo criterio defensivo que la original: sin destino, no se re-apunta
ni se borra, y su pedido no se retaguea).

Busca cada legacy por NOMBRE (robusto entre ambientes, cero acoplamiento a
un id puntual):
- "Rambla Estudio" (`es_recurso_interno=FALSE`, no el propio centinela) →
  destino: el centinela (`estudio.equipo_id`).
- "Estudio Equipos Promo" (`es_recurso_interno=FALSE`, no el propio combo) →
  destino: el combo existente (`estudio.promo_combo_id`), si lo hay.
Si para un nombre hay 0 o más de 1 match, no se toca — no se adivina.

Mismos pasos que `unifestlegacy` §2-4, sobre el conjunto COMBINADO de los
dos legacy encontrados (así un pedido que junta los dos en una reserva
combinada también se detecta como "puro" y se retaguea, igual que la
original):
1. Pedidos "puros" (TODOS sus ítems son legacy CON destino resuelto) se
   retaguean a `tipo='estudio'`. Un pedido MIXTO (con otro equipo real o una
   línea de texto libre) no se retaguea, solo se re-apuntan sus ítems.
2. `alquiler_items.equipo_id` legacy → su destino (la ÚNICA FK sin ON
   DELETE sobre `equipos`; por eso el orden importa: re-apuntar antes de
   borrar).
3. Guarda: si un legacy es componente VIVO de otro combo
   (`kit_componentes.componente_id`), no se borra — se deja la fila para no
   arrastrar en silencio el kit de ese otro producto.
4. DELETE de cada legacy (si no se salteó por la guarda de arriba, y si
   tiene destino resuelto — sin destino, sus ítems no tienen a dónde
   re-apuntar, así que la fila se deja intacta, la misma lógica que
   `unifestlegacy` aplicaba a 266 cuando el pack venía vacío).

Al re-apuntar, el historial hereda el `dueno` del destino (atribución vía
`equipos.dueno`, no snapshotteada por ítem): "Rambla Estudio" pasa a contar
como el `dueno` del centinela (hoy 'Estudio'); "Estudio Equipos Promo" pasa
a contar como el `dueno` del combo (hoy 'Rental') — exactamente lo que pidió
el dueño.

Revision ID: unifestlgcy2
Revises: ipcseries
Create Date: 2026-08-05
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "unifestlgcy2"
down_revision: Union[str, Sequence[str], None] = "ipcseries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ESPACIO_NOMBRE = "Rambla Estudio"
_PROMO_NOMBRE = "Estudio Equipos Promo"


def _match_unico(conn, nombre, excluir_id):
    """Busca un equipo por nombre, excluyendo su propio destino (centinela o
    combo). 0 o >1 matches → None (no adivina)."""
    params = {"nombre": nombre}
    where_excluir = ""
    if excluir_id is not None:
        where_excluir = "AND id != :excluir"
        params["excluir"] = excluir_id
    filas = conn.execute(text(
        f"SELECT id FROM equipos WHERE nombre = :nombre AND es_recurso_interno = FALSE {where_excluir}"
    ), params).fetchall()
    return filas[0][0] if len(filas) == 1 else None


def upgrade() -> None:
    conn = op.get_bind()

    estudio = conn.execute(text(
        "SELECT equipo_id, promo_combo_id FROM estudio WHERE id = 1"
    )).mappings().fetchone()
    if not estudio or not estudio["equipo_id"]:
        return  # sin fila estudio / sin centinela configurado — no tocar nada

    centinela_id = estudio["equipo_id"]
    combo_id = estudio["promo_combo_id"]  # puede ser None — esa mitad se salta

    espacio_legacy_id = _match_unico(conn, _ESPACIO_NOMBRE, centinela_id)
    promo_legacy_id = _match_unico(conn, _PROMO_NOMBRE, combo_id)

    if espacio_legacy_id is None and promo_legacy_id is None:
        return  # nada que unificar en este ambiente

    destinos = {}
    if espacio_legacy_id is not None:
        destinos[espacio_legacy_id] = centinela_id
    if promo_legacy_id is not None and combo_id is not None:
        destinos[promo_legacy_id] = combo_id
    # promo_legacy_id encontrado pero sin combo_id: se deja para el paso de
    # abajo, que no tiene destino → no re-apunta, no borra (mismo criterio
    # defensivo que `unifestlegacy` cuando el pack venía vacío).

    legacy_ids = [lid for lid in (espacio_legacy_id, promo_legacy_id) if lid is not None]

    # ── Re-atribuir historial ────────────────────────────────────────────────
    # "Puro" = TODOS los ítems del pedido son legacy CON destino resuelto —
    # calculado sobre el conjunto COMBINADO para detectar bien un pedido que
    # junta los dos legacy en una reserva combinada (mismo criterio que
    # `unifestlegacy`).
    con_destino = list(destinos.keys())
    if con_destino:
        placeholders = ",".join(f":lid{i}" for i in range(len(con_destino)))
        params = {f"lid{i}": lid for i, lid in enumerate(con_destino)}

        pedidos_afectados = [r[0] for r in conn.execute(text(
            f"SELECT DISTINCT pedido_id FROM alquiler_items WHERE equipo_id IN ({placeholders})"
        ), params).fetchall()]

        for pedido_id in pedidos_afectados:
            otros = conn.execute(text(
                f"SELECT COUNT(*) FROM alquiler_items "
                f"WHERE pedido_id = :pid AND (equipo_id IS NULL OR equipo_id NOT IN ({placeholders}))"
            ), {**params, "pid": pedido_id}).scalar()
            if otros == 0:
                conn.execute(text(
                    "UPDATE alquileres SET tipo = 'estudio' "
                    "WHERE id = :pid AND tipo NOT IN ('estudio', 'estudio_fijo')"
                ), {"pid": pedido_id})

        for legacy_id, target_id in destinos.items():
            conn.execute(text(
                "UPDATE alquiler_items SET equipo_id = :target WHERE equipo_id = :lid"
            ), {"target": target_id, "lid": legacy_id})

    # ── Borrar cada legacy, salvo excepciones defensivas ────────────────────
    for legacy_id in legacy_ids:
        if legacy_id not in destinos:
            continue  # sin destino (ej. promo sin combo aún) — se deja como está
        quedan_items = conn.execute(text(
            "SELECT COUNT(*) FROM alquiler_items WHERE equipo_id = :lid"
        ), {"lid": legacy_id}).scalar()
        if quedan_items:
            continue  # no debería pasar (ya re-apuntado arriba) — por las dudas
        es_componente_de_otro = conn.execute(text(
            "SELECT COUNT(*) FROM kit_componentes WHERE componente_id = :lid"
        ), {"lid": legacy_id}).scalar()
        if es_componente_de_otro:
            continue  # se deja la fila — no arrastrar el kit de otro combo
        conn.execute(text("DELETE FROM equipos WHERE id = :lid"), {"lid": legacy_id})


def downgrade() -> None:
    # Irreversible a propósito — mismo criterio que `unifestlegacy`: no se
    # puede recrear los equipos legacy con su id/historial original, y
    # revertir el retag de tipo='estudio' arriesgaría desatribuir pedidos que
    # legítimamente ya se contaron en reportes de Estudio para entonces.
    pass
