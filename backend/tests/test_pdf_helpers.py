"""Tests de helpers de pdf.py — formato de fechas, montos, nombres."""


import pytest

from pdf import (
    _abs_image_url,
    _es_month,
    _fmt_ars,
    _fmt_date_long,
    _fmt_date_short,
    _nombre_para_pdf,
    _parse_valor,
)


pytestmark = pytest.mark.unit


def test_active_wordmark_cae_al_constante_sin_db():
    """Sin DB (o sin setting `wordmark_svg`), `_active_wordmark` devuelve el SVG
    canónico bundleado — nunca rompe el render del documento."""
    from pdf_templates import WORDMARK, _active_wordmark

    wm = _active_wordmark()
    assert "<svg" in wm
    assert wm == WORDMARK  # en test no hay setting → el constante


class TestEsMonth:
    def test_traduce_meses_individuales(self):
        assert "enero" in _es_month("5 de January de 2026")
        assert "marzo" in _es_month("March 2026")
        assert "diciembre" in _es_month("31 December")

    def test_no_modifica_si_no_hay_mes_en_ingles(self):
        assert _es_month("ya está en español") == "ya está en español"

    def test_traduce_todos_los_meses(self):
        meses_en = ["January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December"]
        meses_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        for en, es in zip(meses_en, meses_es):
            assert _es_month(en) == es, f"{en} debería traducirse a {es}"


class TestFmtArs:
    def test_formato_basico(self):
        assert _fmt_ars(1234) == "$1.234"
        assert _fmt_ars(1234567) == "$1.234.567"

    def test_cero_con_dash_por_default(self):
        assert _fmt_ars(0) == "—"

    def test_cero_sin_dash_devuelve_pesos(self):
        assert _fmt_ars(0, zero_dash=False) == "$0"

    def test_none_devuelve_dash(self):
        assert _fmt_ars(None) == "—"

    def test_acepta_string_numerico(self):
        # _fmt_ars usa int(float(n or 0)) — un string numérico válido funciona
        assert _fmt_ars("1500") == "$1.500"

    def test_string_no_numerico_no_rompe(self):
        # Fallback: devuelve el string crudo o "—"
        result = _fmt_ars("no es número")
        assert isinstance(result, str)


class TestFmtDate:
    def test_short_iso(self):
        assert _fmt_date_short("2026-05-11") == "11/05/2026"

    def test_short_vacio_devuelve_dash(self):
        assert _fmt_date_short("") == "—"
        assert _fmt_date_short(None) == "—"

    def test_long_traduce_mes(self):
        result = _fmt_date_long("2026-05-11")
        assert "mayo" in result
        assert "2026" in result

    def test_invalid_no_rompe(self):
        # Si no es ISO válida, devuelve el string crudo
        result = _fmt_date_short("not-a-date")
        assert isinstance(result, str)


class TestNombreParaPdf:
    def test_publico_corto_por_default(self):
        item = {"nombre_publico": "Sony FX3", "nombre_publico_largo": "Sony FX3 Cuerpo Full-Frame", "nombre": "fx3", "marca": "Sony"}
        assert _nombre_para_pdf(item) == "Sony FX3"

    def test_largo_si_formal(self):
        item = {"nombre_publico": "Sony FX3", "nombre_publico_largo": "Sony FX3 Cuerpo Full-Frame", "nombre": "fx3", "marca": "Sony"}
        assert _nombre_para_pdf(item, formal=True) == "Sony FX3 Cuerpo Full-Frame"

    def test_fallback_a_corto_si_no_hay_largo(self):
        item = {"nombre_publico": "Sony FX3", "nombre_publico_largo": "", "nombre": "fx3", "marca": "Sony"}
        assert _nombre_para_pdf(item, formal=True) == "Sony FX3"

    def test_fallback_marca_nombre_si_no_hay_publico(self):
        item = {"nombre_publico": "", "nombre_publico_largo": "", "nombre": "fx3", "marca": "Sony"}
        assert _nombre_para_pdf(item) == "Sony fx3"

    def test_no_duplica_marca_si_ya_esta_en_nombre(self):
        item = {"nombre_publico": "", "nombre_publico_largo": "", "nombre": "Sony FX3", "marca": "Sony"}
        # marca ya está en nombre → no la repite
        assert _nombre_para_pdf(item) == "Sony FX3"

    def test_dash_si_todo_vacio(self):
        item = {"nombre_publico": "", "nombre_publico_largo": "", "nombre": "", "marca": ""}
        assert _nombre_para_pdf(item) == "—"


