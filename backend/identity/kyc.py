"""identity/kyc.py — orquestación del KYC sobre Didit.

Es el ÚNICO lugar que escribe la identidad validada de un cliente (nombre legal, DNI,
CUIL, dirección oficial → columnas `*_renaper`) y el ancla CUIL. Recibe los datos ya
NORMALIZADOS de `services/didit/` (DatosRenaper, ContactosVerificados); nunca ve el
payload crudo de Didit. Movido desde `routes/didit.py` (que queda fino).

Idempotente y scopeado a una sesión que efectivamente pertenece al cliente (defensa en
profundidad anti vendor_data forjado, sobre la firma HMAC que ya validó el webhook):
o es el puntero VIGENTE (`clientes.didit_session_id`), o quedó registrada en su
historial (`kyc_events`) al crearla — nunca una sesión ajena. `aprobar()` acepta
cualquiera de las dos y MUEVE el puntero a la sesión aprobada si no era la vigente
(ver `_sesion_conocida_del_cliente`): un cliente que reintentó la verificación
pisa `didit_session_id` con la sesión nueva, y si Didit aprueba una sesión ANTERIOR
(el intento que en verdad completó), esa aprobación no se puede perder solo porque
ya no es "la actual" — quedaba silenciosamente descartada antes de este fix.
Re-verificación: el COALESCE deja entrar el dato nuevo de RENAPER (no pisa con NULL,
ni con input del usuario).
"""
import logging

from database import get_db, now_ar, row_to_dict
from services.didit.decision import DatosRenaper

from identity.anchor import cuil_valido, normalizar_cuil
from identity.contacts import guardar_contactos_didit

logger = logging.getLogger(__name__)


def registrar_evento(conn, cliente_id, evento, detalle=None, session_id=None):
    """Bitácora de auditoría del KYC. SOLO texto (Ley 25.326): `detalle` es para
    diagnóstico (presencia de campos), nunca valores sensibles."""
    conn.execute(
        "INSERT INTO kyc_events (cliente_id, evento, detalle, session_id) VALUES (%s, %s, %s, %s)",
        (cliente_id, evento, detalle, session_id),
    )


def registrar_consentimiento(cliente_id, *, conn=None):
    """Marca el consentimiento del KYC (el cliente aceptó verificarse + el guardado).
    Idempotente (no pisa la fecha original)."""
    own = conn is None
    conn = conn or get_db()
    try:
        with conn.transaction():
            conn.execute(
                "UPDATE clientes SET kyc_consent_at=COALESCE(kyc_consent_at, %s) WHERE id=%s",
                (now_ar(), cliente_id),
            )
            registrar_evento(conn, cliente_id, "consent")
    finally:
        if own:
            conn.close()


def _presencia(datos: DatosRenaper) -> str:
    """Detalle del evento: presencia de cada campo (bool), nunca el valor."""
    return (
        f"dni={bool(datos.dni)} cuil={bool(datos.cuil)} "
        f"nombre={bool(datos.nombre_completo or datos.nombre)} "
        f"direccion={bool(datos.direccion)}"
    )


def _session_coincide(conn, cliente_id, session_id) -> bool:
    row = conn.execute(
        "SELECT didit_session_id FROM clientes WHERE id=%s", (cliente_id,)
    ).fetchone()
    return row is not None and row_to_dict(row).get("didit_session_id") == session_id


