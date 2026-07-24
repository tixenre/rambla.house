"""Rendición (#809) — test puro del netting (sin DB).

El cruce real con `alquiler_pagos` y el saldado se ejercen en
`test_contabilidad_db.py`. Acá se prueba la matemática de quién le debe a quién.
"""


from contabilidad.constants import PARTES
from contabilidad.queries.rendicion import _netting


def _by(personas):
    return {p["persona"]: p for p in personas}


class TestNetting:
    def test_partes_son_pablo_tincho_rambla_estudio(self):
        assert set(PARTES) == {"Pablo", "Tincho", "Rambla", "Estudio"}

    def test_todo_cobrado_por_uno_reparte_a_los_demas(self):
        # Junio del ejemplo: total 200k, todo lo cobró Tincho.
        corresponde = {"Pablo": 70000, "Rambla": 123000, "Tincho": 7000}
        cobrado = {"Pablo": 0, "Tincho": 200000, "Rambla": 0}
        r = _netting(corresponde, cobrado, {"Pablo": 0, "Tincho": 0, "Rambla": 0})

        by = _by(r["personas"])
        assert by["Tincho"]["pendiente"] == -193000  # tiene de más, debe pagar
        assert by["Pablo"]["pendiente"] == 70000
        assert by["Rambla"]["pendiente"] == 123000

        sug = r["sugeridos"]
        assert {"de": "Tincho", "a": "Pablo", "monto": 70000} in sug
        assert {"de": "Tincho", "a": "Rambla", "monto": 123000} in sug
        assert sum(s["monto"] for s in sug) == 193000  # cierra

    def test_cuarta_parte_estudio_participa_del_netting(self):
        # Estudio le corresponden 50k pero no cobró nada — Rambla cobró de más
        # (incluida la parte del Estudio, ej. un pago mal asignado) y debe
        # transferirle. Mismo mecanismo que las otras 3 partes — no es un
        # caso especial, solo una 4ta fila en PARTES.
        corresponde = {"Pablo": 0, "Tincho": 0, "Rambla": 0, "Estudio": 50000}
        cobrado = {"Pablo": 0, "Tincho": 0, "Rambla": 50000, "Estudio": 0}
        r = _netting(corresponde, cobrado, {"Pablo": 0, "Tincho": 0, "Rambla": 0, "Estudio": 0})
        by = _by(r["personas"])
        assert by["Estudio"]["pendiente"] == 50000
        assert by["Rambla"]["pendiente"] == -50000
        assert r["sugeridos"] == [{"de": "Rambla", "a": "Estudio", "monto": 50000}]

    def test_balanceado_no_sugiere_nada(self):
        corresponde = {"Pablo": 100, "Tincho": 100, "Rambla": 0}
        cobrado = {"Pablo": 100, "Tincho": 100, "Rambla": 0}
        r = _netting(corresponde, cobrado, {"Pablo": 0, "Tincho": 0, "Rambla": 0})
        assert r["sugeridos"] == []
        assert all(p["pendiente"] == 0 for p in r["personas"])

    def test_ya_transferido_descuenta_lo_pendiente(self):
        corresponde = {"Pablo": 70000, "Rambla": 123000, "Tincho": 7000}
        cobrado = {"Pablo": 0, "Tincho": 200000, "Rambla": 0}
        # Tincho ya le pasó los 70k a Pablo → Pablo queda saldado.
        ya = {"Pablo": 70000, "Tincho": -70000, "Rambla": 0}
        r = _netting(corresponde, cobrado, ya)
        by = _by(r["personas"])
        assert by["Pablo"]["pendiente"] == 0
        # Falta saldar solo lo de Rambla.
        assert r["sugeridos"] == [{"de": "Tincho", "a": "Rambla", "monto": 123000}]

    def test_conservacion(self):
        corresponde = {"Pablo": 60000, "Rambla": 30000, "Tincho": 10000}
        cobrado = {"Pablo": 50000, "Tincho": 50000, "Rambla": 0}
        r = _netting(corresponde, cobrado, {"Pablo": 0, "Tincho": 0, "Rambla": 0})
        positivos = sum(p["pendiente"] for p in r["personas"] if p["pendiente"] > 0)
        assert sum(s["monto"] for s in r["sugeridos"]) == positivos

    def test_determinismo(self):
        corresponde = {"Pablo": 70000, "Rambla": 123000, "Tincho": 7000}
        cobrado = {"Pablo": 0, "Tincho": 200000, "Rambla": 0}
        a = _netting(corresponde, cobrado, {"Pablo": 0, "Tincho": 0, "Rambla": 0})
        b = _netting(corresponde, cobrado, {"Pablo": 0, "Tincho": 0, "Rambla": 0})
        assert a == b
