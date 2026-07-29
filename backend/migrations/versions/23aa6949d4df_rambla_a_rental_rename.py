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


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(text("UPDATE equipos SET dueno = 'Rental' WHERE dueno = 'Rambla'"))
    conn.execute(text("UPDATE cuentas SET socio = 'Rental' WHERE socio = 'Rambla'"))
    conn.execute(text(
        "UPDATE cuentas SET nombre = 'Fondo Rental' WHERE nombre = 'Fondo Rambla'"
    ))
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
