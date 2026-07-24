"""Tests de orquestación de services.facturacion.engine (emitir_factura / NC).

Mockea WSFE/WSAA/DB — sin red, sin Postgres real. Cubre los dos bugs
encontrados en producción:
- La idempotencia post-timeout reusaba número+CAE de la factura ANTERIOR en
  vez de pedir uno nuevo (porque consultaba `ultimo`, que por definición
  siempre está autorizado, en lugar de `ultimo + 1`).
- `emitir_nota_credito` nunca podía insertar la NC mientras la original
  seguía 'emitida' (violaba el índice único parcial por pedido_id).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest

from services.facturacion import engine
from services.facturacion.config import CredARCA
from services.facturacion.repo import Factura

pytestmark = pytest.mark.unit


# ── Fakes ──────────────────────────────────────────────────────────────────


class _FakeConn:
    """Conexión falsa: solo necesita tolerar SELECT/UPDATE/lock arbitrarios."""

    def __init__(self):
        self.committed = False
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

        class _R:
            def fetchone(self_inner):
                return None

            def fetchall(self_inner):
                return []

        return _R()

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class _FakeWsfe:
    """Stub de WsfeClient: registra llamadas, responde según lo configurado."""

    instances: list["_FakeWsfe"] = []

    def __init__(self, *, endpoint, cuit, token, sign):
        self.ultimo = 0
        self.consultar_resp = None
        self.solicitar_calls = []
        self.consultar_calls = []
        type(self).instances.append(self)

    def ultimo_autorizado(self, pto_vta, cbte_tipo):
        return self.ultimo

    def consultar(self, pto_vta, cbte_tipo, numero):
        self.consultar_calls.append(numero)
        return self.consultar_resp

    def solicitar_cae(self, comprobante, numero):
        self.solicitar_calls.append((comprobante, numero))
        from arca_fe import CaeResult
        return CaeResult(resultado="A", cae="86261839900001", cae_vto=date(2030, 1, 1), numero=numero)


def _fake_cred() -> CredARCA:
    return CredARCA(
        emisor_id=1,
        emisor="santini",
        condicion_iva="monotributo",
        ambiente="homologacion",
        cuit=20300000003,
        punto_venta=2,
        cert_pem=b"x",
        key_pem=b"x",
        endpoint_wsaa="https://wsaahomo.afip.gov.ar/ws/services/LoginCms",
        endpoint_wsfe="https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL",
    )


def _fake_pedido() -> dict:
    return {
        "id": 1,
        "estado": "confirmado",
        "monto_total": 5700,
        "iva_monto": 0,
        "cliente_perfil_impuestos": "consumidor_final",
        "cliente_cuit": None,
        "cliente_dni": "42289220",
        "cliente_nombre": "Juan Pérez",
        "fecha_desde": "2026-06-30",
        "fecha_hasta": "2026-07-01",
        "items": [],
    }


def _patch_common(monkeypatch, wsfe_instance):
    monkeypatch.setattr(engine, "get_db", lambda: _FakeConn())
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: _fake_pedido())
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: wsfe_instance)
    monkeypatch.setattr(engine, "get_factura_vigente", lambda pedido_id, conn: None)
    monkeypatch.setattr(engine, "insert_factura", lambda **kw: 99)

    calls = {}

    def _fake_update_cae(factura_id, conn, **kw):
        calls["update_cae"] = kw

    def _fake_update_error(factura_id, conn, **kw):
        calls["update_error"] = kw

    monkeypatch.setattr(engine, "update_cae", _fake_update_cae)
    monkeypatch.setattr(engine, "update_error", _fake_update_error)

    def _fake_get_by_id(factura_id, conn):
        return Factura(
            id=99, pedido_id=1, emisor="santini", ambiente="homologacion",
            cbte_tipo=11, pto_vta=2, cbte_nro=calls.get("update_cae", {}).get("cbte_nro"),
            cae=calls.get("update_cae", {}).get("cae"), cae_vto=None,
            doc_tipo=96, doc_nro="42289220", condicion_iva_receptor=5,
            concepto=2, imp_neto=5700, imp_iva=0, imp_total=5700, moneda="PES",
            cliente_cuit=None, razon_social=None, qr_payload=None, pdf_key=None,
            estado="emitida" if "update_cae" in calls else "error",
            nota_credito_de=None, raw_request=None, raw_response=None,
            errores=None, fecha_emision=None, created_at=None, created_by=None,
        )

    monkeypatch.setattr(engine, "get_by_id", _fake_get_by_id)
    return calls


# ── emitir_factura: idempotencia post-timeout ───────────────────────────────


def test_emitir_factura_pide_cae_nuevo_cuando_no_hay_recovery(monkeypatch):
    """Caso normal: `numero_a_emitir` todavía no existe en ARCA → pide un CAE nuevo."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    wsfe.ultimo = 1  # ya hay una factura anterior autorizada (número 1)
    wsfe.consultar_resp = None  # numero_a_emitir=2 todavía no existe

    calls = _patch_common(monkeypatch, wsfe)

    factura = engine.emitir_factura(1)

    assert len(wsfe.solicitar_calls) == 1, "debe pedir un CAE nuevo a ARCA"
    assert wsfe.consultar_calls == [2], "debe consultar el PRÓXIMO número (2), no el último (1)"
    assert calls["update_cae"]["cbte_nro"] == 2
    assert calls["update_cae"]["cae"] == "86261839900001"


def test_emitir_factura_no_duplica_cae_de_la_factura_anterior(monkeypatch):
    """Bug de prod: NO debe reusar el CAE de la última factura autorizada.

    Si ARCA ya tiene autorizado el número `ultimo` (la factura anterior, de
    OTRO pedido), consultar(ultimo) devolvería 'A' — pero el fix consulta
    `ultimo + 1`, que legítimamente no existe todavía, así que debe pedir un
    CAE propio en vez de heredar el de la anterior.
    """
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    wsfe.ultimo = 1
    wsfe.consultar_resp = None  # numero_a_emitir=2 no existe → no hay "recovery" espurio

    _patch_common(monkeypatch, wsfe)

    engine.emitir_factura(1)

    assert wsfe.solicitar_calls, "no debe saltear solicitar_cae confundiendo la factura anterior con la propia"


