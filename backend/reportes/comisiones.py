"""Modelo de reparto de comisiones entre dueños (#88) — fuente única.

Cada equipo tiene un `dueno`. La plata que genera un equipo se reparte entre
beneficiarios según reglas configurables. El default son las reglas que dio el
dueño; se pueden editar desde el back-office (`app_settings['comisiones_modelo']`).

Forma del modelo (JSON):
    { "<dueño>": { "<beneficiario>": <pct>, ... }, ... }
Los porcentajes de cada dueño suman 100.
"""

import json
from typing import Any

# Default = reglas dadas por el dueño. Si no hay setting cargado, se usa esto,
# así el reporte funciona out-of-the-box.
DEFAULT_MODELO: dict[str, dict[str, float]] = {
    "Rambla": {"Rambla": 100},
    "Pablo": {"Pablo": 50, "Rambla": 45, "Tincho": 5},
    "Tincho": {"Tincho": 50, "Rambla": 45, "Pablo": 5},
    # Economía separada del Estudio (#1283): el centinela del espacio tiene
    # dueno='Estudio' — su plata queda 100% para el Estudio, no se reparte
    # con Rambla/Pablo/Tincho (es otra unidad de negocio, no una comisión).
    "Estudio": {"Estudio": 100},
}

SETTING_KEY = "comisiones_modelo"


def cargar_modelo(conn) -> dict[str, dict[str, float]]:
    """Lee el modelo de `app_settings`; cae al default si no hay o está roto."""
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = %s", (SETTING_KEY,)
    ).fetchone()
    if not row or not row["value"]:
        return DEFAULT_MODELO
    try:
        data = json.loads(row["value"])
        validar_modelo(data)
        return data
    except (ValueError, TypeError):
        # Un setting corrupto no debe romper el reporte: se cae al default.
        return DEFAULT_MODELO


def repartir(dueno: str, monto: float, modelo: dict[str, dict[str, float]]) -> dict[str, float]:
    """Reparte `monto` (lo generado por equipos de `dueno`) entre beneficiarios.

    Un dueño sin regla en el modelo (ej. valor legacy) cobra el 100% él mismo —
    nunca se pierde plata en el reparto.
    """
    reglas = modelo.get(dueno)
    if not reglas:
        return {dueno: monto}
    return {benef: monto * (pct / 100.0) for benef, pct in reglas.items()}


def validar_modelo(data: Any) -> None:
    """Valida la forma del modelo. Lanza ValueError si es inválido.

    Reglas: dict de dueños → dict de beneficiarios → % numérico 0–100, y los %
    de cada dueño suman 100 (±0.01).
    """
    if not isinstance(data, dict) or not data:
        raise ValueError("El modelo debe ser un objeto con al menos un dueño.")
    for dueno, reglas in data.items():
        if not isinstance(dueno, str) or not dueno.strip():
            raise ValueError("Nombre de dueño inválido.")
        if not isinstance(reglas, dict) or not reglas:
            raise ValueError(f"'{dueno}': el reparto debe ser un objeto de beneficiarios.")
        suma = 0.0
        for benef, pct in reglas.items():
            if not isinstance(benef, str) or not benef.strip():
                raise ValueError(f"'{dueno}': beneficiario inválido.")
            if not isinstance(pct, (int, float)) or isinstance(pct, bool):
                raise ValueError(f"'{dueno}' → '{benef}': el porcentaje debe ser un número.")
            if pct < 0 or pct > 100:
                raise ValueError(f"'{dueno}' → '{benef}': el porcentaje debe estar entre 0 y 100.")
            suma += pct
        if abs(suma - 100.0) > 0.01:
            raise ValueError(f"'{dueno}': los porcentajes deben sumar 100 (suman {suma:g}).")
