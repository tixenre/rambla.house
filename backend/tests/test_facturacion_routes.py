"""Tests HTTP/contrato de routes/facturacion.py — transporte fino.

La lógica de negocio vive en services/facturacion/engine.py (testeada en
test_facturacion_engine.py); acá se clava el contrato del handler: guard de
admin a nivel HTTP (rutea + gatea, sin DB — mismo patrón que
test_clientes_merge_route.py), mapeo de errores (ValueError→400,
RuntimeError→503), y los branches format=html/pdf del PDF on-demand.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

import main
from routes import facturacion as facturacion_routes
from services.facturacion.repo import Factura

pytestmark = pytest.mark.unit

_http = TestClient(main.app, raise_server_exceptions=False)


def _fake_request() -> Request:
    """Request real (mínimo, sin transporte ASGI) — no un SimpleNamespace: los
    endpoints de escritura ahora llevan @limiter.limit (#1209), y slowapi exige
    `isinstance(request, Request)`. `request.state.session` queda sin setear
    (mismo resultado que antes: `getattr(..., "session", None)` → None)."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/x",
        "raw_path": b"/x",
        "headers": [],
        "query_string": b"",
        "client": ("testclient", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


def _fake_factura(estado="emitida") -> Factura:
    return Factura(
        id=1, pedido_id=422, emisor="santini", ambiente="homologacion",
        cbte_tipo=11, pto_vta=2, cbte_nro=1, cae="86261839900000", cae_vto=None,
        doc_tipo=96, doc_nro="42289220", condicion_iva_receptor=5,
        concepto=2, imp_neto=5700, imp_iva=0, imp_total=5700, moneda="PES",
        cliente_cuit=None, razon_social=None, qr_payload=None, pdf_key=None,
        estado=estado, nota_credito_de=None, raw_request=None,
        raw_response=None, errores=None, fecha_emision=None,
        created_at=None, created_by=None,
    )


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def commit(self):
        pass


class _FakeRow(dict):
    """Simula una fila de psycopg (acceso por índice de columna)."""


class _FakeConnConEmail:
    """Como `_FakeConn` pero con `execute` para el SELECT de email del cliente
    (regresión: `enviar_mail_factura` consultaba `c.owner_email`, columna que no
    existe en `clientes` — rompía con UndefinedColumn siempre. Ver `c.email`)."""

    def __init__(self, row=None):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def execute(self, _sql, _params=None):
        row = self._row

        class _R:
            def fetchone(self_inner):
                return row

        return _R()


# ── Guard de admin a nivel HTTP (rutea + gatea, sin DB) ─────────────────────


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/facturas/1/pdf"),
        ("POST", "/api/facturas/1/enviar-mail"),
        ("POST", "/api/facturas/1/nota-credito"),
        ("POST", "/api/alquileres/1/facturar"),
        ("GET", "/api/alquileres/1/facturas"),
        ("GET", "/api/admin/facturas"),
        ("GET", "/api/admin/facturacion/estado"),
        ("GET", "/api/admin/facturacion/layouts"),
        ("POST", "/api/admin/arca/catalogos/refrescar"),
        ("GET", "/api/admin/emisores-arca"),
        ("POST", "/api/admin/emisores-arca"),
        ("PUT", "/api/admin/emisores-arca/1"),
        ("DELETE", "/api/admin/emisores-arca/1"),
        ("POST", "/api/admin/emisores-arca/1/cert"),
        ("GET", "/api/admin/emisores-arca/1/puntos-venta"),
        ("GET", "/api/admin/emisores-arca/1/cert-info"),
        ("GET", "/api/admin/arca/padron/20301234567"),
        ("GET", "/api/alquileres/1/facturar/preview"),
    ],
)
def test_rutas_facturacion_gatean_por_admin(method, path):
    r = _http.request(method, path)
    assert r.status_code != 422, f"{method} {path} no rutea bien (revisar orden de paths)"
    assert r.status_code in (401, 403)


