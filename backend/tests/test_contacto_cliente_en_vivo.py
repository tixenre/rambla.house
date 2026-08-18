"""Los datos de contacto/identidad del pedido (nombre, email, teléfono) se
muestran SIEMPRE en vivo desde la ficha del cliente (decisión 2026-06-06).

El pedido guarda una foto al crearse, pero al mostrarlo se sobrescribe con el
dato actual del cliente — en cualquier estado. La plata (precio/descuento) NO
se toca acá: eso queda congelado en confirmados/finalizados.
"""

import pytest

from routes.alquileres import (
    _enriquecer_pedido_con_cliente,
    _enriquecer_pedidos_con_cliente,
)


pytestmark = pytest.mark.unit


class FakeConn:
    """Devuelve filas de `clientes` desde un mapa {id: dict}, de `alquileres`
    (para resolver el cliente_id de un pedido principal) desde un segundo mapa
    {id: cliente_id}, y de `verified_contacts` desde un tercer mapa
    {id: {"email"|"phone": valor}} — sin este último, cualquier query a
    `verified_contacts` cae al `return None`/`[]` por defecto (equivalente a
    "sin contacto verificado"), que es el comportamiento neutro correcto."""

    def __init__(
        self,
        clientes: dict[int, dict],
        principales: dict[int, int | None] | None = None,
        verificados: dict[int, dict[str, str]] | None = None,
    ):
        self._clientes = clientes
        self._principales = principales or {}
        self._verificados = verificados or {}
        self._sql = ""
        self._params = ()

    def execute(self, sql, params=()):
        self._sql = sql
        self._params = params or ()
        return self

    def fetchone(self):
        if "FROM alquileres WHERE id" in self._sql:
            if self._params[0] not in self._principales:
                return None
            return {"cliente_id": self._principales[self._params[0]]}
        if "FROM verified_contacts" in self._sql and "cliente_id=" in self._sql:
            kind = "email" if "kind='email'" in self._sql else "phone"
            val = self._verificados.get(self._params[0], {}).get(kind)
            return {"value": val} if val else None
        if "FROM clientes WHERE id" in self._sql:
            return self._clientes.get(self._params[0])
        return None

    def fetchall(self):
        if "FROM alquileres WHERE id IN" in self._sql:
            return [
                {"id": i, "cliente_id": self._principales[i]}
                for i in self._params if i in self._principales
            ]
        if "FROM verified_contacts" in self._sql and "cliente_id IN" in self._sql:
            out = []
            for cid in self._params:
                for kind, val in self._verificados.get(cid, {}).items():
                    out.append({"cliente_id": cid, "kind": kind, "value": val})
            return out
        if "FROM clientes WHERE id IN" in self._sql:
            return [self._clientes[i] for i in self._params if i in self._clientes]
        return []

    def close(self):
        pass


def _foto():
    """Pedido con la foto vieja del cliente."""
    return {
        "id": 1,
        "cliente_id": 7,
        "cliente_nombre": "Perez, Juan",
        "cliente_email": "viejo@mail.com",
        "cliente_telefono": "111-viejo",
        "descuento_pct": 30,  # la plata no se toca
    }


def test_sobrescribe_con_el_dato_actual():
    conn = FakeConn({7: {"nombre": "Juan", "apellido": "Pereyra",
                         "email": "nuevo@mail.com", "telefono": "222-nuevo"}})
    p = _foto()
    _enriquecer_pedido_con_cliente(conn, p)
    assert p["cliente_nombre"] == "Juan Pereyra"   # apellido corregido, "Nombre Apellido"
    assert p["cliente_email"] == "nuevo@mail.com"
    assert p["cliente_telefono"] == "222-nuevo"
    assert p["descuento_pct"] == 30                  # plata intacta


def test_sin_cliente_vinculado_conserva_la_foto():
    conn = FakeConn({})
    p = _foto()
    p["cliente_id"] = None
    _enriquecer_pedido_con_cliente(conn, p)
    assert p["cliente_nombre"] == "Perez, Juan"
    assert p["cliente_email"] == "viejo@mail.com"


def test_cliente_inexistente_conserva_la_foto():
    conn = FakeConn({})  # id 7 no está
    p = _foto()
    _enriquecer_pedido_con_cliente(conn, p)
    assert p["cliente_nombre"] == "Perez, Juan"


