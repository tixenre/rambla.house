"""Constantes compartidas entre `queries/` y `commands/` de `services/talleres/`
— viven fuera de ambos subpaquetes por el mismo motivo que
`services/estudio/constants.py`/`contabilidad/constants.py`."""

# Namespace del advisory lock que serializa la regeneración de pedidos de una
# edición — evita una carrera entre 2 escrituras concurrentes a la MISMA
# edición decidiendo a la vez qué mes conservar/borrar/recrear. Namespace
# PROPIO, distinto de `_ADVISORY_NS_ESTUDIO` (services/estudio/constants.py):
# son locks sobre recursos distintos (economía de UNA edición de taller vs.
# gate de publicación del Estudio) — no fusionar aunque ambos puedan tomarse
# dentro del mismo flujo de alta de una edición.
_ADVISORY_NS_TALLER = 5390423