def test_emitir_factura_recupera_cae_si_su_propio_reintento_ya_autorizo(monkeypatch):
    """Timeout genuino: nuestro propio intento anterior ya autorizó `numero_a_emitir`
    en ARCA (la respuesta se perdió de nuestro lado) → se recupera, no se duplica."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    wsfe.ultimo = 1
    wsfe.consultar_resp = {
        "Resultado": "A",
        "CodAutorizacion": "86261839900002",
        "CAEFchVto": "20300101",
    }

    calls = _patch_common(monkeypatch, wsfe)

    engine.emitir_factura(1)

    assert not wsfe.solicitar_calls, "no debe pedir un CAE nuevo si ya se recuperó uno"
    assert calls["update_cae"]["cbte_nro"] == 2
    assert calls["update_cae"]["cae"] == "86261839900002"


# ── emitir_nota_credito: orden anulación/insert + snapshot de importes ─────


def _fake_original_factura() -> Factura:
    return Factura(
        id=14, pedido_id=422, emisor="santini", ambiente="homologacion",
        cbte_tipo=11, pto_vta=2, cbte_nro=1, cae="86261839900000", cae_vto=None,
        doc_tipo=96, doc_nro="42289220", condicion_iva_receptor=5,
        concepto=2, imp_neto=5700, imp_iva=0, imp_total=5700, moneda="PES",
        cliente_cuit=None, razon_social=None, qr_payload=None, pdf_key=None,
        estado="emitida", nota_credito_de=None, raw_request=None,
        raw_response=None, errores=None, fecha_emision=None,
        created_at=None, created_by=None, domicilio="Falsa 123, CABA",
    )


def test_emitir_nota_credito_anula_original_antes_de_insertar(monkeypatch):
    """Bug de prod: insertar la NC mientras la original sigue 'emitida' viola
    uq_factura_vigente_por_pedido. `marcar_anulada` debe correr ANTES del insert."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    wsfe.ultimo = 1

    order = []
    monkeypatch.setattr(engine, "get_db", lambda: _FakeConn())
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: _fake_pedido())
    monkeypatch.setattr(engine, "get_by_id", lambda factura_id, conn: _fake_original_factura())
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: wsfe)
    monkeypatch.setattr(engine, "marcar_anulada", lambda factura_id, conn: order.append("anular"))
    monkeypatch.setattr(engine, "insert_factura", lambda **kw: order.append("insert") or 200)
    monkeypatch.setattr(engine, "update_cae", lambda *a, **kw: None)
    monkeypatch.setattr(engine, "update_error", lambda *a, **kw: None)
    monkeypatch.setattr(engine, "revertir_anulacion", lambda *a, **kw: order.append("revertir"))

    engine.emitir_nota_credito(14)

    assert order[0] == "anular", "la original tiene que anularse ANTES de insertar la NC"
    assert order[1] == "insert"
    assert "revertir" not in order, "ARCA aprobó → no debe revertir la anulación"


def test_emitir_nota_credito_revierte_anulacion_si_arca_rechaza(monkeypatch):
    """Si ARCA rechaza la NC, la original nunca se anuló de verdad → revertir."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    wsfe.ultimo = 1

    def _rechazo(comprobante, numero):
        from arca_fe import CaeResult
        return CaeResult(resultado="R", errores=("10: rechazado",))

    wsfe.solicitar_cae = _rechazo

    order = []
    monkeypatch.setattr(engine, "get_db", lambda: _FakeConn())
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: _fake_pedido())
    monkeypatch.setattr(engine, "get_by_id", lambda factura_id, conn: _fake_original_factura())
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: wsfe)
    monkeypatch.setattr(engine, "marcar_anulada", lambda factura_id, conn: order.append("anular"))
    monkeypatch.setattr(engine, "insert_factura", lambda **kw: 200)
    monkeypatch.setattr(engine, "update_cae", lambda *a, **kw: order.append("update_cae"))
    monkeypatch.setattr(engine, "update_error", lambda *a, **kw: order.append("update_error"))
    monkeypatch.setattr(engine, "revertir_anulacion", lambda *a, **kw: order.append("revertir"))

    engine.emitir_nota_credito(14)

    assert "update_cae" not in order
    assert order[-1] == "revertir", "ARCA rechazó → la anulación se tiene que revertir"


def test_emitir_nota_credito_hereda_domicilio_de_la_original_sin_reverificar(monkeypatch):
    """La NC NO re-verifica contra el padrón — hereda el `domicilio` ya
    congelado de la factura original (consistencia original↔NC)."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    wsfe.ultimo = 1

    captured_insert = {}

    def _fake_insert_factura(**kw):
        captured_insert.update(kw)
        return 200

    monkeypatch.setattr(engine, "get_db", lambda: _FakeConn())
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: _fake_pedido())
    monkeypatch.setattr(engine, "get_by_id", lambda factura_id, conn: _fake_original_factura())
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: wsfe)
    monkeypatch.setattr(engine, "marcar_anulada", lambda factura_id, conn: None)
    monkeypatch.setattr(engine, "insert_factura", _fake_insert_factura)
    monkeypatch.setattr(engine, "update_cae", lambda *a, **kw: None)
    monkeypatch.setattr(engine, "update_error", lambda *a, **kw: None)
    monkeypatch.setattr(engine, "revertir_anulacion", lambda *a, **kw: None)

    engine.emitir_nota_credito(14)

    assert captured_insert["domicilio"] == "Falsa 123, CABA"


