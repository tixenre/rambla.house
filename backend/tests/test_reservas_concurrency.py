"""Paso 0 — Concurrencia del gate de reservas (`_check_stock`).

El núcleo sagrado evita el overbooking con `SELECT ... FOR UPDATE`: bloquea la
fila del equipo durante la validación para que dos confirmaciones simultáneas no
agarren la misma última unidad. La suite existente (`test_stock_validation.py`)
prueba la LÓGICA de agregación, pero NO la concurrencia. Estos tests cubren ese
hueco a nivel unit, contra el `_check_stock` ACTUAL.

Limitación honesta: un `FakeConn` no es Postgres. Acá se simula el lock con un
`threading.Lock` por equipo para probar que (a) el `FOR UPDATE` serializa, (b)
`_check_stock` lee las reservas DESPUÉS de tomar el lock, y (c) en una carrera por
la última unidad exactamente una confirmación pasa. La prueba de la serialización
REAL de Postgres vive en `test_reservas_concurrency_db.py` (integration, opt-in).
"""
import threading

import pytest

from reservas import validar_stock as _check_stock

pytestmark = pytest.mark.unit


# ── Fakes con locking ───────────────────────────────────────────────────────

class FakeRow(dict):
    pass


class FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class World:
    """Estado compartido entre conexiones concurrentes.

    - equipos: dict[id, {nombre, cantidad}]
    - reservas: dict[(equipo_id, pedido_id), cantidad]  → reservas COMMITEADAS
    - locks: un threading.Lock por equipo, que emula `FOR UPDATE` (se toma en el
      SELECT ... FOR UPDATE y se libera en commit/rollback/close).
    """

    def __init__(self, equipos, buffer_horas=0):
        self.equipos = equipos
        self.reservas: dict[tuple, int] = {}
        self.buffer_horas = buffer_horas
        # Pre-creamos los locks (defaultdict no es seguro para crear bajo carrera).
        self.locks = {eq_id: threading.Lock() for eq_id in equipos}


class LockingFakeConn:
    """Conn que stubea las queries de `_check_stock` y emula el row-lock.

    `pedido_items`: dict[pedido_id, list[item]] con keys equipo_id/cantidad/nombre/stock_total.
    Sin kits en estos tests (la expansión ya está cubierta en test_stock_validation).
    """

    def __init__(self, world: World, pedido_items):
        self.world = world
        self.pedido_items = pedido_items
        self._held: list[int] = []          # equipos cuyo lock tenemos tomado
        self._pending: dict[tuple, int] = {} # reservas staged, visibles recién en commit
        self.log: list = []                  # traza de queries (orden), para asserts

    def execute(self, sql, params=()):
        s_up = " ".join(sql.split()).upper()

        if "FROM APP_SETTINGS WHERE KEY = %S" in s_up:
            self.log.append("buffer")
            return FakeCursor([FakeRow(value=str(self.world.buffer_horas))])

        # Mantenimiento batcheado (#626): IN + GROUP BY; sin mantenimiento en
        # estos tests → sin filas (el gate default-ea a 0).
        if "FROM EQUIPO_MANTENIMIENTO" in s_up:
            self.log.append(("mant", tuple(params[:-2])))
            return FakeCursor([])

        if s_up.startswith("SELECT EQUIPO_ID, CANTIDAD FROM ALQUILER_ITEMS WHERE PEDIDO_ID = %S"):
            self.log.append("items")
            pid = params[0]
            return FakeCursor([FakeRow(r) for r in self.pedido_items.get(pid, [])])

        # Grafo de composición (componentes_de / parientes_de) — sin kits en estos tests.
        if s_up.startswith("SELECT EQUIPO_ID, COMPONENTE_ID, CANTIDAD") and "FROM KIT_COMPONENTES" in s_up:
            self.log.append("kit_expand")
            return FakeCursor([])

        # Nombres para los mensajes.
        if s_up.startswith("SELECT ID, NOMBRE FROM EQUIPOS WHERE ID IN"):
            self.log.append("nombres")
            return FakeCursor([
                FakeRow(id=i, nombre=e["nombre"]) for i, e in self.world.equipos.items()
            ])

        # ── El lock: emula SELECT ... FOR UPDATE ──
        if "SELECT CANTIDAD FROM EQUIPOS WHERE ID = %S FOR UPDATE" in s_up:
            eq_id = params[0]
            self.world.locks[eq_id].acquire()   # BLOQUEA si otra conn lo tiene
            self._held.append(eq_id)
            self.log.append(("for_update", eq_id))
            eq = self.world.equipos.get(eq_id)
            if not eq:
                return FakeCursor([])
            return FakeCursor([FakeRow(cantidad=eq["cantidad"])])

        # Reservas directas — se leen del estado COMMITEADO (con los locks ya
        # tomados en el Paso 1 del gate). Batcheado (#626): IN + GROUP BY,
        # params = (*equipo_ids, excl, fh_buf, fd_buf). Se loguea por equipo para
        # que el test de "lee reservas DESPUÉS del lock" siga verificando el orden.
        # Substrings (no un match contiguo): #1308 sumó un LEFT JOIN
        # alquiler_turnos_estudio entre el JOIN a alquileres y el WHERE.
        if "FROM ALQUILER_ITEMS PI2" in s_up and "WHERE PI2.EQUIPO_ID IN" in s_up:
            eq_ids, excl = params[:-3], params[-3]
            rows = []
            for eq_id in eq_ids:
                self.log.append(("reservado_directo", eq_id))
                total = sum(
                    c for (e, p), c in self.world.reservas.items()
                    if e == eq_id and p != excl
                )
                rows.append(FakeRow({0: eq_id, 1: total}))
            return FakeCursor(rows)

        return FakeCursor([])

    # Simula el INSERT de la reserva (se hace bajo el lock, antes del commit).
    def reservar(self, equipo_id, pedido_id, cantidad):
        self._pending[(equipo_id, pedido_id)] = cantidad

    def commit(self):
        self.world.reservas.update(self._pending)  # visible para los demás...
        self._pending.clear()
        self._release()                            # ...recién al soltar el lock

    def rollback(self):
        self._pending.clear()
        self._release()

    def close(self):
        self._release()

    def _release(self):
        for eq_id in self._held:
            self.world.locks[eq_id].release()
        self._held.clear()