def test_listar_layouts_factura_devuelve_los_3_con_metadata(monkeypatch):
    """El endpoint es un passthrough de `arca_fe.LAYOUTS_INFO` — el front arma el selector con
    esto, no debería hardcodear nombre/descripción/advertencia por su cuenta."""
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)

    result = facturacion_routes.listar_layouts_factura(_fake_request())

    assert {item["id"] for item in result} == {"oficial", "detallada", "simplificada"}
    for item in result:
        assert item["nombre"]
        assert item["descripcion"]
    simplificada = next(item for item in result if item["id"] == "simplificada")
    assert simplificada["advertencia"]
    oficial = next(item for item in result if item["id"] == "oficial")
    assert oficial["advertencia"] == ""


# ── facturar_pedido / nota_credito: mapeo de errores del engine ─────────────


def test_facturar_pedido_value_error_es_400(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr(
        "services.facturacion.engine.emitir_factura",
        lambda pedido_id, emitido_por=None, emisor_id=None: (_ for _ in ()).throw(
            ValueError("no confirmado")
        ),
    )
    with pytest.raises(HTTPException) as ei:
        facturacion_routes.facturar_pedido(1, _fake_request())
    assert ei.value.status_code == 400


def test_facturar_pedido_runtime_error_es_503_nunca_500(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr(
        "services.facturacion.engine.emitir_factura",
        lambda pedido_id, emitido_por=None, emisor_id=None: (_ for _ in ()).throw(
            RuntimeError("ARCA caída")
        ),
    )
    with pytest.raises(HTTPException) as ei:
        facturacion_routes.facturar_pedido(1, _fake_request())
    assert ei.value.status_code == 503


@pytest.mark.parametrize(
    "excepcion,status_esperado",
    [
        pytest.param(
            "ArcaBusinessError", 422,
            id="business-422-afip-rechazo-por-regla-de-negocio-no-es-transitorio",
        ),
        pytest.param(
            "ArcaResponseError", 502,
            id="response-502-afip-contesto-en-forma-inesperada-imparseable",
        ),
        pytest.param(
            "ArcaAuthError", 503, id="auth-503-cert-vencido-o-relacion-no-delegada",
        ),
        pytest.param(
            "ArcaNetworkError", 503, id="network-503-timeout-o-afip-caida",
        ),
    ],
)
def test_facturar_pedido_arca_error_status_por_subtipo(monkeypatch, excepcion, status_esperado):
    """Cada subtipo de ArcaError elige su propio status HTTP (no un 503
    genérico para todo) — y el mensaje real de AFIP se preserva en el body."""
    import arca_fe.errores as errores_mod

    exc_cls = getattr(errores_mod, excepcion)
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr(
        "services.facturacion.engine.emitir_factura",
        lambda pedido_id, emitido_por=None, emisor_id=None: (_ for _ in ()).throw(
            exc_cls("motivo real de AFIP")
        ),
    )
    with pytest.raises(HTTPException) as ei:
        facturacion_routes.facturar_pedido(1, _fake_request())
    assert ei.value.status_code == status_esperado
    assert "motivo real de AFIP" in ei.value.detail


# ── preview_factura: arma sin emitir, ValueError → 400 ──────────────────────


def test_preview_factura_devuelve_el_armado(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.engine.previsualizar_factura",
        lambda pedido_id, conn, emisor_id=None: {"comprobante": {"letra": "C"}},
    )

    result = facturacion_routes.preview_factura(1, _fake_request())
    assert result == {"comprobante": {"letra": "C"}}


def test_preview_factura_value_error_es_400(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.engine.previsualizar_factura",
        lambda pedido_id, conn, emisor_id=None: (_ for _ in ()).throw(ValueError("no confirmado")),
    )
    with pytest.raises(HTTPException) as ei:
        facturacion_routes.preview_factura(1, _fake_request())
    assert ei.value.status_code == 400


def test_preview_factura_runtime_error_es_503_nunca_500(monkeypatch):
    """El preview llama a ARCA (FECompUltimoAutorizado) — si ARCA está caída
    o el cert venció, tiene que ser 503, no un 500 crudo."""
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.engine.previsualizar_factura",
        lambda pedido_id, conn, emisor_id=None: (_ for _ in ()).throw(RuntimeError("ARCA caída")),
    )
    with pytest.raises(HTTPException) as ei:
        facturacion_routes.preview_factura(1, _fake_request())
    assert ei.value.status_code == 503


def test_preview_factura_arca_business_error_es_422(monkeypatch):
    from arca_fe.errores import ArcaBusinessError

    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.engine.previsualizar_factura",
        lambda pedido_id, conn, emisor_id=None: (_ for _ in ()).throw(
            ArcaBusinessError("CUIT bloqueado por RG 3990-E")
        ),
    )
    with pytest.raises(HTTPException) as ei:
        facturacion_routes.preview_factura(1, _fake_request())
    assert ei.value.status_code == 422
    assert "RG 3990-E" in ei.value.detail


