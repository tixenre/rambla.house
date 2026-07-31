"""Paso 0 — Invariantes de seguridad SQL del motor de reservas.

Se ejecuta contra el código ACTUAL (antes de extraer `backend/reservas/`) para
FIJAR la conducta segura antes de mover nada. Certifica que:

  1. `ESTADOS_RESERVADO` es un literal seguro: solo nombres de estado canónicos,
     sin placeholders SQL/format ni nada derivable de input.
  2. Las copias de `ESTADOS_RESERVADO` en distintos módulos son idénticas (la
     duplicación existente no derivó en drift → un IN clause desincronizado).
  3. Las funciones del MOTOR (gate de confirmación + disponibilidad + centinela)
     interpolan en su SQL únicamente tokens de una allowlist chica
     (`ESTADOS_RESERVADO`, `ph`). Todo VALOR va como bound param (`?`). Si alguien
     mete una interpolación nueva en estas funciones, este test la caza.

Es el guard anti-inyección acotado al núcleo sagrado: no escanea todo el repo
(eso sería frágil), sino exactamente las funciones que resuelven disponibilidad y
reservan stock.
"""
import ast
import inspect
import re
import textwrap

import pytest

pytestmark = pytest.mark.unit

CANON = "('solicitado','confirmado','retirado')"
ESTADOS_CANONICOS = {"solicitado", "confirmado", "retirado"}

# Tokens que el motor PUEDE interpolar en su SQL sin riesgo de inyección:
#   ESTADOS_RESERVADO   → constante interna (su seguridad se verifica abajo)
#   ph                  → string de placeholders "?,?,?" para cláusulas IN (no datos)
#   TIPOS_SIN_RETIRO_SQL → tipos_pedido.py, mismo perfil que ESTADOS_RESERVADO:
#                          tupla SQL literal fija ('taller','estudio_fijo'),
#                          nunca derivada de input (2026-07-28, F0.1/`_centinela_libre`).
# Cualquier otro token interpolado en SQL del motor hace fallar el test.
ALLOWLIST_INTERPOLACIONES = {"ESTADOS_RESERVADO", "ph", "TIPOS_SIN_RETIRO_SQL"}

SQL_KEYWORDS = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", " FROM ", " WHERE ")


# ── Helpers de escaneo AST ──────────────────────────────────────────────────

def _es_sql_fstring(node: ast.JoinedStr) -> bool:
    """True si el f-string parece SQL (descarta f-strings de mensajes/logs)."""
    estatico = "".join(
        v.value for v in node.values
        if isinstance(v, ast.Constant) and isinstance(v.value, str)
    ).upper()
    return any(kw in estatico for kw in SQL_KEYWORDS)


def _nombres_interpolados(node: ast.JoinedStr) -> set[str]:
    """Nombres de variables interpoladas (`{x}`) dentro de un f-string SQL."""
    nombres: set[str] = set()
    for v in node.values:
        if isinstance(v, ast.FormattedValue):
            for n in ast.walk(v.value):
                if isinstance(n, ast.Name):
                    nombres.add(n.id)
    return nombres


def _interpolaciones_sql(func) -> set[str]:
    """Todos los nombres interpolados en cualquier f-string SQL de `func`."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    nombres: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and _es_sql_fstring(node):
            nombres |= _nombres_interpolados(node)
    return nombres


def _funciones_motor():
    """Importadas adentro para que un fallo de import sea un fallo de test claro
    (y para no pagar el import si se colectan solo otros tests)."""
    from reservas import (
        calcular_disponibilidad,
        dias_no_disponibles,
        get_buffer_horas,
        parientes_de,
        rango_con_buffer,
        reservado_directo,
        reservado_directo_batch,
        reservado_total,
        unidades_en_mantenimiento,
        unidades_en_mantenimiento_batch,
        validar_stock,
        validar_stock_hipotetico,
    )
    from reservas.gate import _validar_demanda
    from services.estudio.queries.disponibilidad import _centinela_libre

    return [
        validar_stock,
        validar_stock_hipotetico,
        _validar_demanda,
        calcular_disponibilidad,
        dias_no_disponibles,
        get_buffer_horas,
        parientes_de,
        rango_con_buffer,
        reservado_directo,
        reservado_directo_batch,
        reservado_total,
        unidades_en_mantenimiento,
        unidades_en_mantenimiento_batch,
        _centinela_libre,
    ]


# ── Tests ───────────────────────────────────────────────────────────────────

def test_estados_reservado_es_literal_seguro():
    from reservas import ESTADOS_RESERVADO

    assert ESTADOS_RESERVADO == CANON
    for veneno in ("?", "%s", "%", "{", "}", ";", "--", " OR ", "UNION"):
        assert veneno not in ESTADOS_RESERVADO, f"ESTADOS_RESERVADO contiene {veneno!r}"
    # Solo los estados canónicos, entre comillas simples.
    assert set(re.findall(r"'([^']+)'", ESTADOS_RESERVADO)) == ESTADOS_CANONICOS


def test_solicitado_reserva_stock_y_presupuesto_ya_no_existe():
    """Candado del rename `presupuesto` → `solicitado` (2026-07-14): el estado
    INICIAL del pedido reserva stock bajo su nuevo nombre. Si un cambio futuro
    saca 'solicitado' del IN de reservas (o reaparece el viejo 'presupuesto'), se
    caza acá — el motor dejaría de reservar los pedidos recién solicitados y
    habría SOBREVENTA (dos pedidos del mismo equipo escaso, ambos "solicitados",
    sin que el gate cuente al primero)."""
    from reservas import ESTADOS_RESERVADO

    assert "'solicitado'" in ESTADOS_RESERVADO, "un pedido solicitado DEBE reservar stock"
    assert "'presupuesto'" not in ESTADOS_RESERVADO, "'presupuesto' se renombró a 'solicitado'"


def test_estados_reservado_es_fuente_unica():
    """Tras la modularización, `reservas.ESTADOS_RESERVADO` es la fuente única:
    los módulos que la usan la importan del paquete (no re-definen una copia).
    Si alguien reintroduce una copia divergente, este guard la caza."""
    from reservas import ESTADOS_RESERVADO as PKG
    from routes.alquileres import ESTADOS_RESERVADO as A
    from routes.equipos import ESTADOS_RESERVADO as E

    assert A is PKG, "routes.alquileres debe reusar reservas.ESTADOS_RESERVADO, no copiarla"
    assert E is PKG, "routes.equipos debe reusar reservas.ESTADOS_RESERVADO, no copiarla"
    assert PKG == CANON


@pytest.mark.parametrize(
    "func", _funciones_motor(), ids=lambda f: f.__name__
)
def test_motor_solo_interpola_allowlist_en_sql(func):
    """El SQL del motor solo interpola constantes/placeholders seguros; todo
    valor va como bound param. Caza una interpolación nueva no permitida."""
    interpoladas = _interpolaciones_sql(func)
    fuera = interpoladas - ALLOWLIST_INTERPOLACIONES
    assert not fuera, (
        f"{func.__name__} interpola en SQL tokens fuera de la allowlist: {sorted(fuera)}. "
        f"Si es un placeholder seguro, agregalo a ALLOWLIST_INTERPOLACIONES; "
        f"si es un valor, pasalo como bound param (?)."
    )