def test_email_vacio_en_ficha_no_borra_el_contacto():
    # Si la ficha tiene email/teléfono vacíos, se conserva la foto (no perder
    # el contacto). El nombre siempre se refresca (apellido/nombre son obligatorios).
    conn = FakeConn({7: {"nombre": "Juan", "apellido": "Pereyra",
                         "email": "", "telefono": None}})
    p = _foto()
    _enriquecer_pedido_con_cliente(conn, p)
    assert p["cliente_nombre"] == "Juan Pereyra"
    assert p["cliente_email"] == "viejo@mail.com"
    assert p["cliente_telefono"] == "111-viejo"


def test_batch_listado():
    conn = FakeConn({
        7: {"id": 7, "nombre": "Juan", "apellido": "Pereyra",
            "email": "n@mail.com", "telefono": "222"},
        9: {"id": 9, "nombre": "Ana", "apellido": "Gómez",
            "email": "a@mail.com", "telefono": "333"},
    })
    pedidos = [
        {"id": 1, "cliente_id": 7, "cliente_nombre": "Perez, Juan",
         "cliente_email": "x", "cliente_telefono": "x"},
        {"id": 2, "cliente_id": 9, "cliente_nombre": "Viejo, Ana",
         "cliente_email": "x", "cliente_telefono": "x"},
        {"id": 3, "cliente_id": None, "cliente_nombre": "Manual",
         "cliente_email": "manual@mail.com", "cliente_telefono": "000"},
    ]
    _enriquecer_pedidos_con_cliente(conn, pedidos)
    assert pedidos[0]["cliente_nombre"] == "Juan Pereyra"
    assert pedidos[1]["cliente_nombre"] == "Ana Gómez"
    assert pedidos[2]["cliente_nombre"] == "Manual"  # sin cliente vinculado, intacto


def test_turno_vinculado_resuelve_el_cliente_del_principal_en_vivo():
    """Reproduce el bug real: el turno se creó cuando su pedido principal
    todavía no tenía cliente asignado (`cliente_id`/`cliente_nombre` propios
    vacíos, foto congelada por `_resolver_pedido_principal` en ese momento) —
    el principal consiguió cliente DESPUÉS. El turno tiene que mostrar el
    cliente ACTUAL del principal, no quedarse en "Sin cliente" para siempre."""
    conn = FakeConn(
        clientes={9: {"nombre": "Agustina", "apellido": "Gusman",
                      "email": "ag@mail.com", "telefono": "444"}},
        principales={452: 9},
    )
    turno = {"id": 451, "cliente_id": None, "cliente_nombre": None,
             "pedido_principal_id": 452}
    _enriquecer_pedido_con_cliente(conn, turno)
    assert turno["cliente_nombre"] == "Agustina Gusman"
    assert turno["cliente_email"] == "ag@mail.com"


def test_turno_vinculado_sin_cliente_en_el_principal_sigue_sin_cliente():
    conn = FakeConn(clientes={}, principales={452: None})
    turno = {"id": 451, "cliente_id": None, "cliente_nombre": None,
             "pedido_principal_id": 452}
    _enriquecer_pedido_con_cliente(conn, turno)
    assert turno["cliente_nombre"] is None


def test_batch_turno_vinculado_resuelve_el_cliente_del_principal_en_vivo():
    conn = FakeConn(
        clientes={9: {"id": 9, "nombre": "Agustina", "apellido": "Gusman",
                      "email": "ag@mail.com", "telefono": "444"}},
        principales={452: 9},
    )
    pedidos = [
        {"id": 452, "cliente_id": 9, "cliente_nombre": "Agustina Gusman"},
        {"id": 451, "cliente_id": None, "cliente_nombre": None,
         "pedido_principal_id": 452},
    ]
    _enriquecer_pedidos_con_cliente(conn, pedidos)
    assert pedidos[1]["cliente_nombre"] == "Agustina Gusman"


# --- contacto verificado (verified_contacts) — prioridad distinta por canal ---
#
# email_comunicacion: la base (Google) GANA sobre el verificado (Didit-OTP).
# telefono_contacto:  el VERIFICADO (Didit-OTP) gana sobre la base. Son las
# dos direcciones más fáciles de invertir por error al escribir la fórmula
# mirroreada del batch (`_enriquecer_pedidos_con_cliente`) — un test por
# dirección, single y batch, para que un typo se note enseguida.


def test_telefono_verificado_gana_al_base_single():
    conn = FakeConn(
        clientes={7: {"nombre": "Juan", "apellido": "Pereyra",
                      "email": "juan@mail.com", "telefono": "111-base"}},
        verificados={7: {"phone": "222-verificado"}},
    )
    p = _foto()
    _enriquecer_pedido_con_cliente(conn, p)
    assert p["cliente_telefono"] == "222-verificado"


