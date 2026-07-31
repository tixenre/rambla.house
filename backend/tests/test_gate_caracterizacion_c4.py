"""C4 #635 — caracterización del gate recursivo vs. el gate de 1 nivel.

Protocolo #626: la reescritura del gate (`validar_stock`) a expansión RECURSIVA no
debe cambiar la salida en los casos NO anidados (kits con componentes que son
hojas). Este test diferencial corre el gate nuevo y una IMPLEMENTACIÓN DE
REFERENCIA del comportamiento viejo (forward 1 nivel + backward directo + vía-kit
1 nivel + mantenimiento) sobre cientos de mundos aleatorios no anidados, y exige
salida IDÉNTICA (como conjunto — el gate nuevo lockea/reporta en orden de id,
`ORDER BY id`, mientras el viejo iba en orden de expansión; el CONTENIDO es igual).

Es la red que prueba "diff mínimo, solo en la expansión": misma conducta donde no
hay anidamiento; la corrección de los anidados vive en `test_reservas_nested_db.py`
y `test_stock_validation.py`.
"""
import random

import pytest

from reservas import validar_stock

pytestmark = pytest.mark.unit


class _Row(dict):
    pass


class _Cur:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _World:
    """Mundo NO anidado: hojas + kits que contienen SOLO hojas (1 nivel)."""

    def __init__(self, equipos, kit, reservas_directas, pedido_items, mantenimiento):
        self.equipos = equipos                  # {id: {nombre, cantidad}}
        self.kit = kit                          # {kit_id: [(hoja, q, True)]}
        self.reservas_directas = reservas_directas  # {equipo_id: int}
        self.pedido_items = pedido_items        # [{equipo_id, cantidad}]
        self.mantenimiento = mantenimiento      # {equipo_id: int}

    def execute(self, sql, params=()):
        s = " ".join(sql.split()).upper()
        if "FROM APP_SETTINGS WHERE KEY = %S" in s:
            return _Cur([_Row(value="0")])
        if "FROM EQUIPO_MANTENIMIENTO" in s:  # batcheado: (*equipo_ids, f_hasta, f_desde)
            eq_ids = params[:-2]
            return _Cur([_Row({0: e, 1: self.mantenimiento.get(e, 0)}) for e in eq_ids])
        if s.startswith("SELECT EQUIPO_ID, CANTIDAD FROM ALQUILER_ITEMS WHERE PEDIDO_ID = %S"):
            # `AND TURNO_ESTUDIO_ID IS NULL` (#1308 rediseño "turno como ítem",
            # Fase 1): un ítem de `pedido_items` puede llevar `turno_estudio_id`
            # (ver `test_gate_turno_embebido_c5.py`) — invisible para el gate
            # genérico, igual que en la query real. No-op para `_mundo_aleatorio`
            # de este archivo: nunca setea esa clave.
            return _Cur([
                _Row(r) for r in self.pedido_items if not r.get("turno_estudio_id")
            ])
        if s.startswith("SELECT EQUIPO_ID, COMPONENTE_ID, CANTIDAD") and "FROM KIT_COMPONENTES" in s:
            return _Cur([
                _Row(equipo_id=k, componente_id=c, cantidad=q, esencial=e)
                for k, comps in self.kit.items() for (c, q, e) in comps
            ])
        if s.startswith("SELECT ID, NOMBRE FROM EQUIPOS WHERE ID IN"):
            return _Cur([_Row(id=i, nombre=v["nombre"]) for i, v in self.equipos.items()])
        if "SELECT CANTIDAD FROM EQUIPOS WHERE ID = %S FOR UPDATE" in s:
            eq = self.equipos.get(params[0])
            return _Cur([_Row(cantidad=eq["cantidad"])] if eq else [])
        if ("FROM ALQUILER_ITEMS PI2" in s and "WHERE PI2.EQUIPO_ID IN" in s):
            # Substrings (no un solo `in` contiguo): #1308 rediseño "turno como
            # ítem" sumó un `LEFT JOIN alquiler_turnos_estudio` entre el JOIN a
            # `alquileres` y el `WHERE` — un match de una sola cadena larga se
            # habría roto con ese JOIN nuevo en el medio.
            eq_ids = params[:-3]  # (*equipo_ids, excl, fh_buf, fd_buf)
            return _Cur([_Row({0: e, 1: self.reservas_directas.get(e, 0)}) for e in eq_ids])
        return _Cur([])