class TestParseValor:
    def test_int_devuelve_int(self):
        assert _parse_valor(1500) == 1500

    def test_string_con_signo_pesos(self):
        # Si la implementación remueve $ y puntos: '$1.500' → 1500
        result = _parse_valor("$1.500")
        assert result == 1500

    def test_vacio_o_none_devuelve_cero(self):
        assert _parse_valor("") == 0
        assert _parse_valor(None) == 0

    def test_float_de_la_bd_no_se_multiplica_por_diez(self):
        # Regresión: el valor llega de la BD como FLOAT (ej. 500.0). Antes se
        # convertía a str "500.0" y al borrar el '.' quedaba "5000" → x10.
        assert _parse_valor(500.0) == 500
        assert _parse_valor(1800.0) == 1800
        assert _parse_valor(12000.0) == 12000

    def test_float_con_decimales_redondea(self):
        assert _parse_valor(1500.4) == 1500
        assert _parse_valor(1500.6) == 1501


class TestBrutoItemPdf:
    """`_bruto_item_pdf` — bruto de un ítem en el presupuesto/PDF, cobro_modo-aware
    (auditoría cruzada de plata, 2026-07-02). Antes `_pedido_html`/`_sum_bruto`
    multiplicaban siempre por jornadas, ignorando una línea 'fijo' (#805)."""

    def test_linea_jornada_multiplica_por_jornadas(self):
        from pdf_templates import _bruto_item_pdf

        it = {"precio_jornada": 1000, "cantidad": 2, "cobro_modo": "jornada"}
        assert _bruto_item_pdf(it, 3) == 1000 * 2 * 3

    def test_linea_fija_no_multiplica_por_jornadas(self):
        from pdf_templates import _bruto_item_pdf

        it = {"precio_jornada": 20000, "cantidad": 1, "cobro_modo": "fijo"}
        assert _bruto_item_pdf(it, 3) == 20000

    def test_sin_cobro_modo_default_jornada(self):
        from pdf_templates import _bruto_item_pdf

        it = {"precio_jornada": 1000, "cantidad": 1}
        assert _bruto_item_pdf(it, 3) == 1000 * 3

    def test_sum_bruto_respeta_lineas_fijas(self):
        from pdf_templates import _sum_bruto

        items = [
            {"precio_jornada": 1000, "cantidad": 1, "cobro_modo": "jornada"},
            {"precio_jornada": 20000, "cantidad": 1, "cobro_modo": "fijo"},
        ]
        assert _sum_bruto(items, 3) == (1000 * 3) + 20000


class TestTurnoEmbebidoLabel:
    """`_turno_embebido_label` (#1308 rediseño "turno como ítem", Fase 2.4) —
    la sub-línea de un ítem con `turno_estudio_id`: su PROPIA fecha/hora, no
    el período de jornadas del documento (que es el de los EQUIPOS de un
    pedido `diaria` mixto, puede no coincidir)."""

    def test_item_sin_turno_devuelve_vacio(self):
        from pdf_templates import _turno_embebido_label

        assert _turno_embebido_label({"turno_estudio_id": None}) == ""
        assert _turno_embebido_label({}) == ""

    def test_item_con_turno_pero_sin_fechas_devuelve_vacio(self):
        """Defensivo: un consumidor que no haga el JOIN a
        `alquiler_turnos_estudio` (ej. detalle-seguro) no debe romper — solo
        pierde la sub-línea."""
        from pdf_templates import _turno_embebido_label

        assert _turno_embebido_label({"turno_estudio_id": 5}) == ""

    def test_item_con_turno_arma_fecha_hora_y_horas(self):
        import datetime as _dt

        from pdf_templates import _DOW, _turno_embebido_label

        it = {
            "turno_estudio_id": 5,
            "turno_fecha_desde": "2031-06-10T14:00:00",
            "turno_fecha_hasta": "2031-06-10T16:00:00",
        }
        dow = _DOW[_dt.date(2031, 6, 10).weekday()]
        assert _turno_embebido_label(it) == f'{dow} 10/06 14:00–16:00 · 2 horas'

    def test_una_hora_usa_singular(self):
        from pdf_templates import _turno_embebido_label

        it = {
            "turno_estudio_id": 5,
            "turno_fecha_desde": "2031-06-10T14:00:00",
            "turno_fecha_hasta": "2031-06-10T15:00:00",
        }
        assert _turno_embebido_label(it).endswith("· 1 hora")


