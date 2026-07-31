"""services.facturacion.padron — autocompletar razón social/domicilio/condición
IVA a partir de un CUIT, vía el padrón de ARCA (WSDL personaServiceA5, servicio
WSAA "ws_sr_constancia_inscripcion" — antes "ws_sr_padron_a5", deprecado).

Es una comodidad de carga (lo mismo que hace el facturador oficial de ARCA al
tipear un CUIT) — NUNCA bloquea: el formulario sigue siendo editable a mano
pase lo que pase. Pero "ARCA no tiene datos para este CUIT" resultó ser
engañoso en la práctica para CASI todo lo que puede fallar acá: (a) AFIP SÍ
conoce el CUIT pero bloquea la constancia por una regla de negocio propia
(ej. sin adhesión a Domicilio Fiscal Electrónico, RG 3990-E); (b) no pudimos
ni completar la consulta (WSAA no autoriza, relación no delegada, cert
vencido, red, sin emisor con cert configurado); (c) — encontrado en vivo con
un CUIT real, activo, con Constancia de Inscripción vigente confirmada en el
propio portal de AFIP, que igual devolvía "sin datos". Por eso `get_persona`
YA NO devuelve None en silencio: o devuelve la persona, o levanta el motivo
tipado real (ArcaBusinessError con el texto de AFIP, o ArcaResponseError con la
respuesta cruda). `resolver_persona` captura ese motivo por emisor y, si
ninguno resuelve, levanta RuntimeError con el motivo de cada uno + **el
ambiente** en que consultó (producción/homologación — clave: homologación solo
conoce CUIT de prueba). El route (admin-only) lo muestra tal cual. No participa
del flujo de emisión de comprobantes (no toca `arca_fe.wsfe`/`engine.py`).

Puede haber más de un emisor activo con cert cargado y solo alguno de ellos
tener la relación 'Consulta de constancia de inscripción' delegada en ARCA
(cada emisor delega la suya de forma independiente) — por eso NO alcanza con
probar uno solo: `resolver_persona` reintenta con cada emisor activo con cert,
en orden, hasta que uno devuelva persona; recién si TODOS fallan levanta el
RuntimeError nombrando a cada uno con su motivo real y el ambiente.

**`verificar_y_actualizar_receptor` SÍ participa del flujo de emisión** (la
excepción a lo de arriba): a diferencia del autocompletado de formularios
(best-effort, nunca bloquea), `engine.py::emitir_factura` la usa para
verificar al RECEPTOR de una factura contra el padrón — ahí SÍ bloquea la
emisión si AFIP no puede confirmar el CUIT, porque la condición IVA del
receptor se le manda a AFIP (RG5616) y no se puede facturar con un dato sin
confirmar. Reusa `resolver_persona` (misma consulta, mismo motivo tipado);
solo cambia qué hace el caller con la excepción.
"""

from __future__ import annotations

from arca_fe.padron import PadronClient, PersonaArca, WSAA_SERVICIO

_PADRON_HOMO = "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA5?wsdl"
_PADRON_PROD = "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA5?wsdl"

# Namespace de `pg_advisory_xact_lock` para serializar el alta del PRIMER perfil
# fiscal de un cliente (#1240, hallazgo de revisión) — sin esto, dos requests
# concurrentes dando de alta el primer perfil con CUITs DISTINTOS ven ambos
# "todavía no tiene ninguno" y computan `es_default=True` los dos; el segundo
# INSERT viola `uq_cliente_perfiles_fiscales_default` sin capturar → 500 crudo.
# Mismo patrón que `_ADVISORY_NS_PEDIDO` (services/alquileres/commands/creacion.py, 5390412),
# `_ADVISORY_NS_ESTUDIO` (5390413), `_ADVISORY_NS_CONTAB_MES` (5390420) y
# `_ADVISORY_NS_REPORTES_MES` (5390421); siguiente número libre.
_ADVISORY_NS_PERFIL_FISCAL = 5390422


