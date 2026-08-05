"""services/ipc.py — serie de IPC (INDEC) para ajustar Estadísticas por inflación.

Fuente: API pública de series de tiempo de INDEC / Subsecretaría de Programación
Macroeconómica (apis.datos.gob.ar), serie "148.3_INIVELNAL_DICI_M_26" (Índice de
Precios al Consumidor Nacional, base diciembre 2016). Sin auth, sin límite de tasa
documentado, valores mensuales.

Se cachea en `ipc_series` — Estadísticas no pega a la API en cada request. Un job
1×/día (`jobs/ipc.py`, mismo scheduler in-process que el resto: recordatorios,
reconciliación, cleanup) refresca la serie completa vía `actualizar_ipc` (upsert
idempotente).

**Convención del factor de ajuste — "pesos de HOY":** `factor(mes) = índice del
mes MÁS RECIENTE con dato / índice(mes)`. Multiplicar un monto de `mes` por su
factor lo expresa en el poder adquisitivo del último mes disponible — no del
primer pedido. Es la lectura más intuitiva para el dueño ("¿esto creció de
verdad o es solo inflación comparado con HOY?") y el mes más reciente no
necesita ajuste (factor 1), a diferencia de anclar a la fecha del primer pedido
(que dejaría TODO ajustado, incluido el mes en curso).

**Ajustar EN ORIGEN, no post-suma:** un total que ya sumó plata de varios meses
no se puede corregir multiplicándolo por un solo factor — cada peso que lo
compone perdió valor a un ritmo distinto según de qué mes vino. `IPC_FACTOR_CTE`
se JOINea a la fila de origen (pedido/ítem/movimiento) ANTES del `SUM()`, nunca
después.
"""
from __future__ import annotations

import logging
from decimal import Decimal

import httpx

logger = logging.getLogger(__name__)

INDEC_SERIES_URL = (
    "https://apis.datos.gob.ar/series/api/series/"
    "?ids=148.3_INIVELNAL_DICI_M_26&format=json&limit=5000"
)


def fetch_ipc_series() -> list[tuple[str, Decimal]]:
    """GET a la API de INDEC. Devuelve [(mes 'YYYY-MM', índice), ...] ordenado
    como venga la respuesta. Levanta en error de red/HTTP/parseo — el caller
    (`actualizar_ipc` / el job) decide cómo loguearlo; nunca silencioso acá."""
    resp = httpx.get(INDEC_SERIES_URL, timeout=15)
    resp.raise_for_status()
    filas = resp.json()["data"]
    return [
        (fecha[:7], Decimal(str(indice)))
        for fecha, indice in filas
        if indice is not None
    ]


def actualizar_ipc(conn) -> int:
    """Trae la serie completa y la upsertea en `ipc_series`. Devuelve cuántas
    filas trajo la API (no necesariamente cuántas cambiaron — el `WHERE`
    del upsert evita escrituras no-op, mismo patrón que el resto del repo)."""
    serie = fetch_ipc_series()
    for mes, indice in serie:
        conn.execute(
            """
            INSERT INTO ipc_series (mes, indice, actualizado_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (mes) DO UPDATE
               SET indice = EXCLUDED.indice, actualizado_at = EXCLUDED.actualizado_at
             WHERE ipc_series.indice IS DISTINCT FROM EXCLUDED.indice
            """,
            (mes, indice),
        )
    conn.commit()
    return len(serie)


def mes_referencia(conn) -> str | None:
    """El mes más reciente con dato de IPC — a este mes queda expresado "pesos
    ajustados". `None` si `ipc_series` está vacía (todavía no corrió el job)."""
    row = conn.execute("SELECT mes FROM ipc_series ORDER BY mes DESC LIMIT 1").fetchone()
    return row["mes"] if row else None


# Fragmento SQL compartido: mes → factor de ajuste respecto al mes MÁS
# RECIENTE con dato (ver convención en el docstring del módulo). Se antepone
# con `WITH {IPC_FACTOR_CTE}` a cualquier query que necesite ajustar, mismo
# patrón que `_PRORRATEO_CTE`/`_TURNO_NETO_CTE` de `routes/estadisticas.py`.
#
# `COALESCE(factor, 1)` en el JOIN (no acá adentro): un mes sin fila en
# `ipc_series` (ej. el mes en curso, que INDEC todavía no publicó) se muestra
# en su valor NOMINAL en vez de desaparecer del total o romper la query.
IPC_FACTOR_CTE = """
    ipc_factor AS (
        SELECT mes, (SELECT indice FROM ipc_series ORDER BY mes DESC LIMIT 1) / indice AS factor
        FROM ipc_series
    )
"""
