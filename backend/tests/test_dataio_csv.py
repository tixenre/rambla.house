"""Tests de los exporters CSV planos (sin DB — conn falso)."""

import csv
import datetime
import io

import pytest

from dataio import csv_exporters

pytestmark = pytest.mark.unit


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Devuelve filas fijas para cualquier query (los exporters hacen 1 query)."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, _sql, _params=None):
        return _FakeCursor(self._rows)


def _parse(csv_text):
    assert csv_text[0] == "﻿", "debe arrancar con BOM UTF-8 para Excel"
    return list(csv.reader(io.StringIO(csv_text[1:])))


def test_equipos_csv_header_y_specs_colapsadas():
    rows = [{
        "id": 1, "nombre": "Sony FX3", "marca": "Sony", "modelo": "FX3",
        "categorias": "Cámaras", "cantidad": 2, "precio_jornada": 30000,
        "precio_usd": 6000.0, "dueno": "Rental", "estado": "operativo",
        "visible_catalogo": 1, "serie": None,
        "fecha_compra": datetime.date(2024, 3, 15),
        "specs": "Sensor: Full-frame; Montura: E",
    }]
    out = _parse(csv_exporters.export_equipos_csv(_FakeConn(rows)))
    assert out[0] == [
        "id", "nombre", "marca", "modelo", "categorias", "cantidad",
        "precio_jornada", "precio_usd", "dueno", "estado", "visible_catalogo",
        "serie", "fecha_compra", "specs",
    ]
    fila = out[1]
    assert fila[1] == "Sony FX3"
    assert fila[11] == ""  # serie None → ''
    assert fila[12] == "2024-03-15"  # date → ISO
    assert fila[13] == "Sensor: Full-frame; Montura: E"


def test_alquileres_csv_fechas_iso_y_items():
    rows = [{
        "numero_pedido": 7, "cliente_nombre": "Juan Pérez",
        "cliente_email": "juan@test.com", "estado": "confirmado",
        "fecha_desde": datetime.datetime(2026, 7, 1, 9, 0),
        "fecha_hasta": datetime.datetime(2026, 7, 4, 18, 0),
        "monto_total": 240000, "descuento_pct": 0.0, "monto_pagado": 100000,
        "saldo": 140000, "items": "Sony FX3 x2", "fuente": "sistema",
        "notas": None,
    }]
    out = _parse(csv_exporters.export_alquileres_csv(_FakeConn(rows)))
    fila = out[1]
    assert fila[4] == "2026-07-01T09:00:00"
    assert fila[9] == "140000"
    assert fila[10] == "Sony FX3 x2"
    assert fila[12] == ""  # notas None → ''


def test_clientes_csv_header():
    rows = [{
        "nombre": "Juan", "apellido": "Pérez", "email": "juan@test.com",
        "telefono": "111", "direccion": "Calle 1", "cuit": "20-111",
        "perfil_impuestos": "consumidor_final", "razon_social": "Pérez SA",
        "domicilio_fiscal": None, "descuento": 10.0,
    }]
    out = _parse(csv_exporters.export_clientes_csv(_FakeConn(rows)))
    assert out[0][0] == "nombre" and out[0][-1] == "descuento"
    assert out[1][1] == "Pérez"
    assert out[1][-1] == "10.0"
