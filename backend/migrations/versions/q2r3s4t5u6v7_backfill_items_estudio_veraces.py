"""Backfill: ítems veraces del Estudio (Fase 2 de la economía del Estudio).

Antes de este cambio, los pedidos del Estudio (`tipo IN ('estudio',
'estudio_fijo')`) guardaban la plata SOLO en `alquileres.monto_total`: el
ítem centinela iba con `precio_jornada=0, subtotal=0` (o, para
`estudio_fijo`, sin ningún ítem) — la plata real vivía "fuera" de los ítems.
Eso rompía todo lo que suma por ítem: el desglose recalculado (`monto_neto=0
≠ monto_total`, marcando el semáforo de reconciliación en rojo en falso), el
PDF de presupuesto (mostraba Total=$0) y la liquidación mensual (el
prorrateo por `subtotal` caía al fallback "partes iguales", derramando valor
del espacio a los dueños de los equipos del pack).

El código nuevo (`routes/estudio.py::crear_reserva_estudio`/
`_regenerar_pedidos_slot`) ya inserta ítems VERACES para pedidos NUEVOS —
esta migración backfillea los YA EXISTENTES, una sola vez:

1. `estudio_fijo` sin ítems → INSERT el ítem centinela con
   `precio_jornada=subtotal=monto_total` (`cobro_modo='fijo'`).
2. `estudio` (turno por horas) → UPDATE el ítem centinela (`subtotal=0`) al
   monto REAL del espacio: `LEAST(monto_total, precio_hora_ACTUAL × horas de
   la franja)`. Fallback si `precio_hora` es 0/nulo hoy (no hay tarifa
   confiable para reconstruir el split): el `monto_total` completo queda en
   el espacio, no se inventa una línea de pack.
3. `estudio` CON pack (`estudio_con_pack`) → además, INSERT una línea
   personalizada con el remanente (`monto_total − espacio`) como precio FIJO
   del pack (`equipo_id=NULL` → dueño 'Rambla' por default en la
   liquidación — coherente con que la promo/pack es plata de Rambla, no de
   los dueños tradicionales de los equipos).

Data-only, IDEMPOTENTE (no repite un `precio_hora` que cambió después de
correr esto una vez): cada paso se guarda con su propia condición de "todavía
no procesado" (sin ítems / `cobro_modo != 'fijo'` / sin línea de pack), así
que puede correr más de una vez sin duplicar ni recalcular sobre datos ya
migrados. No va en `init_db()` (que corre en cada arranque).

Revision ID: q2r3s4t5u6v7
Revises: esc1m2i3n4t5
Create Date: 2026-07-23
"""
from typing import Sequence, Union
from alembic import op

revision: str = "q2r3s4t5u6v7"
down_revision: Union[str, Sequence[str], None] = "esc1m2i3n4t5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# CASE compartida por los pasos 2 y 3 — mismo criterio en ambos lugares:
# fallback a `monto_total` completo si no hay `precio_hora` confiable hoy.
_ESPACIO_MONTO = """
    CASE
      WHEN e.precio_hora IS NULL OR e.precio_hora <= 0 THEN a.monto_total
      ELSE LEAST(
             a.monto_total,
             (e.precio_hora * EXTRACT(EPOCH FROM (a.fecha_hasta - a.fecha_desde)) / 3600)::int
           )
    END
"""


def upgrade() -> None:
    # 1. estudio_fijo sin NINGÚN ítem → centinela con el monto real.
    op.execute("""
        INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
        SELECT a.id, e.equipo_id, 1, a.monto_total, a.monto_total, 'fijo'
        FROM alquileres a
        CROSS JOIN estudio e
        WHERE a.tipo = 'estudio_fijo' AND e.id = 1 AND e.equipo_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM alquiler_items pi WHERE pi.pedido_id = a.id)
    """)

    # 2. estudio (turno por horas) → el ítem centinela pasa de $0 al monto
    #    real del ESPACIO (con o sin pack — el pack se separa en el paso 3).
    op.execute(f"""
        UPDATE alquiler_items pi
        SET subtotal = calc.espacio_monto,
            precio_jornada = calc.espacio_monto,
            cobro_modo = 'fijo'
        FROM (
            SELECT a.id AS pedido_id, e.equipo_id, {_ESPACIO_MONTO} AS espacio_monto
            FROM alquileres a
            CROSS JOIN estudio e
            WHERE a.tipo = 'estudio' AND e.id = 1 AND e.equipo_id IS NOT NULL
        ) calc
        WHERE pi.pedido_id = calc.pedido_id
          AND pi.equipo_id = calc.equipo_id
          AND pi.cobro_modo <> 'fijo'
    """)

    # 3. estudio CON pack → línea personalizada con el remanente (precio FIJO
    #    del pack). Solo si queda plata para repartir (fallback precio_hora=0
    #    del paso 2 ya dejó todo en el centinela → remanente 0, no se inserta).
    op.execute(f"""
        INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, nombre_libre, cobro_modo)
        SELECT
            a.id, NULL, 1,
            a.monto_total - espacio.monto, a.monto_total - espacio.monto,
            COALESCE(NULLIF(e.pack_nombre, ''), 'Pack de equipos'), 'fijo'
        FROM alquileres a
        CROSS JOIN estudio e
        CROSS JOIN LATERAL (SELECT {_ESPACIO_MONTO} AS monto) espacio
        WHERE a.tipo = 'estudio' AND a.estudio_con_pack = TRUE AND e.id = 1
          AND (a.monto_total - espacio.monto) > 0
          AND NOT EXISTS (
                SELECT 1 FROM alquiler_items pi2
                WHERE pi2.pedido_id = a.id AND pi2.equipo_id IS NULL
              )
    """)


def downgrade() -> None:
    # Irreversible con precisión (no se puede distinguir qué ítem vino de este
    # backfill vs. de un pedido nuevo creado ya con ítems veraces) — no-op
    # documentado, mismo criterio que otros backfills de este repo
    # (v9w0x1y2z3a4_backfill_descuento_cliente_pct.py).
    pass
