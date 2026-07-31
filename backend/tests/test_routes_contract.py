"""Contrato HTTP de los routes de pedidos — red previa a #501 (#862).

Cuando la modularización del backend (#501) mueva los handlers de
`routes/alquileres.py` y `routes/cliente_portal.py` a paquetes/routers nuevos,
lo que NO debe cambiar es el **contrato HTTP externo**. Estos tests lo fijan en
cuatro capas, **sin tocar la DB**. La capa 1 (existencia) lee la tabla de rutas;
las capas 2-4 (guards) mandan requests reales con `TestClient` (app + middleware
+ routing) — esos guards rechazan ANTES de cualquier query, así que el assert no
depende de la DB:

  1. **Existencia** — cada ruta esperada sigue ruteando (no 404/405). Se chequea
     leyendo la tabla de rutas de la app (`route_status`, ver
     `tests/contract_routing.py`), no mandando un request: instantáneo, sin DB, y
     caza también los GET dropeados — el enfoque viejo por-request los perdía
     (caían al catch-all del SPA → 200, no 404). (`test_endpoint_existe`)
  2. **Middleware** — un anónimo no entra a ningún endpoint protegido (401/403).
     (`test_endpoint_protegido_rechaza_anonimo`)
  3. **Guard admin** — una sesión logueada pero NO admin la rechaza el
     `require_admin` del handler (403). (`test_endpoint_admin_rechaza_sesion_no_admin`)
  4. **Guard cliente** — una sesión sin rol cliente la rechaza el
     `require_cliente` (401). (`test_endpoint_cliente_rechaza_sesion_no_cliente`)

Las capas 3-4 son la protección anti-#55 (handler que pierde su guard), que un
refactor de módulos rompe en silencio. El happy-path con datos (Postgres
sembrado) va como fase de integración de #862. Fuente del inventario:
`routes/alquileres.py` + `routes/cliente_portal.py`.
"""
import pytest
from fastapi.testclient import TestClient

import main
from auth.session import signer
from tests.contract_routing import route_status

pytestmark = pytest.mark.unit

# TestClient sin entrar al context manager → NO dispara los eventos de startup
# (scheduler/DB); solo ejercita middleware + guards (la existencia ya no manda
# request, ver `route_status`). `raise_server_exceptions=False`: si un guard
# FALTA, el request llega al handler y este 500ea sin Postgres; queremos ese 500
# como respuesta —no que TestClient re-lance— para que el assert del guard lo lea
# como "guard perdido" en vez de romper el test con una excepción.
client = TestClient(main.app, raise_server_exceptions=False)

# Cookies de sesión firmadas con el MISMO signer de la app (mismo SECRET_KEY de
# tests) — no tocan la DB, los guards deciden por rol/email.
#   · admin:   sesión válida con email en ADMIN_EMAILS (pasa middleware + require_admin).
#   · cliente: sesión válida de cliente (email fuera de ADMIN_EMAILS).
_COOKIE_ADMIN = f"session={signer.dumps({'email': 'admin@test.com', 'name': 'Admin', 'jti': 'contract-admin'})}"
_COOKIE_CLIENTE = f"session={signer.dumps({'email': 'rando@test.com', 'role': 'cliente', 'cliente_id': 1, 'jti': 'contract-cli'})}"


@pytest.fixture(autouse=True)
def _sessions_active(monkeypatch):
    """jti obligatorio: `get_session` exige que la sesión esté viva en la allowlist.
    Las cookies de contrato llevan jti pero no están en la tabla → stubbeamos
    `is_active` para darlas por activas, así el request pasa el chequeo de revocación
    y llega al routing/guard (que es lo que estos tests verifican). Sin esto,
    `get_session` las cortaría en el middleware (401) y `test_endpoint_existe` no
    distinguiría una ruta dropeada de una viva."""
    monkeypatch.setattr("auth.queries.sessions.is_active", lambda jti: {"jti": jti})


