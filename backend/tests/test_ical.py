"""Tests del generador canónico de iCal (`services/ical.py`).

Es la fuente única que alimenta el feed suscribible y el adjunto del mail, así
que su correctitud se cubre acá una sola vez.
"""
import pytest

from urllib.parse import parse_qs, urlparse

from services.ical import (
    build_vcalendar,
    build_vevent,
    clase_taller_to_vevent,
    clases_taller_to_ics,
    google_calendar_url,
    reserva_to_vevent,
    _escape,
    _fold,
)

pytestmark = pytest.mark.unit


# ── Primitivas ───────────────────────────────────────────────────────────────

class TestEscape:
    def test_escapa_caracteres_especiales(self):
        assert _escape("a,b;c\\d") == "a\\,b\\;c\\\\d"

    def test_salto_de_linea_a_backslash_n(self):
        assert _escape("línea1\nlínea2") == "línea1\\nlínea2"

    def test_none_es_vacio(self):
        assert _escape(None) == ""


class TestFold:
    def test_linea_corta_no_se_pliega(self):
        assert _fold("SUMMARY:hola") == "SUMMARY:hola"

    def test_linea_larga_se_pliega_con_continuacion(self):
        linea = "DESCRIPTION:" + "x" * 200
        folded = _fold(linea)
        # Se parte en varias líneas; las continuaciones empiezan con espacio.
        partes = folded.split("\r\n")
        assert len(partes) > 1
        assert all(len(p.encode("utf-8")) <= 75 for p in partes)
        for cont in partes[1:]:
            assert cont.startswith(" ")

    def test_no_corta_multibyte(self):
        # Cadena de emojis (4 bytes c/u): el plegado no debe romper un caracter.
        linea = "X:" + "🎬" * 40
        folded = _fold(linea)
        # Si rearmamos sacando los CRLF+espacio de continuación, recuperamos todo.
        rearmado = folded.replace("\r\n ", "")
        assert rearmado == linea


# ── build_vevent ─────────────────────────────────────────────────────────────

class TestBuildVevent:
    def test_all_day_usa_value_date(self):
        from datetime import datetime
        ve = build_vevent(
            uid="u@x", summary="S",
            dtstart=datetime(2026, 6, 10), dtend=datetime(2026, 6, 13),
            all_day=True,
        )
        assert "DTSTART;VALUE=DATE:20260610" in ve
        assert "DTEND;VALUE=DATE:20260613" in ve
        assert "BEGIN:VEVENT" in ve and "END:VEVENT" in ve

    def test_con_hora_usa_tiempo_flotante(self):
        from datetime import datetime
        ve = build_vevent(
            uid="u@x", summary="S",
            dtstart=datetime(2026, 6, 10, 14, 0), dtend=datetime(2026, 6, 10, 16, 0),
            all_day=False,
        )
        # Sin sufijo Z (tiempo flotante = wall-clock).
        assert "DTSTART:20260610T140000" in ve
        assert "DTEND:20260610T160000" in ve
        assert "20260610T140000Z" not in ve


# ── reserva_to_vevent ────────────────────────────────────────────────────────

