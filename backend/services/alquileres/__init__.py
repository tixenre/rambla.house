"""`backend/services/alquileres/` — motor de pedidos (creación, ítems, pagos, transiciones).

Barrel (docstring, sin `__all__` — no hay re-exports públicos; los consumidores importan por path
completo, mismo patrón que `services/estudio/`/`services/talleres/`/`descuentos/`/`contabilidad/`).

En construcción incremental, 4 fases (roadmap + estado actual → issue de tracking #1312):
Fase 1 (lecturas sin riesgo de ciclo), Fase 2 (escrituras aisladas — pagos), Fase 3 (ítems/total del
pedido), Fase 4 (máquina de estados + creación). `routes/alquileres/` sigue siendo transporte HTTP
(auth, conn/commit/rollback) y delega acá a medida que cada fase aterriza — hasta que una fase
mueve algo, ese algo sigue viviendo en `routes/alquileres/` como siempre.

Ver `CLAUDE.md` (invariantes + estructura objetivo) y `docs/DECISIONES.md` (el porqué del split).
"""