def resolver_persona(cuit_buscado: str, conn) -> PersonaArca:
    """Consulta el padrón para `cuit_buscado`, probando con cada emisor activo
    con certificado hasta que uno lo resuelva (cada emisor delega su propia
    relación 'Consulta de constancia de inscripción' de forma independiente).

    Devuelve la `PersonaArca` si AFIP la encontró con alguno. Si NINGÚN emisor
    la resuelve, levanta RuntimeError con **el motivo real de AFIP por cada
    emisor probado** y **el ambiente** (producción/homologación) en el que se
    consultó — así el admin ve exactamente qué pasó (CUIT inexistente, bloqueo
    de negocio, relación no delegada, cert vencido, red, o ambiente de prueba)
    en vez de un genérico "sin datos ni motivo". NO se swallowea nada a None.
    El caller (route, admin-only) nunca rompe el formulario, que sigue editable
    a mano."""
    from services.facturacion.config import credenciales
    from services.facturacion.wsaa_cache import get_ta
    from services.facturacion.emisores_repo import list_emisores
    from arca_fe import ArcaError
    from config import settings as app_settings

    candidatos = [e.nombre for e in list_emisores(conn) if e.activo and e.cert_cargado]
    if not candidatos:
        raise RuntimeError(
            "No hay ningún emisor activo con certificado cargado para autenticar "
            "la consulta al padrón."
        )

    ambiente = "producción" if app_settings.is_production else "homologación"

    intentos: list[str] = []
    for emisor_autenticador in candidatos:
        cuit_auth = "?"
        try:
            cred = credenciales(emisor_autenticador, conn)
            cuit_auth = str(cred.cuit)
            token, sign = get_ta(emisor_autenticador, conn, servicio=WSAA_SERVICIO)
            endpoint = _PADRON_PROD if cred.ambiente == "produccion" else _PADRON_HOMO
            client = PadronClient(
                endpoint=endpoint, cuit_representada=cred.cuit, token=token, sign=sign
            )
            # `get_persona` ya NO devuelve None: o devuelve la persona, o levanta
            # ArcaBusinessError/ArcaResponseError con el motivo real de AFIP.
            return client.get_persona(cuit_buscado)
        except (ArcaError, ValueError) as exc:
            # Motivo tipado de AFIP (auth/relación/negocio/respuesta) o de
            # config (ValueError de `credenciales`) — se registra por emisor y
            # se sigue probando el resto. Si la excepción trae la respuesta
            # cruda de AFIP (`ArcaResponseError.raw`), se incluye para poder
            # diagnosticar exactamente qué contestó AFIP.
            motivo = str(exc)
            crudo = getattr(exc, "raw", "")
            if crudo:
                motivo += f" [respuesta cruda de AFIP: {crudo}]"
            intentos.append(f"'{emisor_autenticador}' (CUIT {cuit_auth}): {motivo}")
        except Exception as exc:  # último recurso: se surfacea igual, no se traga
            intentos.append(
                f"'{emisor_autenticador}' (CUIT {cuit_auth}): "
                f"{type(exc).__name__}: {exc}"
            )

    if ambiente == "homologación":
        guia = (
            "Estás consultando en HOMOLOGACIÓN: la base de prueba de AFIP solo "
            "conoce unos pocos CUIT de test, así que cualquier CUIT real da 'no "
            "existe' — no es un error de datos, es el ambiente."
        )
    else:
        guia = (
            "Estás consultando en PRODUCCIÓN: si el CUIT buscado tiene Constancia "
            "de Inscripción vigente y AFIP igual no lo devuelve, revisá que el "
            "emisor autenticador tenga la relación 'Consulta de constancia de "
            "inscripción' delegada en el Administrador de Relaciones de Clave Fiscal."
        )

    raise RuntimeError(
        f"No se pudo traer el padrón del CUIT {cuit_buscado} — consultado en "
        f"AMBIENTE {ambiente.upper()}. Motivo de AFIP por cada emisor "
        f"autenticador probado: {' | '.join(intentos)}. {guia}"
    )


# Columnas de FACTURACIÓN del cliente que este módulo puede corregir con lo
# que confirma AFIP — nunca las `*_renaper` (esas las escribe el flujo de
# Didit/KYC, dominio aparte; ver MEMORIA "Cuentas livianas").
_CAMPOS_FACTURACION_CORREGIBLES = ("razon_social", "domicilio_fiscal", "perfil_impuestos")


def verificar_y_actualizar_receptor(cuit_receptor: str, cliente_id: int, conn) -> PersonaArca:
    """Verifica el RECEPTOR de una factura contra el padrón de ARCA — a
    diferencia de `resolver_persona` en el autocompletado de formularios,
    ACÁ SÍ bloquea: si AFIP no puede confirmar el CUIT, la excepción de
    `resolver_persona` se deja pasar tal cual (no se atrapa) — el caller
    (`emitir_factura`) no factura con un CUIT que AFIP no verificó.

    Si AFIP confirma la persona pero no puede clasificar su condición IVA
    (raro, pero posible — ver `PersonaArca.condicion_iva == ''`), también
    bloquea con RuntimeError: ese dato SÍ se le manda a AFIP en el CAE
    (`CondicionIVAReceptorId`, RG5616), no hay valor "por defecto" seguro
    para mandar sin confirmar.

    Corrige en el mismo movimiento (misma transacción que el caller) los
    campos de FACTURACIÓN del cliente que difieran de lo que AFIP dice
    (`razón social`/`domicilio_fiscal`/`perfil_impuestos`) — nunca los
    campos `*_renaper` (Didit/KYC, dominio aparte)."""
    persona = resolver_persona(cuit_receptor, conn)
    if not persona.condicion_iva:
        raise RuntimeError(
            f"AFIP no pudo clasificar la condición IVA del CUIT {cuit_receptor} "
            "— no se puede facturar sin esa clasificación confirmada."
        )
    _corregir_datos_facturacion_cliente(cliente_id, persona, conn)
    return persona


