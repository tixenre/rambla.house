"""`services.ipc` contra Postgres REAL — upsert idempotente + el factor de ajuste
"pesos de hoy" de `IPC_FACTOR_CTE`.

Mockea `fetch_ipc_series` (no pega a la red real de INDEC en tests) pero ejercita
el upsert y el CTE de factor contra la tabla real. Meses de prueba con prefijo
'1900-*' — claramente ficticios, no chocan con datos reales de la serie.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`): se saltea
salvo `RESERVAS_DB_TEST=1` + `DATABASE_URL` a una base con 'test' en el nombre.

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_ipc_db.py -v -m integration
"""
import os
from decimal import Decimal
from urllib.parse import urlparse

import pytest

from database import get_db
from services import ipc

_OPT_IN = os.getenv("RESERVAS_DB_TEST") == "1"
_DB_URL = os.getenv("DATABASE_URL", "")
_DB_NAME = urlparse(_DB_URL).path.lstrip("/") if _DB_URL else ""


def _looks_like_test_db() -> bool:
    return bool(_DB_NAME) and "test" in _DB_NAME.lower()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _OPT_IN,
        reason="opt-in: setear RESERVAS_DB_TEST=1 + DATABASE_URL a una base de prueba",
    ),
    pytest.mark.skipif(
        _OPT_IN and not _looks_like_test_db(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]

# Meses claramente ficticios (prefijo 1900) — no chocan con la serie real de INDEC.
_MESES_TEST = ["1900-01", "1900-02", "1900-03"]


def _limpiar(conn):
    conn.execute("DELETE FROM ipc_series WHERE mes = ANY(%s)", (_MESES_TEST,))
    conn.commit()


@pytest.fixture(autouse=True)
def _cleanup():
    with get_db() as conn:
        _limpiar(conn)
    yield
    with get_db() as conn:
        _limpiar(conn)


class TestActualizarIpc:
    def test_upsert_inserta_y_es_idempotente(self, monkeypatch):
        monkeypatch.setattr(
            ipc,
            "fetch_ipc_series",
            lambda: [
                ("1900-01", Decimal("100.0000")),
                ("1900-02", Decimal("110.0000")),
            ],
        )
        with get_db() as conn:
            n = ipc.actualizar_ipc(conn)
            assert n == 2
            rows = conn.execute(
                "SELECT mes, indice FROM ipc_series WHERE mes = ANY(%s) ORDER BY mes",
                (_MESES_TEST,),
            ).fetchall()
            assert [dict(r) for r in rows] == [
                {"mes": "1900-01", "indice": Decimal("100.0000")},
                {"mes": "1900-02", "indice": Decimal("110.0000")},
            ]

        # Segunda corrida con el mismo dato: no debe duplicar ni fallar.
        with get_db() as conn:
            n2 = ipc.actualizar_ipc(conn)
            assert n2 == 2
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM ipc_series WHERE mes = ANY(%s)", (_MESES_TEST,)
            ).fetchone()["c"]
            assert count == 2

    def test_upsert_actualiza_indice_revisado(self, monkeypatch):
        # INDEC a veces revisa un mes publicado — el upsert tiene que reflejarlo.
        monkeypatch.setattr(
            ipc, "fetch_ipc_series", lambda: [("1900-01", Decimal("100.0000"))]
        )
        with get_db() as conn:
            ipc.actualizar_ipc(conn)

        monkeypatch.setattr(
            ipc, "fetch_ipc_series", lambda: [("1900-01", Decimal("105.5000"))]
        )
        with get_db() as conn:
            ipc.actualizar_ipc(conn)
            row = conn.execute(
                "SELECT indice FROM ipc_series WHERE mes = '1900-01'"
            ).fetchone()
            assert row["indice"] == Decimal("105.5000")


class TestIpcFactorCte:
    def test_el_mes_mas_reciente_tiene_factor_1(self, monkeypatch):
        monkeypatch.setattr(
            ipc,
            "fetch_ipc_series",
            lambda: [
                ("1900-01", Decimal("100.0000")),
                ("1900-02", Decimal("150.0000")),
                ("1900-03", Decimal("300.0000")),
            ],
        )
        with get_db() as conn:
            ipc.actualizar_ipc(conn)
            rows = conn.execute(
                f"""
                WITH {ipc.IPC_FACTOR_CTE}
                SELECT mes, factor FROM ipc_factor WHERE mes = ANY(%s) ORDER BY mes
                """,
                (_MESES_TEST,),
            ).fetchall()
            factores = {r["mes"]: r["factor"] for r in rows}
            # 1900-03 es el mes MÁS RECIENTE de estos 3 fixtures → factor 1.
            # OJO: si en la tabla hubiera un mes real posterior a 1900 (todo el
            # historial real), el "más reciente global" seguiría siendo ESE, no
            # 1900-03 — por eso este test verifica la RAZÓN entre los 3 fixtures,
            # no un factor absoluto de 1900-03.
            assert factores["1900-02"] / factores["1900-01"] == Decimal("100.0000") / Decimal(
                "150.0000"
            )
            assert factores["1900-03"] / factores["1900-01"] == Decimal("100.0000") / Decimal(
                "300.0000"
            )

    def test_ajustar_en_origen_no_es_lo_mismo_que_ajustar_post_suma(self, monkeypatch):
        """El candado central de la feature: sumar dos meses con montos distintos
        y DESPUÉS aplicarles un solo factor da un número DISTINTO (y equivocado)
        que multiplicar cada monto por SU PROPIO factor antes de sumar. Si algún
        día alguien "simplifica" el ajuste a post-suma, este test lo cacha."""
        monkeypatch.setattr(
            ipc,
            "fetch_ipc_series",
            lambda: [
                ("1900-01", Decimal("100.0000")),  # factor 2× respecto a 1900-02
                ("1900-02", Decimal("200.0000")),  # el más reciente → factor 1×
            ],
        )
        with get_db() as conn:
            ipc.actualizar_ipc(conn)
            # Dos "pedidos" ficticios: $1000 en 1900-01, $1000 en 1900-02.
            montos = {"1900-01": Decimal("1000"), "1900-02": Decimal("1000")}

            rows = conn.execute(
                f"""
                WITH {ipc.IPC_FACTOR_CTE}
                SELECT mes, factor FROM ipc_factor WHERE mes = ANY(%s)
                """,
                (_MESES_TEST[:2],),
            ).fetchall()
            factores = {r["mes"]: r["factor"] for r in rows}

            ajustado_en_origen = sum(montos[m] * factores[m] for m in montos)
            total_nominal = sum(montos.values())
            # Ajustar en origen: 1000×2 + 1000×1 = 3000. Post-suma con el factor
            # del mes más reciente (1×) hubiera dado 2000 — un 33% de menos.
            assert ajustado_en_origen == Decimal("3000")
            assert ajustado_en_origen != total_nominal * factores["1900-02"]

    def test_mes_sin_ipc_no_rompe_el_join_con_coalesce(self):
        # Un mes ausente de ipc_series (ej. el mes en curso, sin publicar) no
        # debe aparecer en ipc_factor — el caller hace LEFT JOIN + COALESCE(factor, 1).
        with get_db() as conn:
            row = conn.execute(
                f"""
                WITH {ipc.IPC_FACTOR_CTE}
                SELECT factor FROM ipc_factor WHERE mes = '1900-99'
                """
            ).fetchone()
            assert row is None
