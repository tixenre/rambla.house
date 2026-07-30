"""rambla_a_rental_rename: el cobrador/dueño/parte 'Rambla' pasa a 'Rental'

Pedido del dueño (2026-07-29): "Rambla" (la marca/empresa) generaba confusión
con "Rambla" como valor interno del cobrador de un pago / dueño de un equipo /
parte de la rendición — sobre todo porque el rental y el Estudio son 2 negocios
conjuntos con cuentas reales separadas (rental = MercadoPago de Tincho, Estudio
= MercadoPago de Pablo). Se renombra el VALOR (no la marca "Rambla Rental", que
no cambia en ningún lado) a "Rental" — simétrico con "Estudio" — en las 3
columnas acopladas por el mismo string:

1. `equipos.dueno` — a quién pertenece un equipo (reparto de comisiones).
2. `cuentas.socio` (+ el nombre de la cuenta real, "Fondo Rambla" → "Fondo
   Rental") — a qué cobrador representa una caja.
3. `alquiler_pagos.destinatario` — quién cobró un pago de cliente.

Los 3 están acoplados: `comisiones.repartir(dueno, monto, modelo)` busca
`modelo[dueno]` — si solo se migran 2 de los 3, un equipo/cobrador que quedó
con el string viejo cae al fallback de reparto ("sin regla, cobra 100% él
mismo"), creando una parte fantasma "Rambla" separada de "Rental" en los
reportes. Por eso los 3 UPDATE van en la misma migración, todos idempotentes
(no rompen si ya corrieron).

Si `app_settings.comisiones_modelo` tiene una fila (el dueño customizó el
reparto desde el back-office), se le renombra la clave de dueño "Rambla" y
cualquier clave de beneficiario anidada "Rambla" a "Rental" — mismo criterio
que el backfill de comisiones de "Estudio" (`t8u9v0w1x2y3`): nunca pisa lo que
el dueño configuró, solo renombra la clave. Si no hay fila, no hace falta nada
— `cargar_modelo` cae a `comisiones.DEFAULT_MODELO`, que esta misma iniciativa
ya actualizó en código.

`init_db()` (esquema en dos capas) ya siembra "Fondo Rental"/"Rental" para
instalaciones nuevas — esta migración es la que arregla una BD que YA tenía
los valores viejos.

**Gotcha real (encontrado en staging, #1314): `cuentas` es la ÚNICA de las 3
columnas con identidad protegida por UNIQUE (activa) — por `socio`
(`idx_cuentas_socio`) Y por `nombre` (`cuentas_nombre_activa_uq`).**
`init_db()` corre ANTES que esta migración en cada boot (`main.py::init_db_bg`)
y, desde que el código pasó a nombrar "Rental", siembra
`('Fondo Rental', 'fondo', 'Rental', ...) ON CONFLICT DO NOTHING` — en una BD
que TODAVÍA tenía la fila vieja ("Fondo Rambla"/`socio='Rambla'`), ese seed NO
choca (nombre/socio distintos todavía) y crea una fila NUEVA vacía, en
paralelo a la vieja que tiene la plata real. Un rename ciego (`UPDATE ... WHERE
socio = 'Rambla'`) choca contra esa fila nueva → `UniqueViolation`, la
migración entera hace rollback (incluido el rename de `equipos.dueno`, en el
mismo `upgrade()`) — exactamente lo que pasó en staging. El fix: en vez de un
rename ciego, la cuenta vieja se MERGEA en la nueva (reasigna sus
`movimientos`, suma su `saldo_inicial`, se borra) — seguro porque la fila
nueva siempre nace vacía (recién sembrada por `init_db()`, sin movimientos).
Si la nueva no existe todavía, el rename de siempre alcanza.

Revision ID: 23aa6949d4df
Revises: pv1nc2l3a4d5
Create Date: 2026-07-29 23:33:57.113933
"""
import json
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = '23aa6949d4df'
down_revision: Union[str, Sequence[str], None] = 'pv1nc2l3a4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _migrar_cuenta_rambla_a_rental(conn) -> None:
    """`cuentas` tiene identidad protegida por UNIQUE(activa) en `socio` Y en
    `nombre` — a diferencia de `equipos.dueno`/`alquiler_pagos.destinatario`
    (simples labels sin unicidad), acá un rename ciego puede chocar contra una
    fila ya sembrada por `init_db()` con el nombre nuevo (ver docstring del
    módulo, #1314). Por cada cuenta vieja encontrada (por `socio='Rambla'` O
    `nombre='Fondo Rambla'` — pueden desincronizarse si el dueño renombró la
    cuenta a mano sin tocar el cobrador, o viceversa):

    - Si YA existe una cuenta activa con `socio='Rental'` (sembrada por
      `init_db()` — nace SIEMPRE vacía, sin movimientos): mergea la vieja en
      esa — reasigna sus `movimientos` (origen y destino), le suma el
      `saldo_inicial`, y borra la vieja (ya no tiene nada referenciándola).
    - Si no existe: rename en el lugar, como antes.
    """
    viejas = conn.execute(text(
        "SELECT id, saldo_inicial FROM cuentas "
        "WHERE (socio = 'Rambla' OR nombre = 'Fondo Rambla') AND activa"
    )).fetchall()
    for vieja_id, vieja_saldo in viejas:
        nueva = conn.execute(
            text("SELECT id FROM cuentas WHERE socio = 'Rental' AND activa AND id != :vieja"),
            {"vieja": vieja_id},
        ).fetchone()
        if nueva:
            nueva_id = nueva[0]
            conn.execute(
                text("UPDATE movimientos SET cuenta_origen_id = :nueva WHERE cuenta_origen_id = :vieja"),
                {"nueva": nueva_id, "vieja": vieja_id},
            )
            conn.execute(
                text("UPDATE movimientos SET cuenta_destino_id = :nueva WHERE cuenta_destino_id = :vieja"),
                {"nueva": nueva_id, "vieja": vieja_id},
            )
            conn.execute(
                text("UPDATE cuentas SET saldo_inicial = saldo_inicial + :extra WHERE id = :nueva"),
                {"extra": vieja_saldo, "nueva": nueva_id},
            )
            conn.execute(text("DELETE FROM cuentas WHERE id = :vieja"), {"vieja": vieja_id})
        else:
            conn.execute(
                text("UPDATE cuentas SET socio = 'Rental', nombre = 'Fondo Rental' WHERE id = :vieja"),
                {"vieja": vieja_id},
            )


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(text("UPDATE equipos SET dueno = 'Rental' WHERE dueno = 'Rambla'"))
    _migrar_cuenta_rambla_a_rental(conn)
    conn.execute(text(
        "UPDATE alquiler_pagos SET destinatario = 'Rental' WHERE destinatario = 'Rambla'"
    ))

    row = conn.execute(text(
        "SELECT value FROM app_settings WHERE key = 'comisiones_modelo'"
    )).fetchone()
    if row and row[0]:
        try:
            modelo = json.loads(row[0])
        except (TypeError, ValueError):
            modelo = None
        if isinstance(modelo, dict):
            cambiado = False
            if "Rambla" in modelo:
                modelo["Rental"] = modelo.pop("Rambla")
                cambiado = True
            for reglas in modelo.values():
                if isinstance(reglas, dict) and "Rambla" in reglas:
                    reglas["Rental"] = reglas.pop("Rambla")
                    cambiado = True
            if cambiado:
                conn.execute(
                    text("UPDATE app_settings SET value = :v WHERE key = 'comisiones_modelo'"),
                    {"v": json.dumps(modelo, ensure_ascii=False)},
                )


def downgrade() -> None:
    # No-op: mismo criterio que la migración de dueno='Rambla'→'Estudio' del
    # centinela (t8u9v0w1x2y3) y la normalización de dueños (c47b6b4e2851) —
    # revertir un rename de valor no tiene sentido una vez que el código/tests
    # ya esperan "Rental", y perdería cualquier dato nuevo creado con ese valor.
    pass
