"""Lectura + cálculo puro de la economía de una edición de taller — mirror de
`commands/economia.py` (ahí vive la mutación real, `_regenerar_pedidos_taller`;
acá lo que necesita para resolver el valor efectivo, más lo que necesita
`routes/talleres.py` para mostrarle al admin un preview antes de guardar).
"""


def _revenue_inscriptos(conn, edicion_id: int) -> int:
    """Suma `modalidad_monto` de los inscriptos NO en lista de espera de una
    edición — lo que la gente ya anotada va a pagar en total. Fuente única
    del "% del total de los inscriptos" (pedido explícito del dueño: "si se
    anotan 6 vamos al 50%"), NUNCA un número tipeado a mano. Mismo filtro
    `en_lista_espera = FALSE` que decide si `cupos_confirmados` cuenta a
    alguien (routes/talleres.py::crear_inscripcion) — alguien en lista de
    espera todavía no es un inscripto real."""
    row = conn.execute(
        "SELECT COALESCE(SUM(modalidad_monto), 0) AS total FROM taller_inscripciones "
        "WHERE edicion_id = %s AND en_lista_espera = FALSE",
        (edicion_id,),
    ).fetchone()
    return row["total"]


def _valor_efectivo(tipo: str, valor: int, pct: int, revenue: int) -> int:
    """Resuelve el valor efectivo de Estudio/equipos según `tipo`: 'fijo' =
    el monto tipeado tal cual (comportamiento de siempre); 'porcentaje' = ese
    % sobre `revenue` (redondeado al peso). Pura — sin `conn`, reusada por
    `_regenerar_pedidos_taller` (el valor que efectivamente se cobra) y por
    `routes/talleres.py` (el preview que ve el admin antes de guardar, mismo
    cálculo — el front nunca lo recalcula)."""
    if tipo == "porcentaje":
        return round(revenue * pct / 100)
    return valor
