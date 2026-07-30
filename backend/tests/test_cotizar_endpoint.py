"""Tests del endpoint de cotización canónica (`POST /api/cotizar`).

El endpoint es la fuente única del total del carrito: el front manda solo
`items` (equipo_id + cantidad) y fechas; el backend pone los precios (de
`equipos`), el perfil/descuento del cliente y devuelve el desglose de
`services.precios.calcular_total`. Reemplaza el cálculo duplicado del front
(`src/lib/cart-total.ts`). Ver #617.

Estilo unitario (sin TestClient): se llama a la función con un FakeConn y
`get_session` monkeypatcheado, como el resto de los tests del módulo.
"""

import pytest
from starlette.requests import Request as StarletteRequest

import services.alquileres.queries.cotizacion as alq
from routes.alquileres import cotizar, CotizarRequest, CotizarItem

# slowapi valida con isinstance(request, StarletteRequest) → necesita una instancia real.
_TEST_SCOPE = {
    "type": "http",
    "method": "POST",
    "path": "/api/cotizar",
    "headers": [],
    "query_string": b"",
    "client": ("127.0.0.1", 1234),
    "app": type("_App", (), {"state": type("_State", (), {})()})(),
}


def FakeReq() -> StarletteRequest:
    return StarletteRequest(_TEST_SCOPE)


pytestmark = pytest.mark.unit


class FakeConn:
    """Conn fake: precios por equipo, fila de cliente y puntos de descuento
    por jornadas, resueltos según el SQL que llega."""

    def __init__(self, precios, perfil=None, descuento=0, descuentos_jornada=None,
                 perfiles_por_id=None):
        self.precios = precios                       # {equipo_id: precio_jornada}
        self.perfil = perfil
        self.descuento = descuento
        self.descuentos_jornada = descuentos_jornada or []
        # {cliente_id: (perfil, descuento)} — para verificar QUÉ cliente se usó.
        self.perfiles_por_id = perfiles_por_id
        self._sql = ""
        self._params = ()
        self.closed = 0  # cuántas veces se devolvió la conexión al pool

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        self.closed += 1

    def execute(self, sql, params=()):
        self._sql = sql
        self._params = params
        return self

    def fetchone(self):
        if "FROM equipos" in self._sql:
            eid = self._params[0]
            if eid in self.precios:
                return {"precio_jornada": self.precios[eid], "tipo": "simple"}
            return None
        if "FROM clientes" in self._sql:
            if self.perfiles_por_id is not None:
                row = self.perfiles_por_id.get(self._params[0])
                return {"perfil_impuestos": row[0], "descuento": row[1]} if row else None
            return {"perfil_impuestos": self.perfil, "descuento": self.descuento}
        return None

    def fetchall(self):
        if "FROM descuentos_jornada" in self._sql:
            return [{"jornadas": j, "pct": p} for j, p in self.descuentos_jornada]
        # Batch query para equipos: SELECT id, precio_jornada, tipo FROM equipos WHERE id IN (...)
        if "FROM equipos" in self._sql and "IN" in self._sql:
            return [
                {"id": eid, "precio_jornada": precio, "tipo": "simple"}
                for eid, precio in self.precios.items()
                if eid in self._params
            ]
        return []


@pytest.fixture
def patch_db(monkeypatch):
    """Devuelve un setter que instala un FakeConn + sesión en el módulo.

    También deshabilita la inyección de headers de rate-limit: cotizar()
    devuelve un dict (no un starlette Response), y slowapi con headers_enabled
    falla al intentar inyectar en un dict. No afecta el comportamiento del
    endpoint — solo elimina la necesidad de un objeto Response real en tests.
    """
    import rate_limit
    monkeypatch.setattr(rate_limit.limiter, "_inject_headers", lambda *a, **kw: None)

    def _install(conn, session=None):
        monkeypatch.setattr(alq, "get_db", lambda: conn)
        monkeypatch.setattr(alq, "get_session", lambda request: session)

    return _install


