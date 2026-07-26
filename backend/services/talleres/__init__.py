"""`backend/services/talleres/` — lógica de decisión de Talleres (Escuela v2).

Barrel (docstring, sin `__all__` — no hay re-exports públicos; los consumidores
importan por path completo, mismo patrón que `services/estudio/`/`descuentos/`/
`contabilidad/`).

Alcance acotado a propósito (Fase 1): solo la lógica de DECISIÓN duplicada o
compartida — el gate de conflicto con Estudio, la creación de una edición
(dedup del INSERT), la validación/upsert de clases y modalidades de pago, y la
economía (`_regenerar_pedidos_taller`). `routes/talleres.py` sigue siendo
dueño de los endpoints HTTP (auth, conn/commit/rollback), los helpers de
lectura/serialización, instructores/instituciones/trabajos/portada, y todo el
sub-sistema de inscripción/seña (diferido a una Fase 2 — ver `CLAUDE.md`).

Ver `CLAUDE.md` (invariantes) y `docs/DECISIONES.md` (el porqué del split).
"""
