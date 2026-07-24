"""Escritura de cuentas/cajas (#809) — única puerta de mutación.

Una cuenta es una caja física/financiera (Efectivo, Banco), la "mano" de un socio
(Caja Pablo / Caja Tincho) o el fondo de la empresa (Fondo Rambla). La columna
`socio` es el puente 1:1 con `alquiler_pagos.destinatario`: la caja con
`socio='Tincho'` recibe automáticamente (vía derivación en `queries/saldos.py`)
todo pago cobrado por Tincho. Por eso `socio` solo es válido cuando `tipo='socio'`,
y solo puede valer uno de los socios físicos.

El nombre es único SOLO entre cuentas ACTIVAS (índice parcial `cuentas_nombre_activa_uq`):
una cuenta dada de baja (baja lógica) deja de bloquear su nombre y se puede reusar.

`validar_cuenta` es pura (testeable sin DB). El resto toca la conexión. Lectura →
`queries/cuentas.py`.
"""

from contabilidad.constants import COBRADORES, MONEDAS, SOCIOS_HUMANOS, TIPOS_CUENTA
from contabilidad.queries.cuentas import obtener_cuenta

# `moneda` se fija al crear (cambiarla con movimientos cargados rompería el saldo).
_CAMPOS_EDITABLES = ("nombre", "saldo_inicial", "fecha_apertura", "orden", "activa")

# Cobradores que un fondo puede representar — los dos no-humanos de COBRADORES
# (Rambla y Estudio son cajas reales de la empresa/economía separada, no
# personas; los socios humanos van por `tipo='socio'`, no por un fondo).
_SOCIOS_FONDO = tuple(c for c in COBRADORES if c not in SOCIOS_HUMANOS)


def validar_cuenta(data: dict) -> None:
    """Valida la forma de una cuenta. Lanza ValueError si es inválida. PURA.

    - `nombre`: string no vacío.
    - `tipo`: uno de TIPOS_CUENTA.
    - `socio` (= el cobrador que la caja representa): si viene, uno de COBRADORES;
      una caja de tipo 'socio' debe representar a un socio humano (Pablo/Tincho).
    - `saldo_inicial`: entero (ARS, sin centavos).
    """
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("El nombre de la cuenta es obligatorio.")

    tipo = data.get("tipo")
    if tipo not in TIPOS_CUENTA:
        raise ValueError(f"Tipo de cuenta inválido (debe ser uno de {', '.join(TIPOS_CUENTA)}).")

    socio = data.get("socio")
    socio = socio.strip() if isinstance(socio, str) else socio
    if socio and socio not in COBRADORES:
        raise ValueError(f"El cobrador debe ser uno de {', '.join(COBRADORES)}.")
    # Cada tipo acota qué cobrador puede representar: socio → Pablo/Tincho;
    # fondo → Rambla o Estudio (o ninguno); caja/banco → ningún cobrador.
    if tipo == "socio":
        if socio not in SOCIOS_HUMANOS:
            raise ValueError(f"Una cuenta de socio debe representar a {', '.join(SOCIOS_HUMANOS)}.")
    elif tipo == "fondo":
        if socio and socio not in _SOCIOS_FONDO:
            raise ValueError(f"Un fondo solo puede representar a {' o '.join(_SOCIOS_FONDO)} (o a nadie).")
    elif socio:
        raise ValueError("Solo una caja de socio (Pablo/Tincho) o un fondo (Rambla/Estudio) tienen cobrador.")

    si = data.get("saldo_inicial", 0)
    if si is None:
        si = 0
    if isinstance(si, bool) or not isinstance(si, int):
        raise ValueError("El saldo inicial debe ser un número entero (sin centavos).")

    moneda = data.get("moneda")
    if moneda is not None and moneda not in MONEDAS:
        raise ValueError(f"La moneda debe ser una de {', '.join(MONEDAS)}.")