def test_construir_comprobante_nc_usa_snapshot_no_pedido_en_vivo():
    """El importe de la NC tiene que salir de la factura original persistida,
    no recalcularse del pedido (que puede haber cambiado de precio/descuento)."""
    from services.facturacion.comprobante_pedido import construir_comprobante_nc
    from arca_fe import Emisor, CondicionIva, CbteAsoc, CbteTipo

    original = _fake_original_factura()
    # El pedido "en vivo" ahora tiene un monto MUY distinto al facturado.
    pedido_con_precio_cambiado = {**_fake_pedido(), "monto_total": 999999, "iva_monto": 0}
    emisor_obj = Emisor(cuit=20300000003, punto_venta=2, condicion_iva=CondicionIva.MONOTRIBUTO)
    cbte_asoc = CbteAsoc(tipo=CbteTipo.FACTURA_C, punto_venta=2, numero=1)

    req = construir_comprobante_nc(
        original, pedido_con_precio_cambiado, emisor_obj,
        fecha=date(2026, 7, 1), cbtes_asoc=(cbte_asoc,),
    )

    assert req.importe_neto == Decimal(original.imp_neto), (
        "la NC tiene que cancelar el monto de la factura ORIGINAL, no el pedido en vivo"
    )


# ── FchVtoPago nunca antes de la fecha del comprobante (ARCA rechaza: 10036) ─
# Bug real en prod: se facturaba casi siempre DESPUÉS de que el pedido ya
# terminó, así que `fecha_hasta` (fin del alquiler) quedaba en el pasado y
# ARCA lo rechazaba con "El campo FchVtoPago no puede ser anterior a la
# fecha del comprobante."


def test_vto_pago_usa_fecha_hasta_si_todavia_no_paso():
    """Si se factura ANTES de que termine el alquiler, el vencimiento sigue
    siendo el fin del servicio (fecha_hasta) — comportamiento previo intacto."""
    from services.facturacion.comprobante_pedido import construir_comprobante
    from arca_fe import Emisor, CondicionIva

    pedido = {**_fake_pedido(), "fecha_desde": "2026-07-05", "fecha_hasta": "2026-07-10"}
    emisor_obj = Emisor(cuit=20300000003, punto_venta=2, condicion_iva=CondicionIva.MONOTRIBUTO)

    req = construir_comprobante(
        pedido, emisor_obj, CondicionIva.MONOTRIBUTO, fecha=date(2026, 7, 1),
    )

    assert req.fecha_vto_pago == date(2026, 7, 10)


def test_vto_pago_cae_a_fecha_del_comprobante_si_el_pedido_ya_termino():
    """Caso real de prod: se factura DESPUÉS del alquiler (fecha_hasta en el
    pasado) — el vencimiento no puede quedar antes que la fecha de emisión."""
    from services.facturacion.comprobante_pedido import construir_comprobante
    from arca_fe import Emisor, CondicionIva

    pedido = {**_fake_pedido(), "fecha_desde": "2026-06-30", "fecha_hasta": "2026-07-01"}
    emisor_obj = Emisor(cuit=20300000003, punto_venta=2, condicion_iva=CondicionIva.MONOTRIBUTO)

    req = construir_comprobante(
        pedido, emisor_obj, CondicionIva.MONOTRIBUTO, fecha=date(2026, 7, 15),
    )

    assert req.fecha_vto_pago == date(2026, 7, 15)


def test_vto_pago_sin_fecha_hasta_usa_fecha_del_comprobante():
    """`_fecha_vto_pago` cae a la fecha del comprobante cuando no hay `fecha_hasta` — probado
    directo sobre la función pura, no vía `construir_comprobante`: desde que
    `ComprobanteRequest.__post_init__` valida que Concepto=SERVICIOS (que `construir_comprobante`
    usa siempre) exige `fecha_serv_hasta`, un pedido sin `fecha_hasta` en absoluto ya no puede
    representarse como un `ComprobanteRequest` completo — es un estado que la librería rechaza
    antes, no algo que este test pueda seguir armando end-to-end."""
    from services.facturacion.comprobante_pedido import _fecha_vto_pago

    assert _fecha_vto_pago(None, date(2026, 7, 15)) == date(2026, 7, 15)


def test_vto_pago_con_fecha_hasta_como_datetime_no_string():
    """Regresión de prod: `fecha_desde`/`fecha_hasta` son columnas TIMESTAMP —
    psycopg3 las devuelve como `datetime.datetime`, no como string ISO (que es
    todo lo que probaban los tests de arriba). `datetime` es subclase de
    `date`, así que `_parse_fecha` los dejaba pasar SIN truncar a `.date()`,
    y comparar ese datetime contra un `date` en `_fecha_vto_pago` explotaba
    con "TypeError: can't compare datetime.datetime to datetime.date" —
    reproducido en vivo en el preview de una factura real (pedido #418)."""
    from services.facturacion.comprobante_pedido import construir_comprobante
    from arca_fe import Emisor, CondicionIva

    pedido = {
        **_fake_pedido(),
        "fecha_desde": datetime(2026, 6, 30, 9, 0),
        "fecha_hasta": datetime(2026, 7, 1, 18, 0),
    }
    emisor_obj = Emisor(cuit=20300000003, punto_venta=2, condicion_iva=CondicionIva.MONOTRIBUTO)

    req = construir_comprobante(
        pedido, emisor_obj, CondicionIva.MONOTRIBUTO, fecha=date(2026, 7, 15),
    )

    assert req.fecha_vto_pago == date(2026, 7, 15)
    assert req.fecha_serv_desde == date(2026, 6, 30)
    assert req.fecha_serv_hasta == date(2026, 7, 1)


