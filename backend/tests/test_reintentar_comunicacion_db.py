"""Job de reintento de comunicación (`jobs/reintentar_comunicacion.py`) contra
Postgres REAL — el SQL usa CTE + `= ANY(%s)` + `make_interval` + `FILTER`, que
un FakeConn no puede validar sintácticamente.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_reintentar_comunicacion_db.py -v -m integration
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

CLIENTE_ID = 9_400_001
P_SOLO_FALLIDO = 9_400_101       # 1 failed, sin sent → candidato
P_YA_LLEGO = 9_400_102           # failed en mail + sent en whatsapp → NO candidato
P_MUCHOS_INTENTOS = 9_400_103    # 3 failed (= MAX_INTENTOS) → NO candidato
P_FALLO_VIEJO = 9_400_104        # failed hace 3 días (fuera de la ventana) → NO candidato
P_OTRO_EVENTO = 9_400_105        # failed de OTRO template_key → no debe contarle a este evento


def _limpiar(conn):
    ids = (P_SOLO_FALLIDO, P_YA_LLEGO, P_MUCHOS_INTENTOS, P_FALLO_VIEJO, P_OTRO_EVENTO)
    conn.execute("DELETE FROM whatsapp_log WHERE alquiler_id = ANY(%s)", (list(ids),))
    conn.execute("DELETE FROM emails_log WHERE alquiler_id = ANY(%s)", (list(ids),))
    conn.execute("DELETE FROM alquileres WHERE id = ANY(%s)", (list(ids),))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


@pytest.fixture
def conn():
    from database import get_db

    c = get_db()
    _limpiar(c)
    c.execute(
        "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
        "VALUES (%s,'Reintento','Test','reintento@test.com','+5491100000099')",
        (CLIENTE_ID,),
    )
    for pid in (P_SOLO_FALLIDO, P_YA_LLEGO, P_MUCHOS_INTENTOS, P_FALLO_VIEJO, P_OTRO_EVENTO):
        c.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, fecha_desde, fecha_hasta, numero_pedido, monto_total) "
            "VALUES (%s,%s,'Reintento Test','reintento@test.com','+5491100000099',"
            "'confirmado','2032-07-01','2032-07-05', %s, 10000)",
            (pid, CLIENTE_ID, pid),
        )
    c.commit()
    yield c
    _limpiar(c)
    c.commit()
    c.close()


def test_pedidos_a_reintentar_encuentra_el_candidato_simple(conn):
    from jobs.reintentar_comunicacion import _pedidos_a_reintentar

    conn.execute(
        "INSERT INTO emails_log (to_addr, subject, template_key, alquiler_id, status, provider) "
        "VALUES ('a@test.com','x','pedido_creado_cliente', %s, 'failed', 'test')",
        (P_SOLO_FALLIDO,),
    )
    conn.commit()
    candidatos = _pedidos_a_reintentar(conn, ["pedido_creado_cliente", "pedido_creado"])
    assert P_SOLO_FALLIDO in candidatos


def test_pedidos_a_reintentar_excluye_si_ya_llego_por_otro_canal(conn):
    from jobs.reintentar_comunicacion import _pedidos_a_reintentar

    conn.execute(
        "INSERT INTO emails_log (to_addr, subject, template_key, alquiler_id, status, provider) "
        "VALUES ('a@test.com','x','pedido_creado_cliente', %s, 'failed', 'test')",
        (P_YA_LLEGO,),
    )
    conn.execute(
        "INSERT INTO whatsapp_log (to_phone, template_key, alquiler_id, status, wamid) "
        "VALUES ('+549', 'pedido_creado', %s, 'sent', 'wamid.OK')",
        (P_YA_LLEGO,),
    )
    conn.commit()
    candidatos = _pedidos_a_reintentar(conn, ["pedido_creado_cliente", "pedido_creado"])
    assert P_YA_LLEGO not in candidatos


def test_pedidos_a_reintentar_respeta_el_tope_de_intentos(conn):
    from jobs.reintentar_comunicacion import MAX_INTENTOS, _pedidos_a_reintentar

    for _ in range(MAX_INTENTOS):
        conn.execute(
            "INSERT INTO emails_log (to_addr, subject, template_key, alquiler_id, status, provider) "
            "VALUES ('a@test.com','x','pedido_creado_cliente', %s, 'failed', 'test')",
            (P_MUCHOS_INTENTOS,),
        )
    conn.commit()
    candidatos = _pedidos_a_reintentar(conn, ["pedido_creado_cliente", "pedido_creado"])
    assert P_MUCHOS_INTENTOS not in candidatos


def test_pedidos_a_reintentar_ignora_fallo_fuera_de_ventana(conn):
    from jobs.reintentar_comunicacion import _pedidos_a_reintentar

    conn.execute(
        "INSERT INTO emails_log (to_addr, subject, template_key, alquiler_id, status, provider, sent_at) "
        "VALUES ('a@test.com','x','pedido_creado_cliente', %s, 'failed', 'test', NOW() - INTERVAL '3 days')",
        (P_FALLO_VIEJO,),
    )
    conn.commit()
    candidatos = _pedidos_a_reintentar(conn, ["pedido_creado_cliente", "pedido_creado"])
    assert P_FALLO_VIEJO not in candidatos


def test_pedidos_a_reintentar_no_mezcla_eventos(conn):
    """Un 'failed' de OTRO evento (otro template_key) no lo hace candidato de
    este evento — la búsqueda es por los template_keys que se le pasan."""
    from jobs.reintentar_comunicacion import _pedidos_a_reintentar

    conn.execute(
        "INSERT INTO emails_log (to_addr, subject, template_key, alquiler_id, status, provider) "
        "VALUES ('a@test.com','x','recordatorio_retiro', %s, 'failed', 'test')",
        (P_OTRO_EVENTO,),
    )
    conn.commit()
    candidatos = _pedidos_a_reintentar(conn, ["pedido_creado_cliente", "pedido_creado"])
    assert P_OTRO_EVENTO not in candidatos


def test_reintentar_fallidos_llama_notificar_pedido_para_el_candidato(conn, monkeypatch):
    """End-to-end: `reintentar_fallidos` encuentra el pedido y despacha por la
    puerta única `notificar_pedido` (mockeada acá — no probamos el envío real,
    solo que el job orquesta bien)."""
    import jobs.reintentar_comunicacion as job

    conn.execute(
        "INSERT INTO emails_log (to_addr, subject, template_key, alquiler_id, status, provider) "
        "VALUES ('a@test.com','x','pedido_creado_cliente', %s, 'failed', 'test')",
        (P_SOLO_FALLIDO,),
    )
    conn.commit()

    llamadas = []
    monkeypatch.setattr(
        job, "notificar_pedido",
        lambda evento_key, pedido, ctx=None: llamadas.append((evento_key, pedido["id"])),
    )
    resumen = job.reintentar_fallidos(conn)
    assert ("pedido_creado", P_SOLO_FALLIDO) in llamadas
    assert resumen["pedido_creado"]["candidatos"] >= 1
    assert resumen["pedido_creado"]["reintentados"] >= 1