def _req(items, fecha_desde=None, fecha_hasta=None):
    return CotizarRequest(
        items=[CotizarItem(equipo_id=e, cantidad=c) for e, c in items],
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


class TestAnonimo:
    """Sin sesión → consumidor_final, sin descuento de cliente, sin IVA."""

    def test_sin_fechas_una_jornada(self, patch_db):
        # Sin fechas y sin cliente → estimado de UNA jornada, sin IVA/descuento.
        patch_db(FakeConn(precios={7: 10000}), session=None)
        out = cotizar(_req([(7, 1)]), FakeReq())

        assert out["jornadas"] == 1
        assert out["bruto"] == 10000
        assert out["neto"] == 10000
        assert out["con_iva"] is False
        assert out["iva_monto"] == 0
        assert out["total_final"] == 10000
        assert out["subtotal_por_jornada"] == 10000
        assert out["descuento_origen"] == "ninguno"

    def test_sin_fechas_cliente_ri_sigue_siendo_estimado(self, patch_db):
        # Aunque haya cliente RI logueado, sin fechas NO se suma IVA (estimado).
        patch_db(
            FakeConn(precios={7: 10000}, perfil="responsable_inscripto", descuento=10),
            session={"role": "cliente", "cliente_id": 42},
        )
        out = cotizar(_req([(7, 1)]), FakeReq())

        assert out["jornadas"] == 1
        assert out["con_iva"] is False
        assert out["iva_monto"] == 0
        assert out["descuento_monto"] == 0
        assert out["total_final"] == 10000

    def test_con_fechas_siete_jornadas(self, patch_db):
        patch_db(FakeConn(precios={7: 10000}), session=None)
        out = cotizar(
            _req([(7, 1)], "2026-06-01T10:00:00", "2026-06-08T10:00:00"),
            FakeReq(),
        )

        assert out["jornadas"] == 7
        assert out["bruto"] == 70000
        assert out["total_final"] == 70000

    def test_varios_items(self, patch_db):
        patch_db(FakeConn(precios={1: 5000, 2: 3000}), session=None)
        out = cotizar(_req([(1, 2), (2, 1)]), FakeReq())

        # (5000×2 + 3000×1) × 1 jornada = 13000
        assert out["bruto"] == 13000
        assert out["total_final"] == 13000


class TestResponsableInscripto:
    """Cliente logueado RI → IVA 21% sobre el neto."""

    def test_iva_sobre_neto(self, patch_db):
        patch_db(
            FakeConn(precios={7: 10000}, perfil="responsable_inscripto"),
            session={"role": "cliente", "cliente_id": 42},
        )
        out = cotizar(
            _req([(7, 1)], "2026-06-01T10:00:00", "2026-06-08T10:00:00"),
            FakeReq(),
        )

        # 70000 neto + 21% = 84700
        assert out["neto"] == 70000
        assert out["con_iva"] is True
        assert out["iva_pct"] == 21.0
        assert out["iva_monto"] == 14700
        assert out["total_final"] == 84700

    def test_descuento_cliente_y_iva(self, patch_db):
        patch_db(
            FakeConn(precios={7: 10000}, perfil="responsable_inscripto", descuento=10),
            session={"role": "cliente", "cliente_id": 42},
        )
        # Con fechas (1 jornada por ser mismo día +) → modo firme.
        out = cotizar(
            _req([(7, 1)], "2026-06-01T10:00:00", "2026-06-02T10:00:00"),
            FakeReq(),
        )

        # 10000 bruto - 10% = 9000 neto; IVA 21% = 1890; total 10890
        assert out["descuento_monto"] == 1000
        assert out["neto"] == 9000
        assert out["iva_monto"] == 1890
        assert out["total_final"] == 10890
        assert out["descuento_origen"] == "cliente"


class TestAdmin:
    """El builder admin cotiza para OTRO cliente vía `cliente_id`."""

    def test_admin_usa_cliente_id(self, patch_db, monkeypatch):
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConn(precios={7: 10000}, perfil="responsable_inscripto"),
            session={"email": "admin@test.com"},  # sesión admin, sin cliente_id
        )
        data = CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-08T10:00:00",
            cliente_id=99,
        )
        out = cotizar(data, FakeReq())

        # Aplicó el perfil RI del cliente 99 → IVA sobre 70000.
        assert out["con_iva"] is True
        assert out["total_final"] == 84700

    def test_admin_override_descuento(self, patch_db, monkeypatch):
        # El admin edita el descuento en vivo → override sobre el del cliente.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConn(precios={7: 10000}, perfil="consumidor_final", descuento=0),
            session={"email": "admin@test.com"},
        )
        data = CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-08T10:00:00",
            cliente_id=99,
            descuento_pct=20,
        )
        out = cotizar(data, FakeReq())

        # 70000 - 20% = 56000 (cliente tenía 0% guardado; ganó el override).
        assert out["descuento_pct"] == 20.0
        assert out["descuento_monto"] == 14000
        assert out["neto"] == 56000

    def test_no_admin_ignora_descuento_override(self, patch_db, monkeypatch):
        monkeypatch.setattr(alq, "is_admin_email", lambda email: False)
        patch_db(
            FakeConn(precios={7: 10000}),
            session={"role": "cliente", "cliente_id": 42},
        )
        data = CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-08T10:00:00",
            descuento_pct=50,
        )
        out = cotizar(data, FakeReq())

        # Cliente no puede auto-aplicarse descuento → 0%.
        assert out["descuento_monto"] == 0
        assert out["neto"] == 70000

    def test_cliente_logueado_no_puede_cotizar_para_otro(self, patch_db, monkeypatch):
        # Seguridad: un cliente logueado que manda el cliente_id de OTRO no
        # cotiza con el perfil ajeno → se usa SIEMPRE el del logueado.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: False)
        patch_db(
            FakeConn(
                precios={7: 10000},
                perfiles_por_id={
                    42: ("consumidor_final", 0),       # el logueado
                    99: ("responsable_inscripto", 0),  # otro (RI)
                },
            ),
            session={"role": "cliente", "cliente_id": 42},
        )
        data = CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-08T10:00:00",
            cliente_id=99,  # intenta cotizar como el cliente 99 (RI)
        )
        out = cotizar(data, FakeReq())

        # Usó el perfil del 42 (consumidor_final) → sin IVA. Ignoró el 99.
        assert out["con_iva"] is False
        assert out["total_final"] == 70000

    def test_no_admin_ignora_cliente_id(self, patch_db, monkeypatch):
        # Sesión NO admin no puede cotizar para terceros → sin perfil aplicado.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: False)
        patch_db(
            FakeConn(precios={7: 10000}, perfil="responsable_inscripto"),
            session={"email": "rando@test.com"},
        )
        data = CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-08T10:00:00",
            cliente_id=99,
        )
        out = cotizar(data, FakeReq())

        assert out["con_iva"] is False
        assert out["total_final"] == 70000

    def test_admin_con_sesion_de_cliente_cotiza_para_el_pedido_no_para_si_mismo(
        self, patch_db, monkeypatch
    ):
        """Regresión del "descuento fantasma" (#1231): un dueño que se logueó por el
        PORTAL DE CLIENTE tiene sesión `role="cliente"` + su propio `cliente_id`, y
        además es admin (por email). El builder del back-office debe cotizar para el
        cliente DEL PEDIDO (`data.cliente_id`), NO para la ficha del propio admin.

        Antes, la rama `role=="cliente"` ganaba y el preview leía el descuento de la
        ficha del admin (acá 50%) para TODO pedido, mostrando un "Descuento para
        <cliente del pedido>" que no existía en la base."""
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConn(
                precios={7: 10000},
                perfiles_por_id={
                    42: ("consumidor_final", 50),  # la ficha del PROPIO admin (50% — el fantasma)
                    99: ("consumidor_final", 0),   # el cliente REAL del pedido (sin descuento)
                },
            ),
            # Sesión de cliente PERO con email admin — el caso que dispara el bug.
            session={"role": "cliente", "cliente_id": 42, "email": "duenio@test.com"},
        )
        data = CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-08T10:00:00",
            cliente_id=99,  # el builder arma el pedido para el cliente 99
        )
        out = cotizar(data, FakeReq())

        # Usó el cliente 99 (0%), NO la ficha del admin (50%). Sin descuento fantasma.
        assert out["descuento_monto"] == 0
        assert out["neto"] == 70000  # bruto = 10000 × 7 jornadas, sin descuento
        assert out["descuento_origen"] == "ninguno"

    def test_admin_sin_cliente_id_no_hereda_su_propio_descuento(self, patch_db, monkeypatch):
        """Corolario: un admin (aunque su sesión sea de cliente con descuento) cotizando
        SIN `cliente_id` (pedido nuevo, sin cliente elegido todavía) NO debe heredar su
        propio descuento — target queda en None → sin descuento de cliente."""
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConn(
                precios={7: 10000},
                perfiles_por_id={42: ("consumidor_final", 50)},
            ),
            session={"role": "cliente", "cliente_id": 42, "email": "duenio@test.com"},
        )
        data = CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-08T10:00:00",
            # sin cliente_id
        )
        out = cotizar(data, FakeReq())

        assert out["descuento_monto"] == 0
        assert out["neto"] == 70000  # bruto = 10000 × 7 jornadas, sin descuento
        assert out["descuento_origen"] == "ninguno"


