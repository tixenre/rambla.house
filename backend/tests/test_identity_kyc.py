"""Tests de identity/kyc — orquestación del KYC.

FakeConn recorder que soporta `transaction()` y responde el SELECT de
didit_session_id (para pasar `_session_coincide`). Valida que aprobar/actualizar_estado
escriban la identidad/estado, anclen el CUIL (mod-11), guarden contactos y dejen evento.
"""
from contextlib import contextmanager

import pytest

from identity import kyc
from services.didit.decision import ContactoVerificado, ContactosVerificados, DatosRenaper

pytestmark = pytest.mark.unit


class _Cur:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class _Recorder:
    """Conn fake: graba execute(); soporta transaction(); el SELECT de
    didit_session_id devuelve el `session_id` esperado. `eventos_previos` simula los
    eventos ya en la bitácora (para el guard de idempotencia)."""

    def __init__(self, session_id, eventos_previos=()):
        self.session_id = session_id
        self.eventos_previos = set(eventos_previos)
        self.calls = []

    def execute(self, sql, params=()):
        norm = " ".join(sql.split())
        self.calls.append((norm, tuple(params)))
        if "SELECT didit_session_id" in norm:
            return _Cur({"didit_session_id": self.session_id})
        if "SELECT 1 FROM kyc_events" in norm:
            # params = (session_id, evento) → ¿ya registrado?
            return _Cur({"?column?": 1} if params[1] in self.eventos_previos else None)
        return _Cur(None)

    @contextmanager
    def transaction(self):
        yield self

    def commit(self):
        pass

    def close(self):
        pass


def _patch(monkeypatch, rec):
    monkeypatch.setattr("identity.kyc.get_db", lambda: rec)


def _sql(rec, needle):
    return [c for c in rec.calls if needle in c[0]]


def test_actualizar_estado_rechazado(monkeypatch):
    rec = _Recorder("sess-1")
    _patch(monkeypatch, rec)
    assert kyc.actualizar_estado(cliente_id=1, session_id="sess-1", estado="rechazado", motivo="x") is True
    upd = _sql(rec, "dni_verificacion_estado")
    assert upd and upd[0][1][0] == "rechazado" and upd[0][1][1] == "x"
    assert _sql(rec, "INSERT INTO kyc_events")  # bitácora


def test_actualizar_estado_session_no_coincide(monkeypatch):
    rec = _Recorder("otra-sess")
    _patch(monkeypatch, rec)
    assert kyc.actualizar_estado(cliente_id=1, session_id="sess-1", estado="rechazado") is False
    assert not _sql(rec, "UPDATE clientes")  # vendor_data forjado / carrera → no aplica


def test_aprobar_ancla_identidad_contactos_y_evento(monkeypatch):
    rec = _Recorder("sess-1")
    _patch(monkeypatch, rec)
    datos = DatosRenaper(dni="12345678", cuil="20123456786",
                         nombre_completo="Juan Pérez", direccion="Av. Corrientes 1234")
    contactos = ContactosVerificados(
        email=ContactoVerificado(kind="email", value="juan@gmail.com"),
        phone=ContactoVerificado(kind="phone", value="+5492235551234"),
    )
    assert kyc.aprobar(cliente_id=1, session_id="sess-1", datos=datos, contactos=contactos) is True
    params = _sql(rec, "dni_validado_at")[0][1]
    assert "12345678" in params and "20123456786" in params  # dni + CUIL válido anclados
    assert _sql(rec, "INSERT INTO verified_contacts")  # contactos verificados
    assert _sql(rec, "INSERT INTO kyc_events")  # evento de auditoría


def test_aprobar_cuil_invalido_no_se_ancla(monkeypatch):
    rec = _Recorder("sess-1")
    _patch(monkeypatch, rec)
    datos = DatosRenaper(dni="12345678", cuil="20-12345678-9")  # dígito verificador malo
    assert kyc.aprobar(cliente_id=1, session_id="sess-1", datos=datos) is True
    params = _sql(rec, "dni_validado_at")[0][1]
    assert "20123456789" not in params  # CUIL inválido NO se ancla (mod-11)


def test_consentimiento(monkeypatch):
    rec = _Recorder("sess-1")
    _patch(monkeypatch, rec)
    kyc.registrar_consentimiento(1)
    assert _sql(rec, "kyc_consent_at")  # marca el consentimiento
    assert _sql(rec, "INSERT INTO kyc_events")


def test_aprobar_idempotente_si_ya_se_aprobo(monkeypatch):
    # Didit re-entrega el webhook → una 2ª 'approved' del MISMO session_id no debe
    # re-pisar dni_validado_at ni duplicar la fila de auditoría.
    rec = _Recorder("sess-1", eventos_previos={"approved"})
    _patch(monkeypatch, rec)
    datos = DatosRenaper(dni="12345678", cuil="20123456786", nombre_completo="Juan Pérez")
    assert kyc.aprobar(cliente_id=1, session_id="sess-1", datos=datos) is True
    assert not _sql(rec, "dni_validado_at")  # no re-escribe la identidad
    assert not _sql(rec, "INSERT INTO kyc_events")  # no duplica el evento


def test_actualizar_estado_idempotente(monkeypatch):
    rec = _Recorder("sess-1", eventos_previos={"en_revision"})
    _patch(monkeypatch, rec)
    assert kyc.actualizar_estado(cliente_id=1, session_id="sess-1", estado="en_revision") is True
    assert not _sql(rec, "UPDATE clientes")  # ya estaba registrado → no-op