def test_construir_comprobante_pedido_estudio_mismo_dia_no_rompe():
    """Chequeo de compatibilidad ARCA para el Estudio (#1283 Fase 6): un turno
    del estudio dura HORAS, no días — `fecha_desde`/`fecha_hasta` caen en el
    MISMO día calendario (ej. 10:00 a 12:00). `construir_comprobante` usa
    SIEMPRE `Concepto.SERVICIOS` (correcto: alquilar es un servicio, no vender
    un producto — no depende de `tipo`), y `_parse_fecha` trunca cada datetime
    a `.date()` — mismo día en ambas puntas da `fecha_serv_desde ==
    fecha_serv_hasta`, que ARCA acepta (un servicio de un solo día). El
    comprobante es UNA línea consolidada (`_conceptos`, sin desglose de ítems),
    así que tampoco hereda el bug de display "1 jornada" que tenía el
    Presupuesto (ya arreglado en Fase 2) — no hay nada que mostrar mal.
    `ComprobanteRequest.__post_init__` corre la validación completa de ARCA
    (`_validar_estructura`/`_validar_fechas_servicio`) al construirse: si esto
    no lanza, el comprobante es válido de punta a punta."""
    from services.facturacion.comprobante_pedido import construir_comprobante
    from arca_fe import Concepto, Emisor, CondicionIva

    pedido = {
        **_fake_pedido(),
        "fecha_desde": datetime(2026, 7, 20, 10, 0),
        "fecha_hasta": datetime(2026, 7, 20, 12, 0),
    }
    emisor_obj = Emisor(cuit=20300000003, punto_venta=2, condicion_iva=CondicionIva.MONOTRIBUTO)

    req = construir_comprobante(
        pedido, emisor_obj, CondicionIva.MONOTRIBUTO, fecha=date(2026, 7, 21),
    )

    assert req.concepto == Concepto.SERVICIOS
    assert req.fecha_serv_desde == date(2026, 7, 20)
    assert req.fecha_serv_hasta == date(2026, 7, 20)
    assert req.fecha_vto_pago is not None


def test_vto_pago_de_la_nc_tambien_respeta_la_fecha_del_comprobante():
    from services.facturacion.comprobante_pedido import construir_comprobante_nc
    from arca_fe import Emisor, CondicionIva, CbteAsoc, CbteTipo

    original = _fake_original_factura()
    pedido = {**_fake_pedido(), "fecha_hasta": "2026-07-01"}
    emisor_obj = Emisor(cuit=20300000003, punto_venta=2, condicion_iva=CondicionIva.MONOTRIBUTO)
    cbte_asoc = CbteAsoc(tipo=CbteTipo.FACTURA_C, punto_venta=2, numero=1)

    req = construir_comprobante_nc(
        original, pedido, emisor_obj, fecha=date(2026, 8, 1), cbtes_asoc=(cbte_asoc,),
    )

    assert req.fecha_vto_pago == date(2026, 8, 1)


# ── previsualizar_factura: arma el comprobante + consulta ARCA (solo lectura,
# NUNCA pide CAE) ────────────────────────────────────────────────────────────


def _patch_preview_common(monkeypatch, wsfe_instance):
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: _fake_pedido())
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: wsfe_instance)


def test_preview_consulta_ultimo_autorizado_pero_nunca_pide_cae(monkeypatch):
    """El preview SÍ llama a ARCA (FECompUltimoAutorizado, de solo lectura —
    valida credenciales y muestra el número real), pero jamás a solicitar_cae
    ni consultar (eso es exclusivo de emitir_factura)."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    wsfe.ultimo = 4
    _patch_preview_common(monkeypatch, wsfe)
    monkeypatch.setattr(engine, "now_ar", lambda: datetime(2026, 7, 15))

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    assert result["comprobante"]["letra"] == "C"  # monotributo → Factura C
    assert result["comprobante"]["numero_a_emitir"] == 5
    assert result["emisor"]["nombre"] == "santini"
    assert result["receptor"]["doc_tipo"] == "DNI"
    assert result["fechas"]["vto_pago"] == "2026-07-15"  # fecha_hasta (07-01) ya pasó → hoy
    assert wsfe.solicitar_calls == [], "el preview NUNCA debe pedir un CAE"
    assert wsfe.consultar_calls == [], "consultar() es de la idempotencia de emitir_factura, no del preview"


def test_preview_incluye_concepto_condicion_iva_y_condicion_venta(monkeypatch):
    """El preview muestra lo mismo que va impreso en la factura real: Concepto, condición IVA
    del emisor y del receptor, y condición de venta (Contado/Cuenta corriente) — pedido a
    pedirlo el dueño, para no tener que adivinar/descubrir esos datos recién en el PDF ya
    emitido. Sin catálogos de ARCA sincronizados (`_FakeConn` no tiene ninguno cargado), cae al
    label ESTÁTICO de `arca_fe` — nunca rompe el preview por un catálogo no actualizado."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    _patch_preview_common(monkeypatch, wsfe)
    monkeypatch.setattr(engine, "now_ar", lambda: datetime(2026, 7, 15))

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    assert result["comprobante"]["concepto"]  # label no vacío (fallback estático)
    assert result["comprobante"]["condicion_venta"] in ("Contado", "Cuenta corriente")
    assert result["emisor"]["condicion_iva_label"] == "Responsable Monotributo"
    assert result["receptor"]["condicion_iva_label"]


def test_preview_condicion_venta_cuenta_corriente_si_no_esta_todo_pagado(monkeypatch):
    """Mismo criterio de negocio que ya usa el render de la factura emitida
    (`comprobante_render.py`): si lo pagado no cubre el total, es "Cuenta corriente"."""
    pedido_con_saldo = {**_fake_pedido(), "monto_total": 10000, "monto_pagado": 3000}
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_con_saldo)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: wsfe)

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    assert result["comprobante"]["condicion_venta"] == "Cuenta corriente"


def test_preview_chequeos_ok_caso_normal(monkeypatch):
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    _patch_preview_common(monkeypatch, wsfe)
    monkeypatch.setattr(engine, "now_ar", lambda: datetime(2026, 7, 15))

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    assert result["listo"] is True
    assert all(c["ok"] for c in result["chequeos"])


