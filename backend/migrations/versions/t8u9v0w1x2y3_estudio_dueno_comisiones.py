"""estudio_dueno_comisiones: el centinela pasa a dueno='Estudio' (Fase 4, #1283)

Economía separada: las horas del espacio del Estudio se atribuyen al Estudio
en la liquidación/P&L, no a Rambla rental (decisión del dueño — "Estudio =
beneficiario propio"). Dos pasos, ambos data-only e idempotentes:

1. El centinela (`estudio.equipo_id`) pasa de `dueno='Rambla'` a
   `dueno='Estudio'`. Solo toca la fila del centinela (join por
   `estudio.equipo_id`), nunca equipos reales. `init_db()` ya siembra el
   centinela con `dueno='Estudio'` para instalaciones nuevas (esquema en dos
   capas) — esta migración es la que arregla una BD que YA lo tenía creado
   con el valor viejo.
2. Si `app_settings.comisiones_modelo` tiene una fila (el dueño customizó el
   reparto desde el back-office), se le suma la entrada `"Estudio": {"Estudio":
   100}` SI todavía no está — mismo criterio que la repintura de templates de
   mail (`r8s9t0u1v2w3`): nunca pisa lo que el dueño ya configuró para otros
   dueños, solo agrega la entrada nueva que antes no podía existir. Si no hay
   fila (nadie tocó el reparto todavía), no hace falta nada — `cargar_modelo`
   cae a `comisiones.DEFAULT_MODELO`, que esta misma iniciativa ya actualizó
   en código.

Sin esto, `reconciliacion.py`'s `duenos_no_canonicos` marcaría a 'Estudio'
como dueño fuera del modelo (typo-looking) apenas el paso 1 corriera solo.

Revision ID: t8u9v0w1x2y3
Revises: s7t8u9v0w1x2
Create Date: 2026-07-23
"""
import json
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "t8u9v0w1x2y3"
down_revision: Union[str, Sequence[str], None] = "s7t8u9v0w1x2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(text("""
        UPDATE equipos SET dueno = 'Estudio'
        WHERE id = (SELECT equipo_id FROM estudio WHERE id = 1)
          AND dueno IS DISTINCT FROM 'Estudio'
    """))

    row = conn.execute(text(
        "SELECT value FROM app_settings WHERE key = 'comisiones_modelo'"
    )).fetchone()
    if row and row[0]:
        try:
            modelo = json.loads(row[0])
        except (TypeError, ValueError):
            modelo = None
        if isinstance(modelo, dict) and "Estudio" not in modelo:
            modelo["Estudio"] = {"Estudio": 100}
            conn.execute(
                text("UPDATE app_settings SET value = :v WHERE key = 'comisiones_modelo'"),
                {"v": json.dumps(modelo, ensure_ascii=False)},
            )


def downgrade() -> None:
    # No-op: revertir el dueno del centinela a 'Rambla' reabriría el bug que
    # esta fase arregla (la plata del espacio volvería a mezclarse con la de
    # Rambla rental). El backfill de comisiones_modelo tampoco se revierte —
    # quitarle la entrada "Estudio" a un modelo ya customizado por el dueño
    # perdería esa edición sin necesidad.
    pass