class TestPreciosDesdeBackend:
    """El precio lo pone el backend (de equipos), nunca el front."""

    def test_equipo_inexistente_se_ignora(self, patch_db):
        # equipo 99 no está en precios → se excluye (best-effort).
        patch_db(FakeConn(precios={7: 10000}), session=None)
        out = cotizar(_req([(7, 1), (99, 5)]), FakeReq())

        assert out["bruto"] == 10000  # solo el 7, el 99 ignorado

    def test_cantidad_no_positiva_se_ignora(self, patch_db):
        patch_db(FakeConn(precios={7: 10000}), session=None)
        out = cotizar(_req([(7, 0), (7, -3)]), FakeReq())

        assert out["bruto"] == 0
        assert out["total_final"] == 0

    def test_carrito_vacio(self, patch_db):
        patch_db(FakeConn(precios={}), session=None)
        out = cotizar(_req([]), FakeReq())

        assert out["bruto"] == 0
        assert out["total_final"] == 0


class TestDescuentoJornadas:
    def test_interpola_y_aplica(self, patch_db):
        # Puntos (1,0%) (7,10%): a 7 jornadas → 10%.
        patch_db(
            FakeConn(precios={7: 10000}, descuentos_jornada=[(1, 0), (7, 10)]),
            session=None,
        )
        out = cotizar(
            _req([(7, 1)], "2026-06-01T10:00:00", "2026-06-08T10:00:00"),
            FakeReq(),
        )

        # 70000 - 10% = 63000
        assert out["descuento_pct"] == 10.0
        assert out["descuento_monto"] == 7000
        assert out["neto"] == 63000


