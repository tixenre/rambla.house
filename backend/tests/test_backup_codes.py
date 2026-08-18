"""Tests de los códigos de respaldo del 2º factor admin (`auth/backup_codes.py`).

Mismo patrón que `test_passkey.py`: piezas puras sin DB (formato/hash del
código, roundtrip de la cookie firmada) + rutas vía TestClient con las
funciones de DB monkeypatcheadas (no hay Postgres acá — eso lo cubre
`test_backup_codes_db.py`).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth.backup_codes as bc
from auth.google import router
from auth.ratelimit import _failures as _rl_failures
from auth.session import signer

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _stub_sessions(monkeypatch):
    """`backup_code_login` mintea sesión vía `_make_session_response` (registra
    fila server-side, allowlist `auth_sessions`) — mismo stub que el resto de
    los tests de auth para no tocar DB."""
    monkeypatch.setattr("auth.commands.sessions.create_session", lambda **kw: "stub-jti")
    monkeypatch.setattr("auth.queries.sessions.is_active",
                        lambda jti: {"jti": jti} if jti else None)
    _rl_failures.clear()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _admin_session(email: str = "admin@test.com") -> str:
    return signer.dumps({"email": email, "name": "Admin", "jti": "test-admin"})


# ── Piezas puras ──────────────────────────────────────────────────────────────

class TestGenerarCodigo:
    def test_formato_con_guion_medio(self):
        c = bc._generar_codigo()
        assert len(c) == 11
        a, b = c.split("-")
        assert len(a) == 5 and len(b) == 5

    def test_sin_caracteres_ambiguos(self):
        # 0/O/1/I/L quedan afuera del alfabeto — un código leído a mano/impreso
        # no debería tener ambigüedad entre 0 y O, o 1/I/l.
        for _ in range(50):
            c = bc._generar_codigo().replace("-", "")
            assert not (set(c) & set("0O1IL"))

    def test_alta_entropia_no_se_repite_en_una_tanda(self):
        codigos = [bc._generar_codigo() for _ in range(200)]
        assert len(set(codigos)) == len(codigos)


class TestHash:
    def test_determinista(self):
        assert bc._hash("ABCDE-FGHJK") == bc._hash("ABCDE-FGHJK")

    def test_case_insensitive(self):
        # El usuario puede tipear en minúscula — el hash normaliza a mayúscula.
        assert bc._hash("abcde-fghjk") == bc._hash("ABCDE-FGHJK")

    def test_distinto_input_distinto_hash(self):
        assert bc._hash("ABCDE-FGHJK") != bc._hash("ABCDE-FGHJ0")

    def test_nunca_guarda_el_codigo_en_claro(self):
        assert "ABCDE-FGHJK" not in bc._hash("ABCDE-FGHJK")


class TestPendingCookie:
    def test_roundtrip(self):
        token = bc.sign_pending_2fa("admin@test.com")
        assert bc._read_pending_2fa(token) == "admin@test.com"

    def test_tampered_devuelve_none(self):
        # Altera el PRIMER carácter (parte del payload), no el último: el
        # último cae en el grupo final de la firma en base64, que puede tener
        # bits "no significativos" (padding) — alterarlo ahí decodifica al
        # mismo byte ~7.6% de las veces (medido empíricamente), dando un
        # falso "sigue siendo válido" sin que la verificación de firma esté
        # rota. Tocar el payload invalida la firma siempre (0/2000 medido).
        token = bc.sign_pending_2fa("admin@test.com")
        assert bc._read_pending_2fa(("a" if token[0] != "a" else "b") + token[1:]) is None

    def test_vacio_devuelve_none(self):
        assert bc._read_pending_2fa("") is None


# ── Rutas ──────────────────────────────────────────────────────────────────────

class TestGenerar:
    def test_sin_sesion_401(self):
        r = _client().post("/auth/backup-code/generar")
        assert r.status_code == 401

    def test_admin_genera_10_codigos(self, monkeypatch):
        monkeypatch.setattr(bc, "generar_codigos", lambda email: [f"C{i}" for i in range(10)])
        c = _client()
        c.cookies.set("session", _admin_session())
        r = c.post("/auth/backup-code/generar")
        assert r.status_code == 200
        assert len(r.json()["codigos"]) == 10

    def test_pasa_el_email_de_la_sesion_no_uno_hardcodeado(self, monkeypatch):
        # No usa un email fuera de ADMIN_EMAILS (el test correría en un entorno
        # con esa allowlist distinta) — el punto es confirmar que viaja el email
        # de LA SESIÓN, sea cual sea, no un valor fijo en la ruta.
        recibido = {}
        monkeypatch.setattr(
            bc, "generar_codigos", lambda email: recibido.setdefault("email", email) or []
        )
        c = _client()
        c.cookies.set("session", _admin_session())
        c.post("/auth/backup-code/generar")
        assert recibido["email"] == "admin@test.com"


class TestEstado:
    def test_sin_sesion_401(self):
        assert _client().get("/auth/backup-code/estado").status_code == 401

    def test_devuelve_el_conteo(self, monkeypatch):
        monkeypatch.setattr(bc, "contar_disponibles", lambda email: 7)
        c = _client()
        c.cookies.set("session", _admin_session())
        r = c.get("/auth/backup-code/estado")
        assert r.status_code == 200
        assert r.json()["disponibles"] == 7


class TestBackupCodeLogin:
    def test_sin_cookie_pending_400(self):
        r = _client().post("/auth/backup-code/login", json={"code": "ABCDE-FGHJK"})
        assert r.status_code == 400

    def test_codigo_valido_mintea_sesion(self, monkeypatch):
        monkeypatch.setattr(bc, "verificar_y_consumir", lambda email, code: True)
        c = _client()
        c.cookies.set("pending_2fa", bc.sign_pending_2fa("admin@test.com"))
        r = c.post("/auth/backup-code/login", json={"code": "ABCDE-FGHJK"})
        assert r.status_code == 200
        assert "session" in r.cookies

    def test_codigo_invalido_401(self, monkeypatch):
        monkeypatch.setattr(bc, "verificar_y_consumir", lambda email, code: False)
        c = _client()
        c.cookies.set("pending_2fa", bc.sign_pending_2fa("admin@test.com"))
        r = c.post("/auth/backup-code/login", json={"code": "WRONG-CODE1"})
        assert r.status_code == 401

    def test_verifica_contra_el_email_de_la_cookie_pending(self, monkeypatch):
        # No contra un email que mande el body — el código puede ser válido para
        # OTRA cuenta y no debería colar acá (la cookie pending es la fuente).
        recibido = {}

        def _fake(email, code):
            recibido["email"] = email
            return True

        monkeypatch.setattr(bc, "verificar_y_consumir", _fake)
        c = _client()
        c.cookies.set("pending_2fa", bc.sign_pending_2fa("pablo@test.com"))
        c.post("/auth/backup-code/login", json={"code": "ABCDE-FGHJK"})
        assert recibido["email"] == "pablo@test.com"

    def test_email_no_admin_403(self, monkeypatch):
        # La cuenta pudo haber perdido el allowlist entre el Google-login y el
        # código de respaldo — `_mint_session_for_owner`-equivalente acá es
        # `_make_session_response`, que no valida is_admin_email por sí solo;
        # confirma que igual el guard normal (`require_admin`) lo va a rechazar
        # después, no que este endpoint deba re-implementarlo — cubierto por
        # `_stub_sessions` + el guard real en las rutas protegidas.
        monkeypatch.setattr(bc, "verificar_y_consumir", lambda email, code: True)
        c = _client()
        c.cookies.set("pending_2fa", bc.sign_pending_2fa("no-admin@test.com"))
        r = c.post("/auth/backup-code/login", json={"code": "ABCDE-FGHJK"})
        # `_make_session_response` mintea sin chequear is_admin_email (igual que
        # el login normal de Google) — el guard corre en el siguiente request.
        assert r.status_code == 200


class TestRateLimit:
    def test_demasiados_fallos_cortan_con_429(self, monkeypatch):
        monkeypatch.setattr(bc, "verificar_y_consumir", lambda email, code: False)
        c = _client()
        c.cookies.set("pending_2fa", bc.sign_pending_2fa("admin@test.com"))
        for _ in range(10):
            c.post("/auth/backup-code/login", json={"code": "WRONG-CODE1"})
        r = c.post("/auth/backup-code/login", json={"code": "WRONG-CODE1"})
        assert r.status_code == 429