# ── preview_factura_html: mismo layout que la factura real, sin emitir ──────


def test_preview_factura_html_devuelve_html(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.engine.previsualizar_factura_html",
        lambda pedido_id, conn, layout="simplificada", emisor_id=None: f"<html>factura {layout}</html>",
    )

    resp = facturacion_routes.preview_factura_html(1, _fake_request())
    assert resp.status_code == 200
    assert b"factura simplificada" in resp.body


def test_preview_factura_html_value_error_es_400(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.engine.previsualizar_factura_html",
        lambda pedido_id, conn, layout="simplificada", emisor_id=None: (_ for _ in ()).throw(
            ValueError("CUIT inválido")
        ),
    )
    with pytest.raises(HTTPException) as ei:
        facturacion_routes.preview_factura_html(1, _fake_request())
    assert ei.value.status_code == 400


def test_nota_credito_value_error_es_400(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr(
        "services.facturacion.engine.emitir_nota_credito",
        lambda factura_id, emitido_por=None: (_ for _ in ()).throw(ValueError("ya anulada")),
    )
    with pytest.raises(HTTPException) as ei:
        facturacion_routes.nota_credito(1, _fake_request())
    assert ei.value.status_code == 400


def test_nota_credito_runtime_error_es_503(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr(
        "services.facturacion.engine.emitir_nota_credito",
        lambda factura_id, emitido_por=None: (_ for _ in ()).throw(RuntimeError("timeout WSFE")),
    )
    with pytest.raises(HTTPException) as ei:
        facturacion_routes.nota_credito(1, _fake_request())
    assert ei.value.status_code == 503


def test_nota_credito_arca_business_error_es_422(monkeypatch):
    from arca_fe.errores import ArcaBusinessError

    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr(
        "services.facturacion.engine.emitir_nota_credito",
        lambda factura_id, emitido_por=None: (_ for _ in ()).throw(
            ArcaBusinessError("comprobante ya autorizado")
        ),
    )
    with pytest.raises(HTTPException) as ei:
        facturacion_routes.nota_credito(1, _fake_request())
    assert ei.value.status_code == 422
    assert "comprobante ya autorizado" in ei.value.detail


# ── descargar_pdf_factura: 404 / 400 / format=html / format=pdf ────────────


def test_descargar_pdf_404_si_no_existe(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr("services.facturacion.repo.get_by_id", lambda factura_id, conn: None)

    with pytest.raises(HTTPException) as ei:
        asyncio.run(facturacion_routes.descargar_pdf_factura(999, _fake_request()))
    assert ei.value.status_code == 404


def test_descargar_pdf_400_si_no_emitida(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.repo.get_by_id", lambda factura_id, conn: _fake_factura("pendiente")
    )

    with pytest.raises(HTTPException) as ei:
        asyncio.run(facturacion_routes.descargar_pdf_factura(1, _fake_request()))
    assert ei.value.status_code == 400


def test_descargar_pdf_503_si_faltan_datos_de_arca(monkeypatch):
    """factura_html falla fuerte (RuntimeError) si a una 'emitida' le faltan
    datos de ARCA — el route lo convierte en 503, nunca en un 500 crudo."""
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.repo.get_by_id", lambda factura_id, conn: _fake_factura()
    )
    monkeypatch.setattr(
        "services.facturacion.engine._get_pedido", lambda conn, pedido_id: {"id": pedido_id}
    )

    def _raise(*a, **kw):
        raise ValueError("ComprobanteFiscal incompleto, faltan: qr_url")

    monkeypatch.setattr("services.facturacion.comprobante_render.factura_html", _raise)

    with pytest.raises(HTTPException) as ei:
        asyncio.run(facturacion_routes.descargar_pdf_factura(1, _fake_request()))
    assert ei.value.status_code == 503


def test_descargar_pdf_format_html_devuelve_preview_sin_renderer(monkeypatch):
    """`format=html` no debe pasar por Playwright — devuelve el HTML tal cual."""
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.repo.get_by_id", lambda factura_id, conn: _fake_factura()
    )
    monkeypatch.setattr(
        "services.facturacion.engine._get_pedido", lambda conn, pedido_id: {"id": pedido_id}
    )
    monkeypatch.setattr(
        "services.facturacion.comprobante_render.factura_html", lambda factura, pedido, **_: "<html>FACTURA-X</html>"
    )

    resp = asyncio.run(
        facturacion_routes.descargar_pdf_factura(1, _fake_request(), format="html")
    )
    assert resp.status_code == 200
    assert b"FACTURA-X" in resp.body


def test_descargar_pdf_format_pdf_default_es_attachment(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.repo.get_by_id", lambda factura_id, conn: _fake_factura()
    )
    monkeypatch.setattr(
        "services.facturacion.engine._get_pedido", lambda conn, pedido_id: {"id": pedido_id}
    )
    monkeypatch.setattr(
        "services.facturacion.comprobante_render.factura_html", lambda factura, pedido, **_: "<html></html>"
    )

    async def _fake_render_pdf(html, **_):
        return b"%PDF-FAKE%"

    monkeypatch.setattr("pdf._render_pdf", _fake_render_pdf)
    monkeypatch.setattr(
        "services.facturacion.signing_cert.get_or_create_signing_cert",
        lambda conn: (b"cert", b"key"),
    )
    monkeypatch.setattr(
        "arca_fe.asegurar_pdf",
        lambda pdf_bytes, cert_pem, key_pem: pdf_bytes,
    )

    resp = asyncio.run(facturacion_routes.descargar_pdf_factura(1, _fake_request()))
    assert resp.status_code == 200
    assert resp.body == b"%PDF-FAKE%"
    assert "attachment" in resp.headers["content-disposition"]
    assert "Factura-C-00002-00000001.pdf" in resp.headers["content-disposition"]


def test_descargar_pdf_format_imagen_devuelve_png_sin_firmar(monkeypatch):
    """`format=imagen` es un artefacto liviano (compartir rápido) — no pasa por
    `get_or_create_signing_cert`/`asegurar_pdf`, a diferencia del PDF."""
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.repo.get_by_id", lambda factura_id, conn: _fake_factura()
    )
    monkeypatch.setattr(
        "services.facturacion.engine._get_pedido", lambda conn, pedido_id: {"id": pedido_id}
    )
    monkeypatch.setattr(
        "services.facturacion.comprobante_render.factura_html", lambda factura, pedido, **_: "<html></html>"
    )

    async def _fake_render_imagen(html, **_):
        return b"%PNG-FAKE%"

    monkeypatch.setattr("pdf._render_imagen", _fake_render_imagen)

    def _boom(conn):
        raise AssertionError("format=imagen no debería pedir el certificado de firma")

    monkeypatch.setattr("services.facturacion.signing_cert.get_or_create_signing_cert", _boom)

    resp = asyncio.run(
        facturacion_routes.descargar_pdf_factura(1, _fake_request(), format="imagen")
    )
    assert resp.status_code == 200
    assert resp.body == b"%PNG-FAKE%"
    assert resp.media_type == "image/png"
    assert "Factura-C-00002-00000001.png" in resp.headers["content-disposition"]