class TestConexion:
    """El handler debe devolver SIEMPRE la conexión al pool (close()).

    Regresión: la primera versión hacía `conn = get_db()` sin cerrarla nunca.
    Como `get_db()` toma del ThreadedConnectionPool (maxconn=10) y el pool
    retiene la referencia en `_used`, cada cotización filtraba una conexión de
    forma permanente → tras ~10 llamadas el pool se agotaba y el endpoint colgaba
    en producción. El fix envolvió el cuerpo en try/finally con `conn.close()`.
    """

    def test_devuelve_conexion_al_pool(self, patch_db):
        conn = FakeConn(precios={7: 10000})
        patch_db(conn, session=None)
        cotizar(_req([(7, 1)]), FakeReq())
        assert conn.closed == 1, "cotizar debe cerrar (devolver) la conexión exactamente una vez"

    def test_devuelve_conexion_aunque_falle(self, patch_db):
        # Si algo explota a mitad, la conexión igual se devuelve (finally).
        conn = FakeConn(precios={7: 10000})
        patch_db(conn, session=None)
        # Forzamos un fallo dentro del handler: items None rompe la iteración.
        bad = CotizarRequest.model_construct(items=None, fecha_desde=None, fecha_hasta=None)
        with pytest.raises(Exception):
            cotizar(bad, FakeReq())
        assert conn.closed == 1, "aún ante error, cotizar debe devolver la conexión"


class TestLineasPorEquipo:
    """Desglose POR LÍNEA (`lineas`) — el front lo MUESTRA, no lo calcula (FASE 3).

    Cada línea trae `subtotal_por_jornada` (el "$X/día" del ítem), y `bruto`/`neto`
    del período. Así el caján/teasers renderizan números del backend en vez de
    multiplicar `precio × cantidad × jornadas × (1-desc)` a mano.
    """

    def test_sin_fechas_subtotal_por_jornada_por_linea(self, patch_db):
        patch_db(FakeConn(precios={7: 10000, 9: 5000}), session=None)
        out = cotizar(_req([(7, 2), (9, 1)]), FakeReq())

        lineas = {l["equipo_id"]: l for l in out["lineas"]}
        # 7: 10000 × 2 = 20000/jornada; sin fechas (1 jornada, sin desc) → bruto=neto=20000.
        assert lineas[7]["subtotal_por_jornada"] == 20000
        assert lineas[7]["bruto"] == 20000
        assert lineas[7]["neto"] == 20000
        assert lineas[7]["cantidad"] == 2
        assert lineas[9]["subtotal_por_jornada"] == 5000
        # La suma de subtotales por jornada coincide con el agregado top-level.
        assert sum(l["subtotal_por_jornada"] for l in out["lineas"]) == out["subtotal_por_jornada"]

    def test_con_fechas_y_descuento_neto_por_linea(self, patch_db):
        # Cliente con 10% de descuento, 7 jornadas.
        patch_db(
            FakeConn(precios={7: 10000}, descuento=10),
            session={"role": "cliente", "cliente_id": 42},
        )
        out = cotizar(
            _req([(7, 1)], "2026-06-01T10:00:00", "2026-06-08T10:00:00"),
            FakeReq(),
        )
        linea = out["lineas"][0]
        # bruto = 10000 × 1 × 7 = 70000; neto = 70000 − 10% = 63000.
        assert linea["bruto"] == 70000
        assert linea["neto"] == 63000
        assert out["descuento_pct"] == 10


