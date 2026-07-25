"""`backend/services/estudio/` — motor de disponibilidad y reserva de El Estudio.

Barrel (docstring, sin `__all__` — no hay re-exports públicos; los consumidores
importan por path completo, `from services.estudio.queries.disponibilidad import
_estudio_disponible`, mismo patrón que `descuentos/`/`contabilidad/`).

Toda la decisión de "el estudio está libre / se reserva" vive acá; `routes/estudio.py`
es transporte (auth, conn/commit/rollback, HTTP) y conserva perfil/fotos/trabajos y
los ENDPOINTS de slots fijos + las vistas de agenda/ocupación del dashboard (lectura
agregada de display, sin decisión de negocio). El motor de reservas de equipos
(`backend/reservas/`) es SAGRADO: este paquete solo lo CONSUME (`calcular_disponibilidad`,
`validar_stock_hipotetico`), nunca lo reimplementa.

Ver `CLAUDE.md` (invariantes) y `docs/DECISIONES.md` (el porqué del split, fecha del PR).
"""