# ── enviar_mail_factura: la columna real es c.email, no c.owner_email ───────


def test_enviar_mail_factura_no_rompe_con_undefined_column(monkeypatch):
    """Regresión: consultaba `c.owner_email` (columna inexistente en `clientes`,
    vive en otra tabla) — rompía SIEMPRE con UndefinedColumn. Ahora usa `c.email`."""
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr(
        "routes.facturacion.get_db",
        lambda: _FakeConnConEmail(_FakeRow(email="cliente@example.com", nombre="Ana", apellido="Gómez")),
    )
    monkeypatch.setattr(
        "services.facturacion.repo.get_by_id", lambda factura_id, conn: _fake_factura()
    )
    monkeypatch.setattr(
        "services.facturacion.engine._get_pedido", lambda conn, pedido_id: {"id": pedido_id}
    )
    monkeypatch.setattr(
        "services.facturacion.comprobante_render.factura_html", lambda factura, pedido, **_: "<html></html>"
    )
    monkeypatch.setattr(
        "services.facturacion.signing_cert.get_or_create_signing_cert",
        lambda conn: (b"cert", b"key"),
    )
    monkeypatch.setattr(
        "arca_fe.asegurar_pdf",
        lambda pdf_bytes, cert_pem, key_pem: pdf_bytes,
    )

    async def _fake_render_pdf(html, **_):
        return b"%PDF-FAKE%"

    monkeypatch.setattr("pdf._render_pdf", _fake_render_pdf)

    sent = {}

    def _fake_send_raw_email(**kwargs):
        sent.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr("services.email.send_raw_email", _fake_send_raw_email)

    resp = asyncio.run(facturacion_routes.enviar_mail_factura(1, _fake_request()))
    assert resp == {"ok": True, "to": "cliente@example.com"}
    assert sent.get("to") == "cliente@example.com"