def _corregir_datos_facturacion_cliente(cliente_id: int, persona: PersonaArca, conn) -> None:
    """UPDATE dinámico — solo toca las columnas de `_CAMPOS_FACTURACION_CORREGIBLES`
    que AFIP trae pobladas y que difieren de lo ya guardado (mismo patrón de
    "solo lo que cambió" que `emisores_repo.update_emisor`)."""
    row = conn.execute(
        "SELECT razon_social, domicilio_fiscal, perfil_impuestos FROM clientes WHERE id = %s",
        (cliente_id,),
    ).fetchone()
    if row is None:
        return

    nuevo = {
        "razon_social": persona.razon_social,
        "domicilio_fiscal": persona.domicilio,
        "perfil_impuestos": persona.condicion_iva,
    }
    cambios = {
        campo: valor
        for campo, valor in nuevo.items()
        if campo in _CAMPOS_FACTURACION_CORREGIBLES
        and valor
        and valor != (row[campo] or "")
    }
    if not cambios:
        return

    set_clause = ", ".join(f"{campo} = %s" for campo in cambios)
    conn.execute(
        f"UPDATE clientes SET {set_clause} WHERE id = %s",
        (*cambios.values(), cliente_id),
    )


def verificar_y_crear_perfil_fiscal(
    cuit: str, cliente_id: int, conn, etiqueta: str | None = None
):
    """Da de alta (o refresca) un perfil fiscal PERSONAL del cliente —
    `cliente_perfiles_fiscales`, #1240. Reusa `resolver_persona` (mismo motivo
    tipado que el resto del módulo); BLOQUEA (RuntimeError) si AFIP no puede
    clasificar la condición IVA — no existe fila "a medias" en esta tabla, toda
    fila nace de una verificación exitosa (cierra el fallback de entrada manual
    sin verificar que tenía `cliente_update_me`).

    Upsert por `(cliente_id, cuit)` — reverificar un CUIT ya guardado refresca
    razón social/domicilio/condición IVA sin duplicar la fila. Si es el
    PRIMER perfil del cliente, se marca `es_default=TRUE` y además se
    actualiza `clientes.cuit/razon_social/domicilio_fiscal/perfil_impuestos`
    (reusa `_corregir_datos_facturacion_cliente`) — así el "perfil default"
    que siguen leyendo los call sites no tocados por esta iniciativa refleja
    el primer perfil verificado, sin que ellos necesiten cambiar nada."""
    persona = resolver_persona(cuit, conn)
    if not persona.condicion_iva:
        raise RuntimeError(
            f"AFIP no pudo clasificar la condición IVA del CUIT {cuit} — no se "
            "puede guardar un perfil fiscal sin esa clasificación confirmada."
        )
    # Bug real (encontrado en revisión): si esto se calculaba solo con "¿el
    # cliente ya tiene ALGÚN perfil?", reverificar el CUIT que YA es el default
    # (el caso más común: refrescar el propio) computaba `es_default=False`
    # (porque ese mismo perfil ya existe) — el ON CONFLICT no toca `es_default`
    # así que la fila en `cliente_perfiles_fiscales` seguía bien, pero el
    # sync a `clientes.*` de abajo se saltaba, dejando el "perfil default" que
    # leen los call sites viejos con razón social/domicilio desactualizados
    # tras una reverificación real. Se resuelve mirando ESTE cuit puntual.
    #
    # Lock por cliente (namespace propio, ver arriba) ANTES de decidir
    # `es_default` — serializa dos altas concurrentes del primer perfil con
    # CUITs distintos para el mismo cliente (después de la consulta a AFIP,
    # que es lo lento; no hace falta tenerla adentro del lock).
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_ADVISORY_NS_PERFIL_FISCAL, cliente_id))
    perfil_existente = conn.execute(
        "SELECT es_default FROM cliente_perfiles_fiscales WHERE cliente_id = %s AND cuit = %s",
        (cliente_id, cuit),
    ).fetchone()
    if perfil_existente is not None:
        es_default = bool(perfil_existente["es_default"])
    else:
        ya_tiene_perfil = conn.execute(
            "SELECT 1 FROM cliente_perfiles_fiscales WHERE cliente_id = %s LIMIT 1",
            (cliente_id,),
        ).fetchone()
        es_default = ya_tiene_perfil is None
    conn.execute(
        """
        INSERT INTO cliente_perfiles_fiscales
            (cliente_id, cuit, perfil_impuestos, razon_social, domicilio_fiscal, etiqueta, es_default)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (cliente_id, cuit) DO UPDATE SET
            perfil_impuestos = EXCLUDED.perfil_impuestos,
            razon_social     = EXCLUDED.razon_social,
            domicilio_fiscal = EXCLUDED.domicilio_fiscal,
            verificado_at    = now(),
            updated_at       = now()
        """,
        (
            cliente_id,
            cuit,
            persona.condicion_iva,
            persona.razon_social or None,
            persona.domicilio or None,
            etiqueta,
            es_default,
        ),
    )
    if es_default:
        conn.execute("UPDATE clientes SET cuit = %s WHERE id = %s", (cuit, cliente_id))
        _corregir_datos_facturacion_cliente(cliente_id, persona, conn)
    return persona


