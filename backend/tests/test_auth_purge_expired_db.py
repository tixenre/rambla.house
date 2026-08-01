"""`purge_expired` de sesiones (`auth_sessions`) y magic-links (`auth_challenges`),
Postgres real — ahora corren automáticamente 1×/día desde `jobs/purgar_auth.py`
(scheduler), así que un bug acá borraría (o dejaría de borrar) datos reales en
producción. Confirma que cada uno borra SOLO lo muerto y preserva lo vivo.

Las fechas de las filas de prueba se siembran con `now_ar()` (la misma función
que usa el código real para escribir `expires_at`), NO con `NOW()`/`interval`
de Postgres crudo: `now_ar()` devuelve un naive datetime en hora de pared AR
(UTC-3) que, atado a una columna TIMESTAMPTZ en una sesión de Postgres en UTC
(el default en Docker/Railway/CI), Postgres lo interpreta COMO SI ya fuera
UTC — 3 horas antes del instante real. Es inofensivo en producción porque
`commands/sessions.py`/`commands/magic.py` escriben Y `queries/sessions.py`/
`is_active`/`purge_expired` comparan con el mismo `now_ar()` de los dos lados
(el corrimiento se cancela). Pero un fixture que siembra con el reloj REAL de
Postgres (`NOW()`) rompe esa consistencia: una fila "vencida hace 1 hora" según
Postgres queda comparándose contra un `now_ar()` que el motor ve 3 horas más
atrás — el `purge_expired()` real no la encuentra vencida y el test falla con
un `n=0` falso. Sembrar con `now_ar() ± timedelta` reproduce el mismo reloj
que usa el código de producción.
"""
import os
from datetime import timedelta
from urllib.parse import urlparse

import pytest

_OPT_IN = os.getenv("RESERVAS_DB_TEST") == "1"
_DB_NAME = urlparse(os.getenv("DATABASE_URL", "")).path.lstrip("/")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _OPT_IN, reason="opt-in: RESERVAS_DB_TEST=1 + DATABASE_URL de test"),
    pytest.mark.skipif(
        _OPT_IN and "test" not in _DB_NAME.lower(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]


def test_sessions_purge_expired_borra_solo_lo_vencido():
    from database import init_db, get_db, now_ar
    from auth.commands import sessions as commands

    init_db()
    ahora = now_ar()
    prefix = "purge-test-"
    jtis = [f"{prefix}vencida", f"{prefix}vigente", f"{prefix}revocada-no-vencida"]
    try:
        with get_db() as conn:
            with conn.transaction():
                conn.execute("DELETE FROM auth_sessions WHERE jti = ANY(%s)", (jtis,))
                # (1) vencida → DEBE borrarse
                conn.execute(
                    "INSERT INTO auth_sessions (jti, owner_type, owner_email, expires_at) "
                    "VALUES (%s, 'admin', 'a@test.local', %s)",
                    (jtis[0], ahora - timedelta(hours=1)),
                )
                # (2) vigente → sobrevive
                conn.execute(
                    "INSERT INTO auth_sessions (jti, owner_type, owner_email, expires_at) "
                    "VALUES (%s, 'admin', 'a@test.local', %s)",
                    (jtis[1], ahora + timedelta(hours=1)),
                )
                # (3) revocada pero AÚN no vencida → sobrevive (revoked_at no es el criterio)
                conn.execute(
                    "INSERT INTO auth_sessions (jti, owner_type, owner_email, expires_at, revoked_at) "
                    "VALUES (%s, 'admin', 'a@test.local', %s, %s)",
                    (jtis[2], ahora + timedelta(hours=1), ahora),
                )

        n = commands.purge_expired()
        assert n >= 1  # al menos la nuestra (puede haber otras vencidas en una DB compartida)

        with get_db() as conn:
            restantes = {
                r["jti"]
                for r in conn.execute(
                    "SELECT jti FROM auth_sessions WHERE jti = ANY(%s)", (jtis,)
                ).fetchall()
            }
        assert restantes == {jtis[1], jtis[2]}  # solo sobrevivieron las 2 no-vencidas
    finally:
        with get_db() as conn:
            with conn.transaction():
                conn.execute("DELETE FROM auth_sessions WHERE jti = ANY(%s)", (jtis,))


def test_magic_purge_expired_borra_usadas_y_vencidas_preserva_vigentes():
    from database import init_db, get_db, now_ar
    from auth.commands import magic as commands

    init_db()
    ahora = now_ar()
    prefix = "purge-magic-"
    hashes = [f"{prefix}usado", f"{prefix}vencido-sin-usar", f"{prefix}vigente-sin-usar"]
    try:
        with get_db() as conn:
            with conn.transaction():
                conn.execute("DELETE FROM auth_challenges WHERE token_hash = ANY(%s)", (hashes,))
                # (1) ya usado (aunque no venció) → DEBE borrarse (ya no sirve)
                conn.execute(
                    "INSERT INTO auth_challenges (kind, email, token_hash, expires_at, used_at) "
                    "VALUES ('magic_link', 'a@test.local', %s, %s, %s)",
                    (hashes[0], ahora + timedelta(hours=1), ahora),
                )
                # (2) vencido sin usar → DEBE borrarse
                conn.execute(
                    "INSERT INTO auth_challenges (kind, email, token_hash, expires_at) "
                    "VALUES ('magic_link', 'a@test.local', %s, %s)",
                    (hashes[1], ahora - timedelta(hours=1)),
                )
                # (3) vigente y sin usar → sobrevive (todavía es un link válido)
                conn.execute(
                    "INSERT INTO auth_challenges (kind, email, token_hash, expires_at) "
                    "VALUES ('magic_link', 'a@test.local', %s, %s)",
                    (hashes[2], ahora + timedelta(hours=1)),
                )

        n = commands.purge_expired()
        assert n >= 2  # al menos las 2 nuestras

        with get_db() as conn:
            restantes = {
                r["token_hash"]
                for r in conn.execute(
                    "SELECT token_hash FROM auth_challenges WHERE token_hash = ANY(%s)", (hashes,)
                ).fetchall()
            }
        assert restantes == {hashes[2]}  # solo el vigente sin usar sobrevivió
    finally:
        with get_db() as conn:
            with conn.transaction():
                conn.execute("DELETE FROM auth_challenges WHERE token_hash = ANY(%s)", (hashes,))
