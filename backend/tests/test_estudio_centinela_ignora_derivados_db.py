"""Bug real reportado por el dueño (pedido #445, taller "Workshop Dirección de
Arte — agosto 2026"): `_centinela_libre` contaba CUALQUIER `alquiler_items`
sobre el centinela del Estudio con estado reservado que solapara la ventana —
sin filtrar `alquileres.tipo`. Un pedido `tipo='taller'` guarda en
`fecha_desde`/`fecha_hasta` el MES CALENDARIO completo de la edición
(`_regenerar_pedidos_taller`, clampeado — ver `services/talleres/commands/
economia.py`), no la franja real de las clases (esa vive en `clases_taller`).
Resultado: un taller confirmado con `usa_estudio` bloqueaba el espacio los 7
días corridos del rango mensual, aunque el taller real fueran 2 clases de 4h
puntuales — el bloqueo REAL de esas clases ya lo hace `_taller_bloqueante`
(que sí lee `clases_taller` con fecha+hora exactas), corrido ANTES en
`_estudio_disponible`. Mismo problema, más benigno, para `estudio_fijo`
(guarda solo la primera ocurrencia semanal del mes) — su bloqueo real ya lo
hace `_slot_bloqueante`.

Este archivo prueba, contra Postgres REAL, que:
1. Un pedido de TALLER con rango mensual ancho NO bloquea una reserva real del
   estudio en una fecha/hora que no coincide con ninguna clase real.
2. Un pedido ESTUDIO_FIJO tampoco bloquea (mismo mecanismo).
3. Un pedido de ESTUDIO real (`tipo='estudio'`) SIGUE bloqueando — no se
   perdió la protección real entre turnos por hora (regresión).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://tincho@localhost/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estudio_centinela_ignora_derivados_db.py -v -m integration
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

PEDIDO_TALLER = 9_497_101      # rango mensual ancho, como genera _regenerar_pedidos_taller
PEDIDO_ESTUDIO_FIJO = 9_497_102  # una sola ocurrencia semanal, como genera _regenerar_pedidos_slot
PEDIDO_ESTUDIO_REAL = 9_497_103  # turno real por hora

# Rango del "mes" del taller: todo agosto — el mismo shape que economia.py
# clampea (1° del mes a último día). La franja de prueba (15 ago, 10-12hs)
# cae DENTRO de este rango pero no coincide con ninguna clase real.
FD_TALLER, FH_TALLER = "2026-08-01T00:00:00", "2026-08-31T00:00:00"
FD_PRUEBA, FH_PRUEBA = "2026-08-15T10:00:00", "2026-08-15T12:00:00"

FD_FIJO, FH_FIJO = "2026-08-01T15:00:00", "2026-08-01T19:00:00"

FD_REAL, FH_REAL = "2026-08-15T10:00:00", "2026-08-15T12:00:00"


def _limpiar(conn):
    ids = (PEDIDO_TALLER, PEDIDO_ESTUDIO_FIJO, PEDIDO_ESTUDIO_REAL)
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN (%s,%s,%s)", ids)
    conn.execute("DELETE FROM alquileres WHERE id IN (%s,%s,%s)", ids)


@pytest.fixture
def centinela_id():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        row = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()
        assert row and row["equipo_id"], "el seed de init_db() debería crear el centinela"
        conn.commit()
        yield row["equipo_id"]
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def _insertar_pedido(conn, pedido_id, tipo, fecha_desde, fecha_hasta, centinela_id, monto=50000):
    conn.execute(
        "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total) "
        "VALUES (%s, %s, 'confirmado', %s, %s, %s, %s)",
        (pedido_id, f"Test {tipo}", tipo, fecha_desde, fecha_hasta, monto),
    )
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
        "VALUES (%s, %s, 1, %s, %s, 'fijo')",
        (pedido_id, centinela_id, monto, monto),
    )


def test_pedido_de_taller_con_rango_mensual_no_bloquea_el_centinela(centinela_id):
    """El bug exacto del reporte: un pedido tipo='taller' con fecha_desde/hasta
    = todo agosto (como genera _regenerar_pedidos_taller) NO debe contar como
    ocupación del espacio para una hora cualquiera dentro de ese mes."""
    from database import get_db, to_datetime
    from services.estudio.queries.disponibilidad import _centinela_libre

    conn = get_db()
    try:
        _insertar_pedido(conn, PEDIDO_TALLER, "taller", FD_TALLER, FH_TALLER, centinela_id)
        conn.commit()

        libre = _centinela_libre(
            conn, centinela_id, to_datetime(FD_PRUEBA), to_datetime(FH_PRUEBA), buffer_horas=0,
        )
        assert libre is True, (
            "el pedido de taller (rango mensual) no debería bloquear una hora "
            "cualquiera del mes — su bloqueo real es _taller_bloqueante, no esto"
        )
    finally:
        conn.close()


def test_pedido_estudio_fijo_no_bloquea_el_centinela_fuera_de_su_franja(centinela_id):
    """Mismo mecanismo para estudio_fijo: no debe contar en _centinela_libre —
    su bloqueo real es _slot_bloqueante (regla de día de semana)."""
    from database import get_db, to_datetime
    from services.estudio.queries.disponibilidad import _centinela_libre

    conn = get_db()
    try:
        _insertar_pedido(conn, PEDIDO_ESTUDIO_FIJO, "estudio_fijo", FD_FIJO, FH_FIJO, centinela_id)
        conn.commit()

        # Franja distinta a la del pedido fijo (15-19hs) pero mismo día — si el
        # filtro no funcionara, igual no chocaría (no solapan); probamos la
        # franja EXACTA del pedido fijo para confirmar que de verdad se ignora.
        libre = _centinela_libre(
            conn, centinela_id, to_datetime(FD_FIJO), to_datetime(FH_FIJO), buffer_horas=0,
        )
        assert libre is True
    finally:
        conn.close()


def test_pedido_estudio_real_sigue_bloqueando_el_centinela(centinela_id):
    """Regresión: un turno REAL (tipo='estudio') tiene que seguir bloqueando
    otro turno que se le solape — no perdimos la protección real entre
    reservas por hora."""
    from database import get_db, to_datetime
    from services.estudio.queries.disponibilidad import _centinela_libre

    conn = get_db()
    try:
        _insertar_pedido(conn, PEDIDO_ESTUDIO_REAL, "estudio", FD_REAL, FH_REAL, centinela_id)
        conn.commit()

        libre = _centinela_libre(
            conn, centinela_id, to_datetime(FD_REAL), to_datetime(FH_REAL), buffer_horas=0,
        )
        assert libre is False, "un turno real del estudio sigue teniendo que bloquear su franja"
    finally:
        conn.close()


def test_estudio_disponible_end_to_end_ignora_el_rango_mensual_del_taller(centinela_id):
    """El engine completo (_estudio_disponible: slot → taller → centinela) da
    libre para una hora que cae dentro del rango mensual de un pedido de
    taller pero no coincide con ninguna clase real (clases_taller vacío en
    este test) — antes del fix, el paso 'centinela' rechazaba esto solo."""
    from database import get_db, to_datetime
    from services.estudio.queries.disponibilidad import _estudio_disponible

    conn = get_db()
    try:
        _insertar_pedido(conn, PEDIDO_TALLER, "taller", FD_TALLER, FH_TALLER, centinela_id)
        conn.commit()

        estudio = conn.execute("SELECT * FROM estudio WHERE id=1").fetchone()
        libre, motivo = _estudio_disponible(
            conn, estudio, to_datetime(FD_PRUEBA), to_datetime(FH_PRUEBA),
        )
        assert libre is True, f"debería estar libre, dio: {motivo}"
        assert motivo is None
    finally:
        conn.close()
