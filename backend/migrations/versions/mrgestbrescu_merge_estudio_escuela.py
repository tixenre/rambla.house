"""Merge de cabezas Alembic divergentes: u9v0w1x2y3z4 (Estudio, #1283) + esc7l8i9m0p1 (Escuela v2, #1278).

Dos iniciativas en ramas aisladas partieron del mismo nodo y cada una agregó
su propia cadena de migraciones sin reconvergir: el backend del Estudio
(`claude/studio-rental-promos-backend-n09s0s`, hasta `estudio_promo_combo_id`)
y Escuela v2 (`feat/escuela-v2-*`, ya en `dev`, hasta `limpieza_legacy`). Esta
migración de merge (no-op) las une en una sola head para que
`alembic upgrade head` sea inequívoco.

Revision ID: mrgestbrescu
Revises: u9v0w1x2y3z4, esc7l8i9m0p1
Create Date: 2026-07-24
"""
from typing import Sequence, Union

revision: str = "mrgestbrescu"
down_revision: Union[str, Sequence[str], None] = ("u9v0w1x2y3z4", "esc7l8i9m0p1")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge no-op: sólo une las dos ramas del grafo de revisiones.
    pass


def downgrade() -> None:
    pass
