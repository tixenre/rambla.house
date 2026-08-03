"""Scheduler in-process del barrido diario de recordatorios de retiro.

Decisión 2026-06-04 (issue #735): el recordatorio se dispara desde un thread
**dentro del backend que ya corre 24/7**, no como servicio de cron aparte.
Costo extra: $0 (reusa el compute que ya se paga).

**Gating en runtime, no en el arranque (Fase B mails):** el thread arranca
siempre (salvo el kill-switch `REMINDERS_SCHEDULER_DISABLED`, para CI/tests) y en
cada ciclo resuelve si está prendido y a qué horas corre vía
`jobs/recordatorios_config.resolve()` — env override > `app_settings` > default.
Así el admin lo prende/apaga y ajusta desde `/admin/comunicacion` **sin redeploy
ni tocar env vars**. Se reusa el mismo mecanismo de thread+sondeo (no se "recrea"
el scheduler).

El recordatorio de retiro corre **dos veces por día** (el aviso depende de la hora
del retiro, ver `jobs/recordatorios.py`): la pasada de la mañana a la hora
configurada y la de la víspera a la hora de cierre del galpón. Cada una lleva su
propia marca de "ya corrió hoy".

**Single-instance:** hoy el backend corre 1 instancia. Si se escala a >1, dos
schedulers dispararían el barrido en paralelo el mismo día → agregar un lock
(ej. `pg_try_advisory_lock`) antes de correr. Aun así no habría mails duplicados:
la red final es el índice único de `emails_log` (ver `jobs/recordatorios.py`).

Mecanismo: un thread daemon que sondea cada `_CHECK_EVERY_S`; una vez por día,
a partir de la hora resuelta (hora AR), corre el barrido y marca la fecha para no
repetir. Simple y sin dependencia nueva (no se agrega APScheduler). Un reinicio
después de la hora puede volver a correrlo, pero el envío es idempotente.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import timedelta

from database import now_ar
from jobs.recordatorios_config import resolve

logger = logging.getLogger(__name__)

_CHECK_EVERY_S = 600  # 10 min: granularidad del sondeo

# Recheck de verificaciones Didit abandonadas: por tiempo transcurrido (no por
# fecha calendario como los otros dos jobs) — la ventana de abandono se mide en
# minutos, no en días, así que un corte a medianoche no aplica.
_RECHECK_DIDIT_EVERY = timedelta(minutes=30)

# Reintento de comunicación fallida: por tiempo transcurrido, no por fecha —
# una falla transitoria (Meta/Resend caídos unos minutos) se quiere recuperar
# dentro de la hora, no esperar al barrido diario siguiente.
_REINTENTAR_COMUNICACION_EVERY = timedelta(hours=1)


def _hard_disabled() -> bool:
    """Kill-switch de ops/CI: apaga el thread por completo (no sondea). Útil en
    tests para no levantar un thread que intente tocar la DB."""
    return os.getenv("REMINDERS_SCHEDULER_DISABLED", "").strip().lower() in ("1", "true", "yes")


def _loop() -> None:
    # Import perezoso: evita cargar el job (y sus imports de routes) al importar
    # este módulo, y rompe cualquier ciclo de importación al arrancar.
    from jobs.recordatorios import (
        PASADA_MANANA,
        PASADA_VISPERA,
        enviar_recordatorios_retiro,
    )
    from jobs.recordatorios_devolucion import enviar_recordatorios_devolucion
    from jobs.recordatorios_devolucion_config import resolve as resolve_devolucion
    from jobs.cleanup_livianas import purgar_cuentas_livianas_stale
    from jobs.recheck_didit_pendientes import recheck_verificaciones_pendientes
    from jobs.purgar_auth import purgar_sesiones_y_challenges_expirados
    from jobs.reintentar_comunicacion import reintentar_fallidos
    from jobs.comunicacion_alertas import chequear_fallas_y_alertar
    from jobs.purgar_logs_comunicacion import purgar_logs_comunicacion_viejos
    from jobs.reconciliacion import chequear_reconciliacion_y_alertar
    from jobs.ipc import actualizar_ipc_job

    ultima_manana = None      # recordatorios de retiro, pasada de la mañana
    ultima_vispera = None     # recordatorios de retiro, pasada de la víspera
    ultima_devolucion = None  # recordatorios de devolución (WhatsApp, ventanas D-1/D-0/vencido)
    ultima_limpieza = None    # cleanup de cuentas livianas (independiente)
    ultimo_recheck_didit = None  # recheck de verificaciones pendientes (por intervalo, no por día)
    ultima_purga_auth = None  # housekeeping de auth_sessions/auth_challenges (independiente)
    ultimo_reintento_comunicacion = None  # reintento de mail/whatsapp fallidos (por intervalo)
    ultima_alerta_comunicacion = None  # alerta de fallas de comunicación (independiente)
    ultima_purga_logs_comunicacion = None  # retención de emails_log/whatsapp_log (independiente)
    ultima_reconciliacion = None  # alerta de reconciliación de plata (#1184 Fase 2 — dormida hasta ahora)
    ultima_actualizacion_ipc = None  # refresh de la serie de IPC/INDEC (Estadísticas ajustadas)
    while True:
        ahora = now_ar()
        try:
            cfg = resolve(dia=ahora.date())  # env > settings > default, en cada ciclo
            if cfg["enabled"]:
                # Mañana: los retiros de HOY que todavía no ocurrieron.
                if ahora.hour >= cfg["hora"] and ahora.date() != ultima_manana:
                    ultima_manana = ahora.date()
                    enviar_recordatorios_retiro(
                        pasada=PASADA_MANANA, corte_manana=cfg["corte_manana"]
                    )
                # Víspera, a la hora de cierre: los retiros de MAÑANA temprano.
                if ahora.hour >= cfg["hora_vispera"] and ahora.date() != ultima_vispera:
                    ultima_vispera = ahora.date()
                    enviar_recordatorios_retiro(
                        pasada=PASADA_VISPERA, corte_manana=cfg["corte_manana"]
                    )
        except Exception:  # nunca dejar morir el thread por un error puntual
            logger.exception("Falló el barrido de recordatorios de retiro")
        try:
            # Recordatorios de devolución (WhatsApp): 1×/día, con sus PROPIAS
            # ventanas (D-1/D-0/vencido) prendibles desde el back-office. Comparte
            # la mecánica del barrido de retiro pero no su on/off ni su hora.
            # Idempotencia real vía whatsapp_log (índice único) — un reinicio no
            # re-manda. Si no hay ninguna ventana activa (o el canal está inerte),
            # es un no-op.
            cfg_dev = resolve_devolucion()
            if (
                cfg_dev["alguna"]
                and ahora.hour >= cfg_dev["hora"]
                and ahora.date() != ultima_devolucion
            ):
                ultima_devolucion = ahora.date()
                enviar_recordatorios_devolucion(ventanas=cfg_dev["ventanas"])
        except Exception:
            logger.exception("Falló el barrido de recordatorios de devolución")
        try:
            # Cleanup de cuentas livianas stale: 1×/día, independiente del recordatorio
            # (no comparte su on/off ni su hora). Idempotente → un reinicio puede
            # re-correrlo sin daño. El kill-switch del thread lo apaga junto con todo.
            if ahora.date() != ultima_limpieza:
                ultima_limpieza = ahora.date()
                purgar_cuentas_livianas_stale()
        except Exception:
            logger.exception("Falló el cleanup de cuentas livianas")
        try:
            # Recheck de verificaciones Didit abandonadas: cada _RECHECK_DIDIT_EVERY,
            # independiente de los demás. Resuelve al cliente que no vuelve a la web
            # sin esperar a que un admin lo note (ver docstring del job).
            if ultimo_recheck_didit is None or (ahora - ultimo_recheck_didit) >= _RECHECK_DIDIT_EVERY:
                ultimo_recheck_didit = ahora
                recheck_verificaciones_pendientes()
        except Exception:
            logger.exception("Falló el recheck de verificaciones Didit pendientes")
        try:
            # Housekeeping de auth: 1×/día, independiente de los demás. Las filas
            # vencidas ya eran inertes (is_active/peek/consumir filtran por
            # expires_at/revoked_at/used_at) — esto solo evita que crezcan sin límite.
            if ahora.date() != ultima_purga_auth:
                ultima_purga_auth = ahora.date()
                purgar_sesiones_y_challenges_expirados()
        except Exception:
            logger.exception("Falló el housekeeping de auth_sessions/auth_challenges")
        try:
            # Reintento de comunicación fallida: cada _REINTENTAR_COMUNICACION_EVERY,
            # independiente de los demás. Idempotente (notificar_pedido hereda el
            # gating/idempotencia de cada canal) — un reinicio del proceso no
            # duplica nada, en el peor caso reintenta antes de tiempo.
            if (
                ultimo_reintento_comunicacion is None
                or (ahora - ultimo_reintento_comunicacion) >= _REINTENTAR_COMUNICACION_EVERY
            ):
                ultimo_reintento_comunicacion = ahora
                reintentar_fallidos()
        except Exception:
            logger.exception("Falló el reintento de comunicación fallida")
        try:
            # Alerta de fallas de comunicación: 1×/día, independiente de los demás.
            if ahora.date() != ultima_alerta_comunicacion:
                ultima_alerta_comunicacion = ahora.date()
                chequear_fallas_y_alertar()
        except Exception:
            logger.exception("Falló la alerta de fallas de comunicación")
        try:
            # Retención de logs de comunicación: 1×/día, independiente de los demás.
            if ahora.date() != ultima_purga_logs_comunicacion:
                ultima_purga_logs_comunicacion = ahora.date()
                purgar_logs_comunicacion_viejos()
        except Exception:
            logger.exception("Falló la purga de logs de comunicación")
        try:
            # Alerta de reconciliación de plata (#1184 Fase 2): existía desde ese PR
            # pero nunca se había conectado acá — corría solo si un admin abría
            # /admin/reportes o /admin/contabilidad a mirar. 1×/día, independiente.
            if ahora.date() != ultima_reconciliacion:
                ultima_reconciliacion = ahora.date()
                chequear_reconciliacion_y_alertar()
        except Exception:
            logger.exception("Falló la alerta de reconciliación de plata")
        try:
            # Refresh de IPC (INDEC) para Estadísticas ajustadas por inflación:
            # 1×/día, independiente de los demás. INDEC publica 1×/mes — sobra
            # de margen, pero re-traer la serie completa es barato e idempotente
            # (upsert con guard IS DISTINCT FROM), así que no hace falta un gate
            # más fino.
            if ahora.date() != ultima_actualizacion_ipc:
                ultima_actualizacion_ipc = ahora.date()
                actualizar_ipc_job()
        except Exception:
            logger.exception("Falló el refresh de la serie de IPC")
        time.sleep(_CHECK_EVERY_S)


def start_scheduler() -> bool:
    """Arranca el thread daemon del scheduler. Devuelve si arrancó.

    Arranca siempre salvo el kill-switch `REMINDERS_SCHEDULER_DISABLED` — el
    on/off real se decide en runtime dentro del loop (ver módulo). Idempotente a
    nivel proceso: pensado para llamarse una vez al inicio.
    """
    if _hard_disabled():
        logger.info(
            "Scheduler de recordatorios DESHABILITADO por REMINDERS_SCHEDULER_DISABLED"
        )
        return False
    threading.Thread(
        target=_loop, name="recordatorios-scheduler", daemon=True
    ).start()
    logger.info(
        "Scheduler de recordatorios ACTIVO (gating en runtime: env > settings > default)"
    )
    return True