class TestReservaToVevent:
    def _diaria(self, **over):
        base = {
            "id": 5, "numero_pedido": 123, "cliente_nombre": "Juan",
            "estado": "confirmado", "tipo": "diaria",
            "fecha_desde": "2026-06-10T00:00:00", "fecha_hasta": "2026-06-12T00:00:00",
        }
        base.update(over)
        return base

    def test_diaria_es_all_day_con_dtend_exclusivo(self):
        ve = reserva_to_vevent(self._diaria())
        assert "DTSTART;VALUE=DATE:20260610" in ve
        # fin 12 → DTEND exclusivo 13.
        assert "DTEND;VALUE=DATE:20260613" in ve
        assert "UID:alquiler-5@rambla.house" in ve
        assert "Pedido #123" in ve

    def test_estudio_es_con_hora_y_lleva_prefijo(self):
        ve = reserva_to_vevent(self._diaria(
            tipo="estudio", fecha_desde="2026-06-10T14:00:00",
            fecha_hasta="2026-06-10T16:00:00",
        ))
        assert "DTSTART:20260610T140000" in ve
        assert "🎬 Estudio:" in ve

    def test_lista_equipos_en_descripcion(self):
        ve = reserva_to_vevent(
            self._diaria(),
            [{"nombre": "FX3", "marca": "Sony", "cantidad": 2}],
            link="https://r.com/admin/pedidos/5",
        )
        # Des-plegamos las continuaciones (CRLF+espacio) antes de comparar: una
        # línea larga como la descripción se pliega por RFC 5545.
        plano = ve.replace("\r\n ", "")
        assert "Equipos:" in plano
        assert "2× Sony FX3" in plano
        assert "https://r.com/admin/pedidos/5" in plano

    def test_link_es_el_que_pasa_el_caller(self):
        # El caller elige el link (no lo arma reserva_to_vevent) → no se filtra
        # el back-office al cliente.
        ve = reserva_to_vevent(self._diaria(), link="https://r.com/cliente/portal")
        plano = ve.replace("\r\n ", "")
        assert "https://r.com/cliente/portal" in plano
        assert "/admin/" not in plano

    def test_numero_pedido_fallback_a_id(self):
        ve = reserva_to_vevent(self._diaria(numero_pedido=None))
        assert "Pedido #5" in ve  # cae al id

    def test_sin_fecha_desde_devuelve_vacio(self):
        assert reserva_to_vevent(self._diaria(fecha_desde=None)) == ""

    def test_escapa_nombre_con_caracteres_especiales(self):
        ve = reserva_to_vevent(self._diaria(cliente_nombre="Pérez, Juan; SA"))
        assert "Pérez\\, Juan\\; SA" in ve

    def test_sin_recordatorio_por_defecto(self):
        ve = reserva_to_vevent(self._diaria())
        assert "BEGIN:VALARM" not in ve

    def test_recordatorio_diaria_dia_antes(self):
        ve = reserva_to_vevent(self._diaria(), with_reminders=True)
        assert "BEGIN:VALARM" in ve and "END:VALARM" in ve
        assert "ACTION:DISPLAY" in ve
        assert "TRIGGER:-PT15H" in ve  # ~9am del día anterior

    def test_recordatorio_estudio_dos_horas_antes(self):
        ve = reserva_to_vevent(
            self._diaria(tipo="estudio", fecha_desde="2026-06-10T14:00:00",
                         fecha_hasta="2026-06-10T16:00:00"),
            with_reminders=True,
        )
        assert "TRIGGER:-PT2H" in ve


# ── build_vcalendar ──────────────────────────────────────────────────────────

class TestBuildVcalendar:
    def test_estructura_y_method(self):
        cal = build_vcalendar([reserva_to_vevent(
            {"id": 1, "fecha_desde": "2026-06-10T00:00:00",
             "fecha_hasta": "2026-06-10T00:00:00", "tipo": "diaria"}
        )], method="PUBLISH", cal_name="Rambla")
        assert cal.startswith("BEGIN:VCALENDAR\r\n")
        assert cal.rstrip().endswith("END:VCALENDAR")
        assert "VERSION:2.0" in cal
        assert "METHOD:PUBLISH" in cal
        assert "X-WR-CALNAME:Rambla" in cal
        # Todo el documento usa CRLF.
        assert "\r\n" in cal and "\n\n" not in cal

    def test_calendario_vacio_es_valido(self):
        cal = build_vcalendar([])
        assert "BEGIN:VCALENDAR" in cal
        assert "END:VCALENDAR" in cal
        assert "BEGIN:VEVENT" not in cal


# ── google_calendar_url ──────────────────────────────────────────────────────

class TestGoogleCalendarUrl:
    def _diaria(self, **over):
        base = {
            "id": 5, "numero_pedido": 123, "cliente_nombre": "Juan",
            "tipo": "diaria",
            "fecha_desde": "2026-06-10T00:00:00", "fecha_hasta": "2026-06-12T00:00:00",
        }
        base.update(over)
        return base

    def test_diaria_all_day_dates_exclusivo(self):
        url = google_calendar_url(self._diaria())
        q = parse_qs(urlparse(url).query)
        assert q["action"] == ["TEMPLATE"]
        assert q["dates"] == ["20260610/20260613"]  # fin exclusivo
        assert "Pedido #123" in q["text"][0]
        assert "ctz" not in q  # all-day no lleva timezone

    def test_estudio_con_hora_y_ctz(self):
        url = google_calendar_url(self._diaria(
            tipo="estudio", fecha_desde="2026-06-10T14:00:00",
            fecha_hasta="2026-06-10T16:00:00",
        ))
        q = parse_qs(urlparse(url).query)
        assert q["dates"] == ["20260610T140000/20260610T160000"]
        assert q["ctz"] == ["America/Argentina/Buenos_Aires"]

    def test_incluye_equipos_y_link_en_details(self):
        url = google_calendar_url(
            self._diaria(),
            [{"nombre": "FX3", "marca": "Sony", "cantidad": 2}],
            link="https://r.com/cliente/portal",
        )
        q = parse_qs(urlparse(url).query)
        assert "2× Sony FX3" in q["details"][0]
        assert "https://r.com/cliente/portal" in q["details"][0]

    def test_sin_fecha_devuelve_vacio(self):
        assert google_calendar_url(self._diaria(fecha_desde=None)) == ""