class FakeConnProductora(FakeConn):
    """FakeConn + soporte de `productora_miembros`/`productoras` para probar
    el candado de membership del target fiscal (#1240)."""

    def __init__(self, *args, miembro_de=(), productora_perfil="responsable_inscripto", **kwargs):
        super().__init__(*args, **kwargs)
        self.miembro_de = set(miembro_de)  # {(productora_id, cliente_id)}
        self.productora_perfil = productora_perfil

    def execute(self, sql, params=()):
        self._sql = sql
        self._params = params
        return self

    def fetchone(self):
        if "FROM productora_miembros" in self._sql:
            productora_id, cliente_id = self._params
            return {"1": 1} if (productora_id, cliente_id) in self.miembro_de else None
        if "FROM productoras" in self._sql:
            return {
                "perfil_impuestos": self.productora_perfil,
                "razon_social": "Productora de Prueba",
                "domicilio_fiscal": None,
                "email_facturacion": None,
                "cuit": "30500000000",
            }
        return super().fetchone()


class TestTargetFiscalProductora:
    """#1240: `productora_id` en el body SOLO se honra si el cliente de la
    sesión está vinculado — sin esto, cualquier sesión cliente podía cotizar
    con el perfil fiscal de una productora ajena adivinando su id."""

    def test_productora_vinculada_gana_el_perfil(self, patch_db):
        patch_db(
            FakeConnProductora(
                precios={7: 10000},
                perfil="consumidor_final",
                miembro_de={(5, 42)},
                productora_perfil="responsable_inscripto",
            ),
            session={"role": "cliente", "cliente_id": 42},
        )
        data = CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-08T10:00:00",
            productora_id=5,
        )
        out = cotizar(data, FakeReq())

        # Ganó la RI de la productora (con IVA), no el consumidor_final de la cuenta.
        assert out["con_iva"] is True

    def test_productora_no_vinculada_no_se_usa(self, patch_db):
        """El cliente 42 NO está vinculado a la productora 5 — cotiza con SU
        propio perfil (consumidor_final), no con el de la productora ajena."""
        patch_db(
            FakeConnProductora(
                precios={7: 10000},
                perfil="consumidor_final",
                miembro_de=set(),  # sin vínculo
                productora_perfil="responsable_inscripto",
            ),
            session={"role": "cliente", "cliente_id": 42},
        )
        data = CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-08T10:00:00",
            productora_id=5,
        )
        out = cotizar(data, FakeReq())

        # Sin membership, la productora se ignora — sigue en consumidor_final (sin IVA).
        assert out["con_iva"] is False