def test_preview_chequeo_cuit_invalido_bloquea(monkeypatch):
    """Un CUIT con el dígito verificador mal formado bloquea — ARCA lo
    rechazaría de entrada, mejor que el admin lo sepa antes de confirmar."""
    pedido_ri = {
        **_fake_pedido(),
        "cliente_perfil_impuestos": "responsable_inscripto",
        "cliente_cuit": "20301234560",  # dígito verificador incorrecto (a propósito)
    }
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    cuit_check = next(c for c in result["chequeos"] if c["check"] == "cuit_receptor")
    assert cuit_check["ok"] is False
    assert result["listo"] is False


def test_preview_error_de_construccion_no_relacionado_a_cuit_no_se_rotula_mal(monkeypatch):
    """Un ValueError de `construir_comprobante` que NO es sobre el CUIT (ej.
    `punto_venta` del emisor fuera de rango) tiene que dar el chequeo genérico
    `comprobante_invalido`, NO `cuit_receptor` — rotularlo mal manda a
    cualquiera que debuguee esto a buscar el problema en el lugar equivocado."""
    pedido_ri = {**_fake_pedido(), "cliente_perfil_impuestos": "responsable_inscripto"}
    cred_pto_venta_invalido = CredARCA(
        emisor_id=1, emisor="santini", condicion_iva="monotributo",
        ambiente="homologacion", cuit=20300000003, punto_venta=0,  # fuera de rango (1-9999)
        cert_pem=b"x", key_pem=b"x",
        endpoint_wsaa="https://wsaahomo.afip.gov.ar/ws/services/LoginCms",
        endpoint_wsfe="https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL",
    )
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: cred_pto_venta_invalido)
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    assert result["listo"] is False
    checks = {c["check"] for c in result["chequeos"]}
    assert "comprobante_invalido" in checks
    assert "cuit_receptor" not in checks
    chequeo = next(c for c in result["chequeos"] if c["check"] == "comprobante_invalido")
    assert "punto_venta" in chequeo["mensaje"]


def test_preview_chequeo_ri_sin_cuit_valido_bloquea(monkeypatch):
    """RI/Monotributo/Exento sin CUIT no existen en Argentina — el preview
    tiene que BLOQUEAR (mismo chequeo duro que `emitir_factura`), no dejar
    pasar con solo una advertencia. Antes de este chequeo, este caso caía a
    Consumidor Final en silencio; ahora se corta ACÁ (preview), antes de
    gastar un comprobante real, en vez de fallar recién al confirmar."""
    pedido_ri_sin_cuit = {**_fake_pedido(), "cliente_perfil_impuestos": "responsable_inscripto"}
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri_sin_cuit)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    perfil_check = next(c for c in result["chequeos"] if c["check"] == "perfil_fiscal_receptor")
    assert perfil_check["ok"] is False  # sigue avisando el "cae a C/B" además del bloqueo

    cuit_verificado_check = next(
        c for c in result["chequeos"] if c["check"] == "perfil_exige_cuit_verificado"
    )
    assert cuit_verificado_check["ok"] is False
    assert cuit_verificado_check["bloqueante"] is True
    assert result["listo"] is False, "sin CUIT verificado no debería poder confirmarse la factura"


def test_preview_chequeo_importe_cero_bloquea(monkeypatch):
    pedido_gratis = {**_fake_pedido(), "monto_total": 0, "iva_monto": 0}
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_gratis)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    importe_check = next(c for c in result["chequeos"] if c["check"] == "importe_positivo")
    assert importe_check["ok"] is False
    assert result["listo"] is False


def test_preview_pedido_no_confirmado_levanta_value_error(monkeypatch):
    monkeypatch.setattr(
        engine, "_get_pedido", lambda conn, pedido_id: {**_fake_pedido(), "estado": "solicitado"}
    )
    with pytest.raises(ValueError, match="solicitado"):
        engine.previsualizar_factura(1, conn=_FakeConn())


def test_preview_arca_caida_propaga_runtime_error(monkeypatch):
    """Si ARCA no responde (o el cert está vencido), el preview lo dice de
    entrada en vez de que el admin confirme y recién ahí se entere."""
    _patch_preview_common(monkeypatch, wsfe_instance=None)

    def _explota(emisor, conn):
        raise RuntimeError("Certificado de 'santini' no cargado.")

    monkeypatch.setattr(engine, "get_ta", _explota)

    with pytest.raises(RuntimeError, match="Certificado"):
        engine.previsualizar_factura(1, conn=_FakeConn())


def test_preview_arca_business_error_se_propaga_sin_envolver(monkeypatch):
    """`wsfe.ultimo_autorizado()` real levanta `ArcaBusinessError`/
    `ArcaResponseError` (taxonomía tipada) — `previsualizar_factura` ya NO la
    envuelve en `RuntimeError`: se deja pasar tal cual para que el route
    elija el status HTTP por subtipo (422/502/503) en vez de un 503 genérico."""
    from arca_fe.errores import ArcaBusinessError

    class _WsfeQueExplota(_FakeWsfe):
        def ultimo_autorizado(self, pto_vta, cbte_tipo):
            raise ArcaBusinessError("FECompUltimoAutorizado error — 600: no autorizado")

    _patch_preview_common(monkeypatch, _WsfeQueExplota(endpoint="x", cuit=1, token="t", sign="s"))

    with pytest.raises(ArcaBusinessError, match="600"):
        engine.previsualizar_factura(1, conn=_FakeConn())


# ── Receptor verificado contra el padrón de ARCA (emitir_factura bloquea;
# el preview solo avisa) ─────────────────────────────────────────────────────

_CUIT_VALIDO = "20301234563"  # dígito verificador correcto (verificado con cuil_valido)


def _persona_afip(razon_social="Empresa Real SA", domicilio="Calle Real 1", condicion_iva="responsable_inscripto"):
    from arca_fe.padron import PersonaArca

    return PersonaArca(
        cuit=_CUIT_VALIDO,
        razon_social=razon_social,
        nombre="",
        apellido="",
        domicilio=domicilio,
        condicion_iva=condicion_iva,
        estado_clave="ACTIVO",
    )


