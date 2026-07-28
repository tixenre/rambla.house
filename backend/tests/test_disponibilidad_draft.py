"""`calcular_disponibilidad_draft` — disponibilidad consciente del draft del editor.

El bug que cierra: el editor de pedidos calculaba "X libres" restando SOLO la
cantidad directa de cada línea (`libres - cantidad`), sin expandir los kits del
MISMO draft. Con Maffer stock 5 y un pedido de 3× Maffer + 1× Brazo Mágico (kit
con 2× Maffer), el badge decía "2 libres" cuando quedan 0 (5 − 3 − 2). Ahora el
backend resta TODO el draft con la MISMA expansión recursiva del gate
(`expandir_demanda`, solo_esenciales=False) y devuelve valores CON SIGNO.

Mismo fake conn que `test_catalogo_disponibilidad.py` (stubea las queries del
pipeline compartido `_libres_crudos` + el grafo de composición).
"""
import pytest

from reservas import calcular_disponibilidad, calcular_disponibilidad_draft

pytestmark = pytest.mark.unit


class FakeRow(dict):
    pass


class FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class DispFakeConn:
    """Stubea las queries de `_libres_crudos` + `componentes_de` (ver
    `test_catalogo_disponibilidad.DispFakeConn`, mismo contrato)."""

    def __init__(self, equipos, reservados=None, kit=None,
                 mantenimiento=None, buffer_horas=0):
        self.equipos = equipos
        self.reservados = reservados or {}
        self.kit = kit or {}
        self.mantenimiento = mantenimiento or {}
        self.buffer_horas = buffer_horas

    def execute(self, sql, params=()):
        s = " ".join(sql.split()).upper()

        if "FROM APP_SETTINGS WHERE KEY = %S" in s:
            return FakeCursor([FakeRow(value=str(self.buffer_horas))])

        if s.startswith("SELECT ID, CANTIDAD FROM EQUIPOS"):
            return FakeCursor([
                FakeRow(id=eid, cantidad=data["cantidad"])
                for eid, data in self.equipos.items()
            ])

        if "FROM ALQUILER_ITEMS PI JOIN ALQUILERES P" in s and "GROUP BY PI.EQUIPO_ID" in s:
            return FakeCursor([
                FakeRow(eid=eid, cant=cant) for eid, cant in self.reservados.items()
            ])

        if s.startswith("SELECT EQUIPO_ID, COMPONENTE_ID, CANTIDAD") and "FROM KIT_COMPONENTES" in s:
            return FakeCursor([
                FakeRow(equipo_id=eid, componente_id=cid, cantidad=q, esencial=ese)
                for eid, comps in self.kit.items()
                for (cid, q, ese) in comps
            ])

        if "FROM EQUIPO_MANTENIMIENTO" in s and "AS BLOQUEADO" in s:
            return FakeCursor([
                FakeRow(equipo_id=eid, bloqueado=n)
                for eid, n in self.mantenimiento.items()
            ])

        return FakeCursor([])


D, H = "2026-08-10", "2026-08-12"

# El escenario del dueño: Maffer (hoja, stock 5), Brazo Mágico (kit, stock 1,
# receta 2× Maffer). Pedido/draft: 3× Maffer + 1× Brazo.
MAFFER, BRAZO = 214, 285


def _conn_escenario_kit(**kw):
    return DispFakeConn(
        equipos={MAFFER: {"cantidad": 5}, BRAZO: {"cantidad": 1}},
        kit={BRAZO: [(MAFFER, 2, True)]},
        **kw,
    )


def test_kit_del_draft_consume_sus_componentes():
    """EL BUG: 3× Maffer + 1× Brazo (2× Maffer) contra stock 5 → 0 libres, no 2."""
    conn = _conn_escenario_kit()
    out = calcular_disponibilidad_draft(conn, D, H, {MAFFER: 3, BRAZO: 1})
    assert out[str(MAFFER)] == 0  # 5 − 3 directas − 2 vía Brazo
    assert out[str(BRAZO)] == 0   # stock propio 1 − 1 del draft


def test_faltante_devuelve_negativo_con_signo():
    """Subir Maffer a 4 (lo que el badge viejo '2 libres' invitaba a hacer):
    el mapa dice cuántas unidades FALTAN, y el kit hereda el faltante de su hoja."""
    conn = _conn_escenario_kit()
    out = calcular_disponibilidad_draft(conn, D, H, {MAFFER: 4, BRAZO: 1})
    assert out[str(MAFFER)] == -1  # 5 − 4 − 2
    assert out[str(BRAZO)] == -1   # min(0 propio, ⌊−1/2⌋) — hereda el faltante