# ── clase_taller_to_vevent / clases_taller_to_ics ───────────────────────────

class TestClaseTallerToVevent:
    def _clase(self, **over):
        base = {
            "id": 42, "fecha": "2026-09-03",
            "hora_inicio_min": 19 * 60, "hora_fin_min": 21 * 60,
            "titulo": "Clase 1", "descripcion": "",
        }
        base.update(over)
        return base

    def test_con_hora_tiempo_flotante_y_uid_estable(self):
        ve = clase_taller_to_vevent(self._clase(), taller_nombre="Semiótica")
        assert "DTSTART:20260903T190000" in ve
        assert "DTEND:20260903T210000" in ve
        assert "20260903T190000Z" not in ve  # tiempo flotante, no UTC
        assert "UID:taller-clase-42@rambla.house" in ve

    def test_summary_con_titulo(self):
        ve = clase_taller_to_vevent(self._clase(titulo="Clase 1"), taller_nombre="Semiótica")
        assert "SUMMARY:Clase 1 — Semiótica" in ve

    def test_summary_sin_titulo_cae_al_nombre_del_taller(self):
        ve = clase_taller_to_vevent(self._clase(titulo=""), taller_nombre="Semiótica")
        assert "SUMMARY:Semiótica" in ve
        assert "—" not in ve

    def test_location_y_descripcion_opcionales(self):
        ve = clase_taller_to_vevent(
            self._clase(descripcion="Fundamentos"),
            taller_nombre="Semiótica", location="Estudio Rambla",
        )
        assert "LOCATION:Estudio Rambla" in ve
        assert "DESCRIPTION:Fundamentos" in ve

    def test_hora_fin_no_mayor_a_inicio_usa_1h_de_duracion(self):
        # Dato corrupto (fin <= inicio): no debe producir un evento invertido.
        ve = clase_taller_to_vevent(
            self._clase(hora_inicio_min=600, hora_fin_min=600), taller_nombre="Semiótica",
        )
        assert "DTSTART:20260903T100000" in ve
        assert "DTEND:20260903T110000" in ve

    def test_recordatorio_dos_horas_antes(self):
        ve = clase_taller_to_vevent(self._clase(), taller_nombre="Semiótica")
        assert "TRIGGER:-PT2H" in ve

    def test_sin_id_devuelve_vacio(self):
        assert clase_taller_to_vevent(self._clase(id=None), taller_nombre="Semiótica") == ""

    def test_sin_fecha_devuelve_vacio(self):
        assert clase_taller_to_vevent(self._clase(fecha=None), taller_nombre="Semiótica") == ""


class TestClasesTallerToIcs:
    def test_una_vevent_por_clase(self):
        clases = [
            {"id": 1, "fecha": "2026-09-03", "hora_inicio_min": 1140, "hora_fin_min": 1260, "titulo": "Clase 1"},
            {"id": 2, "fecha": "2026-09-10", "hora_inicio_min": 1140, "hora_fin_min": 1260, "titulo": "Clase 2"},
        ]
        ics = clases_taller_to_ics(clases, taller_nombre="Semiótica")
        assert ics.count("BEGIN:VEVENT") == 2
        assert ics.count("END:VEVENT") == 2
        assert "X-WR-CALNAME:Semiótica" in ics
        assert "METHOD:PUBLISH" in ics

    def test_clase_invalida_se_omite_sin_romper_las_demas(self):
        clases = [
            {"id": None, "fecha": "2026-09-03", "hora_inicio_min": 1140, "hora_fin_min": 1260},
            {"id": 2, "fecha": "2026-09-10", "hora_inicio_min": 1140, "hora_fin_min": 1260, "titulo": "Clase 2"},
        ]
        ics = clases_taller_to_ics(clases, taller_nombre="Semiótica")
        assert ics.count("BEGIN:VEVENT") == 1
        assert "UID:taller-clase-2@rambla.house" in ics

    def test_sin_clases_validas_devuelve_vacio(self):
        assert clases_taller_to_ics([], taller_nombre="Semiótica") == ""
        assert clases_taller_to_ics([{"id": None, "fecha": None}], taller_nombre="Semiótica") == ""