class FakeConnConPedido(FakeConn):
    """FakeConn + una fila de `alquileres` (para `pedido_id`): así se prueba que
    el preview del editor use el snapshot congelado del pedido, no el descuento
    del cliente en vivo."""

    def __init__(self, *args, pedido=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.pedido = pedido  # {estado, cliente_id, descuento_jornadas_pct, descuento_cliente_pct}
        # `perfil_fiscal_id`/`productora_id` — columnas reales de `alquileres` que el
        # SELECT del endpoint trae siempre; default None para no forzar a cada test
        # existente a declararlas (equivale a un pedido sin target fiscal alternativo).
        if self.pedido is not None:
            self.pedido.setdefault("perfil_fiscal_id", None)
            self.pedido.setdefault("productora_id", None)

    def fetchone(self):
        if "FROM alquileres" in self._sql:
            return self.pedido
        return super().fetchone()


class FakeConnPedidoConPerfilFiscal(FakeConnConPedido):
    """FakeConn + `cliente_perfiles_fiscales`/`productoras` (para resolver el
    target fiscal YA PERSISTIDO en el pedido, no el que manda el body) — misma
    idea que `FakeConnProductora`, pero resuelta desde `alquileres`, no desde
    `data.perfil_fiscal_id`/`data.productora_id`."""

    def __init__(self, *args, perfil_fiscal=None, productora=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.perfil_fiscal = perfil_fiscal  # {"id", "perfil_impuestos", ...} o None
        self.productora = productora

    def fetchone(self):
        if "FROM cliente_perfiles_fiscales" in self._sql:
            return self.perfil_fiscal
        if "FROM productoras" in self._sql:
            return self.productora
        return super().fetchone()


class TestPedidoCongeladoRespetaSnapshot:
    """Editor de un pedido NO-presupuesto (`pedido_id`): el descuento sale del
    SNAPSHOT del pedido (plata congelada), no del descuento del cliente EN VIVO.
    Sin esto, el total del editor divergía de `monto_total` / la lista de pedidos
    cuando al cliente se le cambiaba el descuento DESPUÉS de confirmar el pedido
    (MEMORIA 2026-06-06 "plata congelada")."""

    def _data(self, pedido_id=5):
        return CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-02T10:00:00",  # 1 jornada
            cliente_id=99,
            pedido_id=pedido_id,
        )

    def test_confirmado_usa_snapshot_cero_no_el_vivo(self, patch_db, monkeypatch):
        # Cliente HOY tiene 30% en vivo; el pedido se confirmó con 0% congelado.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, perfil="consumidor_final", descuento=30,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 0},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(), FakeReq())
        # Ganó el snapshot (0%), NO el 30% en vivo → sin descuento.
        assert out["descuento_monto"] == 0
        assert out["neto"] == 10000
        assert out["descuento_origen"] == "ninguno"

    def test_confirmado_con_snapshot_positivo_lo_respeta(self, patch_db, monkeypatch):
        # El pedido se congeló con 10%; el cliente hoy tiene 30%. Gana el 10% del snapshot.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, perfil="consumidor_final", descuento=30,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 10},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(), FakeReq())
        assert out["descuento_pct"] == 10
        assert out["descuento_monto"] == 1000
        assert out["neto"] == 9000
        assert out["descuento_origen"] == "cliente"

    def test_presupuesto_sigue_el_descuento_en_vivo(self, patch_db, monkeypatch):
        # Un presupuesto SÍ debe seguir el descuento del cliente en vivo aunque se
        # pase pedido_id (el builder sigue al cliente que el admin elija).
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, perfil="consumidor_final", descuento=30,
                pedido={"estado": "solicitado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 0},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(), FakeReq())
        # Presupuesto → el 30% en vivo SÍ aplica (bruto 10000 − 30% = 7000).
        assert out["descuento_pct"] == 30
        assert out["neto"] == 7000
        assert out["descuento_origen"] == "cliente"

    def test_no_admin_ignora_pedido_id(self, patch_db, monkeypatch):
        # Sesión no-admin no puede forzar el snapshot de un pedido ajeno vía pedido_id.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: False)
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, descuento=0,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 50},
            ),
            session={"role": "cliente", "cliente_id": 42},
        )
        out = cotizar(self._data(), FakeReq())
        # El pedido_id se ignora (no admin) → sin descuento fantasma del snapshot ajeno.
        assert out["descuento_monto"] == 0
        assert out["neto"] == 10000

    def test_snapshot_congela_el_descuento_pero_el_iva_sigue_en_vivo(self, patch_db, monkeypatch):
        # El descuento sale del snapshot (10%), pero el IVA del perfil RI del
        # cliente se resuelve EN VIVO — el fix congela SOLO el descuento.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, perfil="responsable_inscripto", descuento=30,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 10},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(), FakeReq())
        # Descuento 10% (snapshot, NO el 30% vivo) → neto 9000; IVA 21% en vivo → 1890.
        assert out["descuento_pct"] == 10
        assert out["neto"] == 9000
        assert out["con_iva"] is True
        assert out["iva_monto"] == 1890
        assert out["total_final"] == 10890

    def test_override_manual_del_admin_gana_sobre_el_snapshot(self, patch_db, monkeypatch):
        # El override manual del admin (en vivo) gana OUTRIGHT sobre el snapshot
        # de cliente/jornadas (jerarquía #1219) — el fix no lo congela.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, perfil="consumidor_final", descuento=30,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 10},
            ),
            session={"email": "admin@test.com"},
        )
        data = CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-02T10:00:00",
            cliente_id=99, pedido_id=5, descuento_pct=25,
        )
        out = cotizar(data, FakeReq())
        # El manual 25% gana sobre el snapshot 10% del cliente → neto 7500.
        assert out["descuento_pct"] == 25
        assert out["neto"] == 7500
        assert out["descuento_origen"] == "manual"


