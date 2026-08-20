"""instituciones.slug: URL pública por institución (hub /escuelas/instituciones/$slug)

Escuela v2 gana una página pública que agrupa TODOS los talleres de una
institución co-presentadora (ej. "Filmar", con sus dos niveles) en un solo
link — hasta ahora cada taller solo tenía su propia URL individual, sin
forma de compartir "todos los talleres de esta institución" de una. Agrega
`slug` con la regla canónica de `dataio.slug` (mismo patrón que
equipos/talleres). A diferencia de equipos, sin la danza de 2 fases
nullable→NOT NULL con index parcial: la tabla es chica (pocas filas), el
backfill corre en la misma migración y se deja NOT NULL + UNIQUE de una.

Revision ID: institucslug
Revises: tllrherman0x1
Create Date: 2026-08-19
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "institucslug"
down_revision: Union[str, Sequence[str], None] = "tllrherman0x1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from dataio.slug import slugify, slug_unico

    op.execute("ALTER TABLE instituciones ADD COLUMN IF NOT EXISTS slug TEXT")

    bind = op.get_bind()
    pendientes = bind.execute(
        text("SELECT id, nombre FROM instituciones WHERE slug IS NULL")
    ).mappings().all()
    if pendientes:
        ocupados = {
            row[0]
            for row in bind.execute(
                text("SELECT slug FROM instituciones WHERE slug IS NOT NULL")
            ).all()
        }
        for r in pendientes:
            base = slugify(r["nombre"]) or f"institucion-{r['id']}"
            slug = slug_unico(base, ocupados)
            ocupados.add(slug)
            bind.execute(
                text("UPDATE instituciones SET slug = :s WHERE id = :i"),
                {"s": slug, "i": r["id"]},
            )

    op.execute("ALTER TABLE instituciones ALTER COLUMN slug SET NOT NULL")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'instituciones_slug_key'
                  AND conrelid = 'instituciones'::regclass
            ) THEN
                ALTER TABLE instituciones ADD CONSTRAINT instituciones_slug_key UNIQUE (slug);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE instituciones DROP CONSTRAINT IF EXISTS instituciones_slug_key")
    op.execute("ALTER TABLE instituciones DROP COLUMN IF EXISTS slug")