class TestAbsImageUrl:
    """Resolver foto_url a URL absoluta para que Playwright pueda cargarla."""

    def test_url_absoluta_https_pasa_intacta(self):
        assert _abs_image_url("https://cdn.x/foo.jpg") == "https://cdn.x/foo.jpg"

    def test_url_absoluta_http_pasa_intacta(self):
        assert _abs_image_url("http://cdn.x/foo.jpg") == "http://cdn.x/foo.jpg"

    def test_data_uri_pasa_intacta(self):
        assert _abs_image_url("data:image/png;base64,iVBOR") == "data:image/png;base64,iVBOR"

    def test_none_o_vacio_devuelve_vacio(self):
        assert _abs_image_url(None) == ""
        assert _abs_image_url("") == ""

    def test_relativa_con_base_se_prepende(self, monkeypatch):
        monkeypatch.setenv("FRONTEND_BASE_URL", "https://rambla.com.uy")
        assert _abs_image_url("/uploads/foo.jpg") == "https://rambla.com.uy/uploads/foo.jpg"

    def test_relativa_con_base_con_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("FRONTEND_BASE_URL", "https://rambla.com.uy/")
        assert _abs_image_url("/uploads/foo.jpg") == "https://rambla.com.uy/uploads/foo.jpg"

    def test_relativa_sin_base_devuelve_vacio(self, monkeypatch):
        monkeypatch.delenv("FRONTEND_BASE_URL", raising=False)
        assert _abs_image_url("/uploads/foo.jpg") == ""


