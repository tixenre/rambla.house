"""Tests unitarios para `_regenerar_pedidos_taller`
(services/talleres/commands/economia.py).

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


def _numero_pedido_fn(conn) -> int:
    """Stub de `numero_pedido_fn` inyectado — mismo SQL que
    `routes/alquileres/detalle.py::_next_numero_pedido`, matcheado por el
    `_TallerRegenConn` fake vía `"NEXTVAL" in su`."""
    return conn.execute("SELECT nextval('numero_pedido_seq')").fetchone()[0]


def _mes_offset_ym(n: int) -> tuple[int, int]:
    """(year, month) del mes actual + n meses — relativo a `hoy`, no hardcodeado."""
    from services.fechas import mes_actual_ar
    y, m = (int(x) for x in mes_actual_ar().split("-"))
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
        "valor_estudio_tipo": "fijo",
        "valor_estudio_pct": 0,
        "usa_equipos": False,
        "valor_equipos": 0,
        "valor_equipos_modo": "mensual",
        "valor_equipos_tipo": "fijo",
        "valor_equipos_pct": 0,
    }
    e.update(ov)
    return e


class _TallerRegenConn(_ConnCM):
    """Fake conn para _regenerar_pedidos_taller: graba INSERT/DELETE de
    alquileres + los ítems de cada pedido nuevo."""

    def __init__(self, existing=None, estudio=None, revenue=0):
        # existing: [{id, fecha_desde, monto_pagado, n_items}]
        self.existing = existing or []
        self.inserted = []       # params posicionales de cada INSERT alquileres
        self.deleted = []        # ids borrados
        self.item_inserts = []   # [{columna: valor}] — uno por ítem insertado
        self.estudio = estudio if estudio is not None else _estudio_row()
        self.revenue = revenue   # SUM(modalidad_monto) que devolvería _revenue_inscriptos
        self.revenue_queries = 0  # cuántas veces se consultó — porcentaje comparte 1 sola
        self._num = 5000

    def execute(self, sql, params=()):
        su = " ".join(sql.split()).upper()
        if "FROM ESTUDIO WHERE ID = 1" in su:
            return _Cur([self.estudio])
        if "FROM ALQUILERES A WHERE A.TALLER_EDICION_ID" in su:
            return _Cur(self.existing)
        if "SUM(MODALIDAD_MONTO)" in su:
            self.revenue_queries += 1
            return _Cur([{"total": self.revenue}])
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
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[])
        edicion = _edicion_full(usa_estudio=True, valor_estudio=30000, valor_estudio_modo="mensual")
        _regenerar_pedidos_taller(conn, edicion, "Fotografía Básica", numero_pedido_fn=_numero_pedido_fn)
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
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[])
        edicion = _edicion_full(usa_estudio=True, valor_estudio=100000, valor_estudio_modo="total")
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        montos = sorted(p[3] for p in conn.inserted)
        assert montos == [33333, 33333, 33334]
        assert sum(montos) == 100000

    def test_remainder_pinned_al_mes_calendario_no_al_ultimo_regenerado(self):
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        y2, m2 = _mes_offset_ym(2)  # el ÚLTIMO mes real del rango — ya pagado, se conserva
        existing = [
            {"id": 701, "fecha_desde": datetime(y2, m2, 20, 0), "monto_pagado": 40000, "n_items": 1},
        ]
        conn = _TallerRegenConn(existing=existing)
        edicion = _edicion_full(usa_estudio=True, valor_estudio=100000, valor_estudio_modo="total")
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        assert 701 not in conn.deleted
        assert len(conn.inserted) == 2  # meses 0 y 1 (el 2, pagado, queda intocable)
        # Si el remanente se recalculara sobre "el último mes que SÍ se
        # regenera" (bug), uno de estos 2 pedidos tendría 33334; pinneado al
        # mes calendario real (2, conservado), ambos dan el mismo base.
        assert sorted(p[3] for p in conn.inserted) == [33333, 33333]

    def test_conserva_pedido_pagado_no_lo_borra(self):
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        y0, m0 = _mes_offset_ym(0)
        existing = [{"id": 800, "fecha_desde": datetime(y0, m0, 5, 0), "monto_pagado": 5000, "n_items": 1}]
        conn = _TallerRegenConn(existing=existing)
        edicion = _edicion_full()  # ambos flags off -> n_items_auto = 1, igual al existente
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        assert 800 not in conn.deleted
        assert len(conn.inserted) == 2  # meses 1 y 2 (el 0, pagado, se conserva)

    def test_conserva_pedido_con_linea_manual_agregada(self):
        # El fix propio de Talleres (el slot no lo necesita): el admin tipeó a
        # mano la línea de matrícula -> el pedido tiene MÁS ítems de los que
        # el generador crearía -> se conserva aunque no esté pagado.
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        y0, m0 = _mes_offset_ym(0)
        existing = [{"id": 801, "fecha_desde": datetime(y0, m0, 5, 0), "monto_pagado": 0, "n_items": 2}]
        conn = _TallerRegenConn(existing=existing)
        edicion = _edicion_full(usa_estudio=True, valor_estudio=20000)  # n_items_auto = 1
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        assert 801 not in conn.deleted
        assert len(conn.inserted) == 2  # meses 1 y 2

    def test_no_conserva_si_no_hay_pagos_ni_items_extra(self):
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        y0, m0 = _mes_offset_ym(0)
        existing = [{"id": 802, "fecha_desde": datetime(y0, m0, 5, 0), "monto_pagado": 0, "n_items": 1}]
        conn = _TallerRegenConn(existing=existing)
        edicion = _edicion_full(usa_estudio=True, valor_estudio=20000)  # n_items_auto = 1 == existente
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        assert 802 in conn.deleted
        assert len(conn.inserted) == 3  # se regeneran los 3 meses, incluido el actual

    def test_edicion_inactiva_no_genera_pedidos(self):
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[])
        edicion = _edicion_full(activo=False, usa_estudio=True, valor_estudio=20000)
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        assert conn.inserted == []
        assert conn.item_inserts == []

    def test_sin_estudio_ni_equipos_crea_item_placeholder(self):
        # Ni pedido vacío (estadisticas.py asume ≥1 ítem por pedido) ni 0 ítems.
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[])
        edicion = _edicion_full()
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        assert len(conn.inserted) == 3
        assert len(conn.item_inserts) == 3
        for it in conn.item_inserts:
            assert it["equipo_id"] is None
            assert it["subtotal"] == 0
            assert it["cobro_modo"] == "fijo"
        for p in conn.inserted:
            assert p[3] == 0

    def test_usa_estudio_y_equipos_crea_2_items_por_pedido(self):
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[])
        edicion = _edicion_full(
            usa_estudio=True, valor_estudio=15000, valor_estudio_modo="mensual",
            usa_equipos=True, valor_equipos=5000, valor_equipos_modo="mensual",
        )
        _regenerar_pedidos_taller(conn, edicion, "Taller Y", numero_pedido_fn=_numero_pedido_fn)
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


class TestRegenerarPedidosTallerPorcentaje:
    """`valor_estudio_tipo`/`valor_equipos_tipo` = 'porcentaje': el valor se
    deriva de `_revenue_inscriptos` (SUM(modalidad_monto) de los no en lista
    de espera) en vez de tipearse a mano. Pedido explícito del dueño: "si se
    anotan 6 vamos al 50%"."""

    def test_valor_estudio_porcentaje_deriva_del_revenue(self):
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[], revenue=320_000)
        edicion = _edicion_full(
            usa_estudio=True, valor_estudio_tipo="porcentaje", valor_estudio_pct=50,
            valor_estudio_modo="mensual",
        )
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        assert len(conn.inserted) == 3
        for p in conn.inserted:
            assert p[3] == 160_000  # 50% de 320.000, mismo valor cada mes ("mensual")
        for it in conn.item_inserts:
            assert it["subtotal"] == 160_000

    def test_valor_equipos_porcentaje_deriva_del_revenue(self):
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[], revenue=100_000)
        edicion = _edicion_full(
            usa_equipos=True, valor_equipos_tipo="porcentaje", valor_equipos_pct=25,
            valor_equipos_modo="mensual",
        )
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        for it in conn.item_inserts:
            assert it["subtotal"] == 25_000  # 25% de 100.000

    def test_porcentaje_redondea_al_peso(self):
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[], revenue=333_333)
        edicion = _edicion_full(
            usa_estudio=True, valor_estudio_tipo="porcentaje", valor_estudio_pct=33,
            valor_estudio_modo="mensual",
        )
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        # 333333 * 33 / 100 = 109999.89 -> redondea a 110000
        assert conn.item_inserts[0]["subtotal"] == 110_000

    def test_modo_total_reparte_el_valor_derivado_del_porcentaje(self):
        # `_modo` (mensual/total) sigue repartiendo el TOTAL YA resuelto —
        # 'porcentaje' no cambia cómo se reparte entre meses, solo de dónde
        # sale el total antes de repartirlo.
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[], revenue=300_000)
        edicion = _edicion_full(
            usa_estudio=True, valor_estudio_tipo="porcentaje", valor_estudio_pct=50,
            valor_estudio_modo="total",
        )
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        montos = sorted(p[3] for p in conn.inserted)
        assert montos == [50000, 50000, 50000]  # 150.000 (50% de 300.000) repartido en 3 meses

    def test_fijo_no_consulta_revenue(self):
        # Guardrail de performance/costo: en 'fijo' (el caso común) no debe
        # dispararse la query de inscriptos — solo 'porcentaje' la necesita.
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[], revenue=999_999)
        edicion = _edicion_full(usa_estudio=True, valor_estudio=30000, valor_estudio_modo="mensual")
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        assert conn.revenue_queries == 0
        for p in conn.inserted:
            assert p[3] == 30000  # el revenue (999999) NUNCA se aplicó

    def test_estudio_y_equipos_porcentaje_comparten_una_sola_query(self):
        # Ambos 'porcentaje' a la vez -> 1 sola consulta de revenue, no 2
        # (mismo total se aplica a los dos cálculos).
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[], revenue=200_000)
        edicion = _edicion_full(
            usa_estudio=True, valor_estudio_tipo="porcentaje", valor_estudio_pct=50,
            valor_estudio_modo="mensual",
            usa_equipos=True, valor_equipos_tipo="porcentaje", valor_equipos_pct=10,
            valor_equipos_modo="mensual",
        )
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        assert conn.revenue_queries == 1
        estudio_items = [it for it in conn.item_inserts if it["subtotal"] == 100_000]
        equipos_items = [it for it in conn.item_inserts if it["subtotal"] == 20_000]
        assert len(estudio_items) == 3
        assert len(equipos_items) == 3

    def test_estudio_porcentaje_equipos_fijo_mezcla_ambos_modos(self):
        # Un mismo taller puede combinar 'porcentaje' para el Estudio y
        # 'fijo' para equipos (o viceversa) — son ejes independientes.
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[], revenue=80_000)
        edicion = _edicion_full(
            usa_estudio=True, valor_estudio_tipo="porcentaje", valor_estudio_pct=50,
            valor_estudio_modo="mensual",
            usa_equipos=True, valor_equipos=5000, valor_equipos_modo="mensual",  # fijo, default
        )
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        for p in conn.inserted:
            assert p[3] == 45_000  # 40.000 (50% de 80.000) + 5.000 (fijo)
        estudio_items = [it for it in conn.item_inserts if it["equipo_id"] == 99]
        equipos_items = [it for it in conn.item_inserts if it["equipo_id"] is None]
        for it in estudio_items:
            assert it["subtotal"] == 40_000
        for it in equipos_items:
            assert it["subtotal"] == 5_000

    def test_revenue_cero_no_rompe(self):
        # Edición recién publicada, todavía sin inscriptos -> 0, no error.
        from services.talleres.commands.economia import _regenerar_pedidos_taller
        conn = _TallerRegenConn(existing=[], revenue=0)
        edicion = _edicion_full(
            usa_estudio=True, valor_estudio_tipo="porcentaje", valor_estudio_pct=50,
            valor_estudio_modo="mensual",
        )
        _regenerar_pedidos_taller(conn, edicion, "Taller X", numero_pedido_fn=_numero_pedido_fn)
        for it in conn.item_inserts:
            assert it["subtotal"] == 0
