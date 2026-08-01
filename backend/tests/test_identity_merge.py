"""Tests de identity/merge — fusión pesada de dos cuentas (dedup, Fase 2 #1098).

Dos frentes:
  1. La máquina: reasigna las FKs con datos, deduplica las de UNIQUE por-cuenta, borra
     el source y rehúsa los casos peligrosos (perder identidad / dos personas distintas).
  2. Cobertura ANTI-DRIFT (estática, sin DB): toda FK a clientes(id) en schema.py tiene
     que estar clasificada (reasignada o descartada) — si aparece una tabla nueva con
     cliente_id y nadie la clasifica, este test falla.
"""
import re
from contextlib import contextmanager
from pathlib import Path

import pytest

from identity import merge

pytestmark = pytest.mark.unit


class _Cur:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class _MergeRec:
    """Conn fake: graba execute(); el SELECT de estado de identidad responde por id."""

    def __init__(self, estados):
        self.estados = estados  # {id: {"id","cuil","dni_validado_at"} | None}
        self.calls = []

    def execute(self, sql, params=()):
        norm = " ".join(sql.split())
        self.calls.append((norm, tuple(params)))
        if "dni_validado_at FROM clientes WHERE id=%s" in norm:
            return _Cur(self.estados.get(params[0]))
        return _Cur(None)

    @contextmanager
    def transaction(self):
        yield self

    def close(self):
        pass


def _verificado(cid, cuil="20123456786"):
    return {"id": cid, "cuil": cuil, "dni_validado_at": "2026-06-29T12:00:00"}


def _liviano(cid):
    return {"id": cid, "cuil": None, "dni_validado_at": None}


def _sql(rec, needle):
    return [c for c in rec.calls if needle in c[0]]


# ── La máquina ────────────────────────────────────────────────────────────────

def test_merge_reasigna_todo_y_borra_source():
    rec = _MergeRec({1: _liviano(1), 2: _verificado(2)})
    merge.merge_accounts(source=1, target=2, conn=rec)

    # Reasigna cada tabla con datos al target (2), desde el source (1).
    for tabla in ("alquileres", "cliente_listas",
                  "kyc_events", "passkey_credentials"):
        upd = _sql(rec, f"UPDATE {tabla} SET cliente_id=%s WHERE cliente_id=%s")
        assert upd and upd[0][1] == (2, 1), f"{tabla} no se reasignó al target"
    # Dedup-on-reassign de las dos con UNIQUE por-cuenta.
    assert _sql(rec, "UPDATE verified_contacts AS v SET cliente_id=%s")
    assert _sql(rec, "UPDATE login_identities li SET cliente_id=%s")
    # Bitácora del merge + borrado del source.
    assert _sql(rec, "INSERT INTO kyc_events")
    borrado = _sql(rec, "DELETE FROM clientes WHERE id=%s")
    assert borrado and borrado[0][1] == (1,)


def test_merge_source_igual_target_es_noop():
    rec = _MergeRec({1: _liviano(1)})
    merge.merge_accounts(source=1, target=1, conn=rec)
    assert rec.calls == []  # ni siquiera lee — no hay nada que unir


def test_merge_rehusa_si_source_verificado_y_target_no():
    # Mergear así perdería la identidad RENAPER del source → se rehúsa.
    rec = _MergeRec({1: _verificado(1), 2: _liviano(2)})
    with pytest.raises(ValueError, match="al revés"):
        merge.merge_accounts(source=1, target=2, conn=rec)
    assert not _sql(rec, "DELETE FROM clientes")  # no borró nada


def test_merge_rehusa_dos_personas_distintas():
    rec = _MergeRec({1: _verificado(1, "20111111112"), 2: _verificado(2, "27222222223")})
    with pytest.raises(ValueError, match="dos"):
        merge.merge_accounts(source=1, target=2, conn=rec)
    assert not _sql(rec, "DELETE FROM clientes")


def test_merge_permite_mismo_cuil_verificado():
    # Duplicado real: dos cuentas con el MISMO CUIL verificado → es justo el caso a deduplicar.
    rec = _MergeRec({1: _verificado(1, "20123456786"), 2: _verificado(2, "20123456786")})
    merge.merge_accounts(source=1, target=2, conn=rec)
    assert _sql(rec, "DELETE FROM clientes WHERE id=%s")[0][1] == (1,)


def test_merge_rehusa_cuenta_inexistente():
    rec = _MergeRec({1: _liviano(1), 2: None})  # 2 no existe
    with pytest.raises(ValueError, match="inexistente"):
        merge.merge_accounts(source=1, target=2, conn=rec)


# ── Cobertura anti-drift de FKs (estática, sin DB) ────────────────────────────

def _tablas_con_fk_a_clientes() -> set[str]:
    """Parsea schema.py y devuelve toda tabla cuyo cuerpo declara una FK a clientes(id).
    Fuente única del esquema (decisión 2026-06-03: toda tabla va TAMBIÉN en init_db)."""
    schema = (Path(__file__).resolve().parents[1] / "database" / "schema.py").read_text()
    # Bloques CREATE TABLE IF NOT EXISTS <nombre> ( ... ) — hasta el cierre del string SQL.
    tablas = set()
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\)\s*\"\"\"", schema, re.DOTALL):
        nombre, cuerpo = m.group(1), m.group(2)
        if re.search(r"REFERENCES\s+clientes\s*\(", cuerpo):
            tablas.add(nombre)
    return tablas


def test_identity_merge_cobertura():
    """Toda FK a clientes está clasificada (reasignada XOR descartada). Si una tabla nueva
    con cliente_id aparece sin clasificar, el merge la dejaría colgada/borrada en silencio."""
    declaradas = _tablas_con_fk_a_clientes()
    clasificadas = merge.TABLAS_REASIGNADAS | merge.TABLAS_DESCARTADAS

    # El parser tiene que ver las tablas que sabemos que existen (sanity del regex).
    assert {"alquileres", "verified_contacts", "auth_sessions"} <= declaradas

    sin_clasificar = declaradas - clasificadas
    assert not sin_clasificar, (
        f"FK(s) a clientes sin clasificar en identity/merge: {sin_clasificar}. "
        "Agregá cada tabla a TABLAS_REASIGNADAS (mover sus datos) o TABLAS_DESCARTADAS "
        "(efímera / sesión que muere con el source)."
    )
    # Y nada clasificado de más (un nombre mal tipeado que ninguna tabla respalda).
    fantasma = clasificadas - declaradas
    assert not fantasma, f"identity/merge clasifica tablas que no tienen FK a clientes: {fantasma}"
    # Disjuntos: una tabla no puede reasignarse Y descartarse.
    assert not (merge.TABLAS_REASIGNADAS & merge.TABLAS_DESCARTADAS)
