"""Refresh diario de la serie de IPC (INDEC) para Estadísticas ajustadas.

Corre 1×/día desde el mismo scheduler in-process que el resto (recordatorios,
reconciliación, cleanup — cero costo extra de infra). Idempotente (upsert): un
reinicio del proceso el mismo día no duplica nada, en el peor caso re-trae la
misma serie sin cambios.
"""
import logging

from database import get_db
from services.ipc import actualizar_ipc

logger = logging.getLogger(__name__)


def actualizar_ipc_job() -> int:
    """Trae la serie completa de INDEC y la upsertea en `ipc_series`. Devuelve
    la cantidad de meses traídos. Nunca propaga — un error acá (ej. INDEC caído)
    no debe tumbar el scheduler; el próximo ciclo reintenta solo."""
    with get_db() as conn:
        n = actualizar_ipc(conn)
    logger.info("IPC actualizado: %d meses en ipc_series", n)
    return n
