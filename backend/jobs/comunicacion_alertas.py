"""Alerta proactiva de fallas del canal de comunicación (mail + WhatsApp).

Mirror de `jobs/reconciliacion.py`: antes de esto, si el canal de mail/WhatsApp
empezaba a fallar (credencial vencida, proveedor caído, template rechazado por
Meta), nadie se enteraba salvo que un admin entrara a `/admin/comunicacion` a
mirar. Corre 1×/día desde el mismo scheduler in-process (cero costo de infra
nuevo) y manda un mail resumen a los admins si la cantidad de `status='failed'`
de las últimas 24h (mail + WhatsApp) supera el umbral. No repara nada — solo
avisa (mismo criterio que `reconciliacion.py`)."""
import logging

from database import get_db
from services.email import send_raw_email

logger = logging.getLogger(__name__)

UMBRAL_FALLOS = 3
_LOG_KEY = "comunicacion_alerta"


def _fallos_ultimas_24h(conn) -> dict:
    """`{"mail": [...], "whatsapp": [...]}` — hasta 10 ejemplos por canal, para
    el resumen del mail (no un conteo ciego sin contexto de qué falló)."""
    mail = conn.execute(
        """
        SELECT template_key, to_addr, error, sent_at FROM emails_log
         WHERE status = 'failed' AND sent_at > NOW() - INTERVAL '24 hours'
         ORDER BY sent_at DESC LIMIT 10
        """
    ).fetchall()
    whatsapp = conn.execute(
        """
        SELECT template_key, to_phone, error, sent_at FROM whatsapp_log
         WHERE status = 'failed' AND sent_at > NOW() - INTERVAL '24 hours'
         ORDER BY sent_at DESC LIMIT 10
        """
    ).fetchall()
    return {"mail": [dict(r) for r in mail], "whatsapp": [dict(r) for r in whatsapp]}


def _alertado_recientemente(conn) -> bool:
    """`True` si ya se mandó `comunicacion_alerta` en las últimas 20h. Dedup
    contra `emails_log` (sobrevive un restart del proceso) — mismo criterio y
    misma ventana que `reconciliacion._alertado_recientemente` (evita que el
    gate "1×/día" en memoria del scheduler mande un mail por cada redeploy en
    `dev`, que hace auto-deploy en cada push)."""
    row = conn.execute(
        """
        SELECT 1 FROM emails_log
         WHERE template_key = %s AND status = 'sent' AND sent_at > NOW() - INTERVAL '20 hours'
         LIMIT 1
        """,
        (_LOG_KEY,),
    ).fetchone()
    return row is not None


def _resumen_html(fallos: dict, total: int) -> str:
    filas = []
    for canal, rows in (("Mail", fallos["mail"]), ("WhatsApp", fallos["whatsapp"])):
        for r in rows:
            destino = r.get("to_addr") or r.get("to_phone") or "?"
            filas.append(
                f"<li><strong>{canal}</strong> · {r.get('template_key')} → {destino}: "
                f"{r.get('error') or '(sin detalle)'}</li>"
            )
    lista = "".join(filas) or "<li>(sin detalle disponible)</li>"
    return (
        "<h2 style='margin:0 0 12px'>Comunicación — fallas de las últimas 24h</h2>"
        f"<p>Se registraron <strong>{total}</strong> envío(s) fallido(s) "
        f"(mail + WhatsApp), por encima del umbral ({UMBRAL_FALLOS}).</p>"
        f"<ul>{lista}</ul>"
        "<p>Detalle completo en <code>/admin/comunicacion</code>.</p>"
    )


def chequear_fallas_y_alertar() -> bool:
    """Si los fallos de las últimas 24h superan `UMBRAL_FALLOS`, manda un mail
    a cada admin. Devuelve `True` si mandó alerta, `False` si no. Nunca
    propaga — un error acá no debe tumbar el scheduler."""
    from config import settings

    with get_db() as conn:
        if _alertado_recientemente(conn):
            return False
        fallos = _fallos_ultimas_24h(conn)

    total = len(fallos["mail"]) + len(fallos["whatsapp"])
    # `_fallos_ultimas_24h` trae como mucho 10 por canal (20 total) — si el
    # total real fuera mayor, igual dispara con lo que trajo (el umbral es
    # bajo, 10+10 alcanza de sobra para decidir si avisar).
    if total < UMBRAL_FALLOS:
        return False

    logger.warning("Comunicación: %d fallo(s) en las últimas 24h — alertando a admins", total)
    cuerpo = _resumen_html(fallos, total)
    alertados = False
    for to in sorted(settings.admin_emails):
        r = send_raw_email(
            to=to,
            subject="⚠️ Comunicación — fallas de envío",
            body_html=cuerpo,
            text=f"{total} envío(s) fallido(s) en las últimas 24h. Ver /admin/comunicacion.",
            log_key=_LOG_KEY,
        )
        alertados = alertados or bool(r.get("ok"))
    return alertados
