"""Deadlock real bajo concurrencia entre 2 turnos del Estudio EMBEBIDOS
(#1308) del MISMO pedido — candado permanente para el fix ya shippeado en
`routes/alquileres/turnos_estudio.py::_reintentar_ante_deadlock`, que nunca
había quedado testeado: 2+ turnos del mismo pedido editados a la vez (el caso
real: el descuento COMBINADO de "Turnos del Estudio" dispara un PATCH por
turno desde el mismo cambio del padre) — cada uno actualiza su propio ítem
centinela (lock de fila que se sostiene hasta el commit) y LUEGO, dentro de
`_recalcular_total_pedido`, relee y actualiza el subtotal de **todos** los
ítems del pedido — incluido el del OTRO turno. Si ambos llegan a esa segunda
parte a la vez, cada uno termina esperando el ítem que el otro ya tiene
lockeado desde antes → espera circular → `DeadlockDetected`.

**Determinístico, no probabilístico** (mismo criterio que
`test_pedido_concurrencia_db.py`/`test_reportes_cierres_db.py::test_lock_
serializa_cerrar_mes_concurrente`: "no se apuesta a que la carrera se solape
por suerte"). Un `Barrier`/`Event` que solo sincroniza el ARRANQUE de 2 hilos
NO alcanza acá — confirmado en la práctica: sobre Postgres local (latencia
mínima), las 2 llamadas completas corren tan rápido que rara vez se solapan
en la ventana exacta que hace falta, aunque arranquen "a la vez". Por eso se
monkeypatchea `services.alquileres.commands.items._recalcular_total_pedido`
(el punto exacto donde cada turno pide subir a FOR UPDATE) para forzar la
sincronización — sin tocar qué locks toma ni en qué orden (eso lo decide el
código real, intacto); el patch solo INSERTA una pausa (vía `Barrier`) antes
de delegar en la función original, así los DOS llegan ahí YA con su propio
ítem lockeado, listos para chocar. Se llama a la función NÚCLEO directo
(`editar_turno_embebido`, sin el wrapper de retry) — el objetivo de este test
es probar que el MECANISMO (el deadlock en sí) es real y reproducible; que el
wrapper lo recupera correctamente lo cubre el 2do test, más abajo, con un
fake que no toca la base.

**Nota de alcance:** el hallazgo de auditoría de un deadlock ADYACENTE entre
un turno y `_apply_pedido_datos`/`_apply_pedido_items` (editar "Alquiler de
equipos"/los datos del MISMO pedido en paralelo — mismo `pedido_id`
compartido) tiene el mismo fix (`_reintentar_ante_deadlock` en
`routes/alquileres/pedidos.py`, mismo patrón, cero costo en el camino feliz),
pero el mecanismo exacto que lo dispara resultó más sutil de lo esperado al
intentar reproducirlo determinísticamente acá (`_apply_pedido_datos` no
siempre deja el lock en el estado que un primer análisis asumía) — no se
incluye un test determinístico de ESE caso en esta pasada por no poder
confirmarlo con la misma certeza que el de acá; el fix igual queda aplicado
como defensa en profundidad (costo cero en el camino feliz, mismo patrón ya
probado). Ver `docs/DECISIONES.md` de esta fecha para el detalle.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_turno_estudio_deadlock_db.py -v -m integration
"""
import os
import threading
from urllib.parse import urlparse

import pytest
import psycopg.errors
from fastapi import HTTPException

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

# Ids altos dedicados (bloque 9_491_xxx, sin uso en otros *_db.py).
CLIENTE_ID = 9_491_001
PEDIDO_ID = 9_491_020


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (PEDIDO_ID,))
    conn.execute("DELETE FROM alquiler_turnos_estudio WHERE pedido_id = %s", (PEDIDO_ID,))
    conn.execute("DELETE FROM alquileres WHERE id = %s", (PEDIDO_ID,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


@pytest.fixture
def setup(monkeypatch):
    from database import get_db, init_db

    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Deadlock','Test','deadlock-turno-datos@test.com','+5491100000094')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Deadlock test','confirmado','diaria','2033-05-10','2033-05-13',0)",
            (PEDIDO_ID, CLIENTE_ID),
        )
        conn.commit()
        yield
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def _agregar_turno(fecha, start, horas) -> int:
    """Crea un turno embebido en `PEDIDO_ID` llamando al endpoint REAL (mismo
    criterio del archivo: nada de SQL a mano para lo que se está auditando).
    Devuelve el id del turno nuevo."""
    from starlette.requests import Request
    from routes.alquileres.turnos_estudio import agregar_turno_estudio, TurnoEstudioCreate

    req = Request({"type": "http", "method": "POST", "path": "/api/alquileres/x/turnos-estudio",
                   "headers": [], "client": ("127.0.0.1", 0)})
    pedido = agregar_turno_estudio(PEDIDO_ID, TurnoEstudioCreate(fecha=fecha, start=start, horas=horas), req)
    return max(pedido["turnos_estudio_embebidos"], key=lambda t: t["id"])["id"]


