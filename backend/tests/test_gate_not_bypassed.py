"""Paso 0 — El gate de stock nunca se saltea (guard estructural).

Invariante: toda función de ruta que INSERTA en `alquiler_items` (es decir,
reserva stock) o referencia el gate de validación (`_check_stock` /
`_centinela_libre`), o está en una ALLOWLIST explícita
de helpers que delegan la validación en su caller (patrón documentado en el
código).

Esto es future-proofing: si alguien agrega una nueva función que inserta reservas
y se olvida de validar stock, este test falla — obligando a llamar al gate o a
allowlistear conscientemente (decisión visible en el diff).

Se ejecuta contra el código ACTUAL; las entradas de la allowlist son los
delegadores legítimos de hoy.
"""
import ast
import os

import pytest

pytestmark = pytest.mark.unit

ROUTES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes")
# El motor de disponibilidad/reservas del Estudio se extrajo de
# `routes/estudio.py` a un paquete propio (CQRS-lite, `services/estudio/`) —
# sin sumar este árbol al scan, los INSERT que se llevó (antes visibles acá
# desde siempre) quedarían fuera del guard estructural EN SILENCIO.
SERVICES_ESTUDIO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "services", "estudio"
)
# Mismo motivo: la economía de talleres (_regenerar_pedidos_taller) se
# extrajo de `routes/talleres.py` a `services/talleres/commands/economia.py`
# (CQRS-lite) — sin sumar este árbol, ese INSERT quedaría fuera del scan.
SERVICES_TALLERES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "services", "talleres"
)
# Mismo motivo: el núcleo de ítems/total de un pedido (_apply_pedido_items,
# el INSERT real contra el motor) se extrajo de `routes/alquileres/core.py` a
# `services/alquileres/commands/items.py` (CQRS-lite, #1312 Fase 3) — sin
# sumar este árbol, ese INSERT quedaría fuera del scan.
SERVICES_ALQUILERES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "services", "alquileres"
)

GATE_SYMBOLS = {
    "_check_stock", "_centinela_libre",
    "validar_stock_hipotetico",
    # `_estudio_disponible` (estudio.py) es el gate CANÓNICO del espacio: slot
    # fijo → taller → `_centinela_libre` (buffer propio). Una función que lo
    # llama YA validó el espacio aunque no referencie `_centinela_libre`
    # directo (queda un nivel más adentro) — #1283 Fase 6.
    "_estudio_disponible",
}