def _sesion_conocida_del_cliente(conn, cliente_id, session_id) -> bool:
    """Como `_session_coincide`, pero además acepta una sesión que ya NO es el
    puntero vigente si efectivamente se creó para este cliente (tiene un evento
    propio en `kyc_events` — se registra al crearla, ver `routes/didit.py`).
    Usado SOLO por `aprobar`: una aprobación es un hecho consumado de Didit y no
    se puede perder por un reintento que corrió el puntero; en cambio
    `actualizar_estado` (rechazado/en_revisión) sigue con el chequeo estricto —
    no tiene sentido "resucitar" un estado intermedio de una sesión vieja
    mientras hay una más nueva en curso. Sigue rechazando un `session_id` que
    nunca se creó para este cliente (anti-forgery de `vendor_data`)."""
    row = conn.execute(
        "SELECT didit_session_id FROM clientes WHERE id=%s", (cliente_id,)
    ).fetchone()
    if row is None:
        return False
    if row_to_dict(row).get("didit_session_id") == session_id:
        return True
    return conn.execute(
        "SELECT 1 FROM kyc_events WHERE cliente_id=%s AND session_id=%s LIMIT 1",
        (cliente_id, session_id),
    ).fetchone() is not None


def _ya_registrado(conn, session_id, evento) -> bool:
    """Idempotencia: ¿ya procesamos este `evento` para este `session_id`? Didit re-entrega
    el webhook (reintenta ante cualquier no-200) → sin esto, una re-entrega de 'approved'
    re-pisaría `dni_validado_at` con un timestamp nuevo y duplicaría la fila de auditoría.
    La bitácora `kyc_events` ES la fuente de verdad de 'qué ya se ingirió' (sin tabla extra)."""
    if not session_id:
        return False
    row = conn.execute(
        "SELECT 1 FROM kyc_events WHERE session_id=%s AND evento=%s LIMIT 1",
        (session_id, evento),
    ).fetchone()
    return row is not None


