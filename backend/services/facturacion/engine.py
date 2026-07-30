"""services.facturacion.engine — orquestador de emisión de facturas ARCA.

Implementa la secuencia robusta de `emitir_factura` y `emitir_nota_credito`:
- Advisory lock por (pto_vta, cbte_tipo) durante TODA la llamada SOAP
- Idempotencia via UNIQUE parcial + FECompConsultar ante timeout
- TX atómica para persistir CAE
- Nunca 500: error ARCA → estado='error', reintentable

El PDF NO se genera ni se guarda acá: se renderiza al vuelo cuando hace
falta verlo/descargarlo/mandarlo por mail (`routes/facturacion.py`), a
partir de los datos ya persistidos — la factura no cambia una vez emitida,
así que regenerar el PDF siempre da el mismo resultado.

Reglas invariantes (no violar):
- Nunca DELETE de una factura emitida
- No toca el core de reservas
- Secretos solo en ENV (gating default-deny)
"""

from __future__ import annotations

import hashlib
from typing import Optional

from database import get_db, now_ar

from arca_fe import (
    ArcaError,
    CaeResult,
    CbteTipo,
    CondicionIva,
    DocTipo,
    Emisor,
    tipo_comprobante,
    calcular_importes,
    armar_qr,
    CbteAsoc,
)
from services.facturacion.config import credenciales
from services.facturacion.emisores import emisor_para
from services.facturacion.padron import resolver_persona, verificar_y_actualizar_receptor
from services.facturacion.wsaa_cache import get_ta
from services.facturacion.comprobante_pedido import (
    construir_comprobante,
    construir_comprobante_nc,
)
from services.facturacion.repo import (
    Factura,
    get_factura_vigente,
    get_by_id,
    insert_factura,
    update_cae,
    update_error,
    marcar_anulada,
    revertir_anulacion,
)
from arca_fe.wsfe import WsfeClient

# Namespace de advisory lock para facturas (≠ pedidos, que usan el suyo)
_LOCK_NS = 0xFA0C0000


def _advisory_hash(pto_vta: int, cbte_tipo: int) -> int:
    """Número de lock deterministico para (pto_vta, cbte_tipo)."""
    key = f"{pto_vta}:{cbte_tipo}"
    h = int(hashlib.sha256(key.encode()).hexdigest(), 16) & 0x7FFFFFFF
    return (_LOCK_NS | (h & 0xFFFF)) & 0x7FFFFFFF


def _nombre_emisor(perfil_receptor: str, conn, emisor_id: Optional[int]) -> str:
    """Resuelve el nombre del emisor — sin override, llama a `emisor_para` con el
    mismo call shape (2 posicionales) de siempre, para no exigirle el kwarg nuevo
    a ningún mock existente de `emisor_para` en los tests. El override solo se
    pasa cuando de verdad hay uno (caso excepcional, ver `emisores.emisor_para`)."""
    if emisor_id is not None:
        return emisor_para(perfil_receptor, conn, override_emisor_id=emisor_id)
    return emisor_para(perfil_receptor, conn)


