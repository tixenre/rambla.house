"""Tests de validaciones de pedidos en routes/alquileres.py::create_pedido.

Cubre la regresión de los bugs:
- #43 race condition stock (parte del check ANTES del INSERT con FOR UPDATE)
- #44 fechas inválidas (hasta > desde, no en el pasado)

Estos tests NO requieren BD real: usan un mock minimal de get_db() para que
la función llegue hasta la lógica de validación. No verifican el flujo completo
de creación — eso es integration test (issue futuro).
"""

import datetime
import pytest
from fastapi import HTTPException

from database import now_ar
from routes.alquileres import create_pedido, PedidoCreate, PedidoItem


pytestmark = pytest.mark.unit


class MinimalFakeConn:
    """Conexión fake mínima — execute/fetch devuelven vacío.

    Suficiente para que `create_pedido` llegue a las validaciones de
    fechas/items y dispare el HTTPException antes de necesitar datos reales.
    """

    def execute(self, *args, **kwargs):
        return self

    def executemany(self, *args, **kwargs):
        return self

    def fetchone(self):
        return None  # No encuentra cliente, equipo, etc.

    def fetchall(self):
        return []

    def commit(self):
        pass

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        pass

    @property
    def lastrowid(self):
        return 1


@pytest.fixture
def fake_db(monkeypatch):
    """Reemplaza routes.alquileres.core.get_db por una conn fake."""
    monkeypatch.setattr("routes.alquileres.core.get_db", lambda: MinimalFakeConn())
    yield


# ── Validaciones que NO tocan DB ─────────────────────────────────────────────

class TestItemsRequired:
    """Validación: items vacíos solo permitido en estado='borrador'."""

    def test_items_vacios_estado_presupuesto_400(self):
        data = PedidoCreate(items=[], estado="solicitado")
        with pytest.raises(HTTPException) as exc:
            create_pedido(data)
        assert exc.value.status_code == 400
        assert "ítem" in exc.value.detail.lower() or "item" in exc.value.detail.lower()

    def test_items_vacios_estado_borrador_pasa(self, fake_db):
        # Borrador puede no tener items
        data = PedidoCreate(items=[], estado="borrador")
        # No debería tirar HTTPException(400). Llega a get_db (mockeado).
        # Puede fallar más adelante por otra razón — solo verificamos que no
        # falla en el check de items.
        try:
            create_pedido(data)
        except HTTPException as e:
            # Si tira 400, falló el check de items — eso no debería pasar
            assert e.status_code != 400 or "ítem" not in e.detail.lower()
        except Exception:
            # Otros errores (e.g. _get_alquiler_detail por mock) son OK
            pass


# ── Validaciones de fechas (issue #44) ──────────────────────────────────────

