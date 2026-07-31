"""services.facturacion.repo — DAL para la tabla `facturas`. NUNCA DELETE.

Toda plata es inmutable: no hay DELETE de facturas emitidas.
Anulación = nota de crédito (estado='anulada').
DAL psycopg3 %s style (regla 2026-06-27).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional


@dataclass
class Factura:
    id: int
    pedido_id: int
    emisor: str
    ambiente: str
    cbte_tipo: int
    pto_vta: int
    cbte_nro: Optional[int]
    cae: Optional[str]
    cae_vto: Optional[date]
    doc_tipo: int
    doc_nro: str
    condicion_iva_receptor: int
    concepto: int
    # NUMERIC(12,2): Decimal exacto al centavo (bug #1209 — ver engine.py).
    imp_neto: Decimal
    imp_iva: Decimal
    imp_total: Decimal
    moneda: str
    cliente_cuit: Optional[str]
    razon_social: Optional[str]
    qr_payload: Optional[str]
    pdf_key: Optional[str]
    estado: str
    nota_credito_de: Optional[int]
    raw_request: Optional[dict]
    raw_response: Optional[dict]
    errores: Optional[list]
    fecha_emision: Optional[datetime]
    created_at: datetime
    created_by: Optional[str]
    # Domicilio del receptor, congelado al emitir — a diferencia de
    # razón_social/CUIT (arriba, ya se congelaban desde siempre), este es
    # NUEVO (ver migración d4e6f8a2b1c3): las facturas emitidas antes quedan
    # con NULL acá, así que va al final CON DEFAULT para no romper ninguna
    # construcción existente de `Factura(...)` en tests/callers.
    domicilio: Optional[str] = None


def _row_to_factura(row: dict) -> Factura:
    return Factura(
        id=row["id"],
        pedido_id=row["pedido_id"],
        emisor=row["emisor"],
        ambiente=row["ambiente"],
        cbte_tipo=row["cbte_tipo"],
        pto_vta=row["pto_vta"],
        cbte_nro=row["cbte_nro"],
        cae=row["cae"],
        cae_vto=row["cae_vto"],
        doc_tipo=row["doc_tipo"],
        doc_nro=row["doc_nro"],
        condicion_iva_receptor=row["condicion_iva_receptor"],
        concepto=row["concepto"],
        imp_neto=row["imp_neto"],
        imp_iva=row["imp_iva"],
        imp_total=row["imp_total"],
        moneda=row["moneda"],
        cliente_cuit=row["cliente_cuit"],
        razon_social=row["razon_social"],
        domicilio=row["domicilio"],
        qr_payload=row["qr_payload"],
        pdf_key=row["pdf_key"],
        estado=row["estado"],
        nota_credito_de=row["nota_credito_de"],
        raw_request=row["raw_request"],
        raw_response=row["raw_response"],
        errores=row["errores"],
        fecha_emision=row["fecha_emision"],
        created_at=row["created_at"],
        created_by=row["created_by"],
    )


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------


def get_factura_vigente(pedido_id: int, conn) -> Optional[Factura]:
    """Factura en estado 'pendiente' o 'emitida' para el pedido (UNIQUE parcial)."""
    row = conn.execute(
        """
        SELECT * FROM facturas
         WHERE pedido_id = %s AND estado IN ('pendiente', 'emitida')
         LIMIT 1
        """,
        (pedido_id,),
    ).fetchone()
    return _row_to_factura(row) if row else None


def get_factura_principal_emitida(pedido_id: int, conn) -> Optional[Factura]:
    """La factura vigente del pedido (no NC), solo si ya está 'emitida' —
    para el portal cliente: la factura aparece como documento recién ahí,
    no antes (a diferencia de remito/contrato, que dependen del estado del
    pedido, no de si el documento fiscal existe)."""
    row = conn.execute(
        """
        SELECT * FROM facturas
         WHERE pedido_id = %s AND estado = 'emitida' AND nota_credito_de IS NULL
         LIMIT 1
        """,
        (pedido_id,),
    ).fetchone()
    return _row_to_factura(row) if row else None


def factura_c_vigente(pedido_id: int, conn) -> bool:
    """True si el pedido tiene una Factura C (emisor Monotributo) ya emitida.

    Un emisor Monotributo nunca discrimina NI suma IVA (2026-07-27,
    `comprobante_pedido.construir_comprobante`) — este helper es para que otros
    consumidores del pedido (ej. el Desglose en vivo del editor admin,
    `routes/alquileres/cotizacion.py::cotizar`) sepan que el cliente NO va a pagar
    el 21% que su perfil fiscal por sí solo sugeriría, una vez que la factura real
    ya se emitió así. Se anula (NC) → deja de contar (`get_factura_principal_emitida`
    ya filtra `nota_credito_de IS NULL` y `estado='emitida'`, y la NC deja a la
    original en `estado='anulada'`)."""
    from arca_fe import CbteTipo

    factura = get_factura_principal_emitida(pedido_id, conn)
    return bool(factura and factura.cbte_tipo == int(CbteTipo.FACTURA_C))


def pedidos_con_factura_emitida(pedido_ids: list[int], conn) -> set[int]:
    """Subconjunto de `pedido_ids` que tienen una factura principal 'emitida'
    (batch, para listados — evita N+1)."""
    if not pedido_ids:
        return set()
    rows = conn.execute(
        """
        SELECT DISTINCT pedido_id FROM facturas
         WHERE pedido_id = ANY(%s) AND estado = 'emitida' AND nota_credito_de IS NULL
        """,
        (pedido_ids,),
    ).fetchall()
    return {r["pedido_id"] for r in rows}


def get_by_id(factura_id: int, conn) -> Optional[Factura]:
    row = conn.execute(
        "SELECT * FROM facturas WHERE id = %s",
        (factura_id,),
    ).fetchone()
    return _row_to_factura(row) if row else None


def list_facturas(
    conn,
    *,
    pedido_id: Optional[int] = None,
    emisor: Optional[str] = None,
    estado: Optional[str] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[Factura]:
    clauses = []
    params: list[Any] = []

    if pedido_id is not None:
        clauses.append("pedido_id = %s")
        params.append(pedido_id)
    if emisor:
        clauses.append("emisor = %s")
        params.append(emisor)
    if estado:
        clauses.append("estado = %s")
        params.append(estado)
    if desde:
        clauses.append("fecha_emision >= %s")
        params.append(desde)
    if hasta:
        clauses.append("fecha_emision < (%s::date + interval '1 day')")
        params.append(hasta)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params += [limit, offset]

    rows = conn.execute(
        f"SELECT * FROM facturas {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
        params,
    ).fetchall()
    return [_row_to_factura(r) for r in rows]


# ---------------------------------------------------------------------------
# Escrituras
# ---------------------------------------------------------------------------


def insert_factura(
    *,
    conn,
    pedido_id: int,
    emisor: str,
    ambiente: str,
    cbte_tipo: int,
    pto_vta: int,
    doc_tipo: int,
    doc_nro: str,
    condicion_iva_receptor: int,
    concepto: int,
    imp_neto: Decimal,
    imp_iva: Decimal,
    imp_total: Decimal,
    moneda: str = "PES",
    cliente_cuit: Optional[str] = None,
    razon_social: Optional[str] = None,
    domicilio: Optional[str] = None,
    raw_request: Optional[dict] = None,
    created_by: Optional[str] = None,
) -> int:
    """Inserta una factura en estado 'pendiente'. Devuelve el id.

    `domicilio`: el del receptor, ya verificado contra el padrón de ARCA al
    emitir (`engine.py`) — queda FIJO acá (a diferencia de antes, que se leía
    en vivo de la ficha del cliente en cada reimpresión del PDF)."""
    row = conn.execute(
        """
        INSERT INTO facturas (
            pedido_id, emisor, ambiente, cbte_tipo, pto_vta,
            doc_tipo, doc_nro, condicion_iva_receptor, concepto,
            imp_neto, imp_iva, imp_total, moneda,
            cliente_cuit, razon_social, domicilio,
            raw_request, estado, created_by
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, 'pendiente', %s
        )
        RETURNING id
        """,
        (
            pedido_id, emisor, ambiente, cbte_tipo, pto_vta,
            doc_tipo, doc_nro, condicion_iva_receptor, concepto,
            imp_neto, imp_iva, imp_total, moneda,
            cliente_cuit, razon_social, domicilio,
            json.dumps(raw_request) if raw_request else None,
            created_by,
        ),
    ).fetchone()
    return row["id"]


def update_cae(
    factura_id: int,
    conn,
    *,
    cbte_nro: int,
    cae: str,
    cae_vto: date,
    qr_payload: str,
    raw_response: dict,
    estado: str = "emitida",
) -> None:
    """Actualiza el CAE recibido de ARCA. Estado pasa a 'emitida' (o 'error')."""
    conn.execute(
        """
        UPDATE facturas
           SET cbte_nro = %s, cae = %s, cae_vto = %s, qr_payload = %s,
               raw_response = %s, estado = %s, fecha_emision = now()
         WHERE id = %s
        """,
        (cbte_nro, cae, cae_vto, qr_payload, json.dumps(raw_response), estado, factura_id),
    )


def update_error(
    factura_id: int,
    conn,
    *,
    errores: list,
    raw_response: Optional[dict] = None,
) -> None:
    """Marca la factura como 'error' con detalle de errores."""
    conn.execute(
        """
        UPDATE facturas
           SET estado = 'error', errores = %s, raw_response = %s
         WHERE id = %s
        """,
        (json.dumps(errores), json.dumps(raw_response) if raw_response else None, factura_id),
    )


def marcar_anulada(factura_id: int, conn) -> None:
    """Marca la factura original como 'anulada' (su CAE sigue válido; la NC es la anulación)."""
    conn.execute(
        "UPDATE facturas SET estado = 'anulada' WHERE id = %s",
        (factura_id,),
    )


def revertir_anulacion(factura_id: int, conn) -> None:
    """Vuelve la factura original a 'emitida' si la NC que la iba a anular falló ante ARCA."""
    conn.execute(
        "UPDATE facturas SET estado = 'emitida' WHERE id = %s",
        (factura_id,),
    )
