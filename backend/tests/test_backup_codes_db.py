"""Códigos de respaldo del 2º factor admin contra Postgres real
(`auth/backup_codes.py`) — el consumo atómico (`UPDATE...RETURNING`) es lo
que el `FakeConn` de `test_backup_codes.py` no puede probar de verdad: acá se
confirma con DOS conexiones reales que el MISMO código no se puede consumir
dos veces, ni siquiera si ambos requests llegan casi a la vez.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_backup_codes_db.py -v -m integration
"""
import os
import threading
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

# admin_backup_codes.owner_email no tiene FK (la identidad admin es un email de
# ADMIN_EMAILS, no una fila de `clientes`) — el test no necesita sembrar nada
# más que sus propias filas, identificadas por un email dedicado.
EMAIL = "backup-codes-test-9495@rambla.local"
EMAIL_OTRO = "backup-codes-test-9495-otro@rambla.local"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM admin_backup_codes WHERE owner_email IN (%s, %s)", (EMAIL, EMAIL_OTRO)
    )


@pytest.fixture
def setup():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.commit()
    finally:
        conn.close()

    yield

    conn = get_db()
    try:
        _limpiar(conn)
        conn.commit()
    finally:
        conn.close()


class TestGenerarCodigos:
    def test_genera_diez_y_son_verificables(self, setup):
        import auth.backup_codes as bc

        codigos = bc.generar_codigos(EMAIL)
        assert len(codigos) == 10
        assert bc.contar_disponibles(EMAIL) == 10
        for c in codigos:
            # No los consume (verificar_y_consumir en un connection distinto de
            # solo-lectura no existe acá — se confirma vía contar_disponibles
            # antes/después en el test de consumo, más abajo).
            assert len(c.split("-")) == 2

    def test_regenerar_invalida_el_set_viejo(self, setup):
        import auth.backup_codes as bc

        primeros = bc.generar_codigos(EMAIL)
        segundos = bc.generar_codigos(EMAIL)
        assert bc.contar_disponibles(EMAIL) == 10  # no se acumulan, se reemplazan
        # Ninguno de los códigos viejos sigue siendo válido.
        for c in primeros:
            assert bc.verificar_y_consumir(EMAIL, c) is False
        # Los nuevos sí.
        assert bc.verificar_y_consumir(EMAIL, segundos[0]) is True

    def test_no_mezcla_dos_cuentas(self, setup):
        import auth.backup_codes as bc

        bc.generar_codigos(EMAIL)
        bc.generar_codigos(EMAIL_OTRO)
        assert bc.contar_disponibles(EMAIL) == 10
        assert bc.contar_disponibles(EMAIL_OTRO) == 10
        # Regenerar la cuenta OTRA no toca los códigos de EMAIL.
        bc.generar_codigos(EMAIL_OTRO)
        assert bc.contar_disponibles(EMAIL) == 10


class TestVerificarYConsumir:
    def test_consume_una_sola_vez(self, setup):
        import auth.backup_codes as bc

        codigos = bc.generar_codigos(EMAIL)
        assert bc.verificar_y_consumir(EMAIL, codigos[0]) is True
        assert bc.contar_disponibles(EMAIL) == 9
        # El mismo código de nuevo → False (ya usado).
        assert bc.verificar_y_consumir(EMAIL, codigos[0]) is False
        assert bc.contar_disponibles(EMAIL) == 9

    def test_case_insensitive(self, setup):
        import auth.backup_codes as bc

        codigos = bc.generar_codigos(EMAIL)
        assert bc.verificar_y_consumir(EMAIL, codigos[0].lower()) is True

    def test_codigo_inexistente_false(self, setup):
        import auth.backup_codes as bc

        bc.generar_codigos(EMAIL)
        assert bc.verificar_y_consumir(EMAIL, "ZZZZZ-ZZZZZ") is False

    def test_consumo_concurrente_del_mismo_codigo_solo_uno_gana(self, setup):
        """Dos conexiones reales, la MISMA carrera que dos requests de login
        casi simultáneos con el mismo código de respaldo — el atómico
        `UPDATE ... WHERE used_at IS NULL RETURNING id` tiene que garantizar
        que solo uno de los dos lo consuma, nunca los dos."""
        import auth.backup_codes as bc

        codigos = bc.generar_codigos(EMAIL)
        code = codigos[0]

        resultados = []
        barrera = threading.Barrier(2)

        def _intentar():
            barrera.wait()  # ambos threads pegan al mismo tiempo, no en fila
            resultados.append(bc.verificar_y_consumir(EMAIL, code))

        t1 = threading.Thread(target=_intentar)
        t2 = threading.Thread(target=_intentar)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert sorted(resultados) == [False, True]
        assert bc.contar_disponibles(EMAIL) == 9