class _ConnHistorial:
    """Simula un cliente cuyo puntero vigente (`didit_session_id`) ya avanzó a
    `puntero_actual` (por un reintento), pero `sesiones_conocidas` (creadas para
    este cliente, ver `kyc.registrar_evento(..., "iniciado", ...)`) incluye otras
    sesiones — entre ellas la que Didit terminó aprobando."""

    def __init__(self, puntero_actual, sesiones_conocidas=()):
        self.puntero_actual = puntero_actual
        self.sesiones_conocidas = set(sesiones_conocidas)
        self.calls = []

    def execute(self, sql, params=()):
        norm = " ".join(sql.split())
        self.calls.append((norm, tuple(params)))
        if "SELECT didit_session_id FROM clientes" in norm:
            return _Cur({"didit_session_id": self.puntero_actual})
        if "SELECT 1 FROM kyc_events WHERE cliente_id" in norm:
            # params = (cliente_id, session_id)
            return _Cur({"?column?": 1} if params[1] in self.sesiones_conocidas else None)
        if "SELECT 1 FROM kyc_events WHERE session_id" in norm:
            return _Cur(None)  # _ya_registrado: todavía no se procesó ningún evento
        return _Cur(None)

    @contextmanager
    def transaction(self):
        yield self

    def commit(self):
        pass

    def close(self):
        pass


def test_aprobar_sesion_historica_no_vigente_mueve_puntero(monkeypatch):
    """Regresión del bug real: el cliente reintentó la verificación (el puntero
    avanzó a 'session-2'), pero Didit termina aprobando 'session-1' —el intento
    que en verdad completó—. Antes de este fix, `aprobar` comparaba SOLO contra
    el puntero vigente y descartaba la aprobación en silencio (nunca se marcaba
    `dni_validado_at`, aunque Didit mostrara "Approved"). Ahora debe aplicarse y
    mover el puntero a la sesión aprobada."""
    conn = _ConnHistorial(puntero_actual="session-2", sesiones_conocidas={"session-1", "session-2"})
    monkeypatch.setattr("identity.kyc.get_db", lambda: conn)
    datos = DatosRenaper(dni="12345678", cuil="20123456786", nombre_completo="Juan Pérez")
    assert kyc.aprobar(cliente_id=1, session_id="session-1", datos=datos) is True
    upd = [c for c in conn.calls if "UPDATE clientes SET" in c[0] and "didit_session_id" in c[0]]
    assert upd, "debe escribir dni_validado_at pese a no ser la sesión vigente"
    assert upd[0][1][0] == "session-1"  # el puntero se mueve a la sesión aprobada


def test_aprobar_sin_datos_no_marca_verificado_y_deja_en_revision(monkeypatch):
    """Didit dijo 'Approved' pero no devolvió datos del documento (webhook
    'liviano' + el fallback también vino vacío) — no se marca Verificado con
    la ficha vacía: dni_validado_at NO se toca, el estado pasa a 'en_revision'
    (para que jobs/recheck_didit_pendientes.py lo agarre) y el evento es
    'approved_sin_datos', no 'approved'."""
    rec = _Recorder("sess-1")
    _patch(monkeypatch, rec)
    datos = DatosRenaper()  # vacío — tiene_datos es False (sin DNI)
    assert kyc.aprobar(cliente_id=1, session_id="sess-1", datos=datos) is False
    assert not _sql(rec, "dni_validado_at")  # NO marca verificado
    estado = _sql(rec, "dni_verificacion_estado")
    assert estado and estado[0][1][0] == "en_revision"
    eventos = _sql(rec, "INSERT INTO kyc_events")
    assert eventos and eventos[0][1][1] == "approved_sin_datos"


def test_aprobar_sin_datos_no_bloquea_un_reintento_posterior_con_datos(monkeypatch):
    """Como el evento que queda registrado es 'approved_sin_datos' (no
    'approved'), un reintento posterior para la MISMA session_id que sí traiga
    datos reales tiene que aplicarse igual — la idempotencia de 'approved' no
    lo bloquea (si hubiera quedado 'approved', esta aprobación real se habría
    perdido en silencio para siempre)."""
    rec = _Recorder("sess-1", eventos_previos={"approved_sin_datos"})
    _patch(monkeypatch, rec)
    datos_reales = DatosRenaper(dni="12345678", cuil="20123456786", nombre_completo="Juan Pérez")
    assert kyc.aprobar(cliente_id=1, session_id="sess-1", datos=datos_reales) is True
    params = _sql(rec, "dni_validado_at")[0][1]
    assert "12345678" in params


def test_aprobar_sesion_ajena_se_rechaza(monkeypatch):
    """Anti-forgery preservado: una sesión que NUNCA se creó para este cliente
    (ni es el puntero vigente ni tiene evento en su historial) se sigue
    rechazando, aunque exista para OTRO cliente."""
    conn = _ConnHistorial(puntero_actual="session-2", sesiones_conocidas={"session-2"})
    monkeypatch.setattr("identity.kyc.get_db", lambda: conn)
    datos = DatosRenaper(dni="12345678", cuil="20123456786")
    assert kyc.aprobar(cliente_id=1, session_id="session-ajena", datos=datos) is False
    assert not [c for c in conn.calls if "UPDATE clientes SET" in c[0]]
