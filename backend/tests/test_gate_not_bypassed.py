"""Paso 0 — El gate de stock nunca se saltea (guard estructural).

Invariante: toda función de ruta que INSERTA en `alquiler_items` (es decir,
reserva stock) o referencia el gate de validación (`_check_stock` /
`_check_stock_hipotetico` / `_centinela_libre`), o está en una ALLOWLIST explícita
de helpers que delegan la validación en su caller (patrón documentado en el
código).

Esto es future-proofing: si alguien agrega una nueva función que inserta reservas
y se olvida de validar stock, este test falla — obligando a llamar al gate o a
allowlistear conscientemente (decisión visible en el diff).

Se ejecuta contra el código ACTUAL; las dos entradas de la allowlist son los
delegadores legítimos de hoy.
"""
import ast
import os

import pytest

pytestmark = pytest.mark.unit

ROUTES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes")

GATE_SYMBOLS = {
    "_check_stock", "_check_stock_hipotetico", "_centinela_libre",
    # `estudio.py` no alias-ea `validar_stock_hipotetico` (lo importa tal cual
    # de `reservas`, a diferencia de `cliente_portal` que lo envuelve como
    # `_check_stock_hipotetico`) — misma pieza del motor sagrado, otro nombre.
    "validar_stock_hipotetico",
    # `_estudio_disponible` (estudio.py) es el gate CANÓNICO del espacio: slot
    # fijo → taller → `_centinela_libre` (buffer propio). Una función que lo
    # llama YA validó el espacio aunque no referencie `_centinela_libre`
    # directo (queda un nivel más adentro) — #1283 Fase 6.
    "_estudio_disponible",
}

# Helpers que insertan items PERO delegan la validación de stock en su caller.
# Cada uno está documentado en el código fuente como "el caller valida".
#   - _apply_pedido_items (alquileres): docstring "No valida stock — el caller
#     debe llamar a _check_stock si corresponde".
#   - _agregar_items_pack (estudio): el pack es best-effort; crear_reserva_estudio
#     llama _check_stock tras insertarlo y revierte si no hay stock.
#   - _regenerar_pedidos_slot (estudio, Fase 2 — ítems veraces): el ítem
#     centinela que inserta es para que la plata del slot se atribuya/vea en
#     la liquidación, NO el mecanismo de bloqueo — ese sigue siendo
#     `_slot_bloqueante` (la regla recurrente), validado por el CALLER
#     (`crear_slot`/`actualizar_slot`, vía `verificar_sesiones_disponibles`)
#     ANTES de regenerar. Reventar la reserva acá sería doble validación de
#     algo que el caller ya chequeó.
# Clave = path relativo a routes/ (ej. "alquileres/core.py"), así desambigua entre
# los varios core.py de los paquetes split (#501).
ALLOWLIST_DELEGADORES = {
    ("alquileres/core.py", "_apply_pedido_items"),
    ("estudio.py", "_agregar_items_pack"),
    ("estudio.py", "_regenerar_pedidos_slot"),
}


def _func_envolvente(funcs, lineno):
    """FunctionDef más interna que contiene `lineno`."""
    mejor = None
    for fn in funcs:
        if fn.lineno <= lineno <= (fn.end_lineno or fn.lineno):
            if mejor is None or fn.lineno > mejor.lineno:
                mejor = fn
    return mejor


def _funciones_que_insertan_reservas():
    """Devuelve [(archivo, funcname, referencia_gate?)] por cada sitio que
    inserta en alquiler_items, en todos los módulos de routes/."""
    hallazgos = []
    archivos = []
    for dirpath, _dirs, files in os.walk(ROUTES_DIR):
        for fname in files:
            if fname.endswith(".py"):
                archivos.append(os.path.join(dirpath, fname))
    for path in sorted(archivos):
        # Identificador = path relativo a routes/ (ej. "alquileres/core.py"),
        # así desambigua entre los varios core.py de los paquetes split (#501).
        rel = os.path.relpath(path, ROUTES_DIR)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "INSERT INTO alquiler_items" in node.value
            ):
                fn = _func_envolvente(funcs, node.lineno)
                if fn is None:
                    hallazgos.append((rel, "<module>", False))
                    continue
                nombres = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
                hallazgos.append((rel, fn.name, bool(GATE_SYMBOLS & nombres)))
    return hallazgos


def test_existen_sitios_que_insertan_reservas():
    """Sanity: el escaneo realmente encuentra inserciones (si el patrón de SQL
    cambia y deja de matchear, el guard quedaría vacío sin avisar)."""
    sitios = _funciones_que_insertan_reservas()
    assert len(sitios) >= 3, f"esperaba varios sitios de INSERT, hallé: {sitios}"


def test_toda_insercion_de_reservas_pasa_por_el_gate():
    sitios = _funciones_que_insertan_reservas()
    sin_gate = []
    for archivo, func, ref_gate in sitios:
        if ref_gate:
            continue
        if (archivo, func) in ALLOWLIST_DELEGADORES:
            continue
        sin_gate.append((archivo, func))

    assert not sin_gate, (
        "Funciones que insertan reservas sin pasar por el gate de stock ni estar "
        f"en la allowlist de delegadores: {sin_gate}. Llamá a _check_stock/"
        "_centinela_libre, o (si delega en el caller) agregala a "
        "ALLOWLIST_DELEGADORES con su justificación."
    )


def test_allowlist_no_tiene_entradas_muertas():
    """Si un delegador allowlisteado deja de insertar (o se renombra), sacar la
    entrada — así la allowlist no acumula excepciones obsoletas."""
    presentes = {(a, f) for a, f, _ in _funciones_que_insertan_reservas()}
    muertas = ALLOWLIST_DELEGADORES - presentes
    assert not muertas, f"entradas de allowlist que ya no insertan reservas: {muertas}"
