"""Tests unitarios para `_regenerar_pedidos_taller` (routes/talleres.py).

Espeja `test_estudio.py::TestRegenerarPedidosSlot` (mismo patrón: fake conn
que graba INSERT/DELETE, sin Postgres real) — con un caso propio que el slot
no necesita: conservar un mes cuyo pedido tiene MÁS ítems que los que el
generador crearía (la línea de matrícula que el admin tipeó a mano).
"""

import re
from datetime import date, datetime

import pytest

pytestmark = pytest.mark.unit


class _ConnCM:
    """Mixin que da a los fakes el protocolo context-manager (`with get_db()`)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        close = getattr(self, "close", None)
        if close:
            close()
        return False


class _Cur:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


_INSERT_COLS_RE = re.compile(r"\(([^()]+)\)\s*VALUES\s*\(([^()]+)\)", re.IGNORECASE)


def _parse_insert(sql: str, params: tuple) -> dict:
    """Parsea un INSERT a {columna: valor} por NOMBRE (no por posición) — los
    2 ítems distintos (Estudio/equipos/placeholder) mandan columnas DISTINTAS."""
    m = _INSERT_COLS_RE.search(" ".join(sql.split()))
    cols = [c.strip() for c in m.group(1).split(",")]
    vals = [v.strip() for v in m.group(2).split(",")]
    it = iter(params)
    out = {}
    for col, raw in zip(cols, vals):
        if raw == "%s":
            out[col] = next(it)
        elif raw.upper() == "NULL":
            out[col] = None
        elif raw.startswith("'"):
            out[col] = raw.strip("'")
        else:
            out[col] = int(raw)
    return out


def _mes_offset_ym(n: int) -> tuple[int, int]:
    """(year, month) del mes actual + n meses — relativo a `hoy`, no hardcodeado."""
    from routes.estudio import _mes_actual_ar
    y, m = (int(x) for x in _mes_actual_ar().split("-"))
    total = (y * 12 + (m - 1)) + n
    return total // 12, total % 12 + 1


def _fecha_offset(n: int, day: int) -> date:
    y, m = _mes_offset_ym(n)
    return date(y, m, day)


def _estudio_row(**ov):
    d = {"equipo_id": 99}
    d.update(ov)
    return d


def _edicion_full(**ov):
    """Edición que dura 3 meses calendario (mes actual .. mes actual + 2)."""
    e = {
        "id": 1,
        "fecha_inicio": _fecha_offset(0, 10),
        "fecha_fin": _fecha_offset(2, 20),
        "activo": True,
        "usa_estudio": False,
        "valor_estudio": 0,
        "valor_estudio_modo": "mensual",
        "usa_equipos": False,
        "valor_equipos": 0,
        "valor_equipos_modo": "mensual",
    }
    e.update(ov)
    return e


class _TallerRegenConn(_ConnCM):
    """Fake conn para _regenerar_pedidos_taller: graba INSERT/DELETE de
    alquileres + los ítems de cada pedido nuevo."""

    def __init__(self, existing=None, estudio=None):
        # existing: [{id, fecha_desde, monto_pagado, n_items}]
        self.existing = existing or []
        self.inserted = []       # params posicionales de cada INSERT alquileres
        self.deleted = []        # ids borrados
        self.item_inserts = []   # [{columna: valor}] — uno por ítem insertado
        self.estudio = estudio if estudio is not None else _estudio_row()
        self._num = 5000

    def execute(self, sql, params=()):
        su = " ".join(sql.split()).upper()
        if "FROM ESTUDIO WHERE ID = 1" in su:
            return _Cur([self.estudio])
        if "FROM ALQUILERES A WHERE A.TALLER_EDICION_ID" in su:
            return _Cur(self.existing)
        if "NEXTVAL" in su:
            self._num += 1
            return _Cur([{0: self._num}])
        if "PG_ADVISORY_XACT_LOCK" in su:
            return _Cur([])
        if su.startswith("INSERT INTO ALQUILERES"):
            self.inserted.append(params)
            self._num += 1
            return _Cur([{"id": self._num}])
        if su.startswith("INSERT INTO ALQUILER_ITEMS"):
            self.item_inserts.append(_parse_insert(sql, params))
            return _Cur([])
        if su.startswith("DELETE FROM ALQUILERES WHERE ID = "):
            self.deleted.append(params[0])
            return _Cur([])
        raise AssertionError(f"query no manejada por el fake: {sql}")

    def insert_returning(self, sql, params=(), *, column="id"):
        row = self.execute(sql, params).fetchone()
        return row[column] if row else None


class TestRegenerarPedidosTaller:
    def test_genera_un_pedido_por_mes_modo_mensual(self):
        from routes.talleres import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[])
        edicion = _edicion_full(usa_estudio=True, valor_estudio=30000, valor_estudio_modo="mensual")
        _regenerar_pedidos_taller(conn, edicion, "Fotografía Básica")
        assert len(conn.inserted) == 3
        for p in conn.inserted:
            # (cliente_nombre, fd, fh, monto_total, estado, fuente, tipo, numero_pedido, taller_edicion_id)
            assert "Fotografía Básica" in p[0]
            assert p[3] == 30000  # "mensual" = mismo valor cada mes, no se reparte
            assert p[4] == "confirmado"
            assert p[5] == "taller"
            assert p[6] == "taller"
            assert p[8] == 1
        assert len(conn.item_inserts) == 3
        for it in conn.item_inserts:
            assert it["equipo_id"] == 99  # centinela del Estudio (_estudio_row)
            assert it["subtotal"] == 30000
            assert it["cobro_modo"] == "fijo"

    def test_modo_total_reparte_en_partes_iguales(self):
        from routes.talleres import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[])
        edicion = _edicion_full(usa_estudio=True, valor_estudio=100000, valor_estudio_modo="total")
        _regenerar_pedidos_taller(conn, edicion, "Taller X")
        montos = sorted(p[3] for p in conn.inserted)
        assert montos == [33333, 33333, 33334]
        assert sum(montos) == 100000

    def test_remainder_pinned_al_mes_calendario_no_al_ultimo_regenerado(self):
        from routes.talleres import _regenerar_pedidos_taller
        y2, m2 = _mes_offset_ym(2)  # el ÚLTIMO mes real del rango — ya pagado, se conserva
        existing = [
            {"id": 701, "fecha_desde": datetime(y2, m2, 20, 0), "monto_pagado": 40000, "n_items": 1},
        ]
        conn = _TallerRegenConn(existing=existing)
        edicion = _edicion_full(usa_estudio=True, valor_estudio=100000, valor_estudio_modo="total")
        _regenerar_pedidos_taller(conn, edicion, "Taller X")
        assert 701 not in conn.deleted
        assert len(conn.inserted) == 2  # meses 0 y 1 (el 2, pagado, queda intocable)
        # Si el remanente se recalculara sobre "el último mes que SÍ se
        # regenera" (bug), uno de estos 2 pedidos tendría 33334; pinneado al
        # mes calendario real (2, conservado), ambos dan el mismo base.
        assert sorted(p[3] for p in conn.inserted) == [33333, 33333]

    def test_conserva_pedido_pagado_no_lo_borra(self):
        from routes.talleres import _regenerar_pedidos_taller
        y0, m0 = _mes_offset_ym(0)
        existing = [{"id": 800, "fecha_desde": datetime(y0, m0, 5, 0), "monto_pagado": 5000, "n_items": 1}]
        conn = _TallerRegenConn(existing=existing)
        edicion = _edicion_full()  # ambos flags off -> n_items_auto = 1, igual al existente
        _regenerar_pedidos_taller(conn, edicion, "Taller X")
        assert 800 not in conn.deleted
        assert len(conn.inserted) == 2  # meses 1 y 2 (el 0, pagado, se conserva)

    def test_conserva_pedido_con_linea_manual_agregada(self):
        # El fix propio de Talleres (el slot no lo necesita): el admin tipeó a
        # mano la línea de matrícula -> el pedido tiene MÁS ítems de los que
        # el generador crearía -> se conserva aunque no esté pagado.
        from routes.talleres import _regenerar_pedidos_taller
        y0, m0 = _mes_offset_ym(0)
        existing = [{"id": 801, "fecha_desde": datetime(y0, m0, 5, 0), "monto_pagado": 0, "n_items": 2}]
        conn = _TallerRegenConn(existing=existing)
        edicion = _edicion_full(usa_estudio=True, valor_estudio=20000)  # n_items_auto = 1
        _regenerar_pedidos_taller(conn, edicion, "Taller X")
        assert 801 not in conn.deleted
        assert len(conn.inserted) == 2  # meses 1 y 2

    def test_no_conserva_si_no_hay_pagos_ni_items_extra(self):
        from routes.talleres import _regenerar_pedidos_taller
        y0, m0 = _mes_offset_ym(0)
        existing = [{"id": 802, "fecha_desde": datetime(y0, m0, 5, 0), "monto_pagado": 0, "n_items": 1}]
        conn = _TallerRegenConn(existing=existing)
        edicion = _edicion_full(usa_estudio=True, valor_estudio=20000)  # n_items_auto = 1 == existente
        _regenerar_pedidos_taller(conn, edicion, "Taller X")
        assert 802 in conn.deleted
        assert len(conn.inserted) == 3  # se regeneran los 3 meses, incluido el actual

    def test_edicion_inactiva_no_genera_pedidos(self):
        from routes.talleres import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[])
        edicion = _edicion_full(activo=False, usa_estudio=True, valor_estudio=20000)
        _regenerar_pedidos_taller(conn, edicion, "Taller X")
        assert conn.inserted == []
        assert conn.item_inserts == []

    def test_sin_estudio_ni_equipos_crea_item_placeholder(self):
        # Ni pedido vacío (estadisticas.py asume ≥1 ítem por pedido) ni 0 ítems.
        from routes.talleres import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[])
        edicion = _edicion_full()
        _regenerar_pedidos_taller(conn, edicion, "Taller X")
        assert len(conn.inserted) == 3
        assert len(conn.item_inserts) == 3
        for it in conn.item_inserts:
            assert it["equipo_id"] is None
            assert it["subtotal"] == 0
            assert it["cobro_modo"] == "fijo"
        for p in conn.inserted:
            assert p[3] == 0

    def test_usa_estudio_y_equipos_crea_2_items_por_pedido(self):
        from routes.talleres import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[])
        edicion = _edicion_full(
            usa_estudio=True, valor_estudio=15000, valor_estudio_modo="mensual",
            usa_equipos=True, valor_equipos=5000, valor_equipos_modo="mensual",
        )
        _regenerar_pedidos_taller(conn, edicion, "Taller Y")
        assert len(conn.inserted) == 3
        for p in conn.inserted:
            assert p[3] == 20000  # 15000 (Estudio) + 5000 (equipos)
        assert len(conn.item_inserts) == 6
        estudio_items = [it for it in conn.item_inserts if it["equipo_id"] == 99]
        equipos_items = [it for it in conn.item_inserts if it["equipo_id"] is None]
        assert len(estudio_items) == 3
        assert len(equipos_items) == 3
        for it in estudio_items:
            assert it["subtotal"] == 15000
        for it in equipos_items:
            assert it["subtotal"] == 5000
            assert it["nombre_libre"] == "Uso de equipos — Taller Y"