def test_enviar_mail_factura_400_si_sin_email(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr(
        "routes.facturacion.get_db",
        lambda: _FakeConnConEmail(_FakeRow(email=None, nombre="Ana", apellido="Gómez")),
    )
    monkeypatch.setattr(
        "services.facturacion.repo.get_by_id", lambda factura_id, conn: _fake_factura()
    )
    monkeypatch.setattr(
        "services.facturacion.engine._get_pedido", lambda conn, pedido_id: {"id": pedido_id}
    )
    monkeypatch.setattr(
        "services.facturacion.comprobante_render.factura_html", lambda factura, pedido, **_: "<html></html>"
    )
    monkeypatch.setattr(
        "services.facturacion.signing_cert.get_or_create_signing_cert",
        lambda conn: (b"cert", b"key"),
    )

    with pytest.raises(HTTPException) as ei:
        asyncio.run(facturacion_routes.enviar_mail_factura(1, _fake_request()))
    assert ei.value.status_code == 400


# ── Rate limit + mapeo de errores en escrituras de facturación (#1209) ─────
#
# Antes de esta auditoría, los endpoints de escritura de facturación (facturar
# pedido, NC, enviar mail, CRUD de emisores) no llevaban @limiter.limit ni
# @map_pg_errors — a diferencia del resto de la superficie de escritura de
# plata (contabilidad.py, pagos.py, reportes.py), que ya los tenía desde la
# auditoría 2026-07-02 (#1184).


def _make_facturacion_app():
    """App mínima con SOLO el router de facturación + el limiter compartido
    (mismo patrón que test_rate_limit.py::_make_app — evita el thread de init
    de DB de main.py)."""
    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    from rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(facturacion_routes.router, prefix="/api")
    return app


def test_crear_emisor_corta_con_429_tras_exceder_admin_write_limit(monkeypatch):
    """ADMIN_WRITE_LIMIT = 60/minute: un loop contra un endpoint de escritura de
    facturación corta con 429 en vez de seguir pegándole a Postgres/ARCA sin
    freno. IP dedicada (distinta de la default "testclient" de TestClient) para
    no compartir bucket del limiter con otros tests de este archivo que golpean
    el mismo endpoint (el gate de admin, la prueba de nombre duplicado)."""
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    client = TestClient(_make_facturacion_app(), client=("203.0.113.9", 51000))

    codes = [
        client.post("/api/admin/emisores-arca", json={}).status_code for _ in range(65)
    ]
    assert codes.count(429) >= 1, codes
    assert codes[0] == 400  # body vacío → 400 de validación, ya pasó el limiter


def test_crear_emisor_nombre_duplicado_da_400_no_500(monkeypatch):
    """`nombre` en `emisores_arca` es UNIQUE: un choque debe traducirse a 400
    limpio vía @map_pg_errors, no subir crudo como 500 con el mensaje interno
    de Postgres (constraint/columna) — el bug que motivó #1209."""
    import psycopg.errors

    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())

    def _raise_unique(*_a, **_kw):
        raise psycopg.errors.UniqueViolation(
            'duplicate key value violates unique constraint "emisores_arca_nombre_key"'
        )

    monkeypatch.setattr("services.facturacion.emisores_repo.create_emisor", _raise_unique)

    body = {
        "nombre": "santini",
        "cuit": "20111111112",
        "pto_vta": 3,
        "condicion_iva": "monotributo",
    }
    with pytest.raises(HTTPException) as ei:
        facturacion_routes.crear_emisor(_fake_request(), body)

    assert ei.value.status_code == 400
    assert ei.value.detail == "Ya existe un registro con ese valor."
    assert "constraint" not in ei.value.detail.lower()