# ── Inventario ───────────────────────────────────────────────────────────────
# Endpoints ADMIN: anónimo → 401 (middleware); sesión no-admin → 403 (guard).
_ADMIN = [
    ("POST", "/api/alquileres"),
    ("GET", "/api/alquileres"),
    ("GET", "/api/alquileres/1"),
    ("PATCH", "/api/alquileres/1"),
    ("DELETE", "/api/alquileres/1"),
    ("GET", "/api/alquileres/1/pagos"),
    ("POST", "/api/alquileres/1/pagos"),
    ("POST", "/api/alquileres/1/pagos/1/anular"),
    ("GET", "/api/admin/pagos"),
    ("GET", "/api/descuentos-jornada"),
    ("GET", "/api/descuentos-jornada/interpolar"),
    ("POST", "/api/admin/descuentos-jornada"),
    ("DELETE", "/api/admin/descuentos-jornada/1"),
    ("PATCH", "/api/alquileres/1/datos"),
    ("PUT", "/api/alquileres/1/items"),
    ("GET", "/api/alquileres/1/remito"),
    ("GET", "/api/alquileres/1/detalle-seguro"),
    ("GET", "/api/alquileres/1/checklist-retiro"),
    ("GET", "/api/alquileres/1/contrato"),
    ("POST", "/api/alquileres/1/enviar-documentos"),
    ("POST", "/api/alquileres/1/mail-preview"),
    ("POST", "/api/admin/recordatorios/retiro/run"),
    # cliente_portal.py — solicitudes de modificación (las gestiona el admin)
    ("GET", "/api/admin/solicitudes"),
    ("PATCH", "/api/admin/solicitudes/1"),
]

# Endpoints CLIENTE: anónimo → 401 (middleware); sesión no-cliente → 401 (guard).
_CLIENTE = [
    ("GET", "/api/cliente/me"),
    ("PATCH", "/api/cliente/me"),
    ("POST", "/api/cliente/pedidos"),
    ("GET", "/api/cliente/pedidos"),
    ("GET", "/api/cliente/pedidos/1"),
    ("PATCH", "/api/cliente/pedidos/1/cancelar"),
    ("POST", "/api/cliente/pedidos/1/modificacion"),
    ("DELETE", "/api/cliente/pedidos/1/modificacion/1"),
    ("GET", "/api/cliente/pedidos/1/disponibilidad"),
    ("GET", "/api/cliente/modificacion-config"),
    ("GET", "/api/cliente/pedidos/1/remito"),
    ("GET", "/api/cliente/pedidos/1/remito.pdf"),
    ("GET", "/api/cliente/pedidos/1/contrato"),
    ("GET", "/api/cliente/pedidos/1/contrato.pdf"),
    ("GET", "/api/cliente/pedidos/1/albaran"),
    ("GET", "/api/cliente/pedidos/1/albaran.pdf"),
    ("GET", "/api/cliente/pedidos/1/packing-list"),
    ("GET", "/api/cliente/pedidos/1/packing-list.pdf"),
    ("POST", "/api/cliente/facturacion/verificar-cuit"),
    ("GET", "/api/cliente/favoritos"),
    ("POST", "/api/cliente/favoritos/sync"),
    ("POST", "/api/cliente/favoritos/1"),
    ("DELETE", "/api/cliente/favoritos/1"),
]

# Endpoints PÚBLICOS (anónimo permitido). Solo entran a la capa de existencia.
_PUBLICOS = [
    ("POST", "/api/cotizar"),
    ("GET", "/api/disponibilidad"),
    ("GET", "/api/disponibilidad-dias"),
    ("GET", "/api/cliente/registro-info"),
    ("POST", "/api/cliente/registro"),
]

_PROTEGIDOS = _ADMIN + _CLIENTE
_TODOS = _PROTEGIDOS + _PUBLICOS