def test_draft_simple_sin_kits_no_cambia_la_cuenta():
    """Sin composición de por medio, es la misma resta de siempre."""
    conn = DispFakeConn(equipos={MAFFER: {"cantidad": 5}})
    out = calcular_disponibilidad_draft(conn, D, H, {MAFFER: 3})
    assert out[str(MAFFER)] == 2


def test_suma_reservas_de_otros_pedidos_y_mantenimiento():
    conn = _conn_escenario_kit(reservados={MAFFER: 1}, mantenimiento={MAFFER: 1})
    out = calcular_disponibilidad_draft(conn, D, H, {MAFFER: 1, BRAZO: 1})
    assert out[str(MAFFER)] == 0  # 5 − 1 reservada − 1 mant − 1 draft − 2 vía Brazo


def test_componente_best_effort_tambien_descuenta():
    """Paridad con el gate (solo_esenciales=False): un componente best-effort
    del draft TAMBIÉN consume stock — el gate es estricto y este número existe
    para predecirlo."""
    conn = DispFakeConn(
        equipos={MAFFER: {"cantidad": 5}, BRAZO: {"cantidad": 9}},
        kit={BRAZO: [(MAFFER, 2, False)]},  # esencial=False
    )
    out = calcular_disponibilidad_draft(conn, D, H, {BRAZO: 1})
    assert out[str(MAFFER)] == 3  # 5 − 2 vía Brazo (aunque sea best-effort)


def test_faltante_best_effort_burbujea_a_la_linea_del_kit():
    """H1 de la revisión adversarial: el gate expande ESTRICTO, así que en el
    camino draft la línea de un kit hereda también el faltante de una hoja
    best-effort (derivación con `incluir_best_effort=True`). Sin esto el badge
    del kit decía "libres" y el gate igual rechazaba — la misma mentira que el
    fix vino a matar. El camino clásico (C2, catálogo) NO cambia."""
    conn = DispFakeConn(
        equipos={MAFFER: {"cantidad": 1}, BRAZO: {"cantidad": 5}},
        kit={BRAZO: [(MAFFER, 1, False)]},  # esencial=False
    )
    out = calcular_disponibilidad_draft(conn, D, H, {BRAZO: 2})
    assert out[str(MAFFER)] == -1  # 1 − 2 vía Brazo
    assert out[str(BRAZO)] == -1   # hereda el faltante best-effort → hasOverstock
    # Clásico intacto: el best-effort no limita al kit en el catálogo (C2).
    assert calcular_disponibilidad(conn, D, H)[str(BRAZO)] == 5


def test_endpoint_llamado_directo_sin_items_va_al_camino_clasico():
    """`routes/cliente_portal/solicitudes.py` llama a `get_disponibilidad()`
    DIRECTO con 3 args posicionales: el default de `items` tiene que ser None
    REAL — un `Query(None)` de FastAPI es truthy, activaría el camino draft
    sin querer (hallazgo bloqueante de la revisión original)."""
    import inspect

    from routes.alquileres.disponibilidad import get_disponibilidad

    assert inspect.signature(get_disponibilidad).parameters["items"].default is None


def test_draft_vacio_equivale_al_calculo_clasico_clampeado():
    """Con draft vacío la única diferencia contra `calcular_disponibilidad` es
    el clamp: el clásico nunca baja de 0, el draft-aware conserva el signo."""
    conn = DispFakeConn(
        equipos={MAFFER: {"cantidad": 1}},
        reservados={MAFFER: 3},  # sobre-comprometido (dato legado)
    )
    assert calcular_disponibilidad(conn, D, H)[str(MAFFER)] == 0
    assert calcular_disponibilidad_draft(conn, D, H, {})[str(MAFFER)] == -2


def test_parser_del_route_suma_duplicados():
    """El parser del endpoint consolida sumando (como el gate, issue #102) —
    distinto del MAX de `/disponibilidad-dias` (bloqueo de calendario)."""
    from routes.alquileres.disponibilidad import _parse_items_draft

    assert _parse_items_draft("214:3,285:1,214:1") == {214: 4, 285: 1}
    assert _parse_items_draft("214") == {214: 1}          # sin cantidad → 1
    assert _parse_items_draft(" ") == {}
    assert _parse_items_draft("214:0") == {}              # qty 0 no aporta demanda


def test_parser_del_route_rechaza_basura():
    from fastapi import HTTPException

    from routes.alquileres.disponibilidad import _parse_items_draft

    with pytest.raises(HTTPException):
        _parse_items_draft("abc:1")
    with pytest.raises(HTTPException):
        _parse_items_draft("214:x")
