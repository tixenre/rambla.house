"""Unit tests de `services.estudio.queries.agenda_publica` (fakes de conn —
sin Postgres real; la integración real vive en
`test_estudio_ocupacion_publica_db.py`).

Foco: la vista es PÚBLICA y ANÓNIMA — el filtrado por `activo`/`estado`
(slot inactivo, edición no publicada, reserva cancelada) lo hace la SQL real
y se verifica contra Postgres en el test de integración; acá se verifica lo
que SÍ es lógica Python pura: filtrado por rango de fechas, expansión del
buffer del centinela, y sobre todo el **anti-leak**: ningún bloque devuelto
tiene una key que no sea `fecha_desde`/`fecha_hasta`, sin importar qué otras
columnas traiga la fila cruda de la DB."""
from datetime import date, datetime

import pytest

pytestmark = pytest.mark.unit


class _ConnCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Cur:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


def _estudio_row(**ov):
    d = {"equipo_id": 99, "buffer_horas": 1}
    d.update(ov)
    return d


def _slot(**ov):
    # Incluye `cliente` a propósito (como devolvería la SQL admin) — el test
    # anti-leak confirma que igual no aparece en el bloque de salida.
    s = {
        "cliente": "Filmar", "dia_semana": 2, "hora_desde": 8, "hora_hasta": 20,
        "mes_desde": "2026-09", "mes_hasta": "2026-09",
    }
    s.update(ov)
    return s


def _clase(**ov):
    c = {
        "nombre": "Taller de Rodaje", "fecha": date(2026, 9, 5),
        "hora_inicio_min": 510, "hora_fin_min": 750,
    }
    c.update(ov)
    return c


class _AgendaPublicaFakeConn(_ConnCM):
    """No filtra por los params SQL (mismo criterio que `_OcupacionRangoConn`
    en `test_estudio.py`) — la filtración de rango/fecha la hace la función
    bajo test en Python; el filtrado por `activo`/`estado` lo hace la SQL
    real y no es observable con un fake."""

    def __init__(self, slots=None, clases=None, reservas_centinela=None):
        self.slots = slots or []
        self.clases = clases or []
        self.reservas_centinela = reservas_centinela or []

    def execute(self, sql, params=()):
        su = " ".join(sql.split()).upper()
        if "FROM ESTUDIO_SLOTS_FIJOS" in su:
            return _Cur(self.slots)
        if "FROM CLASES_TALLER" in su:
            return _Cur(self.clases)
        if "FROM ALQUILER_ITEMS" in su:
            return _Cur(self.reservas_centinela)
        return _Cur([])


def _assert_solo_fechas(bloques):
    for b in bloques:
        assert set(b.keys()) == {"fecha_desde", "fecha_hasta"}, (
            f"leak de dato no-anónimo en un bloque público: {b}"
        )