class TestPedidoCongeladoUsaTargetFiscalDelPedido:
    """Bug real (encontrado comparando el 'Desglose' del admin contra la Factura
    ARCA de un pedido ya facturado): el editor de un pedido EXISTENTE cotizaba
    el IVA con el perfil DEFAULT de la cuenta (`clientes.perfil_impuestos`),
    ignorando que ESE pedido puntual quedó atado a un perfil fiscal alternativo
    o productora (selector "Facturar a nombre de" del checkout, #1240,
    `alquileres.perfil_fiscal_id`/`productora_id`) — mismo target que SÍ resuelve
    `services.finanzas_flujo.pedido.desglose_de_pedido` (el que usa la
    facturación real). Antes de este fix, la página del pedido mostraba "sin
    IVA" mientras la Factura C/A emitida para el mismo pedido sí incluía el 21%
    — dos totales del mismo pedido que no podían coincidir."""

    def _data(self, pedido_id=5):
        return CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-02T10:00:00",  # 1 jornada
            cliente_id=99,
            pedido_id=pedido_id,
        )

    def test_perfil_fiscal_del_pedido_gana_sobre_default_de_la_cuenta(self, patch_db, monkeypatch):
        # Cuenta default: consumidor_final (sin IVA). El PEDIDO quedó atado a un
        # perfil fiscal personal RI (`perfil_fiscal_id=7`) — tiene que ganar ese.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConnPedidoConPerfilFiscal(
                precios={7: 10000}, perfil="consumidor_final", descuento=0,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 0,
                        "perfil_fiscal_id": 7, "productora_id": None},
                perfil_fiscal={"perfil_impuestos": "responsable_inscripto",
                               "razon_social": "Bruno D'Onofrio", "domicilio_fiscal": None,
                               "email_facturacion": None, "cuit": "20372380099"},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(), FakeReq())
        # 10000 neto + 21% = 12100 — NO 10000 "sin IVA" (el bug mostraba esto último).
        assert out["neto"] == 10000
        assert out["con_iva"] is True
        assert out["iva_monto"] == 2100
        assert out["total_final"] == 12100

    def test_productora_del_pedido_gana_sobre_default_de_la_cuenta(self, patch_db, monkeypatch):
        # Mismo caso, pero el pedido se facturó a nombre de una productora RI.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConnPedidoConPerfilFiscal(
                precios={7: 10000}, perfil="consumidor_final", descuento=0,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 0,
                        "perfil_fiscal_id": None, "productora_id": 5},
                productora={"perfil_impuestos": "responsable_inscripto",
                            "razon_social": "Productora SA", "domicilio_fiscal": None,
                            "email_facturacion": None, "cuit": "30500000000"},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(), FakeReq())
        assert out["con_iva"] is True
        assert out["iva_monto"] == 2100
        assert out["total_final"] == 12100

    def test_sin_target_fiscal_en_el_pedido_sigue_el_default_de_la_cuenta(self, patch_db, monkeypatch):
        # El pedido NO eligió perfil/productora alternativo (ambos None, el caso
        # común) → sigue el comportamiento de siempre: perfil default de la cuenta.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConnPedidoConPerfilFiscal(
                precios={7: 10000}, perfil="consumidor_final", descuento=0,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 0},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(), FakeReq())
        assert out["con_iva"] is False
        assert out["total_final"] == 10000