def test_descargar_pdf_firma_real_no_explota_dentro_de_un_loop_corriendo(monkeypatch):
    """Regresión de prod: `asegurar_pdf` firma con pyhanko, cuyo `sign_pdf`
    sync hace `asyncio.run()` internamente — si se lo llama directo desde
    este handler async (que ya corre dentro del loop de FastAPI), explota
    con "asyncio.run() cannot be called from a running event loop". El test
    de arriba mockea `asegurar_pdf` entero y nunca ejercita la firma real;
    acá se la deja correr de verdad, dentro de un loop real (`asyncio.run`
    sobre el propio handler), para reproducir el bug si se revierte el fix
    (`asyncio.to_thread` en el route)."""
    import fitz

    from arca_fe import generar_cert_autofirmado as _generar_cert_autofirmado

    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.repo.get_by_id", lambda factura_id, conn: _fake_factura()
    )
    monkeypatch.setattr(
        "services.facturacion.engine._get_pedido", lambda conn, pedido_id: {"id": pedido_id}
    )
    monkeypatch.setattr(
        "services.facturacion.comprobante_render.factura_html", lambda factura, pedido, **_: "<html></html>"
    )

    def _pdf_minimo() -> bytes:
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Factura de prueba")
        return doc.tobytes()

    async def _fake_render_pdf(html, **_):
        return _pdf_minimo()

    cert_pem, key_pem = _generar_cert_autofirmado("test")
    monkeypatch.setattr("pdf._render_pdf", _fake_render_pdf)
    monkeypatch.setattr(
        "services.facturacion.signing_cert.get_or_create_signing_cert",
        lambda conn: (cert_pem, key_pem),
    )

    resp = asyncio.run(facturacion_routes.descargar_pdf_factura(1, _fake_request()))
    assert resp.status_code == 200
    assert resp.body.startswith(b"%PDF")


# ── consultar_padron: autocompletar CUIT — nunca rompe, {encontrado: false} ─


def test_consultar_padron_encontrado(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())

    class _Impuesto:
        id_impuesto = 30
        descripcion = "IVA"
        estado = "AC"
        periodo = 202001

    class _Actividad:
        descripcion = "Servicios de consultores en informática"

    class _Persona:
        razon_social = "Empresa XYZ SRL"
        nombre = ""
        apellido = ""
        domicilio = "Ruta 88 km 12"
        condicion_iva = "responsable_inscripto"
        estado_clave = "ACTIVO"
        tipo_persona = "JURIDICA"
        categoria_monotributo = ""
        actividades = (_Actividad(),)
        impuestos = (_Impuesto(),)

    monkeypatch.setattr(
        "services.facturacion.padron.resolver_persona",
        lambda cuit, conn: _Persona(),
    )

    result = facturacion_routes.consultar_padron("30712345678", _fake_request())
    assert result == {
        "encontrado": True,
        "razon_social": "Empresa XYZ SRL",
        "nombre": "",
        "apellido": "",
        "domicilio": "Ruta 88 km 12",
        "condicion_iva": "responsable_inscripto",
        "estado_clave": "ACTIVO",
        "tipo_persona": "JURIDICA",
        "categoria_monotributo": "",
        "actividades": ["Servicios de consultores en informática"],
        "impuestos": [
            {"id_impuesto": 30, "descripcion": "IVA", "estado": "AC", "periodo": 202001}
        ],
    }