def aprobar(*, cliente_id, session_id, datos, contactos=None, conn=None) -> bool:
    """Persiste una verificación Didit APROBADA: identidad RENAPER (COALESCE, única
    pluma) + ancla CUIL (validado mod-11) + contactos verificados + evento. Atómico.
    Mueve `didit_session_id` a `session_id` si un reintento posterior había corrido
    el puntero (ver `_sesion_conocida_del_cliente`) — la aprobación de Didit gana.
    Devuelve False si el `session_id` nunca se creó para este cliente (vendor_data
    forjado / carrera), o si Didit aprobó sin devolver datos del documento (ver
    `datos.tiene_datos` abajo — no se marca Verificado con la ficha vacía)."""
    own = conn is None
    conn = conn or get_db()
    try:
        if not _sesion_conocida_del_cliente(conn, cliente_id, session_id):
            logger.warning("identity: session_id no coincide cliente_id=%s — no se aplica", cliente_id)
            return False
        if _ya_registrado(conn, session_id, "approved"):
            logger.info("identity: cliente_id=%s session_id=%s ya aprobado — idempotente, no-op",
                        cliente_id, session_id)
            return True

        if not datos.tiene_datos:
            # Didit dijo "Approved" pero no devolvió datos del documento (webhook
            # 'liviano' + el fallback a `retrieve_decision` también vino vacío) —
            # no confundir "Didit aprobó la sesión" con "tenemos identidad para
            # mostrar". NO marcamos Verificado con la ficha vacía: dejamos al
            # cliente en 'en_revision' para que lo agarre el rechequeo automático
            # (mismo motor único, `services.didit.recheck_cliente` — el barrido
            # `jobs/recheck_didit_pendientes.py` SOLO revisa clientes en
            # 'no_verificado'/'en_revision', así que 'en_revision' es necesario,
            # no cosmético). Registramos un evento DISTINTO a 'approved' — si
            # fuera 'approved', `_ya_registrado` bloquearía un reintento futuro
            # para esta MISMA sesión que sí traiga los datos completos.
            detalle = _presencia(datos)
            with conn.transaction():
                conn.execute(
                    """UPDATE clientes SET
                           dni_verificacion_estado=%s,
                           dni_verificacion_motivo=%s,
                           updated_at=%s
                       WHERE id=%s""",
                    ("en_revision", "Aprobado por Didit sin datos de documento", now_ar(), cliente_id),
                )
                if contactos is not None:
                    guardar_contactos_didit(conn, cliente_id, contactos)
                registrar_evento(conn, cliente_id, "approved_sin_datos", detalle, session_id)
            logger.error(
                "identity: cliente_id=%s Didit aprobó session_id=%s SIN datos de documento (%s) "
                "— queda en_revision para el rechequeo automático", cliente_id, session_id, detalle,
            )
            return False

        cuil = normalizar_cuil(datos.cuil)
        if cuil and not cuil_valido(cuil):
            logger.warning("identity: CUIL mal formado de Didit cliente_id=%s (no se ancla)", cliente_id)
            cuil = None  # mod-11 falló → no anclamos basura (COALESCE con None conserva)

        ahora = now_ar()
        with conn.transaction():
            conn.execute(
                """UPDATE clientes SET
                       didit_session_id=%s,
                       dni=COALESCE(%s, dni),
                       cuil=COALESCE(%s, cuil),
                       dni_validado_at=%s,
                       dni_verificacion_estado='verificado',
                       dni_verificacion_motivo=NULL,
                       nombre_renaper=COALESCE(%s, nombre_renaper),
                       apellido_renaper=COALESCE(%s, apellido_renaper),
                       nombre_completo_renaper=COALESCE(%s, nombre_completo_renaper),
                       fecha_nacimiento_renaper=COALESCE(%s, fecha_nacimiento_renaper),
                       direccion_renaper=COALESCE(%s, direccion_renaper),
                       genero_renaper=COALESCE(%s, genero_renaper),
                       nacionalidad_renaper=COALESCE(%s, nacionalidad_renaper),
                       lugar_nacimiento_renaper=COALESCE(%s, lugar_nacimiento_renaper),
                       vencimiento_documento_renaper=COALESCE(%s, vencimiento_documento_renaper),
                       emision_documento_renaper=COALESCE(%s, emision_documento_renaper),
                       tipo_documento_renaper=COALESCE(%s, tipo_documento_renaper),
                       estado_civil_renaper=COALESCE(%s, estado_civil_renaper),
                       updated_at=%s
                   WHERE id=%s""",
                (session_id, datos.dni, cuil, ahora,
                 datos.nombre, datos.apellido, datos.nombre_completo,
                 datos.fecha_nacimiento, datos.direccion,
                 datos.genero, datos.nacionalidad, datos.lugar_nacimiento,
                 datos.vencimiento_documento, datos.emision_documento,
                 datos.tipo_documento, datos.estado_civil,
                 ahora, cliente_id),
            )
            if contactos is not None:
                guardar_contactos_didit(conn, cliente_id, contactos)
            registrar_evento(conn, cliente_id, "approved", _presencia(datos), session_id)
        # Log de PRESENCIA (bool), nunca valores (Ley 25.326).
        logger.info("identity: cliente_id=%s verificado (%s) session_id=%s",
                    cliente_id, _presencia(datos), session_id)
        return True
    finally:
        if own:
            conn.close()


def actualizar_estado(*, cliente_id, session_id, estado, motivo=None, conn=None) -> bool:
    """Persiste un estado intermedio de verificación (rechazado / en_revision) +
    evento. Scopeado al `session_id`."""
    own = conn is None
    conn = conn or get_db()
    try:
        if not _session_coincide(conn, cliente_id, session_id):
            logger.warning("identity: session_id no coincide cliente_id=%s — no se aplica", cliente_id)
            return False
        if _ya_registrado(conn, session_id, estado):
            logger.info("identity: cliente_id=%s session_id=%s estado=%s ya registrado — idempotente",
                        cliente_id, session_id, estado)
            return True
        with conn.transaction():
            conn.execute(
                """UPDATE clientes SET dni_verificacion_estado=%s, dni_verificacion_motivo=%s,
                       updated_at=%s WHERE id=%s AND didit_session_id=%s""",
                (estado, motivo, now_ar(), cliente_id, session_id),
            )
            registrar_evento(conn, cliente_id, estado, None, session_id)
        logger.info("identity: cliente_id=%s estado=%s session_id=%s", cliente_id, estado, session_id)
        return True
    finally:
        if own:
            conn.close()