def _get_pedido(conn, pedido_id: int) -> dict:
    from database import row_to_dict
    from services.pedidos_enriquecimiento import (
        _enriquecer_pedido_con_cliente_fiscal,
        _enriquecer_pedido_con_cliente,
        _batch_get_alquiler_items,
    )
    from services.finanzas_flujo.pedido import combinar_turnos_vinculados, desglose_de_pedido

    row = conn.execute(
        "SELECT * FROM alquileres WHERE id = %s",
        (pedido_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Pedido {pedido_id} no encontrado")
    pedido = row_to_dict(row)

    # Cargar items (necesarios para desglose_de_pedido)
    items_map = _batch_get_alquiler_items(conn, [pedido_id])
    pedido["items"] = items_map.get(pedido_id, [])

    # El desglose de plata (bruto/neto/IVA, cobro_modo-aware) y el enriquecimiento de cliente pasan
    # por módulos de services/, nunca por routes.alquileres — un service no debería depender de un
    # route (auditoría cruzada de plata, 2026-07-02).
    desglose_de_pedido(conn, pedido)
    # Un pedido de alquiler y sus turnos del Estudio vinculados son UNA sola venta
    # → UNA sola factura (#1308, "facturar en el mismo pedido"). Va acá, en el punto
    # único de carga, para que los 4 consumidores de `_get_pedido` (chequeos previos,
    # preview HTML, emisión, y re-render/mail de una factura ya emitida) vean SIEMPRE
    # el mismo número — si viviera solo en `emitir_factura`, el preview y la
    # reimpresión mostrarían un total distinto al del CAE.
    combinar_turnos_vinculados(conn, pedido, expandir_periodo=True)
    _enriquecer_pedido_con_cliente_fiscal(conn, pedido)
    _enriquecer_pedido_con_cliente(conn, pedido)
    return pedido


def _rechazar_si_es_turno_vinculado(pedido: dict) -> None:
    """Un turno del Estudio vinculado NO se factura por su cuenta: su plata ya
    entra en la factura de su pedido principal (`combinar_turnos_vinculados`).
    Sin este gate se podía emitir dos veces la misma plata — el endpoint de
    facturar nunca miró `pedido_principal_id`.

    Va en los dos puntos de ENTRADA de facturación (preview y emisión), NO
    dentro de `_get_pedido`: la nota de crédito y el re-render/mail de una
    factura de turno **preexistente** (emitida antes de que existiera este
    gate) también pasan por `_get_pedido`, y tienen que seguir funcionando —
    la NC es justamente la vía para deshacer una de esas."""
    principal_id = pedido.get("pedido_principal_id")
    if principal_id:
        raise ValueError(
            f"Este turno del Estudio se factura desde su pedido principal "
            f"(#{principal_id}), que ya incluye su importe."
        )


# ---------------------------------------------------------------------------
# Preview — arma el comprobante sin tocar ARCA (para confirmar antes de emitir)
# ---------------------------------------------------------------------------


def _chequeos_previos(
    req,
    perfil_receptor: str,
    importes: dict,
    ambiente: str,
    numero_a_emitir: int,
    *,
    persona_afip=None,
    afip_error: Optional[str] = None,
) -> tuple[list[dict], Optional[str], Optional[str]]:
    """Chequeos fail-not-fast (todos corren, ninguno frena a los demás — mismo
    patrón que `services/checkout/validar.py`). Lo irreversible es "Confirmar
    y emitir": acá se junta todo lo verificable de antemano para que ese paso
    no tenga sorpresas.

    `persona_afip`/`afip_error` ya vienen resueltos por el CALLER (una sola consulta de
    solo lectura a ARCA, `resolver_persona`, hecha ANTES de construir el comprobante — ver
    `previsualizar_factura` — para que `condicion_iva` también salga corregida contra AFIP
    antes de calcular la letra/tipo del comprobante) — esta función no vuelve a pegarle a
    ARCA, solo arma los chequeos a partir de ese resultado ya conocido.

    Devuelve `(chequeos, domicilio_afip, razon_social_afip)` — lo que ARCA devolvió en esa
    consulta si tuvo éxito, o `None` cada uno. Antes se descartaba: el chequeo confirmaba el
    CUIT contra ARCA pero el domicilio/razón social resueltos en esa misma llamada se tiraban,
    así que el preview podía mostrar "sin confirmar" (o peor: el NOMBRE VIEJO guardado en la
    cuenta del cliente) aunque ARCA sí hubiera devuelto el dato real — la ficha del cliente
    (`cliente_razon_social`/`cliente_domicilio_fiscal`) solo se corrige recién al EMITIR de
    verdad (`verificar_y_actualizar_receptor`), no en el preview de solo lectura. Regla del
    dueño: si se factura con un CUIT, los datos que van en el comprobante son los que ARCA
    devuelve PARA ESE CUIT — nunca lo que haya guardado en la cuenta, aunque coincida la
    mayoría de las veces."""
    from identity.anchor import cuil_valido

    domicilio_afip: Optional[str] = persona_afip.domicilio if persona_afip else None
    razon_social_afip: Optional[str] = persona_afip.razon_social if persona_afip else None
    chequeos = [
        {
            "check": "credenciales_arca",
            "ok": True,
            "bloqueante": False,
            "mensaje": f"Conectado a ARCA ({ambiente}) — próximo comprobante N° {numero_a_emitir}",
        },
    ]

    if req.receptor.doc_tipo == DocTipo.CUIT:
        cuit_ok = cuil_valido(str(req.receptor.doc_nro))
        chequeos.append(
            {
                "check": "cuit_receptor",
                "ok": cuit_ok,
                "bloqueante": True,
                "mensaje": (
                    "CUIT del receptor con dígito verificador válido"
                    if cuit_ok
                    else f"CUIT del receptor ({req.receptor.doc_nro}) tiene el dígito verificador mal — ARCA lo va a rechazar"
                ),
            }
        )

        # `emitir_factura` verifica el receptor contra el padrón de ARCA y
        # bloquea si no puede confirmarlo (ver services.facturacion.padron.
        # verificar_y_actualizar_receptor) — el preview hace el MISMO chequeo
        # de solo lectura (resuelto por el caller, sin corregir la ficha del
        # cliente) para que el admin vea el problema ANTES de intentar emitir
        # de verdad, en vez de que la emisión real falle sin aviso previo.
        # Fail-not-fast: si resolvió bien no se agrega nada (mismo criterio
        # que el resto de los chequeos — solo se lista lo que hay que atender).
        if cuit_ok and afip_error:
            chequeos.append(
                {
                    "check": "receptor_verificado_afip",
                    "ok": False,
                    "bloqueante": True,
                    "mensaje": f"AFIP no pudo confirmar este CUIT: {afip_error}",
                }
            )

    ri_degradado = (
        perfil_receptor == "responsable_inscripto"
        and req.receptor.condicion_iva != CondicionIva.RESPONSABLE_INSCRIPTO
    )
    chequeos.append(
        {
            "check": "perfil_fiscal_receptor",
            "ok": not ri_degradado,
            "bloqueante": False,
            "mensaje": (
                "El cliente es Responsable Inscripto pero no tiene un CUIT válido cargado — "
                "se va a facturar como Consumidor Final en vez de Factura A"
                if ri_degradado
                else "Perfil fiscal del receptor consistente"
            ),
        }
    )

    # Mismo chequeo que `emitir_factura` hace de bloqueante real (Responsable
    # Inscripto/Monotributo/Exento no existen sin CUIT en Argentina) — acá en
    # el preview para que el admin lo vea ANTES de gastar un comprobante real
    # intentando emitir, en vez de que la emisión falle recién al confirmar.
    cuit_ok_para_perfil = req.receptor.doc_tipo == DocTipo.CUIT and cuil_valido(
        str(req.receptor.doc_nro)
    )
    perfil_exige_cuit = perfil_receptor and perfil_receptor != "consumidor_final"
    chequeos.append(
        {
            "check": "perfil_exige_cuit_verificado",
            "ok": not perfil_exige_cuit or cuit_ok_para_perfil,
            "bloqueante": True,
            "mensaje": (
                f"El cliente tiene perfil impositivo '{perfil_receptor}' pero sin un CUIT "
                "verificado — pedile que verifique su CUIT en el portal antes de facturar"
                if perfil_exige_cuit and not cuit_ok_para_perfil
                else "Perfil impositivo con CUIT verificado"
            ),
        }
    )

    # total == neto + iva (arca_fe.comprobante.calcular_importes) y el IVA nunca
    # cambia el signo, así que chequear el total (la cifra que ve el admin) o
    # el neto da lo mismo matemáticamente — se muestra el total para no meter
    # jerga fiscal ("neto") en un chequeo pensado para el dueño, no para AFIP.
    total_ok = importes["total"] > 0
    chequeos.append(
        {
            "check": "importe_positivo",
            "ok": total_ok,
            "bloqueante": True,
            "mensaje": "Importe total positivo"
            if total_ok
            else "El importe total es $0 o negativo",
        }
    )

    fechas_ok = (
        req.fecha_serv_desde is None
        or req.fecha_serv_hasta is None
        or req.fecha_serv_desde <= req.fecha_serv_hasta
    )
    chequeos.append(
        {
            "check": "fechas_servicio",
            "ok": fechas_ok,
            "bloqueante": True,
            "mensaje": (
                "Fechas de servicio coherentes"
                if fechas_ok
                else "La fecha de inicio del servicio es posterior a la de fin"
            ),
        }
    )

    return chequeos, domicilio_afip, razon_social_afip


def previsualizar_factura(
    pedido_id: int, conn, *, _incluir_raw: bool = False, emisor_id: Optional[int] = None
) -> dict:
    """Arma el `ComprobanteRequest`, calcula sus importes, y consulta a ARCA
    el próximo número de comprobante — SIN pedir CAE.

    Corre los mismos pasos 1-3 de `emitir_factura` (validar estado, resolver
    emisor/receptor, construir el comprobante) y agrega UNA llamada SOAP de
    solo lectura (`FECompUltimoAutorizado`, la misma que ya usa el paso 7 de
    la emisión real): no crea ni modifica nada en ARCA, pero sirve para dos
    cosas — mostrar el número real que le va a tocar al comprobante, y
    validar que el certificado/las credenciales funcionan ANTES de
    comprometerse a pedir un CAE real (irreversible salvo Nota de Crédito).
    Nada de advisory lock, nada de INSERT — eso sigue siendo exclusivo de
    `emitir_factura`.

    `emisor_id`: override excepcional de `emisor_para` (ver ese docstring) —
    el admin elige facturar este pedido puntual con un emisor distinto al
    que resolvería automáticamente el perfil del receptor."""
    pedido = _get_pedido(conn, pedido_id)
    _rechazar_si_es_turno_vinculado(pedido)

    estado = (pedido.get("estado") or "").lower()
    if estado not in ("confirmado", "retirado", "devuelto", "finalizado"):
        raise ValueError(
            f"El pedido {pedido_id} está en estado '{estado}'; "
            "solo se puede facturar desde 'confirmado' o posterior"
        )

    perfil_receptor = (pedido.get("cliente_perfil_impuestos") or "").strip().lower()

    # Resolución de solo lectura contra el padrón de ARCA — el MISMO chequeo real
    # que `emitir_factura` hace con `verificar_y_actualizar_receptor` (líneas ~596-608),
    # pero sin escribir la ficha del cliente. Tiene que correr ANTES de
    # `construir_comprobante`: `condicion_iva` (que decide la LETRA/tipo del
    # comprobante, vía `tipo_comprobante`) se le manda a AFIP en el CAE (RG5616), así
    # que el preview tiene que calcular la letra con la condición de IVA que ARCA
    # realmente tiene para este CUIT — no con el perfil viejo guardado en la cuenta.
    # Antes esta resolución corría recién en `_chequeos_previos`, DESPUÉS de construir
    # el comprobante: el preview podía mostrar una Factura B/C calculada con el perfil
    # guardado mientras `emitir_factura` terminaba emitiendo una A (o viceversa) tras
    # corregir contra AFIP — inconsistencia real entre lo que el admin "confirma" y lo
    # que se emite. Regla del dueño: el dato de AFIP para el CUIT que se factura
    # siempre tiene prioridad sobre lo guardado en la cuenta.
    cuit_receptor = (pedido.get("cliente_cuit") or "").replace("-", "").strip()
    persona_afip = None
    afip_error: Optional[str] = None
    if cuit_receptor.isdigit() and len(cuit_receptor) == 11:
        try:
            persona_afip = resolver_persona(cuit_receptor, conn)
        except RuntimeError as exc:
            afip_error = str(exc)
        else:
            if persona_afip.condicion_iva:
                perfil_receptor = persona_afip.condicion_iva
                pedido = {**pedido, "cliente_perfil_impuestos": persona_afip.condicion_iva}

    nombre_emisor = _nombre_emisor(perfil_receptor, conn, emisor_id)
    cred = credenciales(nombre_emisor, conn)

    emisor_obj = Emisor(
        cuit=cred.cuit,
        punto_venta=cred.punto_venta,
        condicion_iva=(
            CondicionIva.RESPONSABLE_INSCRIPTO
            if cred.condicion_iva == "responsable_inscripto"
            else CondicionIva.MONOTRIBUTO
        ),
    )

    hoy = now_ar().date()
    try:
        req = construir_comprobante(pedido, emisor_obj, emisor_obj.condicion_iva, fecha=hoy)
    except ValueError as exc:
        # `ComprobanteRequest`/`Receptor.__post_init__` (arca_fe, iniciativa de robustecimiento)
        # ahora validan en la CONSTRUCCIÓN misma — no solo el CUIT del receptor, también fechas de
        # servicio faltantes, punto_venta fuera de rango, importes negativos, etc. (todo lo que
        # antes recién fallaba al armar el payload SOAP). El preview NO puede crashear por ninguno
        # de estos casos (a diferencia de `emitir_factura`, que sí puede propagar la excepción):
        # se distingue el motivo real en vez de etiquetar TODO como "CUIT del receptor inválido"
        # (rotularía mal, por ejemplo, un `punto_venta` mal configurado del emisor).
        motivo = str(exc)
        es_cuit = "Receptor.doc_nro" in motivo or "CUIT" in motivo
        chequeo = (
            {
                "check": "cuit_receptor",
                "ok": False,
                "bloqueante": True,
                "mensaje": f"CUIT del receptor ({pedido.get('cliente_cuit')}) inválido: {motivo}",
            }
            if es_cuit
            else {
                "check": "comprobante_invalido",
                "ok": False,
                "bloqueante": True,
                "mensaje": f"No se pudo armar el comprobante: {motivo}",
            }
        )
        if _incluir_raw:
            # `previsualizar_factura_html` no puede renderizar nada sin un `req` válido — a
            # diferencia del preview de chequeos (que sí puede mostrar el error como una fila
            # más), acá no hay nada que pintar, así que se propaga tal cual.
            raise
        return {
            "ambiente": cred.ambiente,
            "emisor": {
                "nombre": nombre_emisor,
                "cuit": cred.cuit,
                "condicion_iva": cred.condicion_iva,
            },
            "receptor": None,
            "comprobante": None,
            "importes": None,
            "fechas": None,
            "chequeos": [chequeo],
            "listo": False,
        }
    cbte_tipo = tipo_comprobante(req)
    importes = calcular_importes(req)

    # Único llamado a ARCA del preview: de solo lectura, no pide CAE. Si el
    # cert está vencido o ARCA no responde, mejor enterarse acá que después
    # de que el admin ya confirmó. `ArcaError` (Auth/Network/Response/
    # Business) se deja pasar tal cual — el route elige el status HTTP por
    # subtipo en vez de un 503 genérico para todo.
    token, sign = get_ta(nombre_emisor, conn)
    wsfe = WsfeClient(
        endpoint=cred.endpoint_wsfe,
        cuit=cred.cuit,
        token=token,
        sign=sign,
    )
    ultimo = wsfe.ultimo_autorizado(emisor_obj.punto_venta, int(cbte_tipo))
    numero_a_emitir = ultimo + 1

    chequeos, domicilio_afip, razon_social_afip = _chequeos_previos(
        req,
        perfil_receptor,
        importes,
        cred.ambiente,
        numero_a_emitir,
        persona_afip=persona_afip,
        afip_error=afip_error,
    )
    listo = all(c["ok"] or not c["bloqueante"] for c in chequeos)

    from arca_fe import letra_comprobante
    try:
        letra = letra_comprobante(cbte_tipo)
    except ValueError:
        letra = "?"

    # Labels de lo que va IMPRESO en la factura real (Concepto/condición IVA) — mismos catálogos
    # que usa el render (`comprobante_render.py::_armar_comprobante_fiscal`), para que el preview
    # muestre EXACTAMENTE lo que va a decir el comprobante, no una aproximación. El "condición de
    # venta" (Contado/Cuenta corriente) es el mismo criterio de negocio que ya usa el render —
    # ver comprobante_render.py línea ~150 (no un cálculo nuevo, mismo default de Rambla).
    #
    # `catalogos.label_*` levanta `RuntimeError` si nadie corrió "Actualizar catálogos ARCA"
    # todavía — el preview es de solo lectura y nunca debería romperse por un catálogo no
    # sincronizado, así que cae al label ESTÁTICO de `arca_fe` (el mismo texto oficial de AFIP,
    # sin depender de la sincronización) en vez de propagar el error.
    import arca_fe
    from services.facturacion.catalogos import label_concepto, label_condicion_iva_receptor
    from services.facturacion.comprobante_render import emisor_condicion_iva_label

    try:
        concepto_label = label_concepto(int(req.concepto), conn)
    except RuntimeError:
        concepto_label = arca_fe.label_concepto(req.concepto)
    try:
        condicion_iva_receptor_label = label_condicion_iva_receptor(
            int(req.receptor.condicion_iva), conn
        )
    except RuntimeError:
        condicion_iva_receptor_label = arca_fe.label_condicion_iva(req.receptor.condicion_iva)
    total_pedido = pedido.get("monto_total")
    pagado = pedido.get("monto_pagado") or 0
    condicion_venta = "Contado" if total_pedido is None or pagado >= total_pedido else "Cuenta corriente"

    resultado = {
        "ambiente": cred.ambiente,
        "emisor": {
            "nombre": nombre_emisor,
            "cuit": cred.cuit,
            "condicion_iva": cred.condicion_iva,
            "condicion_iva_label": emisor_condicion_iva_label(cred.condicion_iva),
        },
        "receptor": {
            "doc_tipo": req.receptor.doc_tipo.name,
            "doc_nro": str(req.receptor.doc_nro),
            "condicion_iva": req.receptor.condicion_iva.name.lower(),
            "condicion_iva_label": condicion_iva_receptor_label,
            # Regla del dueño: si se factura con un CUIT, el nombre/domicilio son los que ARCA
            # devuelve PARA ESE CUIT — nunca lo que haya guardado en la cuenta (aunque coincida la
            # mayoría de las veces), así que el dato fresco de AFIP tiene PRIORIDAD, no es un
            # fallback-si-falta. Mismo orden de precedencia que ya usa `emitir_factura` de verdad
            # (`persona.razon_social or pedido.get(...)`, línea ~595) — antes el preview usaba el
            # orden invertido para ambos campos, mostrando el nombre viejo de la cuenta aunque ARCA
            # ya hubiera confirmado uno distinto para este CUIT puntual.
            "razon_social": razon_social_afip
            or pedido.get("cliente_razon_social")
            or pedido.get("cliente_nombre")
            or "",
            "domicilio": domicilio_afip or pedido.get("cliente_domicilio_fiscal") or "",
        },
        "comprobante": {
            "letra": letra,
            "tipo_nro": int(cbte_tipo),
            "numero_a_emitir": numero_a_emitir,
            "pto_vta": emisor_obj.punto_venta,
            "concepto": concepto_label,
            "condicion_venta": condicion_venta,
        },
        "importes": {
            "neto": float(importes["neto"]),
            "iva": float(importes["iva"]),
            "total": float(importes["total"]),
        },
        "fechas": {
            "emision": hoy.isoformat(),
            "servicio_desde": req.fecha_serv_desde.isoformat()
            if req.fecha_serv_desde
            else None,
            "servicio_hasta": req.fecha_serv_hasta.isoformat()
            if req.fecha_serv_hasta
            else None,
            "vto_pago": req.fecha_vto_pago.isoformat() if req.fecha_vto_pago else None,
        },
        "chequeos": chequeos,
        "listo": listo,
    }
    if _incluir_raw:
        # Solo para uso interno de `previsualizar_factura_html` — nunca sale por la API pública
        # (el route de chequeos no lo pide). Evita reconstruir `req`/`emisor_obj`/`importes`
        # (que ya implican una llamada real a ARCA) una segunda vez para el render HTML.
        resultado["_raw"] = {
            "pedido": pedido,
            "req": req,
            "emisor_obj": emisor_obj,
            "importes": importes,
            "cbte_tipo": cbte_tipo,
            "numero_a_emitir": numero_a_emitir,
            "nombre_emisor": nombre_emisor,
            "fecha_emision": hoy,
        }
    return resultado


def previsualizar_factura_html(
    pedido_id: int, conn, layout: str = "simplificada", *, emisor_id: Optional[int] = None
) -> str:
    """Renderiza el HTML del comprobante ANTES de emitir — mismo layout/plantilla que la factura
    real (`arca_fe.renderizar_comprobante_html`), para que el admin vea el documento completo
    (no solo el resumen de chequeos) antes de comprometerse a pedir un CAE real.

    CAE/QR son PLACEHOLDER a propósito NO-numérico ("SIN EMITIR — NO VÁLIDO", nunca algo que se
    pueda confundir con un CAE real) porque todavía no existen — nada de esto se pide a ARCA más
    allá de lo que ya hace `previsualizar_factura` (número de comprobante de solo lectura). Es el
    mismo nivel "preview rápido" que ya expone `arca_fe` — HTML crudo, informal, NUNCA el
    documento certificado (eso sigue siendo exclusivo de `asegurar_pdf` tras emitir de verdad, con
    la firma PAdES real). Además del banner y la marca de agua diagonal (ver más abajo), esto es
    a propósito: un preview de factura NUNCA puede parecer válido.

    `emisor_id`: mismo override excepcional que `previsualizar_factura` — el HTML tiene que
    reflejar el mismo emisor que el resumen de chequeos, o el admin vería una letra/CUIT en el
    documento distinta de la que confirmó en el panel de al lado.

    Raises:
        ValueError: pedido en estado inválido, o el comprobante no se pudo armar.
        arca_fe.ArcaError / RuntimeError: igual que `previsualizar_factura`.
    """
    import arca_fe
    from services.facturacion.comprobante_render import _conceptos, _emisor_row, _fonts_css

    preview = previsualizar_factura(pedido_id, conn, _incluir_raw=True, emisor_id=emisor_id)
    raw = preview["_raw"]
    pedido, req, importes = raw["pedido"], raw["req"], raw["importes"]

    em_row = _emisor_row(raw["nombre_emisor"], conn)

    datos = arca_fe.ComprobanteFiscal(
        cbte_tipo=raw["cbte_tipo"],
        pto_vta=raw["emisor_obj"].punto_venta,
        numero=raw["numero_a_emitir"],
        fecha_emision=raw["fecha_emision"],
        cae="SIN EMITIR — NO VÁLIDO",
        cae_vto=raw["fecha_emision"],
        qr_url="https://www.arca.gob.ar/fe/qr/",
        emisor_razon_social=em_row["razon_social"] or "—",
        receptor=req.receptor,
        receptor_nombre=preview["receptor"]["razon_social"] or "—",
        concepto_label=preview["comprobante"]["concepto"],
        doc_tipo_label=arca_fe.label_doc_tipo(req.receptor.doc_tipo),
        condicion_iva_receptor_label=preview["receptor"]["condicion_iva_label"],
        emisor_condicion_iva_label=preview["emisor"]["condicion_iva_label"],
        items=_conceptos(pedido, importes["neto"]),
        importe_neto=importes["neto"],
        importe_iva=importes["iva"],
        importe_total=importes["total"],
        emisor_cuit=em_row["cuit"] or str(raw["emisor_obj"].cuit),
        emisor_domicilio=em_row["domicilio"],
        emisor_iibb=em_row["iibb"],
        emisor_inicio_actividades=em_row["inicio_actividades"] or None,
        receptor_domicilio=preview["receptor"]["domicilio"] or "—",
        condicion_venta=preview["comprobante"]["condicion_venta"],
        periodo_desde=req.fecha_serv_desde,
        periodo_hasta=req.fecha_serv_hasta,
        vencimiento_pago=req.fecha_vto_pago,
    )
    html = arca_fe.renderizar_comprobante_html(datos, layout=layout, fonts_css=_fonts_css())
    # Un preview de factura NUNCA puede parecer válido — dos capas, ninguna opcional:
    # (1) banner sticky arriba de todo, imposible de scrollear fuera de vista;
    # (2) marca de agua diagonal REPETIDA sobre el documento entero (`position:fixed`, así se ve
    # encima del contenido tenga el largo que tenga — A4 real vs. el viewport del iframe — y
    # sigue ahí si se scrollea, se imprime o se saca captura). Los 3 layouts arrancan el body
    # igual (`<body>` sin atributos, ver arca_fe/render.py) — reemplazo simple de texto, sin
    # tocar la librería portable (esto es una decisión de UX de Rambla, no algo que arca_fe deba
    # saber). `pointer-events:none` para no tapar ningún link/QR clickeable de abajo.
    _banner = (
        '<div style="position:sticky;top:0;z-index:999;background:#111;color:#fff;'
        'font:700 13px/1.4 monospace;text-align:center;padding:8px 12px;letter-spacing:.05em;">'
        "BORRADOR — sin emitir, CAE/QR no son reales, no tiene validez fiscal</div>"
    )
    _watermark_texto = "NO VÁLIDO — PREVIEW"
    _watermark = (
        '<div style="position:fixed;inset:0;z-index:998;pointer-events:none;overflow:hidden;'
        'display:flex;flex-direction:column;align-items:center;justify-content:space-evenly;">'
        + "".join(
            '<div style="transform:rotate(-25deg);white-space:nowrap;'
            'font:900 42px/1 monospace;color:rgba(200,30,30,0.16);letter-spacing:.1em;">'
            f"{_watermark_texto}&nbsp;&nbsp;&nbsp;{_watermark_texto}&nbsp;&nbsp;&nbsp;{_watermark_texto}</div>"
            for _ in range(6)
        )
        + "</div>"
    )
    return html.replace("<body>", f"<body>{_banner}{_watermark}", 1)


# ---------------------------------------------------------------------------
# Emisión de factura
# ---------------------------------------------------------------------------


def emitir_factura(
    pedido_id: int, *, emitido_por: Optional[str] = None, emisor_id: Optional[int] = None
) -> Factura:
    """Emite o devuelve la factura vigente para el pedido.

    Secuencia (orden OBLIGATORIO):
    1. Validar estado del pedido ≥ 'confirmado'
    2. Resolver emisor + datos fiscales del receptor
    3. Si el receptor tiene CUIT, verificarlo contra el padrón de ARCA —
       bloquea (RuntimeError) si AFIP no lo confirma; sin lock ni fila
       escrita todavía, así que no deja nada zombie
    4. Construir ComprobanteRequest
    5. Advisory lock por (pto_vta, cbte_tipo) — se mantiene hasta el commit
    6. Idempotencia: si ya hay factura vigente, devolverla
    7. INSERT estado='pendiente' ANTES de llamar al WS
    8. FECompConsultar del último número (por si hubo timeout en request anterior)
    9. FECAESolicitar; persistir CAE+número en TX ATÓMICA
    10. Error ARCA → estado='error', nunca 500
    11. PDF en best-effort fuera de la TX fiscal

    `emisor_id`: override excepcional de `emisor_para` — factura este pedido con ESE emisor
    puntual en vez del que resolvería automáticamente el perfil del receptor (ver el docstring
    de `emisores.emisor_para` para el caso de uso real: un cliente RI que pide igual Factura C).
    """
    with get_db() as conn:
        pedido = _get_pedido(conn, pedido_id)
        _rechazar_si_es_turno_vinculado(pedido)

        estado = (pedido.get("estado") or "").lower()
        if estado not in ("confirmado", "retirado", "devuelto", "finalizado"):
            raise ValueError(
                f"El pedido {pedido_id} está en estado '{estado}'; "
                "solo se puede facturar desde 'confirmado' o posterior"
            )

        # Verificar el receptor contra el padrón de ARCA ANTES de resolver
        # QUÉ EMISOR factura — `emisor_para` (más abajo) decide el emisor
        # según `cliente_perfil_impuestos`, así que tiene que leer el valor
        # YA CORREGIDO por AFIP, no el interno viejo: si el dato guardado
        # difiere del real (ej. guardado 'monotributo', AFIP dice
        # 'responsable_inscripto'), resolver el emisor ANTES de corregir
        # elegía el emisor equivocado — exactamente el caso que esta
        # verificación existe para prevenir. También va antes del lock/insert
        # (sin fila escrita todavía), así que si AFIP no confirma el CUIT esto
        # es un RuntimeError limpio que aborta acá (mismo patrón que el
        # ValueError de estado de arriba: nunca deja una fila 'pendiente'
        # zombie). Solo aplica si el receptor tiene CUIT — Consumidor
        # Final/DNI no tiene nada que verificar en un padrón CUIT-céntrico.
        # `verificar_y_actualizar_receptor` (a diferencia del autocompletado
        # de formularios) SÍ bloquea: la condición IVA del receptor se le
        # manda a AFIP en el CAE (RG5616), no se factura con un dato sin
        # confirmar. De paso corrige razón social/domicilio/perfil de
        # impuestos del cliente si difieren de lo que AFIP dice.
        cuit_receptor = (pedido.get("cliente_cuit") or "").replace("-", "").strip()
        perfil_previo = (pedido.get("cliente_perfil_impuestos") or "").strip().lower()
        if cuit_receptor.isdigit() and len(cuit_receptor) == 11:
            persona = verificar_y_actualizar_receptor(
                cuit_receptor, pedido["cliente_id"], conn
            )
            pedido["cliente_razon_social"] = (
                persona.razon_social or pedido.get("cliente_razon_social")
            )
            pedido["cliente_domicilio_fiscal"] = (
                persona.domicilio or pedido.get("cliente_domicilio_fiscal")
            )
            pedido["cliente_perfil_impuestos"] = persona.condicion_iva
        elif perfil_previo and perfil_previo != "consumidor_final":
            # Bug real encontrado en prod: un cliente puede guardar 'monotributo'/
            # 'responsable_inscripto'/'exento' en el portal (routes/cliente_portal/
            # cuenta.py::cliente_update_me) SIN pasar por la verificación de ARCA —
            # ninguno de esos perfiles existe legalmente sin CUIT en Argentina. Sin
            # este chequeo, la factura salía con el perfil/domicilio viejo o vacío,
            # sin confirmar contra ARCA (el gate de arriba solo corre si hay un
            # CUIT de 11 dígitos — acá NO lo hay, así que antes se facturaba igual).
            raise ValueError(
                f"El cliente tiene perfil impositivo '{perfil_previo}' guardado pero sin un CUIT "
                "verificado contra ARCA — Responsable Inscripto/Monotributo/Exento no existen sin "
                "CUIT. Pedile que verifique su CUIT en el portal (Datos de facturación) antes de "
                "facturar, o corregilo a mano en la ficha del cliente."
            )

        perfil_receptor = (pedido.get("cliente_perfil_impuestos") or "").strip().lower()
        nombre_emisor = _nombre_emisor(perfil_receptor, conn, emisor_id)
        cred = credenciales(nombre_emisor, conn)

        emisor_obj = Emisor(
            cuit=cred.cuit,
            punto_venta=cred.punto_venta,
            condicion_iva=(
                CondicionIva.RESPONSABLE_INSCRIPTO
                if cred.condicion_iva == "responsable_inscripto"
                else CondicionIva.MONOTRIBUTO
            ),
        )

        hoy = now_ar().date()
        req = construir_comprobante(
            pedido, emisor_obj, emisor_obj.condicion_iva, fecha=hoy
        )
        cbte_tipo = tipo_comprobante(req)
        importes = calcular_importes(req)

        lock_n = _advisory_hash(emisor_obj.punto_venta, int(cbte_tipo))
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_n,))

        # 5. Idempotencia
        vigente = get_factura_vigente(pedido_id, conn)
        if vigente and vigente.estado == "emitida":
            return vigente

        # 6. Persistir pendiente
        doc_tipo = int(req.receptor.doc_tipo)
        doc_nro = str(req.receptor.doc_nro)
        cond_iva_rec = int(req.receptor.condicion_iva)
        # Se persiste el Decimal EXACTO al centavo que ya calculó `calcular_importes`
        # — el MISMO valor que se le manda a ARCA en `armar_fecae` y se codifica en
        # el QR fiscal (`armar_qr`, más abajo, con `importes["total"]` sin truncar).
        # A diferencia de la plata "interna" (enteros ARS de `backend/contabilidad/`,
        # 2026-06-07), este es un documento fiscal: redondear a entero acá dejaba el
        # PDF impreso por debajo de lo que el CAE/QR autorizaron ante ARCA en
        # cualquier factura cuyo neto no fuera múltiplo de 100 (bug #1209).
        # `imp_neto`/`imp_iva`/`imp_total` son NUMERIC(12,2).
        neto_dec = importes["neto"]
        iva_dec = importes["iva"]
        total_dec = importes["total"]

        cuit_rec = pedido.get("cliente_cuit") or ""
        razon_social = (
            pedido.get("cliente_razon_social") or pedido.get("cliente_nombre") or ""
        )

        if vigente:
            factura_id = vigente.id
        else:
            factura_id = insert_factura(
                conn=conn,
                pedido_id=pedido_id,
                emisor=nombre_emisor,
                ambiente=cred.ambiente,
                cbte_tipo=int(cbte_tipo),
                pto_vta=emisor_obj.punto_venta,
                doc_tipo=doc_tipo,
                doc_nro=doc_nro,
                condicion_iva_receptor=cond_iva_rec,
                concepto=int(req.concepto),
                imp_neto=neto_dec,
                imp_iva=iva_dec,
                imp_total=total_dec,
                moneda="PES",
                cliente_cuit=cuit_rec or None,
                razon_social=razon_social or None,
                # Ya viene verificado contra el padrón de ARCA (paso 3, arriba)
                # cuando el receptor tiene CUIT — queda FIJO en la factura.
                domicilio=pedido.get("cliente_domicilio_fiscal") or None,
                raw_request={
                    "cbte_tipo": int(cbte_tipo),
                    "concepto": int(req.concepto),
                },
                created_by=emitido_por,
            )

        # 7-8. SOAP (mantenemos el lock durante la llamada)
        token, sign = get_ta(nombre_emisor, conn)
        wsfe = WsfeClient(
            endpoint=cred.endpoint_wsfe,
            cuit=cred.cuit,
            token=token,
            sign=sign,
        )

        try:
            ultimo = wsfe.ultimo_autorizado(emisor_obj.punto_venta, int(cbte_tipo))
            numero_a_emitir = ultimo + 1

            # Idempotencia post-timeout: si un intento anterior de ESTE pedido ya
            # le pidió a ARCA el número `numero_a_emitir` y la respuesta se perdió
            # por timeout de nuestro lado, ARCA ya lo tiene autorizado → lo
            # recuperamos en vez de pedir un CAE nuevo (evitaría "comprobante ya
            # autorizado"). Consultamos el PRÓXIMO número, no el último ya
            # autorizado — `ultimo` por definición siempre devuelve Resultado='A'
            # (no es nuestro, es el de la factura previa) y reusarlo duplicaría
            # número+CAE entre pedidos distintos (bug encontrado en prod).
            recuperado: Optional[CaeResult] = None
            consultado = wsfe.consultar(
                emisor_obj.punto_venta, int(cbte_tipo), numero_a_emitir
            )
            if consultado and (consultado.get("Resultado") or "R") == "A":
                cae_consulta = consultado.get("CodAutorizacion")
                if cae_consulta:
                    vto_raw = consultado.get("CAEFchVto", "")
                    from arca_fe import parse_fecha_arca

                    recuperado = CaeResult(
                        resultado="A",
                        cae=str(cae_consulta),
                        cae_vto=parse_fecha_arca(vto_raw),
                        numero=numero_a_emitir,
                    )

            cae_result: Optional[CaeResult] = recuperado
            if cae_result is None:
                cae_result = wsfe.solicitar_cae(req, numero_a_emitir)
        except (RuntimeError, ValueError, ArcaError):
            # `ArcaError` (Auth/Network/Response/Business) se deja pasar tal
            # cual — el route elige el status HTTP por subtipo (422/502/503)
            # en vez de un 503 genérico para todo.
            raise
        except Exception as exc:
            # Falla de red/SOAP no controlada (invariante "nunca 500" del módulo):
            # la TX nunca llegó a commitear (nada quedó en 'pendiente' zombie).
            raise RuntimeError(
                f"Error al comunicarse con WSFEv1 ({cred.endpoint_wsfe}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        # 8. TX atómica: persistir CAE
        if cae_result.resultado == "A" and cae_result.cae:
            qr_url = armar_qr(
                cuit_emisor=cred.cuit,
                pto_vta=emisor_obj.punto_venta,
                cbte_tipo=int(cbte_tipo),
                nro_cmp=cae_result.numero,
                importe_total=importes["total"],
                doc_tipo_rec=doc_tipo,
                doc_nro_rec=int(doc_nro) if doc_nro.isdigit() else 0,
                cae=cae_result.cae,
                fecha=hoy,
            )
            update_cae(
                factura_id,
                conn,
                cbte_nro=cae_result.numero,
                cae=cae_result.cae,
                cae_vto=cae_result.cae_vto,
                qr_payload=qr_url,
                raw_response={
                    "resultado": cae_result.resultado,
                    "cae": cae_result.cae,
                    "cae_vto": str(cae_result.cae_vto),
                    "observaciones": list(cae_result.observaciones),
                },
                estado="emitida",
            )
        else:
            update_error(
                factura_id,
                conn,
                errores=list(cae_result.errores) + list(cae_result.observaciones),
                raw_response={
                    "resultado": cae_result.resultado,
                    "errores": list(cae_result.errores),
                    "observaciones": list(cae_result.observaciones),
                },
            )
        conn.commit()

    # Leer la factura ya actualizada (fuera de la TX)
    with get_db() as conn:
        factura = get_by_id(factura_id, conn)

    if factura is None:
        raise RuntimeError(f"factura_id={factura_id} desapareció tras commit")

    return factura


# ---------------------------------------------------------------------------
# Nota de crédito
# ---------------------------------------------------------------------------


def emitir_nota_credito(
    factura_id: int, *, emitido_por: Optional[str] = None
) -> Factura:
    """Emite una Nota de Crédito que referencia `factura_id` y la anula.

    La factura original pasa a estado='anulada'. Su CAE sigue válido; la
    anulación ante ARCA es la NC emitida.
    """
    with get_db() as conn:
        original = get_by_id(factura_id, conn)
        if original is None:
            raise ValueError(f"Factura {factura_id} no encontrada")
        if original.estado != "emitida":
            raise ValueError(
                f"La factura {factura_id} está en estado '{original.estado}'; "
                "solo se pueden anular facturas emitidas"
            )

        # Verificar que no haya una NC vigente ya
        nc_existente = conn.execute(
            """SELECT id FROM facturas
               WHERE nota_credito_de = %s AND estado IN ('pendiente','emitida')""",
            (factura_id,),
        ).fetchone()
        if nc_existente:
            return get_by_id(nc_existente["id"], conn)

        pedido = _get_pedido(conn, original.pedido_id)
        nombre_emisor = original.emisor
        cred = credenciales(nombre_emisor, conn)

        emisor_obj = Emisor(
            cuit=cred.cuit,
            punto_venta=original.pto_vta,
            condicion_iva=(
                CondicionIva.RESPONSABLE_INSCRIPTO
                if cred.condicion_iva == "responsable_inscripto"
                else CondicionIva.MONOTRIBUTO
            ),
        )

        cbte_orig = CbteTipo(original.cbte_tipo)
        cbte_asoc = CbteAsoc(
            tipo=cbte_orig,
            punto_venta=original.pto_vta,
            numero=original.cbte_nro,
            cuit=cred.cuit,
            fecha=original.fecha_emision.date() if original.fecha_emision else None,
        )

        hoy = now_ar().date()
        req = construir_comprobante_nc(
            original,
            pedido,
            emisor_obj,
            fecha=hoy,
            cbtes_asoc=(cbte_asoc,),
        )
        cbte_tipo_nc = tipo_comprobante(req)
        importes = calcular_importes(req)

        lock_n = _advisory_hash(emisor_obj.punto_venta, int(cbte_tipo_nc))
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_n,))

        # Mismo criterio que en emitir_factura: Decimal exacto al centavo, no truncado.
        neto_dec = importes["neto"]
        iva_dec = importes["iva"]
        total_dec = importes["total"]

        # Anular la original ANTES de insertar la NC: el índice único parcial
        # uq_factura_vigente_por_pedido permite una sola fila 'pendiente'/'emitida'
        # por pedido — insertar la NC (pendiente) mientras la original sigue
        # 'emitida' viola ese índice. Si ARCA rechaza la NC más abajo, se revierte.
        marcar_anulada(factura_id, conn)

        nc_id = insert_factura(
            conn=conn,
            pedido_id=original.pedido_id,
            emisor=nombre_emisor,
            ambiente=cred.ambiente,
            cbte_tipo=int(cbte_tipo_nc),
            pto_vta=emisor_obj.punto_venta,
            doc_tipo=original.doc_tipo,
            doc_nro=original.doc_nro,
            condicion_iva_receptor=original.condicion_iva_receptor,
            concepto=original.concepto,
            imp_neto=neto_dec,
            imp_iva=iva_dec,
            imp_total=total_dec,
            moneda="PES",
            cliente_cuit=original.cliente_cuit,
            razon_social=original.razon_social,
            # La NC hereda el domicilio ya congelado de la original — no se
            # re-verifica contra el padrón (consistencia original↔NC).
            domicilio=original.domicilio,
            raw_request={"nota_credito_de": factura_id, "cbte_tipo": int(cbte_tipo_nc)},
            created_by=emitido_por,
        )
        # Actualizar FK nota_credito_de
        conn.execute(
            "UPDATE facturas SET nota_credito_de = %s WHERE id = %s",
            (factura_id, nc_id),
        )

        token, sign = get_ta(nombre_emisor, conn)
        wsfe = WsfeClient(
            endpoint=cred.endpoint_wsfe,
            cuit=cred.cuit,
            token=token,
            sign=sign,
        )

        try:
            ultimo = wsfe.ultimo_autorizado(emisor_obj.punto_venta, int(cbte_tipo_nc))
            numero_a_emitir = ultimo + 1

            # Misma idempotencia post-timeout que emitir_factura (consultar el
            # PRÓXIMO número, nunca el último ya autorizado — ver comentario ahí).
            recuperado: Optional[CaeResult] = None
            consultado = wsfe.consultar(
                emisor_obj.punto_venta, int(cbte_tipo_nc), numero_a_emitir
            )
            if consultado and (consultado.get("Resultado") or "R") == "A":
                cae_consulta = consultado.get("CodAutorizacion")
                if cae_consulta:
                    vto_raw = consultado.get("CAEFchVto", "")
                    from arca_fe import parse_fecha_arca

                    recuperado = CaeResult(
                        resultado="A",
                        cae=str(cae_consulta),
                        cae_vto=parse_fecha_arca(vto_raw),
                        numero=numero_a_emitir,
                    )

            cae_result: Optional[CaeResult] = recuperado
            if cae_result is None:
                cae_result = wsfe.solicitar_cae(req, numero_a_emitir)
        except (RuntimeError, ValueError, ArcaError):
            # `ArcaError` se deja pasar tal cual — ver el mismo comentario en
            # `emitir_factura`.
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Error al comunicarse con WSFEv1 ({cred.endpoint_wsfe}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if cae_result.resultado == "A" and cae_result.cae:
            qr_url = armar_qr(
                cuit_emisor=cred.cuit,
                pto_vta=emisor_obj.punto_venta,
                cbte_tipo=int(cbte_tipo_nc),
                nro_cmp=cae_result.numero,
                importe_total=importes["total"],
                doc_tipo_rec=original.doc_tipo,
                doc_nro_rec=int(original.doc_nro) if original.doc_nro.isdigit() else 0,
                cae=cae_result.cae,
                fecha=hoy,
            )
            update_cae(
                nc_id,
                conn,
                cbte_nro=cae_result.numero,
                cae=cae_result.cae,
                cae_vto=cae_result.cae_vto,
                qr_payload=qr_url,
                raw_response={"resultado": "A", "cae": cae_result.cae},
                estado="emitida",
            )
        else:
            update_error(
                nc_id,
                conn,
                errores=list(cae_result.errores),
                raw_response={
                    "resultado": cae_result.resultado,
                    "errores": list(cae_result.errores),
                },
            )
            # ARCA rechazó la NC: la original nunca se anuló de verdad, revertir.
            revertir_anulacion(factura_id, conn)
        conn.commit()

    with get_db() as conn:
        return get_by_id(nc_id, conn)
