"""Purga de logs de comunicación (`jobs/purgar_logs_comunicacion.py`) contra
Postgres REAL — el `DELETE ... RETURNING` + `make_interval` es el mismo tipo
de SQL que un FakeConn no valida sintácticamente.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_purgar_logs_comunicacion_db.py -v -m integration
"""
import os
from urllib.parse import urlparse

import pytest

_OPT_IN = os.getenv("RESERVAS_DB_TEST") == "1"
_DB_URL = os.getenv("DATABASE_URL", "")
_DB_NAME = urlparse(_DB_URL).path.lstrip("/") if _DB_URL else ""


def _looks_like_test_db() -> bool:
    return bool(_DB_NAME) and "test" in _DB_NAME.lower()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _OPT_IN,
        reason="opt-in: setear RESERVAS_DB_TEST=1 + DATABASE_URL a una base de prueba",
    ),
    pytest.mark.skipif(
        _OPT_IN and not _looks_like_test_db(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]

# Marcador de este test en el destinatario (no ids fijos: la purga borra por
# fecha, no por id — un WHERE por marca evita pisar filas de otros tests).
_MARCA = "purgatest-marca-unica@test.com"
_MARCA_WA = "+549purgatestmarca"


def _limpiar(conn):
    conn.execute("DELETE FROM emails_log WHERE to_addr = %s", (_MARCA,))
    conn.execute("DELETE FROM whatsapp_log WHERE to_phone = %s", (_MARCA_WA,))


@pytest.fixture
def conn():
    from database import get_db

    c = get_db()
    _limpiar(c)
    c.commit()
    yield c
    _limpiar(c)
    c.commit()
    c.close()


def test_purga_borra_solo_lo_mas_viejo_que_la_retencion(conn):
    from jobs.purgar_logs_comunicacion import purgar_logs_comunicacion_viejos

    conn.execute(
        "INSERT INTO emails_log (to_addr, subject, template_key, status, provider, sent_at) "
        "VALUES (%s, 'x', 'test', 'sent', 'test', NOW() - INTERVAL '400 days')",
        (_MARCA,),
    )
    conn.execute(
        "INSERT INTO emails_log (to_addr, subject, template_key, status, provider, sent_at) "
        "VALUES (%s, 'x', 'test', 'sent', 'test', NOW() - INTERVAL '10 days')",
        (_MARCA,),
    )
    conn.execute(
        "INSERT INTO whatsapp_log (to_phone, template_key, status, wamid, sent_at) "
        "VALUES (%s, 'test', 'sent', 'wamid.OLD', NOW() - INTERVAL '400 days')",
        (_MARCA_WA,),
    )
    conn.commit()

    n_mails, n_whatsapp = purgar_logs_comunicacion_viejos(retencion_dias=365)
    assert n_mails >= 1
    assert n_whatsapp >= 1

    restante_mail = conn.execute(
        "SELECT COUNT(*) AS n FROM emails_log WHERE to_addr = %s", (_MARCA,)
    ).fetchone()
    restante_wa = conn.execute(
        "SELECT COUNT(*) AS n FROM whatsapp_log WHERE to_phone = %s", (_MARCA_WA,)
    ).fetchone()
    assert restante_mail["n"] == 1  # sobrevivió el de 10 días
    assert restante_wa["n"] == 0  # el único era de 400 días


def test_purga_sin_candidatos_no_rompe(conn):
    from jobs.purgar_logs_comunicacion import purgar_logs_comunicacion_viejos

    n_mails, n_whatsapp = purgar_logs_comunicacion_viejos(retencion_dias=365)
    assert isinstance(n_mails, int)
    assert isinstance(n_whatsapp, int)