def crear_cuenta(conn, *, nombre, tipo, socio=None, moneda="ARS", saldo_inicial=0,
                 fecha_apertura=None, orden=0, por=None) -> dict:
    """Crea una cuenta (valida primero). Devuelve la cuenta creada.

    `fecha_apertura` None → clean start de la liquidación (`LIQUIDACION_INICIO`).
    `moneda` ARS (default) o USD.
    """
    moneda = (moneda or "ARS")
    data = {"nombre": (nombre or "").strip(), "tipo": tipo, "moneda": moneda,
            "socio": (socio or None), "saldo_inicial": int(saldo_inicial or 0)}
    validar_cuenta(data)
    # `fondo` SÍ persiste su cobrador (Rambla/Estudio) — antes solo `socio` lo
    # hacía, así que crear un fondo nuevo (ej. Caja Estudio) por este camino
    # descartaba el cobrador en silencio; el seed de Fondo Rambla lo sorteaba
    # insertando la fila por SQL directo, no vía este comando.
    socio_val = data["socio"] if tipo in ("socio", "fondo") else None

    # Default de `fecha_apertura` = el clean start de la liquidación (constante única
    # en reportes/), como bound param (DAL: nada de literales de valor en el SQL).
    from reportes.liquidacion import LIQUIDACION_INICIO

    cur = conn.execute(
        """INSERT INTO cuentas (nombre, tipo, socio, moneda, saldo_inicial, fecha_apertura, orden, created_by, updated_by)
           VALUES (%s, %s, %s, %s, %s, COALESCE(%s::date, %s::date), %s, %s, %s)
           RETURNING id""",
        (data["nombre"], tipo, socio_val, moneda, data["saldo_inicial"], fecha_apertura,
         LIQUIDACION_INICIO, int(orden or 0), por, por),
    )
    new_id = cur.fetchone()[0]
    return obtener_cuenta(conn, new_id)


def editar_cuenta(conn, cuenta_id: int, *, campos: dict, por=None) -> dict:
    """Edita una cuenta. NO permite cambiar `tipo` ni `socio` (reasignaría
    histórico). Solo toca los campos en _CAMPOS_EDITABLES presentes en `campos`.
    """
    actual = obtener_cuenta(conn, cuenta_id)
    if not actual:
        raise ValueError("La cuenta no existe.")

    # Construir el set de cambios validando el resultado final.
    propuesta = dict(actual)
    sets, params = [], []
    for campo in _CAMPOS_EDITABLES:
        if campo not in campos:
            continue
        valor = campos[campo]
        if campo == "saldo_inicial":
            valor = int(valor or 0)
        if campo == "nombre":
            valor = (valor or "").strip()
        propuesta[campo] = valor
        if campo == "fecha_apertura":
            sets.append("fecha_apertura = %s::date")
        else:
            sets.append(f"{campo} = %s")
        params.append(valor)

    if not sets:
        return actual

    validar_cuenta(propuesta)  # tipo/socio se conservan del actual → valida coherencia
    sets.append("updated_by = %s")
    params.append(por)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.append(cuenta_id)
    conn.execute(f"UPDATE cuentas SET {', '.join(sets)} WHERE id = %s", tuple(params))
    return obtener_cuenta(conn, cuenta_id)


def desactivar_cuenta(conn, cuenta_id: int, por=None) -> dict:
    """Baja lógica de una cuenta. Falla si su saldo actual no es cero (no se da de
    baja una caja con plata adentro). Devuelve la cuenta desactivada.

    `FOR UPDATE` sobre la fila ANTES de leer el saldo (auditoría 2026-07-02):
    sin esto, un `crear_movimiento` concurrente contra esta cuenta podía colarse
    entre el chequeo de saldo=0 y el `UPDATE activa=FALSE`, dejando la cuenta
    inactiva con saldo real ≠ 0 (esa plata deja de aparecer en `saldos()` hasta
    que alguien la reactive o corra la reconciliación). Un INSERT/UPDATE en
    `movimientos` que referencia esta cuenta toma un lock `FOR KEY SHARE`
    implícito por la FK, que conflictúa con este `FOR UPDATE` — cierra la
    ventana sin tocar `crear_movimiento`."""
    from contabilidad.queries.saldos import saldo_de_cuenta

    row = conn.execute("SELECT activa FROM cuentas WHERE id = %s FOR UPDATE", (cuenta_id,)).fetchone()
    if not row:
        raise ValueError("La cuenta no existe.")
    if not row["activa"]:
        return obtener_cuenta(conn, cuenta_id)

    saldo = saldo_de_cuenta(conn, cuenta_id)
    if saldo != 0:
        raise ValueError(
            f"No se puede desactivar una cuenta con saldo (${saldo:,}). "
            "Transferí o ajustá su saldo a cero primero."
        )

    conn.execute(
        "UPDATE cuentas SET activa = FALSE, updated_by = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        (por, cuenta_id),
    )
    return obtener_cuenta(conn, cuenta_id)