class TestContratoHtmlMostrarLocador:
    """`_contrato_html(pedido, mostrar_locador=False)` — usado por el preview
    del checkout (`routes/checkout.py::checkout_contrato_preview`): al
    cliente le importa leer las cláusulas, no los datos institucionales de
    Rambla (fijos, no cambian por pedido). Default `True` no cambia — el
    contrato REAL (de un pedido ya creado) los sigue mostrando siempre."""

    def _pedido(self):
        return {
            "id": "preview",
            "estado": "solicitado",
            "fecha_desde": "2026-07-10",
            "fecha_hasta": "2026-07-12",
            "emitido": None,
            "items": [
                {
                    "nombre": "Cámara test",
                    "cantidad": 1,
                    "serie": "ABC123",
                    "valor_reposicion": 100000,
                    "componentes": [],
                }
            ],
            "cliente_nombre": "Ana Gómez",
            "cliente_email": "ana@test.com",
            "cliente_telefono": "2235551234",
            "cliente_direccion": "Calle Falsa 123",
            "cliente_cuit": None,
            "cliente_perfil_impuestos": "consumidor_final",
            "cliente_razon_social": None,
        }

    def test_default_muestra_locador(self):
        from pdf_templates import OWNER_CUIL, OWNER_NOMBRE, _contrato_html

        html_str = _contrato_html(self._pedido())
        assert OWNER_NOMBRE in html_str
        assert OWNER_CUIL in html_str
        assert "Firma Locador" in html_str

    def test_mostrar_locador_false_omite_datos_institucionales(self):
        from pdf_templates import OWNER_CUIL, OWNER_NOMBRE, _contrato_html

        html_str = _contrato_html(self._pedido(), mostrar_locador=False)
        assert OWNER_NOMBRE not in html_str
        assert OWNER_CUIL not in html_str
        assert "Firma Locador" not in html_str
        # Lo que sí importa sigue: cláusulas, equipo, locatario.
        assert "Primero" in html_str
        assert "Cámara test" in html_str
        assert "Ana Gómez" in html_str

    def test_fonts_ligeras_saca_las_fuentes_embebidas(self):
        """`fonts_ligeras=True` (el preview del checkout, pintado por el browser
        real del cliente — no por Playwright) saca el @font-face en base64
        (~1.2MB, causaba 10s+ para pintar el iframe) y el link a Google Fonts.
        El contenido (cláusulas/equipo/cliente) tiene que seguir intacto."""
        from pdf_templates import _contrato_html

        pesado = _contrato_html(self._pedido(), mostrar_locador=False)
        liviano = _contrato_html(self._pedido(), mostrar_locador=False, fonts_ligeras=True)

        assert "@font-face" not in liviano
        assert "fonts.googleapis.com" not in liviano
        assert "@font-face" in pesado  # default sigue embebiendo (Playwright/PDF real)
        assert len(liviano) < len(pesado) / 10  # reducción drástica, no cosmética

        for esperado in ("Primero", "Cámara test", "Ana Gómez"):
            assert esperado in liviano

    def test_fonts_ligeras_saca_tambien_el_wordmark_svg(self):
        """`fonts_ligeras=True` es "documento de muestra nomás" — sin el isologo
        SVG (ni la lectura a `app_settings.wordmark_svg` que eso implica).
        Cae a texto plano "Rambla"."""
        from pdf_templates import _contrato_html

        liviano = _contrato_html(self._pedido(), mostrar_locador=False, fonts_ligeras=True)
        pesado = _contrato_html(self._pedido(), mostrar_locador=False)

        assert "<svg" not in liviano
        assert "<svg" in pesado

    def test_fonts_ligeras_default_no_cambia_el_pdf_real(self):
        """El contrato REAL (de un pedido ya creado, generado por Playwright vía
        `_render_pdf`) sigue embebiendo las fuentes siempre — default `False`."""
        from pdf_templates import _contrato_html

        html_str = _contrato_html(self._pedido())
        assert "@font-face" in html_str
        assert "fonts.googleapis.com" in html_str

    def test_locador_override_reemplaza_datos_reales(self):
        """`locador_override` (usado por el preview del checkout) reemplaza los
        `OWNER_*` reales en el bloque de datos, la firma Y la cláusula de
        Jurisdicción (que hornea el domicilio real aparte, en `_CLAUSULAS`)."""
        from pdf_templates import OWNER_CUIL, OWNER_DIRECCION, OWNER_NOMBRE, _contrato_html

        override = {
            "nombre": "Locador de Muestra S.R.L.",
            "cuil": "30-00000000-0",
            "direccion": "Calle Falsa 123, Muestra",
            "telefono": "223 000-0000",
            "email": "muestra@ejemplo.com",
        }
        html_str = _contrato_html(self._pedido(), locador_override=override)

        assert OWNER_NOMBRE not in html_str
        assert OWNER_CUIL not in html_str
        assert OWNER_DIRECCION not in html_str  # incluye la cláusula de Jurisdicción
        assert override["nombre"] in html_str
        assert override["cuil"] in html_str
        assert override["direccion"] in html_str
        assert "Firma Locador" in html_str  # el bloque se sigue mostrando, con datos falsos

    def test_locador_override_none_no_cambia_el_contrato_real(self):
        """Sin override (default `None`), el contrato REAL sigue mostrando los
        datos institucionales reales — no hay regresión para el documento válido."""
        from pdf_templates import OWNER_NOMBRE, _contrato_html

        html_str = _contrato_html(self._pedido(), locador_override=None)
        assert OWNER_NOMBRE in html_str