# ── Tests ───────────────────────────────────────────────────────────────────

def test_for_update_es_exclusivo():
    """Mientras una conn tiene el lock del equipo (FOR UPDATE sin commit), otra
    conn que pide el mismo lock queda bloqueada hasta que la primera commitea."""
    world = World({1: {"nombre": "Cámara", "cantidad": 1}})
    a = LockingFakeConn(world, {})
    b = LockingFakeConn(world, {})

    a.execute("SELECT cantidad FROM equipos WHERE id = %s FOR UPDATE", (1,))

    arranco_b = threading.Event()

    def tomar_b():
        arranco_b.set()
        b.execute("SELECT cantidad FROM equipos WHERE id = %s FOR UPDATE", (1,))
        b.commit()

    t = threading.Thread(target=tomar_b)
    t.start()
    arranco_b.wait()
    t.join(timeout=0.3)
    assert t.is_alive(), "B debería estar bloqueada esperando el lock de A"

    a.commit()                  # libera el lock
    t.join(timeout=2.0)
    assert not t.is_alive(), "B debería haber tomado el lock tras el commit de A"


def test_check_stock_lee_reservas_bajo_el_lock():
    """`_check_stock` toma el FOR UPDATE del equipo ANTES de leer las reservas
    de ese equipo — así la lectura ocurre con la fila bloqueada."""
    world = World({1: {"nombre": "Cámara", "cantidad": 1}})
    conn = LockingFakeConn(
        world,
        {7: [{"equipo_id": 1, "cantidad": 1, "nombre": "Cámara", "stock_total": 1}]},
    )

    problemas = _check_stock(conn, 7, "2026-06-01T08:00", "2026-06-02T20:00")
    assert problemas == []

    i_lock = conn.log.index(("for_update", 1))
    i_read = conn.log.index(("reservado_directo", 1))
    assert i_lock < i_read, f"se leyó reservas antes de lockear: {conn.log}"


def test_dos_confirmaciones_ultima_unidad_solo_una_pasa():
    """Carrera real por la única unidad: dos pedidos distintos validan + reservan
    a la vez. El FOR UPDATE serializa → exactamente uno confirma sin problemas."""
    world = World({1: {"nombre": "Cámara", "cantidad": 1}})
    items = {
        101: [{"equipo_id": 1, "cantidad": 1, "nombre": "Cámara", "stock_total": 1}],
        102: [{"equipo_id": 1, "cantidad": 1, "nombre": "Cámara", "stock_total": 1}],
    }
    a = LockingFakeConn(world, items)
    b = LockingFakeConn(world, items)

    resultados: dict[int, list] = {}

    def confirmar(conn, pedido_id):
        try:
            problemas = _check_stock(conn, pedido_id, "2026-06-01T08:00", "2026-06-02T20:00")
            if not problemas:
                conn.reservar(1, pedido_id, 1)  # "INSERT" de la reserva, bajo el lock
            resultados[pedido_id] = problemas
            conn.commit()
        finally:
            conn.close()

    ta = threading.Thread(target=confirmar, args=(a, 101))
    tb = threading.Thread(target=confirmar, args=(b, 102))
    ta.start()
    tb.start()
    ta.join(timeout=5.0)
    tb.join(timeout=5.0)
    assert not ta.is_alive() and not tb.is_alive(), "deadlock: alguna confirmación no terminó"

    ok = [pid for pid, probs in resultados.items() if not probs]
    fallo = [pid for pid, probs in resultados.items() if probs]
    assert len(ok) == 1, f"esperaba exactamente 1 confirmación OK, hubo {len(ok)}: {resultados}"
    assert len(fallo) == 1
    # El que falló debe reportar el equipo sin stock.
    assert any("Cámara" in p for p in resultados[fallo[0]])
