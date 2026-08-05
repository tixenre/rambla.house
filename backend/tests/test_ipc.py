"""`services.ipc` — parseo de la respuesta de la API de series de INDEC.

Puro (sin red, sin DB): mockea `httpx.get` con una respuesta real (mismo shape
que devuelve `apis.datos.gob.ar/series/api/series/`, confirmado contra la API
en vivo). El upsert/factor contra Postgres real vive en `test_ipc_db.py`.
"""
import httpx

from services import ipc


def _fake_get(*args, **kwargs):
    return httpx.Response(
        200,
        json={
            "data": [
                ["2016-12-01", 100.0],
                ["2017-01-01", 101.5859],
                ["2026-06-01", 11826.4103],
                ["2026-07-01", None],  # mes sin publicar todavía
            ],
            "count": 4,
        },
        # `raise_for_status()` exige un `request` asociado (httpx >=0.28) incluso
        # en el camino OK — sin esto, cualquier respuesta fabricada a mano rompe
        # con "Cannot call raise_for_status as the request instance has not been set".
        request=httpx.Request("GET", ipc.INDEC_SERIES_URL),
    )


class TestFetchIpcSeries:
    def test_parsea_fecha_a_mes_yyyy_mm(self, monkeypatch):
        monkeypatch.setattr(ipc.httpx, "get", _fake_get)
        serie = ipc.fetch_ipc_series()
        meses = [mes for mes, _ in serie]
        assert meses == ["2016-12", "2017-01", "2026-06"]

    def test_indice_queda_como_decimal(self, monkeypatch):
        from decimal import Decimal

        monkeypatch.setattr(ipc.httpx, "get", _fake_get)
        serie = ipc.fetch_ipc_series()
        assert serie[0] == ("2016-12", Decimal("100.0"))

    def test_meses_sin_publicar_null_se_excluyen(self, monkeypatch):
        # 2026-07 viene con índice None (INDEC todavía no lo publicó) — no debe
        # aparecer en la serie devuelta (ni como None ni como 0).
        monkeypatch.setattr(ipc.httpx, "get", _fake_get)
        serie = ipc.fetch_ipc_series()
        assert "2026-07" not in [mes for mes, _ in serie]

    def test_error_http_se_propaga(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(ipc.httpx, "get", _boom)
        try:
            ipc.fetch_ipc_series()
            assert False, "debería haber levantado"
        except httpx.ConnectError:
            pass