def test_emitir_factura_receptor_con_cuit_se_verifica_y_sobreescribe(monkeypatch):
    """Receptor con CUIT: `verificar_y_actualizar_receptor` se llama y sus
    datos (razón social/domicilio/condición IVA) sobreescriben lo que tenía
    el pedido ANTES de construir el comprobante — la factura sale con lo que
    dice AFIP, no con el dato interno viejo."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    wsfe.ultimo = 0
    wsfe.consultar_resp = None

    pedido_ri = {
        **_fake_pedido(),
        "cliente_id": 7,
        "cliente_perfil_impuestos": "monotributo",  # dato interno VIEJO
        "cliente_cuit": _CUIT_VALIDO,
        "cliente_razon_social": "Nombre Viejo Mal Escrito",
    }
    calls = _patch_common(monkeypatch, wsfe)
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)

    verificaciones = []

    def _fake_verificar(cuit, cliente_id, conn):
        verificaciones.append((cuit, cliente_id))
        return _persona_afip()

    monkeypatch.setattr(engine, "verificar_y_actualizar_receptor", _fake_verificar)
    monkeypatch.setattr(
        engine, "insert_factura", lambda **kw: (calls.setdefault("insert_factura", kw), 99)[1]
    )

    engine.emitir_factura(1)

    assert verificaciones == [(_CUIT_VALIDO, 7)]
    ins = calls["insert_factura"]
    assert ins["razon_social"] == "Empresa Real SA"
    # condicion_iva='responsable_inscripto' de AFIP → CondicionIva.RESPONSABLE_INSCRIPTO (=1)
    assert ins["condicion_iva_receptor"] == 1


def test_emitir_factura_resuelve_emisor_con_perfil_ya_corregido_por_afip(monkeypatch):
    """Bug real encontrado en revisión: `emisor_para` (decide QUÉ emisor
    factura, según la condición IVA del receptor) tiene que resolverse con el
    perfil YA CORREGIDO por AFIP, no con el dato interno viejo — si se
    resuelve antes de la corrección, un pedido con perfil interno
    desactualizado ('monotributo') pero AFIP confirmando 'responsable_inscripto'
    elegiría el emisor equivocado (justo el caso que esta verificación existe
    para prevenir)."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    wsfe.ultimo = 0
    wsfe.consultar_resp = None

    pedido_ri = {
        **_fake_pedido(),
        "cliente_id": 7,
        "cliente_perfil_impuestos": "monotributo",  # dato interno VIEJO
        "cliente_cuit": _CUIT_VALIDO,
    }
    calls = _patch_common(monkeypatch, wsfe)
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)
    monkeypatch.setattr(
        engine, "verificar_y_actualizar_receptor",
        lambda cuit, cliente_id, conn: _persona_afip(),  # condicion_iva='responsable_inscripto'
    )
    monkeypatch.setattr(
        engine, "insert_factura", lambda **kw: (calls.setdefault("insert_factura", kw), 99)[1]
    )

    perfiles_recibidos = []
    monkeypatch.setattr(
        engine, "emisor_para",
        lambda perfil, conn: perfiles_recibidos.append(perfil) or "santini",
    )

    engine.emitir_factura(1)

    assert perfiles_recibidos == ["responsable_inscripto"], (
        "emisor_para tiene que recibir el perfil YA CORREGIDO por AFIP, no "
        "'monotributo' (el dato interno viejo del pedido)"
    )


def test_emitir_factura_receptor_no_verificado_bloquea_sin_insertar(monkeypatch):
    """Si AFIP no puede confirmar el CUIT del receptor, `emitir_factura`
    propaga el RuntimeError SIN llegar nunca a `insert_factura` — no queda
    ninguna fila 'pendiente' zombie."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    pedido_ri = {
        **_fake_pedido(),
        "cliente_id": 7,
        "cliente_cuit": _CUIT_VALIDO,
    }
    calls = _patch_common(monkeypatch, wsfe)
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)

    def _fake_verificar(cuit, cliente_id, conn):
        raise RuntimeError("AFIP no pudo traer el padrón del CUIT — sistema caído")

    monkeypatch.setattr(engine, "verificar_y_actualizar_receptor", _fake_verificar)
    insert_llamado = []
    monkeypatch.setattr(
        engine, "insert_factura", lambda **kw: insert_llamado.append(kw) or 99
    )

    with pytest.raises(RuntimeError, match="sistema caído"):
        engine.emitir_factura(1)

    assert insert_llamado == []


def test_emitir_factura_receptor_sin_cuit_no_consulta_afip(monkeypatch):
    """Consumidor Final / DNI: no hay CUIT que verificar en un padrón
    CUIT-céntrico — `verificar_y_actualizar_receptor` NUNCA se llama."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    calls = _patch_common(monkeypatch, wsfe)  # _fake_pedido() ya tiene cliente_cuit=None

    def _fake_verificar(cuit, cliente_id, conn):
        raise AssertionError("no debería consultarse el padrón sin CUIT")

    monkeypatch.setattr(engine, "verificar_y_actualizar_receptor", _fake_verificar)

    engine.emitir_factura(1)  # no debe levantar nada


