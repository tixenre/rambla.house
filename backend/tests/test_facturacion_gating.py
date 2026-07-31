"""Tests del gating de ambiente ARCA (default-deny).

Verifica el invariante central del sistema de facturación:
- Emite en PRODUCCIÓN solo si is_production=True Y cert ENV presente.
- Ante la duda (staging, local, sin cert) → homologación, nunca producción.
- Emisor desconocido → ValueError (no cae silenciosamente a un default).
- Falta de cert/clave → ValueError descriptivo (no IntegrityError en DB).
- Emisores_para: RI → pablo, cualquier otro → santini.
"""

import pytest

pytestmark = pytest.mark.unit


# ── Fixtures de DB falsa ──────────────────────────────────────────────────────


class _Row:
    def __init__(self, d):
        self._d = d

    def __getitem__(self, k):
        return self._d[k]


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Simula la tabla emisores_arca para tests de credenciales."""
    def __init__(self, nombre="pablo", cuit="20-30000000-0", pto_vta=1, condicion_iva="responsable_inscripto"):
        self._nombre = nombre
        self._cuit = cuit
        self._pto_vta = pto_vta
        self._condicion_iva = condicion_iva

    def execute(self, query, params=None):
        conn = self

        class _Result:
            def fetchone(self_inner):
                # Simular fila de emisores_arca
                return {
                    "id": 1,
                    "nombre": conn._nombre,
                    "cuit": conn._cuit,
                    "pto_vta": conn._pto_vta,
                    "condicion_iva": conn._condicion_iva,
                    "cert_enc": b"FAKE_CERT_ENC",
                    "key_enc": b"FAKE_KEY_ENC",
                    "activo": True,
                    "razon_social": None,
                    "domicilio": None,
                    "iibb": None,
                    "inicio_actividades": None,
                    "notas": None,
                    "created_at": None,
                    "updated_at": None,
                }

        return _Result()


# ── Helpers ────────────────────────────────────────────────────────────────────


def _set_is_production(monkeypatch, value: bool):
    import config
    monkeypatch.setattr(type(config.settings), "is_production", property(lambda self: value))


def _set_env_certs(monkeypatch, emisor: str, present: bool = True):
    cert_var = f"AFIP_{emisor.upper()}_CERT"
    key_var = f"AFIP_{emisor.upper()}_KEY"
    if present:
        monkeypatch.setenv(cert_var, "-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----")
        monkeypatch.setenv(key_var, "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----")
    else:
        monkeypatch.delenv(cert_var, raising=False)
        monkeypatch.delenv(key_var, raising=False)


# ── Gating default-deny ────────────────────────────────────────────────────────


_FAKE_CERT = b"-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----"
_FAKE_KEY = b"-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----"


def _mock_get_cert_pem(monkeypatch, cert=_FAKE_CERT, key=_FAKE_KEY):
    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_cert_pem",
        lambda emisor_id, conn: (cert, key),
    )


def test_gating_produccion_cuando_is_production(monkeypatch):
    """is_production=True → ambiente='produccion'."""
    from services.facturacion.config import credenciales

    _set_is_production(monkeypatch, True)
    _mock_get_cert_pem(monkeypatch)

    cred = credenciales("pablo", _FakeConn())
    assert cred.ambiente == "produccion"
    assert "wsaa.afip.gov.ar" in cred.endpoint_wsaa
    assert "homo" not in cred.endpoint_wsaa


def test_gating_homologacion_cuando_no_is_production(monkeypatch):
    """is_production=False → homologación sin importar el cert."""
    from services.facturacion.config import credenciales

    _set_is_production(monkeypatch, False)
    _mock_get_cert_pem(monkeypatch)

    cred = credenciales("pablo", _FakeConn())
    assert cred.ambiente == "homologacion"
    assert "homo" in cred.endpoint_wsaa


def test_gating_emisor_no_encontrado_levanta(monkeypatch):
    """Emisor no en DB → ValueError descriptivo."""
    from services.facturacion.config import credenciales

    _set_is_production(monkeypatch, True)

    class _ConnNone:
        def execute(self, q, p=None):
            class _R:
                def fetchone(self): return None
            return _R()

    with pytest.raises(ValueError, match="no encontrado"):
        credenciales("inexistente", _ConnNone())


def test_gating_emisor_inactivo_levanta(monkeypatch):
    """Emisor inactivo → ValueError."""
    from services.facturacion.config import credenciales

    _set_is_production(monkeypatch, True)

    class _ConnInactivo:
        def execute(self, q, p=None):
            class _R:
                def fetchone(self):
                    return {
                        "id": 1, "nombre": "pablo", "cuit": "20-30000000-0",
                        "pto_vta": 1, "condicion_iva": "responsable_inscripto",
                        "cert_enc": b"x", "key_enc": b"x",
                        "activo": False, "razon_social": None,
                        "domicilio": None, "iibb": None, "inicio_actividades": None,
                        "notas": None,
                        "created_at": None, "updated_at": None,
                    }
            return _R()

    with pytest.raises(ValueError, match="inactivo"):
        credenciales("pablo", _ConnInactivo())


def test_gating_sin_cert_en_db_levanta(monkeypatch):
    """Emisor sin cert en DB → ValueError descriptivo."""
    from services.facturacion.config import credenciales

    _set_is_production(monkeypatch, True)
    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_cert_pem",
        lambda emisor_id, conn: (_ for _ in ()).throw(
            ValueError("no tiene certificado cargado")
        ),
    )

    with pytest.raises(ValueError, match="certificado"):
        credenciales("pablo", _FakeConn())


def test_gating_condicion_iva_en_cred(monkeypatch):
    """CredARCA incluye condicion_iva del emisor."""
    from services.facturacion.config import credenciales

    _set_is_production(monkeypatch, False)
    _mock_get_cert_pem(monkeypatch)

    cred = credenciales("pablo", _FakeConn(condicion_iva="responsable_inscripto"))
    assert cred.condicion_iva == "responsable_inscripto"


def test_gating_santini_homologacion(monkeypatch):
    """Santini con is_production=False → homologación."""
    from services.facturacion.config import credenciales

    _set_is_production(monkeypatch, False)
    _mock_get_cert_pem(monkeypatch)

    cred = credenciales(
        "santini",
        _FakeConn(nombre="santini", condicion_iva="monotributo"),
    )
    assert cred.emisor == "santini"
    assert cred.ambiente == "homologacion"


def test_cert_cargado_true_si_enc_presente(monkeypatch):
    """cert_cargado_para_emisor devuelve True si cert_enc + key_enc están en DB."""
    from services.facturacion.config import cert_cargado_para_emisor

    class _ConnConCert:
        def execute(self, q, p=None):
            class _R:
                def fetchone(self): return {"cert_enc": b"x", "key_enc": b"y"}
            return _R()

    assert cert_cargado_para_emisor(1, _ConnConCert()) is True


def test_cert_cargado_false_si_enc_null(monkeypatch):
    from services.facturacion.config import cert_cargado_para_emisor

    class _ConnSinCert:
        def execute(self, q, p=None):
            class _R:
                def fetchone(self): return {"cert_enc": None, "key_enc": None}
            return _R()

    assert cert_cargado_para_emisor(1, _ConnSinCert()) is False


# ── Routing de emisor (vía DB) ────────────────────────────────────────────────


class _FakeEmisorRow:
    """Simula una row de emisores_arca."""
    def __init__(self, nombre, condicion_iva="monotributo", activo=True):
        self.nombre = nombre
        self.condicion_iva = condicion_iva
        self.activo = activo

    def __getitem__(self, k):
        return getattr(self, k)


class _FakeConnEmisor:
    """Conexión que devuelve un emisor según condicion_iva."""
    def __init__(self, nombre="santini", condicion_iva="monotributo"):
        self._nombre = nombre
        self._condicion_iva = condicion_iva

    def execute(self, query, params=None):
        conn = self

        class _Result:
            def fetchone(self_inner):
                row = {
                    "id": 1,
                    "nombre": conn._nombre,
                    "cuit": "20-30000000-0",
                    "pto_vta": 1,
                    "condicion_iva": conn._condicion_iva,
                    "cert_enc": None,
                    "key_enc": None,
                    "activo": True,
                    "razon_social": None,
                    "domicilio": None,
                    "iibb": None,
                    "inicio_actividades": None,
                    "notas": None,
                    "created_at": None,
                    "updated_at": None,
                }
                return row

        return _Result()


def test_emisor_para_ri_llama_con_condicion_ri(monkeypatch):
    """emisor_para pasa 'responsable_inscripto' a la consulta SQL para RI."""
    from services.facturacion import emisores as mod

    captured = {}

    def fake_get(condicion, conn):
        captured["condicion"] = condicion
        r = _FakeEmisorRow("pablo", condicion)
        return r

    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_activo_para_condicion", fake_get
    )
    result = mod.emisor_para("responsable_inscripto", _FakeConnEmisor())
    assert captured["condicion"] == "responsable_inscripto"
    assert result == "pablo"


def test_emisor_para_monotributo_llama_con_condicion_mt(monkeypatch):
    from services.facturacion import emisores as mod

    captured = {}

    def fake_get(condicion, conn):
        captured["condicion"] = condicion
        return _FakeEmisorRow("santini", condicion)

    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_activo_para_condicion", fake_get
    )
    mod.emisor_para("monotributo", _FakeConnEmisor())
    assert captured["condicion"] == "monotributo"


def test_emisor_para_vacio_usa_monotributo(monkeypatch):
    """Default seguro: sin perfil fiscal → monotributo (nunca RI)."""
    from services.facturacion import emisores as mod

    captured = {}

    def fake_get(condicion, conn):
        captured["condicion"] = condicion
        return _FakeEmisorRow("santini", condicion)

    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_activo_para_condicion", fake_get
    )
    mod.emisor_para("", _FakeConnEmisor())
    assert captured["condicion"] == "monotributo"


def test_emisor_para_sin_emisor_activo_levanta(monkeypatch):
    """Sin emisor activo → ValueError descriptivo."""
    from services.facturacion import emisores as mod

    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_activo_para_condicion",
        lambda condicion, conn: None,
    )
    with pytest.raises(ValueError, match="No hay emisor activo"):
        mod.emisor_para("monotributo", _FakeConnEmisor())


# ── override_emisor_id: caso "cliente RI que pide igual Factura C" ──────────


def test_emisor_para_override_ignora_la_condicion_automatica(monkeypatch):
    """Con override_emisor_id seteado, ni siquiera se consulta get_activo_para_condicion
    — un cliente RI puede facturar con el emisor monotributista (Factura C: legal, la
    letra depende del EMISOR, no del receptor) sin que la resolución automática interfiera."""
    from services.facturacion import emisores as mod

    def _raise_si_se_llama(condicion, conn):
        raise AssertionError("no debería resolver automáticamente si hay override")

    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_activo_para_condicion", _raise_si_se_llama
    )
    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_by_id",
        lambda emisor_id, conn: _FakeEmisorRow("santini", "monotributo", activo=True),
    )
    result = mod.emisor_para("responsable_inscripto", _FakeConnEmisor(), override_emisor_id=7)
    assert result == "santini"


def test_emisor_para_override_inactivo_levanta(monkeypatch):
    """Override a un emisor inactivo → ValueError descriptivo (no factura en silencio)."""
    from services.facturacion import emisores as mod

    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_by_id",
        lambda emisor_id, conn: _FakeEmisorRow("pablo", "responsable_inscripto", activo=False),
    )
    with pytest.raises(ValueError, match="inactivo"):
        mod.emisor_para("responsable_inscripto", _FakeConnEmisor(), override_emisor_id=7)


def test_emisor_para_override_inexistente_levanta(monkeypatch):
    """Override a un id que no existe → ValueError descriptivo."""
    from services.facturacion import emisores as mod

    monkeypatch.setattr(
        "services.facturacion.emisores_repo.get_by_id", lambda emisor_id, conn: None
    )
    with pytest.raises(ValueError, match="no encontrado"):
        mod.emisor_para("responsable_inscripto", _FakeConnEmisor(), override_emisor_id=999)