def test_telefono_verificado_gana_al_base_batch():
    conn = FakeConn(
        clientes={7: {"id": 7, "nombre": "Juan", "apellido": "Pereyra",
                      "email": "juan@mail.com", "telefono": "111-base"}},
        verificados={7: {"phone": "222-verificado"}},
    )
    pedidos = [{"id": 1, "cliente_id": 7, "cliente_nombre": "x",
                "cliente_email": "x", "cliente_telefono": "x"}]
    _enriquecer_pedidos_con_cliente(conn, pedidos)
    assert pedidos[0]["cliente_telefono"] == "222-verificado"


def test_email_base_gana_al_verificado_single():
    conn = FakeConn(
        clientes={7: {"nombre": "Juan", "apellido": "Pereyra",
                      "email": "base@mail.com", "telefono": "111"}},
        verificados={7: {"email": "otro-verificado@mail.com"}},
    )
    p = _foto()
    _enriquecer_pedido_con_cliente(conn, p)
    assert p["cliente_email"] == "base@mail.com"  # el de Google gana, no el verificado


def test_email_base_gana_al_verificado_batch():
    conn = FakeConn(
        clientes={7: {"id": 7, "nombre": "Juan", "apellido": "Pereyra",
                      "email": "base@mail.com", "telefono": "111"}},
        verificados={7: {"email": "otro-verificado@mail.com"}},
    )
    pedidos = [{"id": 1, "cliente_id": 7, "cliente_nombre": "x",
                "cliente_email": "x", "cliente_telefono": "x"}]
    _enriquecer_pedidos_con_cliente(conn, pedidos)
    assert pedidos[0]["cliente_email"] == "base@mail.com"


def test_sin_email_base_cae_a_verificado_single():
    """El caso real (Camila, #466): cuenta passkey-only sin Google — sin email
    base, pero con uno verificado por Didit en `verified_contacts`."""
    conn = FakeConn(
        clientes={7: {"nombre": "Camila", "apellido": "Simoni",
                      "email": None, "telefono": None}},
        verificados={7: {"email": "camila@mail.com", "phone": "+549..."}},
    )
    p = _foto()
    _enriquecer_pedido_con_cliente(conn, p)
    assert p["cliente_email"] == "camila@mail.com"
    assert p["cliente_telefono"] == "+549..."


def test_sin_email_base_cae_a_verificado_batch():
    conn = FakeConn(
        clientes={7: {"id": 7, "nombre": "Camila", "apellido": "Simoni",
                      "email": None, "telefono": None}},
        verificados={7: {"email": "camila@mail.com", "phone": "+549..."}},
    )
    pedidos = [{"id": 1, "cliente_id": 7, "cliente_nombre": "x",
                "cliente_email": "x", "cliente_telefono": "x"}]
    _enriquecer_pedidos_con_cliente(conn, pedidos)
    assert pedidos[0]["cliente_email"] == "camila@mail.com"
    assert pedidos[0]["cliente_telefono"] == "+549..."


def test_batch_no_cruza_contactos_entre_clientes():
    """Riesgo real de un batch: que el indexado por cliente_id se mezcle y un
    pedido termine con el contacto verificado de OTRO cliente."""
    conn = FakeConn(
        clientes={
            7: {"id": 7, "nombre": "Juan", "apellido": "Pereyra",
                "email": None, "telefono": "111-base"},
            9: {"id": 9, "nombre": "Ana", "apellido": "Gómez",
                "email": "ana@mail.com", "telefono": None},
        },
        verificados={
            7: {"email": "juan-verificado@mail.com"},
            9: {"phone": "999-verificado"},
        },
    )
    pedidos = [
        {"id": 1, "cliente_id": 7, "cliente_nombre": "x", "cliente_email": "x", "cliente_telefono": "x"},
        {"id": 2, "cliente_id": 9, "cliente_nombre": "x", "cliente_email": "x", "cliente_telefono": "x"},
    ]
    _enriquecer_pedidos_con_cliente(conn, pedidos)
    assert pedidos[0]["cliente_email"] == "juan-verificado@mail.com"  # sin base → verificado propio
    assert pedidos[0]["cliente_telefono"] == "111-base"               # base gana, no el de Ana
    assert pedidos[1]["cliente_email"] == "ana@mail.com"               # base gana, no el de Juan
    assert pedidos[1]["cliente_telefono"] == "999-verificado"          # sin base → verificado propio
