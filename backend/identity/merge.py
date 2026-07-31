"""identity/merge.py — fusión PESADA de dos cuentas de cliente (dedup, Fase 2 #1098).

A diferencia de `auth/account_merge.py` (que solo ABSORBE una cuenta liviana SIN datos),
acá **ambas** cuentas pueden tener pedidos, plata e historia. `merge_accounts` REASIGNA
las FKs de `source` a `target` y borra `source`, todo en UNA transacción.

Lo dispara el **ADMIN** desde el back-office tras un diagnóstico (`candidatos_duplicados`)
— NUNCA un auto-merge en una migración (FKs a alquileres/contabilidad = radio de
explosión). El índice único de CUIL se crea al FINAL, recién después de deduplicar lo
existente con esta herramienta.

Quién sobrevive: el **target**, con SU identidad intacta. Por eso se REHÚSA mergear si el
`source` está verificado y el `target` no (perderíamos una identidad RENAPER) → el admin
debe mergear al revés. Y se rehúsa si ambos están verificados con CUIL distinto (son dos
personas, no un duplicado).

Cobertura de FKs: toda columna que referencia `clientes(id)` está clasificada acá —
`TABLAS_REASIGNADAS` (datos que se mueven) ∪ `TABLAS_DESCARTADAS` (efímeras / sesiones que
mueren con el source). `test_identity_merge_cobertura` cruza estos sets contra `schema.py`
y falla si aparece una FK nueva sin clasificar (anti-drift mecánico).
"""
import logging

from database import get_db, now_ar

from identity.kyc import registrar_evento

logger = logging.getLogger(__name__)


# ── Clasificación de TODAS las FKs a clientes(id) ─────────────────────────────
# Datos que se MUEVEN del source al target (se preservan). Las dos primeras tienen
# UNIQUE por-cuenta → se reasignan deduplicando (la fila sobrante muere con el source).
TABLAS_REASIGNADAS = frozenset({
    "verified_contacts",        # UNIQUE(cliente_id, kind, value) → dedup por (kind, value)
    "login_identities",         # un método por cuenta (un Google, un mail) → dedup por method
    "kyc_events",               # bitácora de ambas cuentas (se conserva la historia)
    "passkey_credentials",      # credential_id es UNIQUE global → mover sin conflicto
    "alquileres",               # los PEDIDOS (plata/historia) — jamás se pierden
    "cliente_listas",           # listas guardadas del usuario
    "aceptaciones_tyc",         # UNIQUE(cliente_id, version) → dedup por version (ON CONFLICT DO NOTHING)
    "cliente_perfiles_fiscales",  # #1240 — dedup por cuit; es_default se resuelve aparte (no puede
                                   # haber dos TRUE para el mismo cliente_id, índice único parcial)
    "productora_miembros",         # #1240 — dedup por productora_id (PK compuesta)
})
# FKs que NO se mueven: mueren con el DELETE del source. Las sesiones llevan el id viejo
# en la cookie firmada → re-login; los carritos son efímeros (FK SET NULL).
TABLAS_DESCARTADAS = frozenset({
    "auth_sessions",        # la cookie tiene el cliente_id viejo → re-login en el target
    "carritos_activos",     # efímero, client-side (FK SET NULL)
    "carritos_compartidos", # link efímero de compartir (FK SET NULL)
})


def candidatos_duplicados(conn=None) -> list[dict]:
    """Diagnóstico: grupos de cuentas que comparten un CUIL verificado — exactamente lo
    que el índice único de CUIL va a rechazar. El admin usa esto para encontrar duplicados
    antes de mergearlos (y de crear el índice). Devuelve [{cuil, ids:[...], n}]."""
    own = conn is None
    conn = conn or get_db()
    try:
        rows = conn.execute(
            """SELECT cuil, array_agg(id ORDER BY id) AS ids, COUNT(*) AS n
                 FROM clientes
                WHERE cuil IS NOT NULL AND dni_validado_at IS NOT NULL
                GROUP BY cuil
               HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, cuil""",
        ).fetchall()
        return [{"cuil": r["cuil"], "ids": list(r["ids"]), "n": r["n"]} for r in rows]
    finally:
        if own:
            conn.close()


def _estado_identidad(conn, cliente_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, cuil, dni_validado_at FROM clientes WHERE id=%s", (cliente_id,)
    ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "cuil": row["cuil"], "verificado": row["dni_validado_at"] is not None}


