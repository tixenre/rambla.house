"""El descuento del cliente se recotiza en vivo en sus PRESUPUESTOS (pedidos no
confirmados) sin override manual; los pedidos confirmados/cerrados conservan su
snapshot (lock de precio).

Bug original del dueño (2026-06-06): "le modifiqué el descuento a un cliente y
al entrar en su pedido no se actualizó". Decisión: presupuestos en vivo,
confirmados congelados.

Fase C-1 (#1219): la jerarquía cambió esto de raíz — `alquileres.descuento_pct`
pasa a ser SOLO el override manual (0 = sin override, sigue al cliente en
vivo); `propagar_descuento_a_presupuestos` ya NO escribe esa columna, solo
dispara el recálculo, y SOLO para los presupuestos sin override (los que
tienen uno explícito no dependen del descuento del cliente — antes se
clobbereaban sin aviso, bug real encontrado auditando esta iniciativa).
"""

import pytest

from routes.alquileres import (
    propagar_descuento_a_presupuestos,
    _recalcular_total_pedido,
)


pytestmark = pytest.mark.unit


class FakeConn:
    """Simula los SELECT/UPDATE que tocan propagación + recálculo.

    `presupuesto_ids_all` = todos los presupuestos del cliente en la tabla;
    el filtro real `AND (descuento_pct IS NULL OR descuento_pct = 0)` se
    simula acá mismo (los que tienen override manual no aparecen). `clientes`
    modela la tabla `clientes` para el lookup EN VIVO del descuento.
    """

    def __init__(self, presupuesto_ids_all, pedido_rows, items_by_pedido,
                 descuentos_jornada, clientes=None):
        self.presupuesto_ids_all = presupuesto_ids_all
        self.pedido_rows = pedido_rows
        self.items_by_pedido = items_by_pedido
        self.descuentos_jornada = descuentos_jornada
        self.clientes = clientes or {}  # {cliente_id: descuento}
        self.total_updates = []  # (id, monto_total, descuento_jornadas_pct, descuento_cliente_pct)
        self._sql = ""
        self._params = ()

    def execute(self, sql, params=()):
        self._sql = sql
        self._params = params or ()
        s = sql.strip().upper()
        if s.startswith("UPDATE ALQUILERES SET MONTO_TOTAL"):
            monto, descj, desccli, pid = params
            self.total_updates.append((pid, monto, descj, desccli))
        return self

    def executemany(self, sql, seq):
        return self

    def fetchone(self):
        if "FROM alquileres WHERE id" in self._sql:
            return self.pedido_rows.get(self._params[0])
        if "FROM clientes WHERE id" in self._sql:
            cid = self._params[0]
            return {"descuento": self.clientes[cid]} if cid in self.clientes else None
        return None

    def fetchall(self):
        sql = self._sql
        if "estado='solicitado'" in sql:
            return [
                {"id": i} for i in self.presupuesto_ids_all
                if not (self.pedido_rows.get(i, {}).get("descuento_pct") or 0)
            ]
        if "FROM alquiler_items WHERE pedido_id" in sql:
            return self.items_by_pedido.get(self._params[0], [])
        if "FROM descuentos_jornada" in sql:
            return [{"jornadas": j, "pct": p} for j, p in self.descuentos_jornada]
        return []

    def commit(self):
        pass

    def close(self):
        pass


def _pedido(id, cliente_id=5, descuento_pct=0, descuento_manual_tipo="pct", descuento_manual_monto=0,
            estado="solicitado", descuento_cliente_pct=0):
    return {
        "id": id,
        "cliente_id": cliente_id,
        "fecha_desde": "2026-07-01T10:00:00",
        "fecha_hasta": "2026-07-08T10:00:00",  # 7 jornadas
        "estado": estado,
        "descuento_pct": descuento_pct,
        "descuento_jornadas_pct": 0,
        "descuento_cliente_pct": descuento_cliente_pct,
        "descuento_manual_tipo": descuento_manual_tipo,
        "descuento_manual_monto": descuento_manual_monto,
    }


def test_propaga_a_presupuestos_sin_override_y_recotiza():
    # Dos presupuestos del cliente (id 10 y 11), sin override manual, cada uno
    # 1 ítem 10.000 x 7 = 70.000. Cliente pasa a tener 20% de descuento.
    rows = {10: _pedido(10), 11: _pedido(11)}
    items = {
        10: [{"id": 100, "equipo_id": 42, "cantidad": 1, "precio_jornada": 10000, "cobro_modo": "jornada", "turno_estudio_id": None}],
        11: [{"id": 101, "equipo_id": 42, "cantidad": 1, "precio_jornada": 10000, "cobro_modo": "jornada", "turno_estudio_id": None}],
    }
    conn = FakeConn([10, 11], rows, items, descuentos_jornada=[(1, 0.0)], clientes={5: 20})

    n = propagar_descuento_a_presupuestos(conn, cliente_id=5)

    assert n == 2
    montos = {pid: monto for pid, monto, _, _ in conn.total_updates}
    assert montos == {10: 56000, 11: 56000}  # 70.000 − 20% = 56.000


