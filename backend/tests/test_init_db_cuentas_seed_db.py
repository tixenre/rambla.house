"""Regresión #932: el seed de `cuentas` en init_db debe ser idempotente aunque una
cuenta de socio se haya renombrado/desactivado.

`cuentas` tiene DOS unique: el parcial de nombre activo (`cuentas_nombre_activa_uq`)
y `idx_cuentas_socio` (sobre socio). El seed usaba `ON CONFLICT (nombre) WHERE
activa`, que NO atrapa el choque por socio: si el nombre salió del índice parcial
(rename o baja) pero el socio sigue, el INSERT reventaba con UniqueViolation en
CADA boot (ensucia logs + corta el resto del seed). Postgres real, opt-in.
"""
import os
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


def test_init_db_idempotente_con_cuenta_socio_renombrada():
    from database import init_db, get_db

    init_db()  # 1ª vez: crea la tabla + siembra las cuentas (incl. socio='Rental')

    # Estado de prod: el usuario renombró la cuenta del socio Rental. Su nombre
    # sale del índice parcial activo, pero socio='Rental' sigue en idx_cuentas_socio.
    conn = get_db()
    conn.execute("UPDATE cuentas SET nombre = 'Caja Rental (renombrada)' WHERE socio = 'Rental'")
    conn.commit()
    conn.close()

    try:
        # 2ª vez: el seed re-inserta ('Fondo Rental', socio='Rental'). SIN el fix,
        # no hay choque por nombre-activo (ya no existe 'Fondo Rental' activo) pero
        # SÍ por idx_cuentas_socio → UniqueViolation e init_db revienta. CON el fix
        # (`ON CONFLICT DO NOTHING`) salta y no rompe.
        init_db()  # no debe lanzar

        conn = get_db()
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM cuentas WHERE socio = 'Rental'"
        ).fetchone()["c"]
        conn.close()
        assert n == 1, f"se duplicó la cuenta del socio Rental ({n})"
    finally:
        # Restaurar el nombre para no contaminar otros tests de la base compartida.
        conn = get_db()
        conn.execute("UPDATE cuentas SET nombre = 'Fondo Rental' WHERE socio = 'Rental'")
        conn.commit()
        conn.close()
