"""Resolver único de emisor: perfil fiscal del receptor → quién factura.

Compartido con firma de contratos (#1138): la misma regla decide el Locador
del contrato y el emisor de la factura.

El routing es dinámico: busca en `emisores_arca` el primer emisor activo con
la `condicion_iva` que corresponde al perfil del receptor. El admin puede
agregar/cambiar emisores desde el back-office sin tocar el código.
"""
from __future__ import annotations

from typing import Optional


def emisor_para(
    perfil_impuestos: str, conn, *, override_emisor_id: Optional[int] = None
) -> str:
    """Devuelve el `nombre` del emisor en `emisores_arca` para el perfil fiscal.

    - 'responsable_inscripto' → busca emisor con condicion_iva='responsable_inscripto'
    - cualquier otro           → busca emisor con condicion_iva='monotributo'

    `override_emisor_id`: cuando se pasa, ignora la resolución automática de
    arriba y factura con ESE emisor puntual — para el caso excepcional en que
    el NEGOCIO decide facturar distinto al default (ej. un cliente responsable
    inscripto que pide igual una Factura C: eso es legal — la letra depende
    solo de que el EMISOR sea monotributista, nunca del receptor — pero el
    default de Rambla arriba nunca lo elegiría solo). Sigue siendo la fuente
    única: no bypasea esta función, la extiende con un segundo modo explícito.

    Raises:
        ValueError: si no hay emisor activo configurado para esa condición, o
        (con override) si el emisor puntual no existe o está inactivo.
    """
    from services.facturacion.emisores_repo import get_activo_para_condicion, get_by_id

    if override_emisor_id is not None:
        emisor = get_by_id(override_emisor_id, conn)
        if emisor is None:
            raise ValueError(f"Emisor {override_emisor_id} no encontrado.")
        if not emisor.activo:
            raise ValueError(f"El emisor '{emisor.nombre}' está inactivo.")
        return emisor.nombre

    condicion = (
        "responsable_inscripto"
        if (perfil_impuestos or "").strip().lower() == "responsable_inscripto"
        else "monotributo"
    )
    emisor = get_activo_para_condicion(condicion, conn)
    if emisor is None:
        raise ValueError(
            f"No hay emisor activo configurado para condición IVA '{condicion}'. "
            "Configurá un emisor en el back-office → Facturación ARCA → Emisores."
        )
    return emisor.nombre
