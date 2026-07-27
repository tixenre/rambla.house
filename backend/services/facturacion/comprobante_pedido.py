"""services.facturacion.comprobante_pedido — mapea un pedido Rambla a ComprobanteRequest.

Punto único: arca_fe.ComprobanteRequest se construye acá, no en el engine ni en el route.
La plata viene de `services.precios.calcular_total` (ya guardada en `alquileres.monto_total`);
este módulo solo la lee y transforma — NO recalcula (regla "el backend no recalcula").
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from arca_fe import (
    Concepto,
    CondicionIva,
    DocTipo,
    Emisor,
    IVA_21,
    ComprobanteRequest,
    Receptor,
    CbteAsoc,
)

# Condición IVA por perfil_impuestos del receptor (fuente única)
_PERFIL_A_COND_IVA: dict[str, CondicionIva] = {
    "responsable_inscripto": CondicionIva.RESPONSABLE_INSCRIPTO,
    "exento": CondicionIva.EXENTO,
    "monotributo": CondicionIva.MONOTRIBUTO,
    "consumidor_final": CondicionIva.CONSUMIDOR_FINAL,
}


def _condicion_iva_receptor(perfil: Optional[str]) -> CondicionIva:
    return _PERFIL_A_COND_IVA.get((perfil or "").strip().lower(), CondicionIva.CONSUMIDOR_FINAL)


def _doc_tipo_y_nro(pedido: dict) -> tuple[DocTipo, int]:
    """Decide DocTipo / doc_nro a partir de los datos del cliente en el pedido.

    Fallback: si no hay CUIT pero el pedido es RI → degradar a CF con DNI.
    """
    cuit = (pedido.get("cliente_cuit") or "").strip().replace("-", "").replace(" ", "")
    dni = (pedido.get("cliente_dni") or "").strip()
    perfil = (pedido.get("cliente_perfil_impuestos") or "").strip().lower()

    if perfil == "responsable_inscripto" and cuit and cuit.isdigit():
        return DocTipo.CUIT, int(cuit)
    if cuit and cuit.isdigit() and len(cuit) == 11:
        return DocTipo.CUIT, int(cuit)
    if dni and dni.isdigit():
        return DocTipo.DNI, int(dni)
    return DocTipo.CONSUMIDOR_FINAL, 0


def construir_comprobante(
    pedido: dict,
    emisor_obj: Emisor,
    emisor_cond: CondicionIva,
    *,
    fecha: date,
    es_nota_credito: bool = False,
    cbtes_asoc: tuple[CbteAsoc, ...] = (),
) -> ComprobanteRequest:
    """Arma un ComprobanteRequest desde los datos del pedido enriquecido fiscalmente.

    `pedido` debe haber pasado por:
    - `_enriquecer_pedido_con_cliente_fiscal` (perfil/cuit)
    - `_enriquecer_pedido_con_total` (neto/iva ya calculados)

    La plata que se usa:
    - Para RI (Factura A): `neto = pedido['monto_total']`, alicuota=IVA_21 (21%)
    - Para emisor Monotributo (Factura C): `neto = pedido['monto_total']`, SIN alícuota — un
      monotributista no le agrega el 21% a NADIE (regla legal fija, no depende de si el
      receptor es RI). Antes de este fix se plegaba `iva_monto` del receptor adentro del
      "neto" facturado (`neto_int + iva_int`) — vestigio de cuando el emisor Monotributo
      solo se resolvía automáticamente para receptores no-RI (`iva_monto` siempre 0 en ese
      caso, así que el pliegue nunca hacía nada distinto); el override de emisor (permite
      facturar Factura C a un cliente RI) expuso el caso real donde `iva_monto` > 0 —
      confirmado con el dueño: la Factura C tiene que facturar el neto solo, sin el 21%.
    """
    perfil_receptor = (pedido.get("cliente_perfil_impuestos") or "").strip().lower()
    cond_receptor = _condicion_iva_receptor(perfil_receptor)
    doc_tipo, doc_nro = _doc_tipo_y_nro(pedido)

    # Fallback: RI sin CUIT → degradar a Factura B/C (no puede emitir A)
    if (
        perfil_receptor == "responsable_inscripto"
        and doc_tipo != DocTipo.CUIT
    ):
        cond_receptor = CondicionIva.CONSUMIDOR_FINAL

    receptor = Receptor(
        doc_tipo=doc_tipo,
        doc_nro=doc_nro,
        condicion_iva=cond_receptor,
    )

    # --- importes ---
    # `monto_total` es SIEMPRE el neto (sin IVA), persistido por calcular_total.
    neto_int = int(pedido.get("monto_total") or 0)
    iva_int = int(pedido.get("iva_monto") or 0)
    importe_neto = Decimal(neto_int)

    # Emisor Monotributo → Factura C, nunca discrimina IVA — y nunca lo suma tampoco,
    # sea cual sea la condición del receptor (un monotributista no le agrega el 21% a
    # NADIE, es una regla legal fija, no una preferencia). `iva_int` solo se usa para
    # el emisor RI (Factura A/B), que sí discrimina IVA cuando corresponde.
    alicuota = None if emisor_cond == CondicionIva.MONOTRIBUTO else (IVA_21 if iva_int > 0 else None)

    # --- fechas de servicio ---
    # Concepto = SERVICIOS (2) → requiere FchServDesde/Hasta/VtoPago
    fecha_desde = _parse_fecha(pedido.get("fecha_desde"))
    fecha_hasta = _parse_fecha(pedido.get("fecha_hasta"))
    fecha_vto_pago = _fecha_vto_pago(fecha_hasta, fecha)

    return ComprobanteRequest(
        emisor=emisor_obj,
        receptor=receptor,
        concepto=Concepto.SERVICIOS,
        importe_neto=importe_neto,
        alicuota=alicuota,
        fecha=fecha,
        fecha_serv_desde=fecha_desde,
        fecha_serv_hasta=fecha_hasta,
        fecha_vto_pago=fecha_vto_pago,
        es_nota_credito=es_nota_credito,
        cbtes_asoc=cbtes_asoc,
    )


def _fecha_vto_pago(fecha_hasta: Optional[date], fecha_comprobante: date) -> date:
    """ARCA rechaza (10036) un FchVtoPago anterior a la fecha del comprobante.

    `fecha_hasta` (fin del alquiler) es un vencimiento razonable cuando se
    factura DURANTE el servicio, pero acá se factura casi siempre DESPUÉS de
    que el pedido ya terminó — en ese caso queda en el pasado y ARCA lo
    rechaza. El vencimiento nunca puede ser anterior a hoy (la fecha del
    comprobante que se está emitiendo)."""
    if fecha_hasta is None or fecha_hasta < fecha_comprobante:
        return fecha_comprobante
    return fecha_hasta


def _parse_fecha(s) -> Optional[date]:
    """`fecha_desde`/`fecha_hasta` vienen de columnas TIMESTAMP (`datetime.datetime`,
    no `datetime.date`) — hay que chequear `datetime` ANTES que `date` porque
    `datetime` es subclase de `date`: `isinstance(dt, date)` da True y devolvía
    el datetime completo sin truncar. `_fecha_vto_pago` comparaba ese datetime
    contra un `date` (`hoy`) y explotaba con TypeError en prod."""
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


def construir_comprobante_nc(
    original,  # services.facturacion.repo.Factura
    pedido: dict,
    emisor_obj: Emisor,
    *,
    fecha: date,
    cbtes_asoc: tuple[CbteAsoc, ...],
) -> ComprobanteRequest:
    """Arma el ComprobanteRequest de la Nota de Crédito que anula `original`.

    A diferencia de `construir_comprobante`, los importes y el receptor salen
    del snapshot YA PERSISTIDO en `original` — NO se recalculan desde el pedido
    en vivo. Una NC tiene que cancelar EXACTAMENTE lo que se facturó ante ARCA;
    si el pedido cambió de precio/descuento después de emitida la factura, una
    NC recalculada dejaría un remanente sin cancelar en la cuenta de ARCA.
    Las fechas de servicio sí vienen del pedido (no son plata, son estables).
    """
    receptor = Receptor(
        doc_tipo=DocTipo(original.doc_tipo),
        doc_nro=int(original.doc_nro) if str(original.doc_nro).isdigit() else 0,
        condicion_iva=CondicionIva(original.condicion_iva_receptor),
    )
    importe_neto = Decimal(original.imp_neto)
    alicuota = IVA_21 if original.imp_iva > 0 else None

    fecha_desde = _parse_fecha(pedido.get("fecha_desde"))
    fecha_hasta = _parse_fecha(pedido.get("fecha_hasta"))

    return ComprobanteRequest(
        emisor=emisor_obj,
        receptor=receptor,
        concepto=Concepto.SERVICIOS,
        importe_neto=importe_neto,
        alicuota=alicuota,
        fecha=fecha,
        fecha_serv_desde=fecha_desde,
        fecha_serv_hasta=fecha_hasta,
        fecha_vto_pago=_fecha_vto_pago(fecha_hasta, fecha),
        es_nota_credito=True,
        cbtes_asoc=cbtes_asoc,
    )