def test_emitir_factura_perfil_no_final_sin_cuit_bloquea(monkeypatch):
    """Regresión de bug real en producción: un cliente con `perfil_impuestos='monotributo'`
    guardado (posible desde el portal SIN pasar nunca por 'Verificar' contra ARCA — ver
    routes/cliente_portal/cuenta.py::cliente_update_me) pero SIN CUIT — Responsable Inscripto/
    Monotributo/Exento no existen sin CUIT en Argentina. Antes de este fix, `emitir_factura`
    facturaba igual (el gate de verificación solo corre si HAY un CUIT de 11 dígitos), saliendo
    con el perfil/domicilio viejo o vacío, sin confirmar contra ARCA."""
    pedido_sin_cuit = {
        **_fake_pedido(),
        "cliente_perfil_impuestos": "monotributo",
        "cliente_cuit": None,
    }
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    calls = _patch_common(monkeypatch, wsfe)
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_sin_cuit)

    def _fake_verificar(cuit, cliente_id, conn):
        raise AssertionError("no debería llamar al padrón sin un CUIT válido")

    monkeypatch.setattr(engine, "verificar_y_actualizar_receptor", _fake_verificar)
    insert_llamado = []
    monkeypatch.setattr(
        engine, "insert_factura", lambda **kw: insert_llamado.append(kw) or 99
    )

    with pytest.raises(ValueError, match="monotributo"):
        engine.emitir_factura(1)

    assert insert_llamado == []


def test_preview_chequeo_receptor_afip_bloquea_sin_romper(monkeypatch):
    """CUIT con dígito verificador OK pero que AFIP rechaza (o no responde)
    — el preview lo muestra como chequeo BLOQUEANTE, sin romper el preview
    en sí (fail-not-fast, mismo criterio que el resto de los chequeos)."""
    pedido_ri = {
        **_fake_pedido(),
        "cliente_perfil_impuestos": "responsable_inscripto",
        "cliente_cuit": _CUIT_VALIDO,
    }
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))

    def _fake_resolver(cuit, conn):
        raise RuntimeError("AFIP no pudo traer el padrón del CUIT — no existe persona")

    monkeypatch.setattr(engine, "resolver_persona", _fake_resolver)

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    afip_check = next(c for c in result["chequeos"] if c["check"] == "receptor_verificado_afip")
    assert afip_check["ok"] is False
    assert afip_check["bloqueante"] is True
    assert "no existe persona" in afip_check["mensaje"]
    assert result["listo"] is False


def test_preview_chequeo_receptor_afip_no_aparece_si_todo_bien(monkeypatch):
    """Si AFIP confirma el CUIT sin problemas, no se agrega ningún chequeo
    extra — mismo criterio que el resto: solo se lista lo que hay que
    atender."""
    pedido_ri = {
        **_fake_pedido(),
        "cliente_perfil_impuestos": "responsable_inscripto",
        "cliente_cuit": _CUIT_VALIDO,
    }
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))
    monkeypatch.setattr(engine, "resolver_persona", lambda cuit, conn: _persona_afip())

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    assert not any(c["check"] == "receptor_verificado_afip" for c in result["chequeos"])


def test_preview_perfil_con_cuit_verificado_no_bloquea(monkeypatch):
    """Contracara de `test_preview_chequeo_ri_sin_cuit_valido_bloquea`: con un
    CUIT válido presente, `perfil_exige_cuit_verificado` no bloquea (el chequeo
    de AFIP de verdad — `receptor_verificado_afip` — es el que confirma que ese
    CUIT existe de verdad, ver el test anterior)."""
    pedido_ri = {
        **_fake_pedido(),
        "cliente_perfil_impuestos": "responsable_inscripto",
        "cliente_cuit": _CUIT_VALIDO,
    }
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))
    monkeypatch.setattr(engine, "resolver_persona", lambda cuit, conn: _persona_afip())

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    check = next(c for c in result["chequeos"] if c["check"] == "perfil_exige_cuit_verificado")
    assert check["ok"] is True


def test_preview_receptor_domicilio_prioriza_afip_sobre_lo_guardado(monkeypatch):
    """Regla del dueño: si se factura con un CUIT, los datos que van en el comprobante son los
    que ARCA devuelve PARA ESE CUIT — nunca lo guardado en la cuenta, aunque coincidan la
    mayoría de las veces. El domicilio fresco de AFIP tiene que GANARLE al guardado, no ser
    un fallback-si-falta (antes era al revés: se mostraba "Calle Ficticia 123" — la cuenta —
    pese a que ARCA ya había confirmado "Calle Real 1" para este CUIT puntual)."""
    pedido_ri = {
        **_fake_pedido(),
        "cliente_perfil_impuestos": "responsable_inscripto",
        "cliente_cuit": _CUIT_VALIDO,
        "cliente_domicilio_fiscal": "Calle Ficticia 123",
    }
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))
    monkeypatch.setattr(
        engine, "resolver_persona", lambda cuit, conn: _persona_afip(domicilio="Calle Real 1")
    )

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    assert result["receptor"]["domicilio"] == "Calle Real 1"