def test_consultar_padron_error_real_incluye_motivo(monkeypatch):
    """Distinto de "sin datos": si resolver_persona no pudo ni completar la
    consulta (WSAA/relación/cert/red), el route sigue sin romper (nunca un
    error HTTP) pero incluye el `motivo` real — más útil para diagnosticar
    que un genérico {encontrado: false}."""
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.padron.resolver_persona",
        lambda cuit, conn: (_ for _ in ()).throw(RuntimeError("WSAA rechazó: cert vencido")),
    )

    result = facturacion_routes.consultar_padron("30712345678", _fake_request())
    assert result == {"encontrado": False, "motivo": "WSAA rechazó: cert vencido"}


# ── consultar_puntos_venta_emisor: validar/elegir en vez de cargar a mano ───


def _fake_emisor_arca(nombre="pablo"):
    from datetime import datetime
    from services.facturacion.emisores_repo import EmisorArca

    return EmisorArca(
        id=1, nombre=nombre, cuit="20300000000", pto_vta=2,
        condicion_iva="responsable_inscripto", cert_cargado=True,
        activo=True, razon_social=None, domicilio=None, iibb=None,
        inicio_actividades=None, notas=None,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
    )


def test_consultar_puntos_venta_devuelve_lista(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_by_id",
        lambda emisor_id, conn: _fake_emisor_arca(),
    )
    monkeypatch.setattr(
        "services.facturacion.puntos_venta.consultar_puntos_venta",
        lambda nombre_emisor, conn: {
            "habilitados": [{"nro": 2}, {"nro": 5}],
            "excluidos": [{"nro": 9, "motivo": "bloqueado"}],
        },
    )

    result = facturacion_routes.consultar_puntos_venta_emisor(1, _fake_request())
    assert result == {
        "puntos_venta": [{"nro": 2}, {"nro": 5}],
        "excluidos": [{"nro": 9, "motivo": "bloqueado"}],
    }


def test_consultar_puntos_venta_emisor_no_encontrado_es_404(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_by_id", lambda emisor_id, conn: None
    )

    with pytest.raises(HTTPException) as exc:
        facturacion_routes.consultar_puntos_venta_emisor(1, _fake_request())
    assert exc.value.status_code == 404


def test_consultar_puntos_venta_sin_cert_es_400(monkeypatch):
    """Emisor existe pero no tiene cert cargado — `credenciales()` (dentro
    del service) levanta ValueError; la route lo mapea a 400, no a 500."""
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_by_id",
        lambda emisor_id, conn: _fake_emisor_arca(),
    )

    def _boom(nombre_emisor, conn):
        raise ValueError("Certificado no cargado")

    monkeypatch.setattr("services.facturacion.puntos_venta.consultar_puntos_venta", _boom)

    with pytest.raises(HTTPException) as exc:
        facturacion_routes.consultar_puntos_venta_emisor(1, _fake_request())
    assert exc.value.status_code == 400


def test_consultar_puntos_venta_arca_caida_es_503_nunca_500(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_by_id",
        lambda emisor_id, conn: _fake_emisor_arca(),
    )

    def _boom(nombre_emisor, conn):
        raise RuntimeError("WSAA no respondió")

    monkeypatch.setattr("services.facturacion.puntos_venta.consultar_puntos_venta", _boom)

    with pytest.raises(HTTPException) as exc:
        facturacion_routes.consultar_puntos_venta_emisor(1, _fake_request())
    assert exc.value.status_code == 503


