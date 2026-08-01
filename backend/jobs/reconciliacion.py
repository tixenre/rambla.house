"""Alerta proactiva de reconciliación de plata (#1184 Fase 2).

Antes del job, el semáforo de reconciliación era **100% manual**: solo se
enteraba de un desbalance quien abriera `/admin/reportes` o
`/admin/contabilidad` a mirar. Este job corre 1×/día desde el mismo scheduler
in-process que ya corre los recordatorios de retiro y el cleanup de cuentas
livianas (mismo patrón, cero costo extra de infra) y manda un mail resumen a
`settings.admin_emails` si el semáforo unificado (`finanzas_flujo.reconciliacion.estado`)
da `ok=False`. No repara nada — solo avisa.
"""
import logging

from database import get_db
from services.email import send_raw_email
from services.finanzas_flujo.reconciliacion import estado

logger = logging.getLogger(__name__)


def _resumen_html(data: dict) -> str:
    """Arma un resumen legible del detalle para el cuerpo del mail. No repite la
    forma exacta del dashboard admin — solo señala qué mirar."""
    filas = []

    reporte = data.get("reporte", {})
    for key, label in (
        ("pagados_sin_ledger", "Pagados sin ledger"),
        ("monto_pagado_divergente", "Monto pagado divergente"),
        ("sobrepagados", "Sobrepagados"),
        ("desglose_divergente", "Desglose de pedido divergente"),
    ):
        chk = reporte.get(key) or {}
        if chk.get("cantidad"):
            filas.append(f"<li><strong>{label}:</strong> {chk['cantidad']} pedido(s)</li>")
    mes_stale = reporte.get("mes_cerrado_desactualizado") or {}
    if mes_stale.get("cantidad"):
        filas.append(
            f"<li><strong>Mes cerrado desactualizado:</strong> {mes_stale['cantidad']} pedido(s), "
            f"meses {', '.join(mes_stale.get('meses') or [])}</li>"
        )
    if reporte.get("duenos_no_canonicos"):
        filas.append(
            f"<li><strong>Dueños fuera del modelo de comisiones:</strong> "
            f"{', '.join(reporte['duenos_no_canonicos'])}</li>"
        )

    contable = data.get("contabilidad", {})
    if (contable.get("saldos_negativos") or {}).get("cantidad"):
        filas.append(
            f"<li><strong>Cajas con saldo negativo:</strong> "
            f"{contable['saldos_negativos']['cantidad']}</li>"
        )
    if (contable.get("pagos_sin_socio") or {}).get("cantidad"):
        filas.append(
            f"<li><strong>Pagos sin cobrador válido:</strong> "
            f"{contable['pagos_sin_socio']['cantidad']}</li>"
        )
    if (contable.get("movimientos_cuenta_inactiva") or {}).get("cantidad"):
        filas.append(
            f"<li><strong>Movimientos a cuenta inactiva:</strong> "
            f"{contable['movimientos_cuenta_inactiva']['cantidad']}</li>"
        )
    # Este chequeo BAJA el semáforo (`reconciliacion.py`), así que tiene que salir
    # nombrado en el mail — si no, la alerta llega sin decir qué pasó.
    sin_cuenta = contable.get("devengado_sin_cuenta") or {}
    if sin_cuenta.get("cantidad"):
        quienes = ", ".join(b["beneficiario"] for b in sin_cuenta.get("beneficiarios") or [])
        filas.append(
            f"<li><strong>Devengado sin caja donde verse:</strong> "
            f"${sin_cuenta.get('monto', 0):,} para {quienes} — revisar el modelo de "
            f"comisiones o crear la cuenta</li>"
        )

    if not filas:
        filas = ["<li>El detalle no trae ítems positivos — revisar el dashboard admin.</li>"]

    return (
        "<h2 style='margin:0 0 12px'>Reconciliación de plata — atención</h2>"
        "<p>El semáforo de reconciliación detectó una divergencia. Resumen:</p>"
        f"<ul>{''.join(filas)}</ul>"
        "<p>Detalle completo en <code>/admin/reportes</code> y "
        "<code>/admin/contabilidad</code> (pestaña Reconciliación).</p>"
    )


def _alertado_recientemente(conn) -> bool:
    """`True` si ya se mandó `reconciliacion_alerta` en las últimas 20h.

    Dedup contra `emails_log` (sobrevive un restart del proceso): el gate
    "1×/día" del scheduler (`ultima_reconciliacion` en `jobs/scheduler.py`) es
    una variable EN MEMORIA que arranca en `None` y se resetea en cada restart
    del thread — en `dev` (auto-deploy en cada push) eso disparaba un mail
    completo por cada contenedor nuevo mientras la divergencia seguía sin
    resolver, en vez de 1×/día real. Ventana de 20h (no medianoche calendario,
    evita líos de huso horario) calculada en Postgres."""
    row = conn.execute(
        """
        SELECT 1 FROM emails_log
         WHERE template_key = 'reconciliacion_alerta'
           AND status = 'sent'
           AND sent_at > NOW() - INTERVAL '20 hours'
         LIMIT 1
        """
    ).fetchone()
    return row is not None


def chequear_reconciliacion_y_alertar() -> bool:
    """Corre el semáforo unificado; si `ok=False`, manda un mail a cada admin.
    Devuelve `True` si mandó alerta, `False` si todo estaba en orden. Nunca
    propaga — un error acá no debe tumbar el scheduler (mismo contrato que los
    otros jobs)."""
    from config import settings

    with get_db() as conn:
        if _alertado_recientemente(conn):
            return False
        data = estado(conn)

    if data.get("ok"):
        return False

    logger.warning("Reconciliación de plata con divergencias — alertando a admins")
    cuerpo = _resumen_html(data)
    alertados = False
    for to in sorted(settings.admin_emails):
        r = send_raw_email(
            to=to,
            subject="⚠️ Reconciliación de plata — atención",
            body_html=cuerpo,
            text="El semáforo de reconciliación de plata detectó una divergencia. Ver /admin/reportes.",
            log_key="reconciliacion_alerta",
        )
        alertados = alertados or bool(r.get("ok"))
    return alertados