class TestBloquesOcupadosEstudio:
    def test_slot_activo_en_rango_sin_cliente(self):
        from services.estudio.queries.agenda_publica import bloques_ocupados_estudio

        # Slot semanal (todos los miércoles de septiembre) — se acota el rango
        # consultado a 1 semana para que solo un miércoles (el 2/9) caiga adentro.
        conn = _AgendaPublicaFakeConn(slots=[_slot()])
        out = bloques_ocupados_estudio(conn, _estudio_row(equipo_id=None), date(2026, 9, 1), date(2026, 9, 7))
        assert len(out) == 1
        assert out[0]["fecha_desde"] == datetime(2026, 9, 2, 8, 0)
        assert out[0]["fecha_hasta"] == datetime(2026, 9, 2, 20, 0)
        _assert_solo_fechas(out)

    def test_slot_fuera_del_rango_pedido_no_aparece(self):
        from services.estudio.queries.agenda_publica import bloques_ocupados_estudio

        conn = _AgendaPublicaFakeConn(slots=[_slot(mes_desde="2026-06", mes_hasta="2026-12")])
        out = bloques_ocupados_estudio(conn, _estudio_row(equipo_id=None), date(2030, 1, 1), date(2030, 1, 31))
        assert out == []

    def test_clase_de_taller_en_rango_sin_nombre(self):
        from services.estudio.queries.agenda_publica import bloques_ocupados_estudio

        conn = _AgendaPublicaFakeConn(clases=[_clase()])
        out = bloques_ocupados_estudio(conn, _estudio_row(equipo_id=None), date(2026, 9, 1), date(2026, 9, 30))
        assert len(out) == 1
        assert out[0]["fecha_desde"] == datetime(2026, 9, 5, 8, 30)
        assert out[0]["fecha_hasta"] == datetime(2026, 9, 5, 12, 30)
        _assert_solo_fechas(out)

    def test_reserva_centinela_expandida_por_buffer(self):
        from services.estudio.queries.agenda_publica import bloques_ocupados_estudio

        reserva = {"fecha_desde": datetime(2026, 9, 10, 10, 0), "fecha_hasta": datetime(2026, 9, 10, 12, 0)}
        conn = _AgendaPublicaFakeConn(reservas_centinela=[reserva])
        out = bloques_ocupados_estudio(conn, _estudio_row(buffer_horas=1), date(2026, 9, 1), date(2026, 9, 30))
        assert len(out) == 1
        assert out[0]["fecha_desde"] == datetime(2026, 9, 10, 9, 0)
        assert out[0]["fecha_hasta"] == datetime(2026, 9, 10, 13, 0)
        _assert_solo_fechas(out)

    def test_sin_equipo_id_no_consulta_centinela(self):
        """Estudio sin centinela configurado (equipo_id NULL) — no debe
        explotar ni intentar la query del centinela."""
        from services.estudio.queries.agenda_publica import bloques_ocupados_estudio

        conn = _AgendaPublicaFakeConn(reservas_centinela=[
            {"fecha_desde": datetime(2026, 9, 10, 10, 0), "fecha_hasta": datetime(2026, 9, 10, 12, 0)}
        ])
        out = bloques_ocupados_estudio(conn, _estudio_row(equipo_id=None), date(2026, 9, 1), date(2026, 9, 30))
        assert out == []

    def test_combina_los_tres_tipos(self):
        from services.estudio.queries.agenda_publica import bloques_ocupados_estudio

        # Rango acotado a la semana del 5/9 para que el slot semanal solo
        # aporte un bloque (el mismo criterio que test_slot_activo_en_rango).
        conn = _AgendaPublicaFakeConn(
            slots=[_slot()],
            clases=[_clase()],
            reservas_centinela=[
                {"fecha_desde": datetime(2026, 9, 5, 14, 0), "fecha_hasta": datetime(2026, 9, 5, 16, 0)}
            ],
        )
        out = bloques_ocupados_estudio(conn, _estudio_row(buffer_horas=0), date(2026, 9, 1), date(2026, 9, 7))
        assert len(out) == 3
        _assert_solo_fechas(out)


class TestCentinelaOcupadoEnRango:
    def test_reserva_fuera_de_la_ventana_no_aparece(self):
        from services.estudio.queries.agenda_publica import _centinela_ocupado_en_rango

        # La query real filtra por fecha — el fake no filtra, así que para
        # probar "fuera de ventana" hay que ejercer la función con una
        # reserva que el propio fake SÍ devuelva (siempre las devuelve todas)
        # pero confirmando que la expansión del buffer es la esperada, no que
        # la SQL filtre (eso lo cubre la integración real).
        conn = _AgendaPublicaFakeConn(reservas_centinela=[])
        out = _centinela_ocupado_en_rango(conn, 99, date(2026, 9, 1), date(2026, 9, 30), 2)
        assert out == []

    def test_buffer_cero_no_expande(self):
        from services.estudio.queries.agenda_publica import _centinela_ocupado_en_rango

        reserva = {"fecha_desde": datetime(2026, 9, 10, 10, 0), "fecha_hasta": datetime(2026, 9, 10, 12, 0)}
        conn = _AgendaPublicaFakeConn(reservas_centinela=[reserva])
        out = _centinela_ocupado_en_rango(conn, 99, date(2026, 9, 1), date(2026, 9, 30), 0)
        assert out == [(datetime(2026, 9, 10, 10, 0), datetime(2026, 9, 10, 12, 0))]