# FastAPI valida el body/query (Pydantic) ANTES de ejecutar el cuerpo del
# handler, que es donde vive `require_admin`/`require_cliente`. Para estos
# endpoints, un request con body vacío devuelve 422 antes de llegar al guard →
# no se pueden ejercer en las capas 3-4 sin armar un body válido por-schema
# (frágil, acopla el test al schema → queda como fase de integración de #862).
# Igual están cubiertos por la capa 1 (existencia) y la 2 (anónimo).
_VALIDA_ANTES_DEL_GUARD = {
    ("PATCH", "/api/alquileres/1"),
    ("POST", "/api/alquileres/1/pagos"),
    ("POST", "/api/alquileres/1/pagos/1/anular"),
    ("POST", "/api/admin/descuentos-jornada"),
    ("GET", "/api/descuentos-jornada/interpolar"),  # jornadas: list[int] = Query(...) obligatorio
    ("PUT", "/api/alquileres/1/items"),
    ("POST", "/api/alquileres/1/enviar-documentos"),
    ("PATCH", "/api/admin/solicitudes/1"),
    ("POST", "/api/cliente/pedidos/1/modificacion"),
    ("GET", "/api/cliente/pedidos/1/disponibilidad"),
    ("POST", "/api/cliente/favoritos/sync"),
}
_ADMIN_GUARD = [e for e in _ADMIN if e not in _VALIDA_ANTES_DEL_GUARD]
_CLIENTE_GUARD = [e for e in _CLIENTE if e not in _VALIDA_ANTES_DEL_GUARD]


def _id(pares):
    return [f"{m}_{p}" for m, p in pares]


@pytest.mark.parametrize("method,path", _TODOS, ids=_id(_TODOS))
def test_endpoint_existe(method, path):
    """Cada ruta esperada sigue ruteando (no 404/405). Se chequea leyendo la tabla
    de rutas (`route_status`), NO mandando un request: el request llegaba al
    handler → `get_db()` y sin Postgres colgaba el timeout del pool (era el cuello
    de botella del job `python-tests`). Leer la tabla es instantáneo y, a
    diferencia del enfoque viejo, caza también los GET dropeados (antes caían al
    catch-all del SPA → 200). Cómo → `tests/contract_routing.py`."""
    estado = route_status(method, path)
    assert estado == "full", (
        f"{method} {path} no rutea "
        f"({'método caído → 405' if estado == 'partial' else 'ruta caída → 404'})"
        f" — ¿la movió/renombró un refactor?"
    )


@pytest.mark.parametrize("method,path", _PROTEGIDOS, ids=_id(_PROTEGIDOS))
def test_endpoint_protegido_rechaza_anonimo(method, path):
    """Anónimo (sin cookie) → 401/403 en todo endpoint protegido (lo corta el
    middleware antes de la DB)."""
    res = client.request(method, path, json={})
    assert res.status_code in (401, 403), (
        f"{method} {path} dejó pasar a un anónimo → {res.status_code}"
    )


@pytest.mark.parametrize("method,path", _ADMIN_GUARD, ids=_id(_ADMIN_GUARD))
def test_endpoint_admin_rechaza_sesion_no_admin(method, path):
    """Sesión LOGUEADA pero no-admin → rechazada por el `require_admin` del
    handler (403). Si #501 mueve el handler y se pierde el guard, un no-admin
    pasaría el middleware y llegaría a la lógica → este test lo caza."""
    res = client.request(method, path, json={}, headers={"Cookie": _COOKIE_CLIENTE})
    assert res.status_code in (401, 403), (
        f"{method} {path}: un logueado no-admin no fue rechazado → {res.status_code} "
        f"(¿se perdió require_admin?)"
    )


@pytest.mark.parametrize("method,path", _CLIENTE_GUARD, ids=_id(_CLIENTE_GUARD))
def test_endpoint_cliente_rechaza_sesion_no_cliente(method, path):
    """Sesión LOGUEADA pero sin rol cliente → rechazada por el `require_cliente`
    del handler (401). Protege el guard a nivel handler ante el refactor."""
    res = client.request(method, path, json={}, headers={"Cookie": _COOKIE_ADMIN})
    assert res.status_code in (401, 403), (
        f"{method} {path}: una sesión no-cliente no fue rechazada → {res.status_code} "
        f"(¿se perdió require_cliente?)"
    )