def verificar_y_crear_productora(
    cuit: str,
    conn,
    notas: str | None = None,
    nombre: str | None = None,
    redes_sociales: str | None = None,
):
    """Da de alta (o refresca) una PRODUCTORA — entidad fiscal compartida entre
    varias cuentas de cliente, `productoras`/`productora_miembros` (#1240).
    A diferencia de los perfiles personales, la crea/edita el ADMIN (sin
    self-service del cliente, sin login propio) — mismo mecanismo de
    verificación (`resolver_persona`, bloqueante si AFIP no clasifica la
    condición IVA) que el resto del módulo, sin reimplementar la consulta.

    Upsert por `cuit` (UNIQUE) — reverificar refresca razón social/domicilio/
    condición IVA sin duplicar la fila; `notas`/`nombre`/`redes_sociales` (los
    3 campos que el admin carga a mano, no vienen de AFIP) se preservan si no
    se manda uno nuevo (no se pisan con NULL en un re-verify, #1251 Fase 2)."""
    persona = resolver_persona(cuit, conn)
    if not persona.condicion_iva:
        raise RuntimeError(
            f"AFIP no pudo clasificar la condición IVA del CUIT {cuit} — no se "
            "puede dar de alta una productora sin esa clasificación confirmada."
        )
    conn.execute(
        """
        INSERT INTO productoras
            (cuit, perfil_impuestos, razon_social, domicilio_fiscal, notas, nombre, redes_sociales)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (cuit) DO UPDATE SET
            perfil_impuestos = EXCLUDED.perfil_impuestos,
            razon_social     = EXCLUDED.razon_social,
            domicilio_fiscal = EXCLUDED.domicilio_fiscal,
            notas            = COALESCE(EXCLUDED.notas, productoras.notas),
            nombre           = COALESCE(EXCLUDED.nombre, productoras.nombre),
            redes_sociales   = COALESCE(EXCLUDED.redes_sociales, productoras.redes_sociales),
            verificado_at    = now(),
            updated_at       = now()
        """,
        (
            cuit, persona.condicion_iva, persona.razon_social or None, persona.domicilio or None,
            notas, nombre, redes_sociales,
        ),
    )
    return persona


def verificar_y_asignar_cuit(productora_id: int, cuit: str, conn):
    """Completa una productora BORRADOR (creada solo con `nombre`, sin CUIT
    — #1251 Fase 3, "podemos crear una productora sin el CUIT") con un CUIT
    recién verificado contra ARCA.

    A diferencia de `verificar_y_crear_productora` (upsert POR CUIT — usado
    para alta nueva o re-verificar el cuit YA asignado), esto resuelve por
    `id`: completa LA MISMA fila borrador en vez de insertar una fila nueva
    separada. El caller (`routes/productoras.py`) garantiza que la fila no
    tenga cuit todavía — reasignar el cuit de una productora YA verificada
    no es un caso soportado (cambiaría su identidad fiscal)."""
    persona = resolver_persona(cuit, conn)
    if not persona.condicion_iva:
        raise RuntimeError(
            f"AFIP no pudo clasificar la condición IVA del CUIT {cuit} — no se "
            "puede confirmar el CUIT de esta productora sin esa clasificación."
        )
    conn.execute(
        """UPDATE productoras SET
               cuit             = %s,
               perfil_impuestos = %s,
               razon_social     = %s,
               domicilio_fiscal = %s,
               verificado_at    = now(),
               updated_at       = now()
           WHERE id = %s""",
        (cuit, persona.condicion_iva, persona.razon_social or None, persona.domicilio or None, productora_id),
    )
    return persona
