"""Tests puros del reporte de liquidación en PDF + envío por mail (#88).

No tocan DB ni Playwright: validan el armado del HTML branded (a partir del
dict del motor) y el parseo de destinatarios. El render real a PDF y el envío
se validan en staging (igual que el resto de la infra de mail).
"""

from pdf import _liquidacion_html
from routes.reportes import _split_emails, _periodo_label


_DATA = {
    "beneficiarios": ["Rental", "Pablo"],
    "resumen": {"por_beneficiario": {"Rental": 120000, "Pablo": 80000}, "total": 200000},
    "por_mes": [
        {"mes": "2026-06", "por_beneficiario": {"Rental": 120000, "Pablo": 80000}, "total": 200000},
    ],
    "por_dueno": [
        {
            "dueno": "Pablo",
            "equipos": [{"equipo": "Cámara A", "veces": 3, "monto": 80000}],
            "monto_generado": 80000,
            "pedidos": 2,
        },
    ],
}


def test_html_incluye_beneficiarios_y_total():
    html = _liquidacion_html(_DATA, "junio de 2026")
    assert "Rental" in html
    assert "Pablo" in html
    assert "Cámara A" in html
    assert "junio de 2026" in html
    # Total formateado en pesos (con separador de miles).
    assert "$200.000" in html
    assert html.lstrip().startswith("<!DOCTYPE html>")


def test_html_es_hoja_a4():
    # Requisito: todo documento que se manda por mail es A4. Tras el rediseño DS
    # el tamaño de hoja lo declara el shell compartido (_DOC_CSS): @page A4 + el
    # contenedor .paper (igual que presupuesto/albarán/contrato/packing).
    html = _liquidacion_html(_DATA, "junio de 2026")
    assert "@page{size:A4" in html
    assert 'class="paper"' in html


def test_html_periodo_vacio_no_rompe():
    html = _liquidacion_html(
        {"beneficiarios": [], "resumen": {}, "por_mes": [], "por_dueno": []},
        "mayo de 2026",
    )
    assert "No hay pedidos saldados" in html


def test_html_incluye_pedidos_detalle():
    # Tabla "Pedidos" (2026-07-04): # de pedido, cliente, fecha, monto — además
    # de la tabla de equipos, no en su lugar.
    data = dict(
        _DATA,
        por_dueno=[
            dict(
                _DATA["por_dueno"][0],
                pedidos_detalle=[
                    {"pedido_id": 501, "numero_pedido": 1042, "cliente": "Juan Pérez",
                     "fecha": "2026-06-15", "monto": 80000},
                ],
            )
        ],
    )
    html = _liquidacion_html(data, "junio de 2026")
    assert "#1042" in html
    assert "Juan Pérez" in html
    assert "15/06/2026" in html
    assert "Cámara A" in html  # la tabla de equipos sigue estando


def test_html_pedidos_detalle_vacio_no_rompe():
    # Compat: dicts sin `pedidos_detalle` (fotos congeladas de antes de este
    # cambio) no rompen — cae al estado vacío de la tabla.
    html = _liquidacion_html(_DATA, "junio de 2026")
    assert "Sin pedidos con ingreso en el período" in html


def test_html_escapa_nombres():
    data = dict(_DATA, por_dueno=[{"dueno": "<script>x</script>", "equipos": [], "monto_generado": 0, "pedidos": 0}])
    html = _liquidacion_html(data, "junio de 2026")
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_escapa_cliente_en_pedidos_detalle():
    data = dict(
        _DATA,
        por_dueno=[
            dict(
                _DATA["por_dueno"][0],
                pedidos_detalle=[
                    {"pedido_id": 1, "numero_pedido": 1, "cliente": "<script>x</script>",
                     "fecha": "2026-06-15", "monto": 1000},
                ],
            )
        ],
    )
    html = _liquidacion_html(data, "junio de 2026")
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


_STATS = {
    "totales": {"total_ars": 8_450_000, "total_pedidos": 64, "total_clientes": 23},
    "por_mes": [
        {"mes": "2026-06", "pedidos": 12, "total_ars": 1_980_000},
        {"mes": "2026-05", "pedidos": 10, "total_ars": 1_620_000},
        {"mes": "2026-04", "pedidos": 9, "total_ars": 1_410_000},
    ],
    "crecimiento": [
        {"mes": "2026-06", "total_ars": 1_980_000, "crecimiento_pct": 22.2},
        {"mes": "2026-05", "total_ars": 1_620_000, "crecimiento_pct": 14.9},
    ],
    "por_dueno": [
        {"dueno": "Rental", "total_ars": 5_100_000, "items": 140},
        {"dueno": "Pablo", "total_ars": 2_300_000, "items": 60},
        {"dueno": "Tincho", "total_ars": 1_050_000, "items": 28},
    ],
    "top_clientes": [
        {"cliente": "Faro Audiovisual", "pedidos": 8, "total_ars": 1_200_000},
        {"cliente": "Productora Sur", "pedidos": 5, "total_ars": 740_000},
    ],
}


def test_html_sin_stats_es_solo_liquidacion():
    # Compat hacia atrás: stats=None → no aparece la sección Resumen general.
    html = _liquidacion_html(_DATA, "junio de 2026")
    assert "Resumen general" not in html
    assert "Liquidación" in html


def test_html_con_stats_incluye_resumen_general():
    html = _liquidacion_html(_DATA, "junio de 2026", stats=_STATS)
    assert "Resumen general" in html
    assert "Facturado neto" in html
    # Total facturado formateado en pesos.
    assert "$8.450.000" in html
    # Dueños del histórico + un cliente del top.
    assert "Tincho" in html
    assert "Faro Audiovisual" in html
    # Crecimiento positivo con signo +.
    assert "+22.2%" in html


def test_split_emails_separadores():
    assert _split_emails("a@x.com, b@y.com;c@z.com\nd@w.com") == [
        "a@x.com", "b@y.com", "c@z.com", "d@w.com",
    ]
    assert _split_emails("  ") == []
    assert _split_emails("") == []


def test_periodo_label_mes_calendario():
    # Un mes calendario exacto → rótulo en español.
    assert _periodo_label("2026-06-01", "2026-06-30") == "junio de 2026"
    # Rango arbitrario → fallback con fechas.
    assert _periodo_label("2026-01-01", "2026-12-31") == "2026-01-01 a 2026-12-31"