def merge_accounts(*, source: int, target: int, conn=None) -> None:
    """Une `source` en `target`: reasigna sus datos (pedidos, listas, contactos, llaves,
    bitácora) y borra `source`. Transaccional (todo o nada). `target` sobrevive con SU
    identidad intacta.

    Rehúsa (ValueError) si:
      - source == target (no-op silencioso, sin error).
      - alguno no existe.
      - source verificado y target NO → perderíamos la identidad RENAPER (mergeá al revés).
      - ambos verificados con CUIL distinto → son dos personas, no un duplicado.
    """
    if source == target:
        return

    own = conn is None
    conn = conn or get_db()
    try:
        s = _estado_identidad(conn, source)
        t = _estado_identidad(conn, target)
        if s is None or t is None:
            raise ValueError(f"merge: cuenta inexistente (source={source} target={target})")
        if s["verificado"] and not t["verificado"]:
            raise ValueError(
                "merge: el source está verificado y el target no — mergeá al revés "
                "(el verificado debe sobrevivir) para no perder la identidad RENAPER"
            )
        if s["verificado"] and t["verificado"] and s["cuil"] != t["cuil"]:
            raise ValueError(
                "merge: ambas cuentas están verificadas con CUIL distinto — son dos "
                "personas, no un duplicado; no se mergean"
            )

        with conn.transaction():
            # Dedup-on-reassign: las tablas con UNIQUE por-cuenta mueven solo lo que el
            # target no tiene ya; la fila sobrante se va con el DELETE del source (cascade).
            conn.execute(
                """UPDATE verified_contacts AS v SET cliente_id=%s
                     WHERE v.cliente_id=%s
                       AND NOT EXISTS (SELECT 1 FROM verified_contacts t
                                        WHERE t.cliente_id=%s AND t.kind=v.kind AND t.value=v.value)""",
                (target, source, target),
            )
            conn.execute(
                """UPDATE login_identities li SET cliente_id=%s
                     WHERE li.cliente_id=%s
                       AND NOT EXISTS (SELECT 1 FROM login_identities t
                                        WHERE t.method=li.method AND t.cliente_id=%s)""",
                (target, source, target),
            )
            conn.execute(
                """UPDATE aceptaciones_tyc a SET cliente_id=%s
                     WHERE a.cliente_id=%s
                       AND NOT EXISTS (SELECT 1 FROM aceptaciones_tyc t
                                        WHERE t.cliente_id=%s AND t.version=a.version)""",
                (target, source, target),
            )
            # #1240: perfiles fiscales — dedup por cuit; `es_default` se pone en FALSE en el
            # move para nunca chocar con el índice único parcial (a lo sumo el target ya
            # tenía uno propio, o se promueve el más reciente abajo si se quedó sin ninguno).
            conn.execute(
                """UPDATE cliente_perfiles_fiscales AS p SET cliente_id=%s, es_default=FALSE
                     WHERE p.cliente_id=%s
                       AND NOT EXISTS (SELECT 1 FROM cliente_perfiles_fiscales t
                                        WHERE t.cliente_id=%s AND t.cuit=p.cuit)""",
                (target, source, target),
            )
            conn.execute(
                """UPDATE cliente_perfiles_fiscales SET es_default=TRUE
                     WHERE id = (SELECT id FROM cliente_perfiles_fiscales
                                  WHERE cliente_id=%s ORDER BY created_at DESC LIMIT 1)
                       AND NOT EXISTS (SELECT 1 FROM cliente_perfiles_fiscales
                                        WHERE cliente_id=%s AND es_default)""",
                (target, target),
            )
            # #1240: vínculos a productoras — dedup por productora_id (PK compuesta).
            conn.execute(
                """UPDATE productora_miembros AS m SET cliente_id=%s
                     WHERE m.cliente_id=%s
                       AND NOT EXISTS (SELECT 1 FROM productora_miembros t
                                        WHERE t.cliente_id=%s AND t.productora_id=m.productora_id)""",
                (target, source, target),
            )
            # Reasignación simple (sin UNIQUE por-cuenta que pueda chocar).
            for tabla in ("kyc_events", "passkey_credentials", "alquileres",
                          "cliente_listas"):
                conn.execute(
                    f"UPDATE {tabla} SET cliente_id=%s WHERE cliente_id=%s",  # noqa: S608 (tabla de allowlist constante)
                    (target, source),
                )
            # Bitácora del merge en el sobreviviente (solo ids, sin PII — Ley 25.326).
            registrar_evento(conn, target, "merge", f"absorbió cliente_id={source}")
            # Las FKs DESCARTADAS (sesiones + carritos) mueren con el source: CASCADE / SET NULL.
            conn.execute("DELETE FROM clientes WHERE id=%s", (source,))
            conn.execute("UPDATE clientes SET updated_at=%s WHERE id=%s", (now_ar(), target))
        logger.info("identity merge: source=%s absorbida en target=%s", source, target)
    finally:
        if own:
            conn.close()