def test_consultar_puntos_venta_arca_response_error_es_502(monkeypatch):
    from arca_fe.errores import ArcaResponseError

    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_by_id",
        lambda emisor_id, conn: _fake_emisor_arca(),
    )

    def _boom(nombre_emisor, conn):
        raise ArcaResponseError("ARCA no devolvió ResultGet ni Errors")

    monkeypatch.setattr("services.facturacion.puntos_venta.consultar_puntos_venta", _boom)

    with pytest.raises(HTTPException) as exc:
        facturacion_routes.consultar_puntos_venta_emisor(1, _fake_request())
    assert exc.value.status_code == 502
    assert "ResultGet" in exc.value.detail


# ── info_cert_emisor: Nº de serie para comparar contra ARCA ─────────────────


def test_info_cert_emisor_devuelve_subject_y_serie(monkeypatch):
    from arca_fe import generar_cert_autofirmado as _generar_cert_autofirmado

    cert_pem, key_pem = _generar_cert_autofirmado("Comprobantes — Motor de Facturación")

    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_cert_pem",
        lambda emisor_id, conn: (cert_pem, key_pem),
    )

    result = facturacion_routes.info_cert_emisor(1, _fake_request())

    assert "Comprobantes" in result["subject"]
    assert result["numero_serie"]
    assert result["vigente_desde"] < result["vigente_hasta"]


def test_info_cert_emisor_sin_cert_es_400(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())

    def _boom(emisor_id, conn):
        raise ValueError("Emisor 1 no tiene certificado cargado.")

    monkeypatch.setattr("services.facturacion.emisores_repo.get_cert_pem", _boom)

    with pytest.raises(HTTPException) as exc:
        facturacion_routes.info_cert_emisor(1, _fake_request())
    assert exc.value.status_code == 400


# ── refrescar_catalogos_arca: actualiza las etiquetas del PDF desde ARCA ────


def test_refrescar_catalogos_arca_devuelve_conteos(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())
    monkeypatch.setattr(
        "services.facturacion.catalogos.refrescar_catalogos",
        lambda conn: {
            "doc_tipo": [{"id": 80, "desc": "CUIT"}],
            "concepto": [{"id": 1, "desc": "Productos"}, {"id": 2, "desc": "Servicios"}],
            "condicion_iva_receptor": [],
        },
    )

    result = facturacion_routes.refrescar_catalogos_arca(_fake_request())
    assert result == {"ok": True, "doc_tipo": 1, "concepto": 2, "condicion_iva_receptor": 0}


def test_refrescar_catalogos_arca_sin_emisor_es_400(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())

    def _boom(conn):
        raise ValueError("No hay ningún emisor activo con certificado cargado")

    monkeypatch.setattr("services.facturacion.catalogos.refrescar_catalogos", _boom)

    with pytest.raises(HTTPException) as exc:
        facturacion_routes.refrescar_catalogos_arca(_fake_request())
    assert exc.value.status_code == 400


def test_refrescar_catalogos_arca_caida_es_503(monkeypatch):
    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())

    def _boom(conn):
        raise RuntimeError("FEParamGetTiposDoc error")

    monkeypatch.setattr("services.facturacion.catalogos.refrescar_catalogos", _boom)

    with pytest.raises(HTTPException) as exc:
        facturacion_routes.refrescar_catalogos_arca(_fake_request())
    assert exc.value.status_code == 503


def test_refrescar_catalogos_arca_network_error_es_503(monkeypatch):
    """ArcaNetworkError también da 503 (igual que RuntimeError) — es la
    categoría genuinamente transitoria, tiene sentido reintentar."""
    from arca_fe.errores import ArcaNetworkError

    monkeypatch.setattr("routes.facturacion.require_admin", lambda request: None)
    monkeypatch.setattr("routes.facturacion.get_db", lambda: _FakeConn())

    def _boom(conn):
        raise ArcaNetworkError("timeout al contactar WSFEv1")

    monkeypatch.setattr("services.facturacion.catalogos.refrescar_catalogos", _boom)

    with pytest.raises(HTTPException) as exc:
        facturacion_routes.refrescar_catalogos_arca(_fake_request())
    assert exc.value.status_code == 503
    assert "timeout" in exc.value.detail
