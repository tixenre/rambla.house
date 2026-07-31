"""Unifica los equipos legacy del Estudio (pre-centinela) con el sistema actual.

Contexto (a pedido del dueño, tras notar duplicados confusos en el buscador
de equipos): antes de que el Estudio se modelara con un "centinela" invisible
+ pack/combo (2026-05-27 en adelante), reservar el espacio y su promo de
equipos vivían como dos equipos `tipo='simple'` COMUNES y VISIBLES en el
catálogo público:

- id 327 "Rambla Estudio" (marca=Rambla, modelo=Estudio, $50.000/jornada) —
  representación pre-centinela del espacio físico. Coincide textualmente con
  `estudio.nombre` ("Rambla Estudio", el nombre configurado del Estudio hoy).
- id 266 "Estudio Equipos Promo" (marca=Estudio, modelo=Equipos Promo,
  $100.000/jornada) — representación pre-pack de la promo de equipos.

Ambos tienen historial REAL (pedidos ya facturados/cobrados) que hoy queda
FUERA de la economía separada del Estudio (Fase 3/4/7 de #1283): sus pedidos
son `tipo='diaria'` normal, no `tipo='estudio'` — así que ni la liquidación
los atribuye al beneficiario "Estudio", ni Estadísticas los cuenta en la
sección "Estudio" nueva. El dueño pidió UNIFICAR: que esas estadísticas
viejas pasen a referir al MISMO Estudio que se usa de ahora en más (el
centinela real + el combo de promo), y borrar los equipos legacy — en
`dev` y, cuando esto se promueva a `main`, en producción también (misma
migración, mismo mecanismo de siempre — no hace falta nada especial).

Pasos (todos idempotentes — no-op si ya corrieron):

1. Si `estudio.promo_combo_id` es NULL, crea el combo real desde el pack
   curado actual (`estudio_pack_equipos`) — MISMA lógica que el endpoint
   `POST /admin/estudio/promo/crear-desde-pack` (#1283 Fase 5): combo
   `tipo='combo'`, `dueno='Rambla'`, `visible_catalogo=0`, componentes desde
   el pack, descuento uniforme para clavar `pack_precio` como precio exacto.
2. Re-atribuye el historial: cada `alquiler_items` que apunte a 327 pasa a
   apuntar al centinela real (`estudio.equipo_id`); cada uno que apunte a 266
   pasa a apuntar al combo nuevo. Los pedidos donde TODOS los ítems son 266
   y/o 327 ("puros" — el caso esperado, dado que eran productos standalone;
   incluye el caso de ambos juntos en un mismo pedido, como una reserva
   combinada de hoy) se retaguean a `alquileres.tipo='estudio'` para que
   caigan en la sección Estudio de Estadísticas/liquidación. Un pedido MIXTO
   (con otro equipo real, o una línea de texto libre, además del legacy) NO
   se retaguea — se re-apunta el ítem pero el pedido sigue siendo rental
   normal, para no arrastrar equipos no relacionados a la economía del
   Estudio por error.
3. Guarda de seguridad: si 266 o 327 son COMPONENTE VIVO de algún otro combo
   (`kit_componentes.componente_id`) — la única FK cuyo CASCADE perdería
   configuración de negocio real en vez de metadata descartable — esa fila
   se deja SIN borrar (se salta el DELETE puntual de ese id) en vez de
   arrastrar en silencio el kit de otro combo. Todo lo demás (fichas,
   specs, categorías, fotos, mantenimiento, favoritos, listas, historial de
   precio, search_clicks, adaptador de compatibilidad, pack curado) tiene
   CASCADE/SET NULL en `schema.py` — Postgres lo limpia solo al hacer el
   DELETE final, es metadata/analítica propia del equipo, no plata ni
   configuración de otro producto (mapeo completo verificado antes de
   escribir esta migración).
4. DELETE final de 266/327 (los que no se saltearon en el paso 3).

Revision ID: unifestlegacy
Revises: mrgestbrescu
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

from services.precios import resolver_descuento_uniforme

revision: str = "unifestlegacy"
down_revision: Union[str, Sequence[str], None] = "mrgestbrescu"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_ESPACIO_ID = 327   # "Rambla Estudio" — pre-centinela
_LEGACY_PROMO_ID = 266     # "Estudio Equipos Promo" — pre-combo
_COMBO_STOCK_SENTINEL = 9999


def upgrade() -> None:
    conn = op.get_bind()

    existe = conn.execute(text(
        "SELECT COUNT(*) FROM equipos WHERE id IN (:a, :b)"
    ), {"a": _LEGACY_ESPACIO_ID, "b": _LEGACY_PROMO_ID}).scalar()
    if not existe:
        return  # entorno sin estos ids (ej. base de test/CI fresca) — no-op

    estudio = conn.execute(text(
        "SELECT equipo_id, promo_combo_id, pack_nombre, pack_precio "
        "FROM estudio WHERE id = 1"
    )).mappings().fetchone()
    if not estudio or not estudio["equipo_id"]:
        return  # sin fila estudio / sin centinela configurado — no tocar nada

    centinela_id = estudio["equipo_id"]
    combo_id = estudio["promo_combo_id"]

    # ── 1. Crear el combo real si todavía no existe ─────────────────────────
    if combo_id is None:
        pack_ids = [r[0] for r in conn.execute(text("""
            SELECT e.id FROM estudio_pack_equipos pe
            JOIN equipos e ON e.id = pe.equipo_id
            WHERE pe.estudio_id = 1 AND e.eliminado_at IS NULL
        """)).fetchall()]
        precio_objetivo = estudio["pack_precio"] or 0
        if pack_ids and precio_objetivo > 0:
            nombre = (estudio["pack_nombre"] or "Promo de equipos").strip()
            combo_id = conn.execute(text("""
                INSERT INTO equipos (nombre, tipo, cantidad, dueno, visible_catalogo,
                                     es_recurso_interno, estado)
                VALUES (:nombre, 'combo', :cant, 'Rambla', 0, FALSE, 'operativo')
                RETURNING id
            """), {"nombre": nombre, "cant": _COMBO_STOCK_SENTINEL}).scalar()
            for eid in pack_ids:
                conn.execute(text("""
                    INSERT INTO kit_componentes (equipo_id, componente_id, cantidad, esencial)
                    VALUES (:combo, :comp, 1, TRUE)
                """), {"combo": combo_id, "comp": eid})
            rows = conn.execute(text("""
                SELECT e.precio_jornada, kc.cantidad
                FROM kit_componentes kc JOIN equipos e ON e.id = kc.componente_id
                WHERE kc.equipo_id = :combo AND e.eliminado_at IS NULL
            """), {"combo": combo_id}).mappings().fetchall()
            try:
                descuento = resolver_descuento_uniforme(rows, precio_objetivo)
            except ValueError:
                descuento = 0.0  # componentes sin precio base — combo queda sin descuento
            conn.execute(text(
                "UPDATE kit_componentes SET descuento_pct = :d WHERE equipo_id = :combo"
            ), {"d": descuento, "combo": combo_id})
            conn.execute(text(
                "UPDATE estudio SET promo_combo_id = :combo, pack_activo = FALSE WHERE id = 1"
            ), {"combo": combo_id})
        # Si no hay pack curado o precio, no se crea combo — el paso 2 se
        # salta la re-atribución de 266 (queda sin destino) hasta que exista.

    # ── 2. Re-atribuir historial ─────────────────────────────────────────────
    # "Puro" = TODOS los ítems del pedido son legacy CON destino resuelto
    # (nunca otro equipo real, una línea de texto libre, NI un legacy sin
    # combo/centinela a dónde re-apuntar) — se calcula UNA sola vez contra el
    # conjunto combinado, antes de re-apuntar nada. Si se calculara
    # por-legacy-id por separado, un pedido con AMBOS juntos (espacio + promo,
    # como una reserva combinada de hoy) se vería "mixto" desde cada uno de
    # los dos lados y nunca se retaguearía — este cálculo conjunto lo evita.
    #
    # `-1` como sentinela "sin destino": si el combo no se pudo crear (pack
    # vacío/sin precio), `combo_id` es None — un pedido con 266 NO puede
    # considerarse puro (su ítem se va a quedar sin re-apuntar, ver el loop
    # de abajo), así que 266 se excluye del conjunto "procesable" en vez de
    # tratarlo como si igual tuviera dónde ir.
    procesable_espacio = _LEGACY_ESPACIO_ID if centinela_id is not None else -1
    procesable_promo = _LEGACY_PROMO_ID if combo_id is not None else -1

    pedidos_afectados = [r[0] for r in conn.execute(text(
        "SELECT DISTINCT pedido_id FROM alquiler_items WHERE equipo_id IN (:a, :b)"
    ), {"a": _LEGACY_ESPACIO_ID, "b": _LEGACY_PROMO_ID}).fetchall()]

    for pedido_id in pedidos_afectados:
        otros = conn.execute(text(
            "SELECT COUNT(*) FROM alquiler_items "
            "WHERE pedido_id = :pid AND (equipo_id IS NULL OR equipo_id NOT IN (:pa, :pp))"
        ), {"pid": pedido_id, "pa": procesable_espacio, "pp": procesable_promo}).scalar()
        if otros == 0:
            conn.execute(text(
                "UPDATE alquileres SET tipo = 'estudio' "
                "WHERE id = :pid AND tipo NOT IN ('estudio', 'estudio_fijo')"
            ), {"pid": pedido_id})

    for legacy_id, target_id in ((_LEGACY_ESPACIO_ID, centinela_id), (_LEGACY_PROMO_ID, combo_id)):
        if target_id is None:
            continue
        conn.execute(text(
            "UPDATE alquiler_items SET equipo_id = :target WHERE equipo_id = :lid"
        ), {"target": target_id, "lid": legacy_id})

    # ── 3+4. Borrar los legacy, salvo excepciones defensivas ────────────────
    for legacy_id in (_LEGACY_ESPACIO_ID, _LEGACY_PROMO_ID):
        # (a) si todavía queda algún alquiler_items apuntándolo (ej. el combo
        #     no se pudo crear por pack vacío/sin precio, y 266 nunca se
        #     re-apuntó) — `alquiler_items.equipo_id` es la ÚNICA FK sin
        #     ON DELETE, el DELETE de abajo rompería el deploy entero.
        quedan_items = conn.execute(text(
            "SELECT COUNT(*) FROM alquiler_items WHERE equipo_id = :lid"
        ), {"lid": legacy_id}).scalar()
        if quedan_items:
            continue  # se deja la fila — re-atribuir quedó pendiente
        # (b) si es componente vivo de OTRO combo real, no arrastrar su kit.
        es_componente_de_otro = conn.execute(text(
            "SELECT COUNT(*) FROM kit_componentes WHERE componente_id = :lid"
        ), {"lid": legacy_id}).scalar()
        if es_componente_de_otro:
            continue  # se deja la fila — no arrastrar el kit de otro combo
        conn.execute(text("DELETE FROM equipos WHERE id = :lid"), {"lid": legacy_id})


def downgrade() -> None:
    # Irreversible a propósito: no se puede recrear "Estudio Equipos Promo"/
    # "Rambla Estudio" con sus ids/historial originales (DELETE real), y
    # revertir el retag de tipo='estudio' arriesgaría desatribuir pedidos que
    # legítimamente ya se contaron en reportes de Estudio para entonces.
    pass
