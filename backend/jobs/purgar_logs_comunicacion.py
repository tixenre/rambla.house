"""Purga de logs de comunicación (`emails_log`/`whatsapp_log`) — retención de 1 año.

Antes de esto, estas dos tablas crecían sin límite para siempre: la única
tabla con PII de contacto (teléfono/mail) del repo sin ninguna política de
retención — todo lo demás sí la tiene (`auth_sessions`/`auth_challenges` vía
`purgar_auth.py`, cuentas livianas vía `cleanup_livianas.py`). Corre 1×/día
desde el mismo scheduler in-process (mismo patrón, cero costo de infra nuevo).

`RETENCION_DIAS = 365` (1 año): decisión explícita del dueño — cubre una
temporada completa de alquiler + margen para resolver un reclamo tipo "no me
llegó el mail". Constante fija, NO configurable desde el back-office: es
política de housekeeping/privacidad, no una perilla operativa del día a día
(mismo criterio que `DIAS_GRACIA` en `cleanup_livianas.py`)."""
import logging

from database import get_db

logger = logging.getLogger(__name__)

RETENCION_DIAS = 365


def purgar_logs_comunicacion_viejos(retencion_dias: int = RETENCION_DIAS) -> tuple[int, int]:
    """Borra filas de `emails_log`/`whatsapp_log` con `sent_at` más viejo que
    `retencion_dias`. Devuelve `(mails_borrados, whatsapps_borrados)`.
    Idempotente: re-correrlo sin candidatos borra 0. Usa el reloj de la DB
    (`NOW()`) para que la comparación con `sent_at` (DEFAULT CURRENT_TIMESTAMP)
    sea internamente coherente."""
    with get_db() as conn:
        with conn.transaction():
            mails = conn.execute(
                "DELETE FROM emails_log WHERE sent_at < NOW() - make_interval(days => %s) RETURNING id",
                (retencion_dias,),
            ).fetchall()
        with conn.transaction():
            whatsapps = conn.execute(
                "DELETE FROM whatsapp_log WHERE sent_at < NOW() - make_interval(days => %s) RETURNING id",
                (retencion_dias,),
            ).fetchall()
    n_mails, n_whatsapp = len(mails), len(whatsapps)
    if n_mails:
        logger.info("purga logs de comunicación: %s mail(s) viejo(s) borrado(s)", n_mails)
    if n_whatsapp:
        logger.info("purga logs de comunicación: %s whatsapp(s) viejo(s) borrado(s)", n_whatsapp)
    return n_mails, n_whatsapp