# Helpers que insertan items PERO delegan la validación de stock en su caller.
# Cada uno está documentado en el código fuente como "el caller valida".
#   - _apply_pedido_items (services/alquileres/commands/items.py — extraído de
#     routes/alquileres/core.py en el split CQRS-lite, #1312 Fase 3): docstring
#     "No valida stock — el caller debe llamar a _check_stock si corresponde".
#   - _regenerar_pedidos_slot (estudio, Fase 2 — ítems veraces): el ítem
#     centinela que inserta es para que la plata del slot se atribuya/vea en
#     la liquidación, NO el mecanismo de bloqueo — ese sigue siendo
#     `_slot_bloqueante` (la regla recurrente), validado por el CALLER
#     (`crear_slot`/`actualizar_slot`, vía `verificar_sesiones_disponibles`)
#     ANTES de regenerar. Reventar la reserva acá sería doble validación de
#     algo que el caller ya chequeó.
#   - _regenerar_pedidos_taller (services/talleres/commands/economia.py,
#     economía del taller — extraído de routes/talleres.py en el split
#     CQRS-lite): mismo patrón que el slot — los ítems (Estudio y/o equipos)
#     son para que la plata del taller se atribuya/vea en la liquidación
#     (`equipos.dueno`), NO reservan stock ni bloquean nada. El bloqueo real
#     del ESPACIO (las clases del taller) lo sigue validando
#     `verificar_sesiones_disponibles`, ahora vía el helper deduplicado
#     `_gate_conflicto_estudio` (`services/talleres/commands/ediciones.py`)
#     en los 3 callers (`admin_create_taller`/`admin_create_edicion`/
#     `admin_update_edicion`, en `routes/talleres.py`), no esta función.
# ⏰ `_agregar_items_pack` (estudio) — el delegador del pack — se retiró en la
# Fase 8 (#1283) junto con el mecanismo que validaba.
#   - _insertar_item_pintura (services/estudio/commands/reserva.py, add-on
#     "recién pintado" #1300 seguimiento): NO es un recurso con stock — es un
#     cargo fijo opcional (equipo_id NULL, cobro_modo='fijo', mismo patrón que
#     flete/limpieza #805), nunca necesita `validar_stock_hipotetico`/
#     `_centinela_libre`. Se inserta directo desde `_crear_pedido_estudio`/
#     `editar_reserva`, DESPUÉS de que esas funciones ya validaron
#     espacio/promo/sueltos vía el gate real.
#   - _insertar_item_centinela (services/estudio/commands/reserva.py, #1308
#     rediseño "turno como ítem" Fase 4 — extraído del INSERT que antes vivía
#     inline en `_crear_pedido_estudio`): el chequeo real (`_centinela_libre`,
#     bajo el `FOR UPDATE` del centinela) pasa SIEMPRE en el CALLER
#     (`_crear_pedido_estudio`/`agregar_turno_embebido`), inmediatamente antes
#     de llamar a este helper — que solo hace el INSERT, sin decidir nada.
# Clave = path relativo a routes/ (ej. "alquileres/core.py") o al árbol
# services/estudio|talleres/ con su prefijo (ver `fuentes` abajo), así
# desambigua entre los varios core.py de los paquetes split (#501) y entre árboles.
ALLOWLIST_DELEGADORES = {
    ("services/alquileres/commands/items.py", "_apply_pedido_items"),
    ("estudio.py", "_regenerar_pedidos_slot"),
    ("services/talleres/commands/economia.py", "_regenerar_pedidos_taller"),
    ("services/estudio/commands/reserva.py", "_insertar_item_pintura"),
    ("services/estudio/commands/reserva.py", "_insertar_item_centinela"),
}


def _func_envolvente(funcs, lineno):
    """FunctionDef más interna que contiene `lineno`."""
    mejor = None
    for fn in funcs:
        if fn.lineno <= lineno <= (fn.end_lineno or fn.lineno):
            if mejor is None or fn.lineno > mejor.lineno:
                mejor = fn
    return mejor


def _archivos_py(root):
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if fname.endswith(".py"):
                out.append(os.path.join(dirpath, fname))
    return out


def _funciones_que_insertan_reservas():
    """Devuelve [(archivo, funcname, referencia_gate?)] por cada sitio que
    inserta en alquiler_items, en `routes/` y en `services/estudio/` +
    `services/talleres/` + `services/alquileres/` (los motores de
    disponibilidad/reservas del Estudio, la economía de talleres y el núcleo
    de ítems de un pedido, los tres extraídos a CQRS-lite)."""
    hallazgos = []
    # (raíz, prefijo del identificador) — el prefijo distingue cada árbol de
    # services/ sin tocar el formato ya usado para routes/ (así las keys
    # existentes de ALLOWLIST_DELEGADORES no cambian).
    fuentes = [
        (ROUTES_DIR, ""),
        (SERVICES_ESTUDIO_DIR, "services/estudio/"),
        (SERVICES_TALLERES_DIR, "services/talleres/"),
        (SERVICES_ALQUILERES_DIR, "services/alquileres/"),
    ]
    for root, prefijo in fuentes:
        for path in sorted(_archivos_py(root)):
            # Identificador = path relativo a la raíz (ej. "alquileres/core.py",
            # "services/estudio/commands/reserva.py") — desambigua entre los
            # varios core.py de los paquetes split (#501) y entre árboles.
            rel = prefijo + os.path.relpath(path, root)
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