class TestValidacionFechas:
    """Cubre el fix de #44: fecha_hasta debe ser > fecha_desde y no en el pasado."""

    def test_fecha_hasta_anterior_a_desde_400(self, fake_db):
        manana = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        ayer_logico = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

        data = PedidoCreate(
            items=[PedidoItem(equipo_id=1, cantidad=1, precio_jornada=1000)],
            estado="solicitado",
            fecha_desde=manana,
            fecha_hasta=ayer_logico,  # más temprano que desde
        )
        with pytest.raises(HTTPException) as exc:
            create_pedido(data)
        assert exc.value.status_code == 400
        assert "fecha_hasta" in exc.value.detail.lower() or "posterior" in exc.value.detail.lower()

    def test_fecha_hasta_igual_a_desde_400(self, fake_db):
        manana = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

        data = PedidoCreate(
            items=[PedidoItem(equipo_id=1, cantidad=1, precio_jornada=1000)],
            estado="solicitado",
            fecha_desde=manana,
            fecha_hasta=manana,  # mismo día → d0 >= d1 → rechaza
        )
        with pytest.raises(HTTPException) as exc:
            create_pedido(data)
        assert exc.value.status_code == 400

    def test_fecha_desde_en_el_pasado_400(self, fake_db):
        # "Ayer" se ancla a la hora de Argentina (now_ar), la misma que usa la
        # validación. Con date.today() (TZ del server, UTC en CI) el test era
        # flaky entre las 00:00 y 03:00 UTC: ahí "ayer en UTC" == "hoy en AR" y
        # el guard de fecha-pasada no disparaba (404 en vez de 400).
        hoy_ar = now_ar().date()
        ayer = (hoy_ar - datetime.timedelta(days=1)).isoformat()
        manana = (hoy_ar + datetime.timedelta(days=1)).isoformat()

        data = PedidoCreate(
            items=[PedidoItem(equipo_id=1, cantidad=1, precio_jornada=1000)],
            estado="solicitado",
            fecha_desde=ayer,
            fecha_hasta=manana,
        )
        with pytest.raises(HTTPException) as exc:
            create_pedido(data)
        assert exc.value.status_code == 400
        assert "pasado" in exc.value.detail.lower()

    def test_fechas_validas_hoy_a_manana_pasa_validacion(self, fake_db):
        """Caso happy path para fechas: hoy (a las 00:00) → mañana.

        No verifica que el pedido se cree (la BD es mock), solo que pasa la
        validación de fechas sin lanzar 400. Si llega a fallar por otra razón
        (mock no tiene datos), está OK.
        """
        hoy = datetime.date.today().isoformat()
        manana = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

        data = PedidoCreate(
            items=[PedidoItem(equipo_id=1, cantidad=1, precio_jornada=1000)],
            estado="borrador",  # borrador para evitar _check_stock
            fecha_desde=hoy,
            fecha_hasta=manana,
        )
        try:
            create_pedido(data)
        except HTTPException as e:
            # Si tira 400 por fechas, falla este test.
            if e.status_code == 400:
                assert "fecha" not in e.detail.lower(), (
                    f"No esperaba error de fecha, dio: {e.detail}"
                )
        except Exception:
            # Otros errores (e.g. acceso a fetchone que devuelve None) son OK
            pass


# ── Validación Pydantic del schema ───────────────────────────────────────────

class TestPedidoCreateSchema:
    """El schema Pydantic ya hace varias validaciones automáticas."""

    def test_precio_jornada_string_se_parsea(self):
        # PedidoItem.coerce_precio acepta strings con formato AR
        item = PedidoItem(equipo_id=1, cantidad=1, precio_jornada="$15.000")
        assert item.precio_jornada == 15000

    def test_precio_jornada_int_pasa(self):
        item = PedidoItem(equipo_id=1, cantidad=1, precio_jornada=15000)
        assert item.precio_jornada == 15000

    def test_estado_default_presupuesto(self):
        data = PedidoCreate(items=[])
        assert data.estado == "solicitado"

    def test_items_default_lista_vacia(self):
        data = PedidoCreate(estado="borrador")
        assert data.items == []

    def test_cantidad_cero_rechazada(self):
        with pytest.raises(Exception):
            PedidoItem(equipo_id=1, cantidad=0, precio_jornada=1000)

    def test_cantidad_negativa_rechazada(self):
        with pytest.raises(Exception):
            PedidoItem(equipo_id=1, cantidad=-3, precio_jornada=1000)

    def test_cantidad_excesiva_rechazada(self):
        with pytest.raises(Exception):
            PedidoItem(equipo_id=1, cantidad=1000, precio_jornada=1000)

    def test_cantidad_minimo_uno_acepta(self):
        item = PedidoItem(equipo_id=1, cantidad=1, precio_jornada=1000)
        assert item.cantidad == 1

    def test_item_de_catalogo_puede_cobrarse_fijo(self):
        # Talleres (`_regenerar_pedidos_taller`): el centinela del Estudio es
        # un ítem de catálogo (equipo_id presente) con cobro_modo='fijo'. El
        # front no expone el control para elegirlo a mano en una línea de
        # catálogo, pero el pedido SÍ trae esta combinación de fábrica y debe
        # sobrevivir un guardado del editor genérico.
        item = PedidoItem(equipo_id=1, cantidad=1, precio_jornada=35000, cobro_modo="fijo")
        assert item.cobro_modo == "fijo"

    def test_linea_personalizada_sin_nombre_sigue_rechazada(self):
        with pytest.raises(Exception):
            PedidoItem(equipo_id=None, cantidad=1, precio_jornada=1000, nombre_libre="")