def test_presupuesto_con_override_manual_no_se_toca():
    """Candado del bug de clobbering: un override manual explícito (#11, 15%)
    NO se pisa ni se recotiza cuando cambia el descuento del cliente — solo el
    presupuesto sin override (#10) sigue al cliente."""
    rows = {10: _pedido(10, descuento_pct=0), 11: _pedido(11, descuento_pct=15)}
    items = {
        10: [{"id": 100, "equipo_id": 42, "cantidad": 1, "precio_jornada": 10000, "cobro_modo": "jornada", "turno_estudio_id": None}],
        11: [{"id": 101, "equipo_id": 42, "cantidad": 1, "precio_jornada": 10000, "cobro_modo": "jornada", "turno_estudio_id": None}],
    }
    conn = FakeConn([10, 11], rows, items, descuentos_jornada=[(1, 0.0)], clientes={5: 20})

    n = propagar_descuento_a_presupuestos(conn, cliente_id=5)

    assert n == 1
    montos = {pid: monto for pid, monto, _, _ in conn.total_updates}
    assert montos == {10: 56000}


def test_sin_presupuestos_no_hace_nada():
    conn = FakeConn([], {}, {}, descuentos_jornada=[(1, 0.0)], clientes={5: 30})
    n = propagar_descuento_a_presupuestos(conn, cliente_id=5)
    assert n == 0
    assert conn.total_updates == []


def test_recalcular_usa_el_descuento_mayor_entre_cliente_y_jornadas():
    # Sin override manual (0): descuento cliente 5% vs jornadas 10% → gana jornadas.
    rows = {7: _pedido(7, cliente_id=9, descuento_pct=0)}
    items = {7: [{"id": 70, "equipo_id": 1, "cantidad": 2, "precio_jornada": 5000, "cobro_modo": "jornada", "turno_estudio_id": None}]}
    # 2 x 5000 x 7 = 70.000 bruto. A 7 jornadas → 10%. → 63.000 neto.
    conn = FakeConn([7], rows, items, descuentos_jornada=[(1, 0.0), (7, 10.0)], clientes={9: 5})
    _recalcular_total_pedido(conn, 7)
    assert conn.total_updates == [(7, 63000, 10.0, 5.0)]


def test_recalcular_override_manual_gana_outright_no_compite():
    """Jerarquía (Fase C-1): un override manual (5%) gana OUTRIGHT aunque
    jornadas (20%) sea numéricamente mayor — no es una competencia por tamaño."""
    rows = {7: _pedido(7, cliente_id=9, descuento_pct=5)}
    items = {7: [{"id": 70, "equipo_id": 1, "cantidad": 2, "precio_jornada": 5000, "cobro_modo": "jornada", "turno_estudio_id": None}]}
    conn = FakeConn([7], rows, items, descuentos_jornada=[(1, 0.0), (7, 20.0)], clientes={9: 0})
    _recalcular_total_pedido(conn, 7)
    # 70.000 − 5% = 66.500 (NO 56.000, que sería con el 20% de jornadas).
    assert conn.total_updates == [(7, 66500, 20.0, 0.0)]


def test_recalcular_override_monto_fijo_gana_outright_capeado():
    """Fase C-2: un override manual en $ fijo (30.000) gana OUTRIGHT sobre
    jornadas (20%) — el `descuento_pct` crudo (5) queda stale/ignorado porque
    `descuento_manual_tipo='monto'`."""
    rows = {
        7: _pedido(7, cliente_id=9, descuento_pct=5,
                   descuento_manual_tipo="monto", descuento_manual_monto=30_000),
    }
    items = {7: [{"id": 70, "equipo_id": 1, "cantidad": 2, "precio_jornada": 5000, "cobro_modo": "jornada", "turno_estudio_id": None}]}
    conn = FakeConn([7], rows, items, descuentos_jornada=[(1, 0.0), (7, 20.0)], clientes={9: 0})
    _recalcular_total_pedido(conn, 7)
    # 70.000 − 30.000 = 40.000 neto.
    assert conn.total_updates == [(7, 40000, 20.0, 0.0)]


def test_recalcular_confirmado_no_relee_cliente_ni_jornadas_en_vivo():
    """Bug real (reportado por el dueño): un pedido YA CONFIRMADO no debe
    recalcular su % de cliente/jornadas en vivo — cualquier guardado
    (`_apply_pedido_datos`/`_apply_pedido_items`) dispara `_recalcular_total_pedido`,
    y antes de este guard eso pisaba `descuento_cliente_pct` con el valor
    ACTUAL del cliente sin mirar el estado. Acá el cliente vale 99% en vivo
    (`clientes={9: 99}`) y jornadas 20%, pero el pedido confirmado tiene
    congelado cliente=5%/jornadas=0% — el resultado tiene que seguir esos
    valores frozen, no los de `clientes={9: 99}`."""
    rows = {
        7: _pedido(7, cliente_id=9, descuento_pct=0, estado="confirmado",
                   descuento_cliente_pct=5.0),
    }
    items = {7: [{"id": 70, "equipo_id": 1, "cantidad": 2, "precio_jornada": 5000, "cobro_modo": "jornada", "turno_estudio_id": None}]}
    conn = FakeConn([7], rows, items, descuentos_jornada=[(1, 0.0), (7, 20.0)], clientes={9: 99})
    _recalcular_total_pedido(conn, 7)
    # 70.000 − 5% (congelado) = 66.500 — NO 700 (que sería con el 99% en vivo).
    assert conn.total_updates == [(7, 66500, 0.0, 5.0)]