class TestPedidoConFacturaCVigente:
    """El dueño probó en staging: un pedido con Factura C YA EMITIDA (emisor
    Monotributo, nunca suma IVA — 2026-07-27) seguía mostrando el Desglose/
    Cobranza como si el cliente fuera a pagar el 21% de su perfil RI —
    desfasaje real entre lo que el pedido dice que falta cobrar y lo que la
    factura real ya cobró. `factura_c_vigente` (monkeypatcheado acá — su
    propia lógica de query vive y se prueba en `test_facturacion_engine.py`)
    tiene que apagar el IVA del Desglose/Cobranza cuando ya hay una Factura C."""

    def _data(self, pedido_id=5):
        return CotizarRequest(
            items=[CotizarItem(equipo_id=7, cantidad=1)],
            fecha_desde="2026-06-01T10:00:00",
            fecha_hasta="2026-06-02T10:00:00",  # 1 jornada
            cliente_id=99,
            pedido_id=pedido_id,
        )

    def test_factura_c_emitida_apaga_el_iva_aunque_el_cliente_sea_ri(self, patch_db, monkeypatch):
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        monkeypatch.setattr(alq, "factura_c_vigente", lambda pedido_id, conn: True)
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, perfil="responsable_inscripto", descuento=0,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 0},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(), FakeReq())
        # Sin la Factura C, esto daría con_iva=True/total_final=12100 (21% sobre
        # 10000) — con ella, el pedido tiene que mostrar lo que se cobró de verdad.
        assert out["neto"] == 10000
        assert out["con_iva"] is False
        assert out["iva_monto"] == 0
        assert out["total_final"] == 10000

    def test_sin_factura_c_sigue_sumando_iva_del_perfil_ri(self, patch_db, monkeypatch):
        # Control: sin factura (o con una Factura A), el comportamiento no cambia.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        monkeypatch.setattr(alq, "factura_c_vigente", lambda pedido_id, conn: False)
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, perfil="responsable_inscripto", descuento=0,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 0},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(), FakeReq())
        assert out["con_iva"] is True
        assert out["iva_monto"] == 2100
        assert out["total_final"] == 12100

    def test_presupuesto_no_chequea_factura_c(self, patch_db, monkeypatch):
        # Un presupuesto (`estado='solicitado'`) nunca tiene factura — pero
        # además `pedido_congelado` ya es None para ese estado (ver
        # TestPedidoCongeladoRespetaSnapshot), así que el chequeo ni corre.
        # Si `factura_c_vigente` devolviera True por error acá, este test lo cazaría.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        monkeypatch.setattr(
            alq, "factura_c_vigente",
            lambda pedido_id, conn: (_ for _ in ()).throw(AssertionError("no debería llamarse")),
        )
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, perfil="responsable_inscripto", descuento=0,
                pedido={"estado": "solicitado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 0},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(), FakeReq())
        assert out["con_iva"] is True
        assert out["total_final"] == 12100


class TestRespetarPrecioItemCobroModo:
    """Bug real encontrado en vivo (Fase 1, #1308) mientras se probaba el
    Desglose de un pedido de taller: con `respetar_precio_item` (el editor
    admin de un pedido existente), un ítem de CATÁLOGO siempre se etiquetaba
    `cobro_modo="jornada"` para `calcular_total`, sin importar el cobro_modo
    REAL persistido en la línea. Un ítem `cobro_modo='fijo'` (ej. el
    centinela del Estudio en un pedido de taller, cuyo rango es el mes
    contable completo) se multiplicaba igual por las jornadas del rango —
    para 31 jornadas, un pedido de $1.200.000 mostraba $37.200.000 en el
    Desglose/Cobranza del editor, mintiendo sobre cuánto falta cobrar. El
    front YA mandaba el `cobro_modo` real (`lib/cotizacion.ts`); el bug era
    puramente que el backend lo ignoraba para ítems de catálogo."""

    def _data(self, cobro_modo=None):
        item = CotizarItem(
            equipo_id=7, cantidad=1, precio_jornada=1_200_000, cobro_modo=cobro_modo,
        )
        return CotizarRequest(
            items=[item],
            fecha_desde="2026-08-01T00:00:00",
            fecha_hasta="2026-08-31T23:59:59",  # 31 jornadas
            cliente_id=99,
            pedido_id=5,
            respetar_precio_item=True,
        )

    def test_item_fijo_no_se_multiplica_por_jornadas(self, patch_db, monkeypatch):
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, descuento=0,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 0},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(cobro_modo="fijo"), FakeReq())
        assert out["neto"] == 1_200_000, (
            f"cobro_modo='fijo' no debe multiplicarse por jornadas (31); dio {out['neto']}"
        )

    def test_item_jornada_si_se_multiplica_por_jornadas(self, patch_db, monkeypatch):
        # Control: el caso normal (catálogo, cobro por jornada) tiene que
        # seguir multiplicando — el fix no debe apagar esto por accidente.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, descuento=0,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 0},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(cobro_modo="jornada"), FakeReq())
        assert out["neto"] == 1_200_000 * 31

    def test_sin_cobro_modo_explicito_default_jornada(self, patch_db, monkeypatch):
        # Si el front no manda cobro_modo (ej. un caller viejo), el default
        # sigue siendo "jornada" — mismo comportamiento que antes del fix.
        monkeypatch.setattr(alq, "is_admin_email", lambda email: True)
        patch_db(
            FakeConnConPedido(
                precios={7: 10000}, descuento=0,
                pedido={"estado": "confirmado", "cliente_id": 99,
                        "descuento_jornadas_pct": 0, "descuento_cliente_pct": 0},
            ),
            session={"email": "admin@test.com"},
        )
        out = cotizar(self._data(cobro_modo=None), FakeReq())
        assert out["neto"] == 1_200_000 * 31