def test_deadlock_turno_vs_turno_reproducible(setup, monkeypatch):
    """2 turnos del MISMO pedido editados a la vez: ambos insertan sus propios
    ítems (KEY SHARE implícito sobre `alquileres`) y SOLO DESPUÉS de que los
    dos terminaron de insertar, se los deja avanzar juntos a pedir el upgrade
    a FOR UPDATE — la ventana exacta que produce el deadlock simétrico.
    `contador`/`lock` hacen que la pausa sea de un solo uso: si algún lado
    reintentara (no aplica acá, se llama al núcleo sin retry), una 3ª llamada
    no se quedaría esperando un 2do compañero que no llega."""
    import services.alquileres.commands.items as items_mod
    from services.estudio.commands.reserva import editar_turno_embebido
    from database import get_db

    turno_a = _agregar_turno("2033-05-10", "10:00", 3)
    turno_b = _agregar_turno("2033-05-11", "10:00", 2)

    original = items_mod._recalcular_total_pedido
    barrera = threading.Barrier(2)
    contador = {"n": 0}
    contador_lock = threading.Lock()

    def _pausado(conn, pedido_id):
        with contador_lock:
            usar_barrera = contador["n"] < 2
            contador["n"] += 1
        if usar_barrera:
            barrera.wait(timeout=5)
        return original(conn, pedido_id)

    monkeypatch.setattr(items_mod, "_recalcular_total_pedido", _pausado)

    resultados: dict[str, str] = {}
    errores: dict[str, Exception] = {}

    def _editar(nombre, turno_id, pct):
        conn = None
        try:
            conn = get_db()
            editar_turno_embebido(conn, turno_id, descuento_pct=pct, descuento_manual_tipo="pct")
            conn.commit()
            resultados[nombre] = "ok"
        except psycopg.errors.DeadlockDetected:
            resultados[nombre] = "deadlock"
            conn.rollback()
        except Exception as e:  # noqa: BLE001 — clasificado en el assert de abajo
            errores[nombre] = e
        finally:
            if conn is not None:
                conn.close()

    ta = threading.Thread(target=_editar, args=("A", turno_a, 10.0))
    tb = threading.Thread(target=_editar, args=("B", turno_b, 20.0))
    ta.start()
    tb.start()
    ta.join(timeout=15)
    tb.join(timeout=15)

    assert not ta.is_alive() and not tb.is_alive(), "deadlock del propio test: algún hilo no terminó"
    assert not errores, f"excepciones inesperadas (no DeadlockDetected): {errores}"
    assert set(resultados.values()) == {"ok", "deadlock"}, (
        f"esperaba que UNO de los dos chocara con DeadlockDetected y el otro completara "
        f"ok (la precondición que hace necesario el retry) — resultados: {resultados}"
    )


def test_reintentar_ante_deadlock_reintenta_y_da_503_tras_agotar():
    """Unit puro (sin Postgres): confirma que las 2 copias de
    `_reintentar_ante_deadlock` (`turnos_estudio.py`/`pedidos.py`, duplicadas
    a propósito — ver sus docstrings) reintentan ante `DeadlockDetected` y,
    agotados los intentos, tiran 503 — nunca dejan escapar la excepción cruda
    de psycopg ni devuelven éxito con datos a medio escribir."""
    from routes.alquileres.turnos_estudio import _reintentar_ante_deadlock as retry_turnos
    from routes.alquileres.pedidos import _reintentar_ante_deadlock as retry_pedidos

    for retry_fn, nombre in [(retry_turnos, "turnos_estudio"), (retry_pedidos, "pedidos")]:
        llamadas = {"n": 0}

        def _siempre_falla():
            llamadas["n"] += 1
            raise psycopg.errors.DeadlockDetected("boom")

        with pytest.raises(HTTPException) as exc_info:
            retry_fn(_siempre_falla, intentos=3)
        assert exc_info.value.status_code == 503, nombre
        assert llamadas["n"] == 3, f"{nombre}: esperaba exactamente 3 intentos, hubo {llamadas['n']}"

        llamadas2 = {"n": 0}

        def _falla_2_veces_luego_ok():
            llamadas2["n"] += 1
            if llamadas2["n"] < 3:
                raise psycopg.errors.DeadlockDetected("boom")
            return "resultado ok"

        resultado = retry_fn(_falla_2_veces_luego_ok, intentos=5)
        assert resultado == "resultado ok", nombre
        assert llamadas2["n"] == 3, nombre
