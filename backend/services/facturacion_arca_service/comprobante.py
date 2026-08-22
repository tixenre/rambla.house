"""services.facturacion_arca_service.comprobante — mapea un pedido de Rambla a
`arca_service_client.ComprobanteInput`.

Espejo DELIBERADO de la lógica de negocio de `services/facturacion/comprobante_pedido.py`
(mismo criterio de receptor/plata/fechas — es el mismo negocio, alquileres de Rambla, no
dos reglas fiscales distintas) pero SIN importar ese módulo ni nada de `arca_fe`: los dos
motores son paralelos a propósito (ver docstring de `__init__.py`), y los tipos de
`ComprobanteInput` (arca-service) no son los de `ComprobanteRequest` (arca_fe) — no hay
nada que compartir en código, solo en criterio. Si el criterio de negocio cambia
(ej. una nueva regla de qué condición de IVA le corresponde al emisor), actualizar los
DOS lugares es responsabilidad de quien lo cambie — documentado acá para que no se
pierda, no automatizable sin acoplar los dos motores.

`_get_pedido` SÍ se reusa de `services.facturacion.engine` — es lectura general de datos
de un pedido (compone `services.finanzas_flujo.pedido` + `services.pedidos_enriquecimiento`,
ninguno de los dos específico de arca_fe), no lógica de arca_fe en sí.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from arca_service_client import Alicuota, Concepto, CondicionIva, ComprobanteInput, DocTipo, ItemFactura

# Condición IVA del RECEPTOR por perfil_impuestos — mismo mapeo que
# services/facturacion/comprobante_pedido.py::_PERFIL_A_COND_IVA, portado a
# los enums de arca_service_client (valores enteros ya verificados idénticos
# a arca_fe.modelos, ver arca_service_client/enums.py).
_PERFIL_A_COND_IVA: dict[str, CondicionIva] = {
    "responsable_inscripto": CondicionIva.RESPONSABLE_INSCRIPTO,
    "exento": CondicionIva.EXENTO,
    "monotributo": CondicionIva.MONOTRIBUTO,
    "consumidor_final": CondicionIva.CONSUMIDOR_FINAL,
}


def _condicion_iva_receptor(perfil: Optional[str]) -> CondicionIva:
    return _PERFIL_A_COND_IVA.get((perfil or "").strip().lower(), CondicionIva.CONSUMIDOR_FINAL)


def _doc_tipo_y_nro(pedido: dict) -> tuple[DocTipo, str]:
    """Decide DocTipo / doc_nro del receptor — mismo criterio que
    `comprobante_pedido.py::_doc_tipo_y_nro` (fallback: RI sin CUIT → degrada
    a Consumidor Final con DNI). `receptor_doc_nro` en `ComprobanteInput` es
    `str` (no `int`, a diferencia de `arca_fe.Receptor.doc_nro`) — ver su
    docstring en `models.py`."""
    cuit = (pedido.get("cliente_cuit") or "").strip().replace("-", "").replace(" ", "")
    dni = (pedido.get("cliente_dni") or "").strip()
    perfil = (pedido.get("cliente_perfil_impuestos") or "").strip().lower()

    if perfil == "responsable_inscripto" and cuit and cuit.isdigit():
        return DocTipo.CUIT, cuit
    if cuit and cuit.isdigit() and len(cuit) == 11:
        return DocTipo.CUIT, cuit
    if dni and dni.isdigit():
        return DocTipo.DNI, dni
    return DocTipo.CONSUMIDOR_FINAL, "0"


def _parse_fecha(s) -> Optional[date]:
    """`fecha_desde`/`fecha_hasta` vienen de columnas TIMESTAMP (`datetime`, no
    `date`) — chequear `datetime` ANTES que `date` (es subclase de `date`).
    Mismo gotcha ya documentado en `comprobante_pedido.py::_parse_fecha`."""
    if not s:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    s = str(s)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _fecha_vto_pago(fecha_hasta: Optional[date], fecha_comprobante: date) -> date:
    """ARCA rechaza un vencimiento de pago anterior a la fecha del comprobante
    — se factura casi siempre DESPUÉS de que el pedido ya terminó, así que
    `fecha_hasta` puede quedar en el pasado. Mismo criterio que
    `comprobante_pedido.py::_fecha_vto_pago`."""
    if fecha_hasta is None or fecha_hasta < fecha_comprobante:
        return fecha_comprobante
    return fecha_hasta


def idempotency_key_de_pedido(pedido: dict) -> str:
    """Clave determinística por pedido — SIEMPRE la misma para el mismo pedido,
    nunca un valor random (la SDK exige esto para que la idempotencia
    funcione, ver su README). Usa `numero_pedido` si está (el identificador
    que ve el dueño), `id` si no."""
    return f"pedido-{pedido.get('numero_pedido') or pedido['id']}"


def construir_comprobante_input(
    pedido: dict,
    *,
    emisor_condicion_iva: CondicionIva,
    emisor_razon_social: str = "",
    emisor_domicilio: str = "",
    emisor_iibb: str = "",
    fecha: Optional[date] = None,
    idempotency_key: Optional[str] = None,
) -> ComprobanteInput:
    """Arma un `ComprobanteInput` desde un pedido enriquecido (`services.facturacion.
    engine._get_pedido` — trae `monto_total`/`iva_monto` ya calculados por
    `services.precios.calcular_total`, este módulo NO recalcula plata, solo la lee).

    `emisor_condicion_iva`/`emisor_razon_social`/`emisor_domicilio`/`emisor_iibb` son
    explícitos a propósito (no se resuelven acá): quién factura y con qué identidad es
    una decisión de negocio que vive en el caller (routing por perfil del receptor,
    igual que `services/facturacion/emisores.py::emisor_para` — reimplementado
    localmente si hace falta esa regla, no importado, ver docstring del módulo). Este
    módulo solo sabe transformar UN pedido + una identidad de emisor YA decidida.

    La plata (idéntico criterio que `comprobante_pedido.py::construir_comprobante`):
    - RI: `importe_neto = pedido['monto_total']`, `alicuota_unica = IVA_21` si
      `iva_monto > 0`.
    - Monotributo (Factura C): `importe_neto = pedido['monto_total']`, SIN alícuota —
      un monotributista no le agrega el 21% a NADIE, sea cual sea la condición del
      receptor (regla legal fija, confirmada con el dueño para el motor arca_fe — el
      mismo hecho fiscal, no una preferencia de este motor)."""
    fecha_comprobante = fecha or date.today()

    perfil_receptor = (pedido.get("cliente_perfil_impuestos") or "").strip().lower()
    cond_receptor = _condicion_iva_receptor(perfil_receptor)
    doc_tipo, doc_nro = _doc_tipo_y_nro(pedido)

    # Fallback: RI sin CUIT → no puede ser Factura A, degrada a Consumidor Final.
    if perfil_receptor == "responsable_inscripto" and doc_tipo != DocTipo.CUIT:
        cond_receptor = CondicionIva.CONSUMIDOR_FINAL

    neto_int = int(pedido.get("monto_total") or 0)
    iva_int = int(pedido.get("iva_monto") or 0)
    importe_neto = Decimal(neto_int)

    alicuota_unica = (
        None
        if emisor_condicion_iva == CondicionIva.MONOTRIBUTO
        else (Alicuota.IVA_21 if iva_int > 0 else None)
    )

    fecha_desde = _parse_fecha(pedido.get("fecha_desde"))
    fecha_hasta = _parse_fecha(pedido.get("fecha_hasta"))

    numero_pedido = pedido.get("numero_pedido") or pedido["id"]
    items = [
        ItemFactura(
            descripcion=f"Alquiler de equipos audiovisuales — Pedido #{numero_pedido}",
            precio_unitario=importe_neto,
            subtotal=importe_neto,
            cantidad=Decimal("1"),
        )
    ]

    return ComprobanteInput(
        idempotency_key=idempotency_key or idempotency_key_de_pedido(pedido),
        concepto=Concepto.SERVICIOS,
        emisor_condicion_iva=emisor_condicion_iva,
        receptor_doc_tipo=doc_tipo,
        receptor_doc_nro=doc_nro,
        receptor_condicion_iva=cond_receptor,
        fecha=fecha_comprobante,
        fecha_serv_desde=fecha_desde,
        fecha_serv_hasta=fecha_hasta,
        fecha_vto_pago=_fecha_vto_pago(fecha_hasta, fecha_comprobante),
        importe_neto=importe_neto,
        alicuota_unica=alicuota_unica,
        items=items,
        emisor_razon_social=emisor_razon_social,
        emisor_domicilio=emisor_domicilio,
        emisor_iibb=emisor_iibb,
        receptor_nombre=(pedido.get("cliente_nombre") or "").strip(),
        receptor_domicilio=(pedido.get("cliente_domicilio_fiscal") or "").strip(),
    )