def test_preview_receptor_domicilio_vacio_si_falta(monkeypatch):
    """Sin domicilio guardado, el preview manda `""` (nunca `None` ni la
    clave ausente) — el front distingue "vacío" de "sin confirmar" sin tener
    que chequear `undefined`."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    _patch_preview_common(monkeypatch, wsfe)

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    assert result["receptor"]["domicilio"] == ""


def test_preview_receptor_usa_domicilio_de_afip_si_no_esta_guardado(monkeypatch):
    """Bug real reportado por el dueño: el preview mostraba "sin confirmar" pese a que el
    chequeo `receptor_verificado_afip` (llama a `resolver_persona`, de solo lectura) ya había
    confirmado el CUIT contra ARCA con éxito — se descartaba el domicilio que esa misma
    respuesta traía, en vez de usarlo, porque `cliente_domicilio_fiscal` todavía no estaba
    persistido (recién se persiste al EMITIR de verdad, no en el preview)."""
    pedido_ri = {
        **_fake_pedido(),
        "cliente_perfil_impuestos": "responsable_inscripto",
        "cliente_cuit": _CUIT_VALIDO,
        "cliente_domicilio_fiscal": None,
    }
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))
    monkeypatch.setattr(
        engine,
        "resolver_persona",
        lambda cuit, conn: _persona_afip(domicilio="Domicilio Ficticio 456"),
    )

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    assert result["receptor"]["domicilio"] == "Domicilio Ficticio 456"
    assert not any(c["check"] == "receptor_verificado_afip" for c in result["chequeos"])


def test_preview_receptor_razon_social_prioriza_afip_sobre_lo_guardado(monkeypatch):
    """Bug real reportado por el dueño (screenshot): el preview mostraba el nombre GUARDADO EN
    LA CUENTA del cliente aunque ARCA ya hubiera confirmado un nombre distinto para el CUIT que
    se está usando para facturar — regla del dueño: "si se factura con el CUIT que se pone, los
    datos deben pertenecer a ese CUIT... se usa el fetch de AFIP", sin importar qué diga la
    cuenta. Mismo criterio que ya aplica `emitir_factura` de verdad (persona.razon_social gana),
    ahora también en el preview."""
    pedido_ri = {
        **_fake_pedido(),
        "cliente_perfil_impuestos": "responsable_inscripto",
        "cliente_cuit": _CUIT_VALIDO,
        "cliente_razon_social": "Nombre Viejo Ficticio SA",
    }
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))
    monkeypatch.setattr(
        engine, "resolver_persona", lambda cuit, conn: _persona_afip(razon_social="Nombre Real SA")
    )

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    assert result["receptor"]["razon_social"] == "Nombre Real SA"


def test_preview_letra_comprobante_prioriza_condicion_iva_de_afip_sobre_lo_guardado(monkeypatch):
    """Mismo patrón que la razón social/domicilio, pero para la condición de IVA — que decide
    la LETRA del comprobante (A/B/C), un dato que se le manda a AFIP en el CAE (RG5616). Si el
    perfil guardado en la cuenta está desactualizado ('monotributo') pero AFIP ya confirma
    'responsable_inscripto' para el CUIT, el preview tiene que calcular la letra con el dato de
    AFIP — la misma corrección que `emitir_factura` ya hacía antes de construir el comprobante
    (`test_emitir_factura_resuelve_emisor_con_perfil_ya_corregido_por_afip`). Antes, el preview
    resolvía AFIP recién en `_chequeos_previos`, DESPUÉS de construir el comprobante con el
    perfil viejo — mostraba una letra distinta a la que `emitir_factura` terminaba emitiendo."""
    pedido_ri = {
        **_fake_pedido(),
        "cliente_perfil_impuestos": "monotributo",  # dato interno VIEJO
        "cliente_cuit": _CUIT_VALIDO,
    }
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)
    # emisor RI (no monotributo) para que la letra resultante sea "A" y el test verifique
    # que `condicion_iva` de AFIP llegó de punta a punta hasta `tipo_comprobante`.
    monkeypatch.setattr(
        engine, "credenciales",
        lambda nombre, conn: replace(_fake_cred(), condicion_iva="responsable_inscripto"),
    )
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))
    monkeypatch.setattr(
        engine, "resolver_persona",
        lambda cuit, conn: _persona_afip(condicion_iva="responsable_inscripto"),
    )

    perfiles_recibidos = []
    monkeypatch.setattr(
        engine, "emisor_para",
        lambda perfil, conn: perfiles_recibidos.append(perfil) or "santini",
    )

    result = engine.previsualizar_factura(1, conn=_FakeConn())

    assert perfiles_recibidos == ["responsable_inscripto"], (
        "emisor_para (y por lo tanto la letra del comprobante) tiene que resolverse con el "
        "perfil YA CORREGIDO por AFIP, no 'monotributo' (el dato interno viejo del pedido)"
    )
    assert result["receptor"]["condicion_iva"] == "responsable_inscripto"
    assert result["comprobante"]["letra"] == "A"


# ── previsualizar_factura_html: mismo layout que la factura real, SIN CAE ──


def test_preview_html_renderiza_el_mismo_layout_sin_cae_real(monkeypatch):
    """Pedido del dueño: ver la factura COMPLETA (mismo layout/plantilla real) antes de
    emitir, no solo el resumen de chequeos — sin pedirle nada más a ARCA. Un preview de
    factura NUNCA puede parecer válido: el CAE es texto explícitamente no-numérico (no
    "(pendiente)" a secas, que podría leerse como un número truncado), más banner + marca
    de agua imposibles de confundir con un comprobante real."""
    wsfe = _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s")
    _patch_preview_common(monkeypatch, wsfe)
    monkeypatch.setattr(engine, "now_ar", lambda: datetime(2026, 7, 15))

    html = engine.previsualizar_factura_html(1, conn=_FakeConn())

    assert "<html" in html.lower() or "<!doctype" in html.lower()
    assert "SIN EMITIR" in html and "NO VÁLIDO" in html  # CAE explícitamente no-numérico
    assert "Juan Pérez" in html  # nombre del receptor, del pedido de prueba
    assert "BORRADOR" in html  # banner imposible de confundir con un comprobante real
    assert html.count("NO VÁLIDO — PREVIEW") >= 6  # marca de agua repetida, no un solo aviso chico


def test_preview_html_propaga_error_de_comprobante_invalido(monkeypatch):
    """Si `construir_comprobante` falla (ej. CUIT inválido), no hay nada que renderizar — a
    diferencia del preview de chequeos (que sí puede mostrar el error como fila), acá se
    propaga la excepción tal cual."""
    pedido_ri = {
        **_fake_pedido(),
        "cliente_perfil_impuestos": "responsable_inscripto",
        "cliente_cuit": "20301234560",  # dígito verificador incorrecto
    }
    monkeypatch.setattr(engine, "_get_pedido", lambda conn, pedido_id: pedido_ri)
    monkeypatch.setattr(engine, "emisor_para", lambda perfil, conn: "santini")
    monkeypatch.setattr(engine, "credenciales", lambda nombre, conn: _fake_cred())
    monkeypatch.setattr(engine, "get_ta", lambda emisor, conn: ("tok", "sign"))
    monkeypatch.setattr(engine, "WsfeClient", lambda **kw: _FakeWsfe(endpoint="x", cuit=1, token="t", sign="s"))

    with pytest.raises(ValueError):
        engine.previsualizar_factura_html(1, conn=_FakeConn())