def _gate_referencia(world: _World) -> set:
    """Comportamiento del gate VIEJO (1 nivel) — calculado directo, como referencia.

    forward 1 nivel: el item + sus componentes directos (ponderados).
    backward 1 nivel: reserva directa del nodo + Σ (kits que lo contienen × cant).
    """
    demanda: dict[int, int] = {}
    for it in world.pedido_items:
        e, q = it["equipo_id"], it["cantidad"]
        demanda[e] = demanda.get(e, 0) + q
        for (c, cq, _ese) in world.kit.get(e, []):
            demanda[c] = demanda.get(c, 0) + q * cq

    problemas = set()
    for eid, qty in demanda.items():
        eq = world.equipos[eid]  # garantizamos que existen
        directo = world.reservas_directas.get(eid, 0)
        via = sum(
            world.reservas_directas.get(kid, 0) * cq
            for kid, comps in world.kit.items()
            for (c, cq, _e) in comps
            if c == eid
        )
        mant = world.mantenimiento.get(eid, 0)
        disp = eq["cantidad"] - directo - via - mant
        if disp < qty:
            problemas.add(f"{eq['nombre']} (necesitás {qty}, disponible: {max(0, disp)})")
    return problemas


def _mundo_aleatorio(rng: random.Random) -> _World:
    # Hojas: ids 1..nhojas
    nhojas = rng.randint(1, 5)
    hojas = list(range(1, nhojas + 1))
    equipos = {h: {"nombre": f"eq{h}", "cantidad": rng.randint(0, 4)} for h in hojas}

    # Kits: ids 100.. cada uno con 1..3 hojas distintas (q 1..3), todas esenciales.
    nkits = rng.randint(0, 3)
    kit = {}
    for j in range(nkits):
        kid = 100 + j
        equipos[kid] = {"nombre": f"kit{kid}", "cantidad": rng.randint(0, 4)}
        comps = rng.sample(hojas, rng.randint(1, len(hojas)))
        kit[kid] = [(c, rng.randint(1, 3), True) for c in comps]

    todos = list(equipos.keys())
    # Reservas directas en cualquier equipo (hojas y kits).
    reservas = {e: rng.randint(0, 3) for e in todos if rng.random() < 0.5}
    # Mantenimiento solo en hojas (los kits no tienen mantenimiento físico propio
    # en datos reales, pero el gate lo soporta igual; mantenerlo en hojas alcanza).
    mant = {h: rng.randint(0, 2) for h in hojas if rng.random() < 0.3}
    # Pedido: 1..4 items de equipos al azar (puede repetir → consolidación).
    nit = rng.randint(1, 4)
    pedido = [{"equipo_id": rng.choice(todos), "cantidad": rng.randint(1, 3)} for _ in range(nit)]

    return _World(equipos, kit, reservas, pedido, mant)


@pytest.mark.parametrize("seed", range(300))
def test_gate_recursivo_identico_a_1_nivel_en_no_anidados(seed):
    rng = random.Random(seed)
    world = _mundo_aleatorio(rng)
    nuevo = set(validar_stock(world, 7, "2026-06-01", "2026-06-05"))
    referencia = _gate_referencia(world)
    assert nuevo == referencia, (
        f"seed={seed}: el gate recursivo difiere del de 1 nivel en un caso NO anidado.\n"
        f"  nuevo={sorted(nuevo)}\n  ref  ={sorted(referencia)}\n"
        f"  pedido={world.pedido_items}\n  kit={world.kit}\n"
        f"  reservas={world.reservas_directas}\n  mant={world.mantenimiento}\n"
        f"  equipos={world.equipos}"
    )
