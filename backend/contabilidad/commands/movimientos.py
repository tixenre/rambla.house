"""Escritura del libro de movimientos (#809) — única puerta de mutación.

Cada fila mueve plata entre cuentas (o desde/hacia afuera). El **tipo** define qué
cuentas se usan:

| tipo          | origen | destino | categoría | qué es                                   |
|---------------|--------|---------|-----------|------------------------------------------|
| gasto         | ✓      | —       | ✓         | sale plata de una caja (con rubro)       |
| transferencia | ✓      | ✓       | —         | mueve plata entre dos cajas (cuadra)     |
| retiro        | ✓      | —       | —         | un socio saca su plata                   |
| aporte        | —      | ✓       | —         | un socio mete plata                      |
| ajuste        | ✓ o —  | ✓ o —   | —         | conciliación manual (con nota)           |

Un **cambio de divisa** (comprar/vender USD con ARS) NO es un tipo nuevo: son dos
`ajuste` atados por `movimiento_par_id`, uno por cuenta — ver `crear_cambio_divisa`
(única puerta; `transferencia` no sirve porque exige la misma moneda en ambos lados).

Los ingresos por alquiler NO viven acá: derivan de `alquiler_pagos` (Fase 1). El
saldo de cada cuenta se deriva de estos movimientos + esos cobros
(`queries/saldos.py`).

`validar_estructura_movimiento` es pura (testeable sin DB). El resto toca la
conexión. La plata nunca se borra: `anular_movimiento` hace soft-delete con motivo.
Lectura → `queries/movimientos.py`.

**TIPO de cuenta vs TIPO de movimiento (resuelto 2026-07-02, confirmado con el dueño):** la
tabla de arriba dice contra qué CANTIDAD de cuentas es válido cada tipo; esto agrega qué TIPO
de cuenta (`caja`/`banco`/`fondo` vs `socio`, cuenta corriente) puede tocar cada uno. Un socio
humano (Pablo/Tincho) tiene su plata en un banco propio, fuera del sistema — su cuenta acá es
**puro balance de deuda**, nunca plata real:

- **`retiro`/`aporte` están BLOQUEADOS contra una cuenta `socio`** (`_validar_cuentas_y_categoria`):
  representan plata física entrando/saliendo de una caja, y una cuenta corriente no tiene "caja"
  que mover — no tienen sentido de negocio ahí.
- **`transferencia`/`ajuste` siguen permitidos sin restricción**: `transferencia` DEBE poder tocar
  una cuenta `socio` (así funciona `commands/rendicion.py::saldar`, que arma transferencias
  Caja↔Fondo Rental); un `ajuste` contra una cuenta `socio` puede ser una corrección legítima de
  arranque de cuenta corriente.
- **`gasto` está PERMITIDO a propósito contra una cuenta `socio`** (como origen — nunca tuvo
  destino): es el caso "el socio pagó un gasto de Rental con su propia plata". Ni
  `gastos_por_categoria` ni `ganancia_neta` (`queries/pyl.py`) filtran por tipo de cuenta origen
  — solo por moneda — así que un `gasto` con origen una cuenta de socio **cuenta en el P&L
  categorizado** y a la vez **baja la deuda del socio** (`egresos` resta en la fórmula de cuenta
  corriente de `queries/saldos.py`: Rental ahora le debe eso). Un solo movimiento cubre el caso
  completo, sin código extra más allá de dejarlo pasar la validación.

Fijado por `test_retiro_aporte_bloqueados_contra_cuenta_socio` (bloqueo) y
`test_gasto_contra_cuenta_socio_cuenta_en_pyl_y_baja_deuda` (permiso + efecto doble).
"""

from contabilidad.constants import METODOS_MOVIMIENTO, SOCIOS_HUMANOS, TIPOS_MOVIMIENTO
from contabilidad.queries.movimientos import listar_movimientos, obtener_movimiento

# Campos que se pueden editar de un movimiento ya creado (el tipo no se cambia:
# cambiar de gasto a transferencia es otro movimiento, se anula y se rehace).
_CAMPOS_EDITABLES = ("monto", "cuenta_origen_id", "cuenta_destino_id", "categoria_id",
                     "metodo", "fecha", "nota", "beneficiario")


def validar_estructura_movimiento(tipo, monto, origen, destino, categoria_id) -> None:
    """Valida la coherencia tipo↔cuentas↔categoría de un movimiento. PURA.
    No chequea existencia en DB (eso lo hace `crear_movimiento`)."""
    if tipo not in TIPOS_MOVIMIENTO:
        raise ValueError(f"Tipo de movimiento inválido (debe ser uno de {', '.join(TIPOS_MOVIMIENTO)}).")
    if not isinstance(monto, int) or isinstance(monto, bool) or monto <= 0:
        raise ValueError("El monto debe ser un entero positivo (pesos, sin centavos).")
    if origen and destino and origen == destino:
        raise ValueError("El origen y el destino no pueden ser la misma cuenta.")

    if tipo == "gasto":
        if not origen:
            raise ValueError("Un gasto necesita la caja de la que sale la plata.")
        if destino:
            raise ValueError("Un gasto no tiene cuenta destino.")
        if not categoria_id:
            raise ValueError("Un gasto necesita una categoría.")
    elif tipo == "transferencia":
        if not (origen and destino):
            raise ValueError("Una transferencia necesita cuenta de origen y de destino.")
    elif tipo == "retiro":
        if not origen or destino:
            raise ValueError("Un retiro sale de una caja (origen), sin destino.")
    elif tipo == "aporte":
        if not destino or origen:
            raise ValueError("Un aporte entra a una caja (destino), sin origen.")
    elif tipo == "ajuste":
        if not (origen or destino):
            raise ValueError("Un ajuste necesita al menos una cuenta (origen o destino).")

    if tipo != "gasto" and categoria_id:
        raise ValueError("Solo los gastos llevan categoría.")


def _validar_metodo(metodo):
    if metodo and metodo not in METODOS_MOVIMIENTO:
        raise ValueError(f"Método inválido (debe ser uno de {', '.join(METODOS_MOVIMIENTO)}).")


def _cuentas_validas(conn) -> set[int]:
    rows = conn.execute("SELECT id FROM cuentas WHERE activa = TRUE").fetchall()
    return {r["id"] for r in rows}


def _validar_cuentas_y_categoria(conn, tipo, cuenta_origen_id, cuenta_destino_id, categoria_id) -> None:
    """Existencia+actividad de las cuentas, misma moneda si hay origen y destino,
    categoría existente+activa, y retiro/aporte bloqueados contra una cuenta de socio
    (ver docstring del módulo). Toca DB (a diferencia de `validar_estructura_movimiento`,
    que es pura). La usan `crear_movimiento` Y `editar_movimiento` — antes solo la
    tenía crear, así que editar podía dejar un movimiento apuntando a una cuenta
    inactiva/inexistente o mezclando monedas (auditoría 2026-07-02)."""
    validas = _cuentas_validas(conn)
    for cid in (cuenta_origen_id, cuenta_destino_id):
        if cid and cid not in validas:
            raise ValueError("La cuenta indicada no existe o está inactiva.")
    ids = [cid for cid in (cuenta_origen_id, cuenta_destino_id) if cid]
    info_por_id = {}
    if ids:
        ph = ", ".join("%s" for _ in ids)
        rows = conn.execute(
            f"SELECT id, moneda, socio FROM cuentas WHERE id IN ({ph})", tuple(ids)
        ).fetchall()
        info_por_id = {r["id"]: r for r in rows}
    # Una transferencia/ajuste entre dos cuentas debe ser de la misma moneda
    # (no hay conversión automática; los saldos no se mezclan).
    if cuenta_origen_id and cuenta_destino_id:
        if info_por_id[cuenta_origen_id]["moneda"] != info_por_id[cuenta_destino_id]["moneda"]:
            raise ValueError("No se puede transferir entre cuentas de distinta moneda.")
    if tipo in ("retiro", "aporte"):
        for cid in (cuenta_origen_id, cuenta_destino_id):
            if cid and info_por_id[cid]["socio"] in SOCIOS_HUMANOS:
                raise ValueError(
                    f"Un {tipo} no puede tocar la cuenta corriente de un socio (no representa "
                    "plata real en una caja) — usá gasto, transferencia o ajuste."
                )
    if categoria_id:
        ok = conn.execute(
            "SELECT 1 FROM gasto_categorias WHERE id = %s AND activa = TRUE", (categoria_id,)
        ).fetchone()
        if not ok:
            raise ValueError("La categoría indicada no existe o está inactiva.")


def _mes_de_fecha(fecha) -> str:
    if not fecha:
        from services.fechas import mes_actual_ar
        return mes_actual_ar()
    return str(fecha)[:7]


# Namespace del advisory lock para serializar cerrar_mes/reabrir_mes contra
# crear/editar/anular movimiento (y actualizar_comprobante) del mismo mes
# contable. Arbitrario y privado de este flujo — mismo patrón que
# _ADVISORY_NS_PEDIDO (services/alquileres/commands/creacion.py, 5390412) y
# _ADVISORY_NS_ESTUDIO (services/estudio/constants.py, 5390413); siguiente número libre.
_ADVISORY_NS_CONTAB_MES = 5390420


def _lock_mes(conn, mes: str) -> None:
    """xact-scoped (se libera solo al commit/rollback de `conn`): sin esto, un
    `cerrar_mes` puede leer los movimientos de un mes en T0 y commitear su foto
    DESPUÉS de que otro request haya insertado un movimiento con fecha de ese
    mismo mes (que pasó `_exigir_mes_abierto` porque el cierre todavía no había
    commiteado) — el mes queda "cerrado" con una foto que no incluye ese
    movimiento, que además ya no se puede tocar (auditoría 2026-07-02)."""
    try:
        anio, mo = mes.split("-")
        key = int(anio) * 100 + int(mo)   # 'YYYY-MM' → YYYYMM, key natural
    except (ValueError, AttributeError):
        key = 0
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_ADVISORY_NS_CONTAB_MES, key))


def _exigir_mes_abierto(conn, fecha) -> None:
    """Traba tocar un movimiento cuyo mes contable está cerrado (#809 Fase 6)."""
    from contabilidad.queries.cierres import mes_cerrado

    mes = _mes_de_fecha(fecha)
    _lock_mes(conn, mes)
    if mes_cerrado(conn, mes):
        raise ValueError(
            f"El mes {mes} está cerrado. Reabrilo desde Rendición para tocar movimientos de esa fecha."
        )


def _es_reparto_entre_partes(conn, cuenta_origen_id, cuenta_destino_id) -> bool:
    """¿Esta transferencia mueve plata ENTRE DOS PARTES de la rendición (Pablo/
    Tincho/Rental/Estudio)? Las dos puntas tienen que resolver a una parte por su
    columna `socio` (o ser el Fondo Rental), y ser DISTINTAS.

    ⚠️ **A propósito es MÁS ANGOSTA que `queries/posiciones.py::clasificar_flujo`
    rama 1, y NO hay que "alinearlas".** El clasificador hace caer una caja
    genérica (Efectivo, Banco — sin `socio`) a "Rental"; acá NO, porque los dos
    consumidores tienen requisitos opuestos:

    - `clasificar_flujo` alimenta la posición ACUMULADA, que suma y resta por
      parte: contar `Efectivo → Caja Pablo` como "Rental → Pablo" es correcto y
      necesario (si no, ese reparto se perdería).
    - Esta marca alimenta `queries/rendicion.py::ya_transferido`, que mapea cada
      punta con `parte_de_cuenta` **sin fallback** y saltea la que da `None`.
      Marcar `Efectivo → Caja Pablo` le SUMARÍA a Pablo sin restarle a Rental →
      la rendición del mes dejaría de cerrar en cero.

    El costo aceptado de esa asimetría: un reparto pagado desde Efectivo/Banco no
    aparece en la lista mensual "Movimientos de rendición" (sí está bien contado
    en la vista acumulada, que es la que decide). Cerrarlo de verdad requiere que
    `ya_transferido` sepa resolver una caja genérica, no ensanchar esto.

    Candado: `test_reparto_desde_caja_generica_no_se_marca` (Postgres real)."""
    if not (cuenta_origen_id and cuenta_destino_id):
        return False
    from contabilidad.queries.posiciones import parte_de_cuenta

    rows = conn.execute(
        "SELECT id, socio, tipo, nombre FROM cuentas WHERE id IN (%s, %s)",
        (cuenta_origen_id, cuenta_destino_id),
    ).fetchall()
    info = {r["id"]: r for r in rows}
    if cuenta_origen_id not in info or cuenta_destino_id not in info:
        return False
    po = parte_de_cuenta(info[cuenta_origen_id]["socio"], info[cuenta_origen_id]["tipo"],
                         info[cuenta_origen_id]["nombre"])
    pd = parte_de_cuenta(info[cuenta_destino_id]["socio"], info[cuenta_destino_id]["tipo"],
                         info[cuenta_destino_id]["nombre"])
    return bool(po and pd and po != pd)


def crear_movimiento(conn, *, tipo, monto, cuenta_origen_id=None, cuenta_destino_id=None,
                     categoria_id=None, metodo=None, fecha=None, nota=None, beneficiario=None,
                     por=None, es_rendicion=False, rendicion_mes=None, cotizacion=None,
                     movimiento_par_id=None) -> dict:
    """Crea un movimiento (valida estructura + existencia de cuentas/categoría).
    `fecha` None → hoy. `es_rendicion`/`rendicion_mes` marcan un saldado de
    rendición entre socios (lo usa `commands/rendicion.py::saldar`, no la UI
    general). `cotizacion`/`movimiento_par_id` los usa `crear_cambio_divisa`
    (no se exponen en el form general de movimientos). Devuelve el movimiento
    con nombres resueltos.

    Si el caller NO marcó `es_rendicion` explícitamente, se AUTO-DETECTA: una
    `transferencia` (u otro tipo con las dos cuentas puestas) entre dos partes
    distintas ES un reparto por definición — la cuenta corriente de un socio no
    tiene otro motivo para que le muevan plata. Sin esto, un "Repartimos" cargado
    desde el form general (o el viejo "Me pagó / Le cargué" de la ficha del
    socio) quedaba invisible para `queries/rendicion.py::ya_transferido` (que
    filtra por `es_rendicion`), aunque la posición ACUMULADA sí lo contara bien
    (`clasificar_flujo` no mira esa marca) — dos vistas de acuerdo en el número
    pero en desacuerdo en qué movimientos lo explican."""
    monto = int(monto or 0)
    validar_estructura_movimiento(tipo, monto, cuenta_origen_id, cuenta_destino_id, categoria_id)
    _validar_metodo(metodo)
    _exigir_mes_abierto(conn, fecha)
    _validar_cuentas_y_categoria(conn, tipo, cuenta_origen_id, cuenta_destino_id, categoria_id)

    if not es_rendicion and _es_reparto_entre_partes(conn, cuenta_origen_id, cuenta_destino_id):
        es_rendicion = True
        rendicion_mes = rendicion_mes or _mes_de_fecha(fecha)

    beneficiario = (beneficiario or "").strip() or None
    cur = conn.execute(
        """INSERT INTO movimientos
               (tipo, monto, cuenta_origen_id, cuenta_destino_id, categoria_id,
                metodo, fecha, nota, beneficiario, es_rendicion, rendicion_mes,
                cotizacion, movimiento_par_id, created_by, updated_by)
           VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s::date, CURRENT_DATE), %s, %s, %s, %s,
                   %s, %s, %s, %s)
           RETURNING id""",
        (tipo, monto, cuenta_origen_id, cuenta_destino_id, categoria_id,
         metodo, fecha, nota, beneficiario, bool(es_rendicion), rendicion_mes,
         cotizacion, movimiento_par_id, por, por),
    )
    new_id = cur.fetchone()[0]
    movs = listar_movimientos(conn, incluir_anulados=True)
    for m in movs:
        if m["id"] == new_id:
            return m
    return obtener_movimiento(conn, new_id)


def _validar_montos_cambio_divisa(monto_origen, monto_destino, cotizacion) -> None:
    for m in (monto_origen, monto_destino):
        if m is not None and (not isinstance(m, int) or isinstance(m, bool) or m <= 0):
            raise ValueError("Los montos deben ser enteros positivos (sin centavos).")
    if cotizacion is not None and float(cotizacion) <= 0:
        raise ValueError("La cotización debe ser mayor a cero.")


def derivar_cambio_divisa(moneda_origen, moneda_destino, monto_origen=None,
                          monto_destino=None, cotizacion=None) -> tuple[int, int, float]:
    """PURA — la aritmética de un cambio de divisa, sin tocar DB (testeable
    aparte, igual que `validar_estructura_movimiento`). Exige distinta moneda a
    cada lado y que una de las dos sea ARS (hoy `MONEDAS` solo tiene ARS/USD).
    La `cotizacion` es siempre "pesos por dólar" — no depende de cuál lado es
    origen/destino, así que sirve igual para comprar o vender dólares. Acepta
    2 de {monto_origen, monto_destino, cotizacion}; deriva el que falte.
    Devuelve `(monto_origen, monto_destino, cotizacion)` ya enteros/redondeados."""
    _validar_montos_cambio_divisa(monto_origen, monto_destino, cotizacion)
    if moneda_origen == moneda_destino:
        raise ValueError(
            "Un cambio de divisa necesita cuentas de distinta moneda "
            "(para la misma moneda usá una transferencia)."
        )
    if "ARS" not in (moneda_origen, moneda_destino):
        raise ValueError("Un cambio de divisa necesita que una de las dos cuentas sea en pesos (ARS).")

    lado_ars = "origen" if moneda_origen == "ARS" else "destino"
    monto_ars = monto_origen if lado_ars == "origen" else monto_destino
    monto_divisa = monto_destino if lado_ars == "origen" else monto_origen
    if cotizacion is not None:
        cotizacion = float(cotizacion)

    provistos = sum(x is not None for x in (monto_ars, monto_divisa, cotizacion))
    if provistos < 2:
        raise ValueError(
            "Necesito al menos dos de estos tres datos: el monto en pesos, el monto en la "
            "otra moneda, o la cotización."
        )
    if monto_ars is None:
        monto_ars = round(monto_divisa * cotizacion)
    elif monto_divisa is None:
        monto_divisa = round(monto_ars / cotizacion)
    if cotizacion is None:
        cotizacion = round(monto_ars / monto_divisa, 4)
    cotizacion = round(float(cotizacion), 4)

    monto_origen = monto_ars if lado_ars == "origen" else monto_divisa
    monto_destino = monto_divisa if lado_ars == "origen" else monto_ars
    return int(monto_origen), int(monto_destino), cotizacion


def crear_cambio_divisa(conn, *, cuenta_origen_id, cuenta_destino_id, monto_origen=None,
                        monto_destino=None, cotizacion=None, fecha=None, nota=None,
                        por=None) -> dict:
    """Compra/venta de divisa: registra DOS `ajuste` atados (uno por cuenta), la
    única forma soportada de mover plata entre cajas de distinta moneda —
    `transferencia` exige la misma moneda en origen y destino (ver docstring del
    módulo), así que una conversión real necesita su propio flujo explícito
    (DECISIONES.md 2026-06-07). No es un tipo de movimiento nuevo: reusa `ajuste`
    dos veces, cada pata pasa por `crear_movimiento` (misma validación de
    siempre) y quedan linkeadas por `movimiento_par_id`. La aritmética
    (qué monto/cotización se deriva) vive en `derivar_cambio_divisa` (pura)."""
    if not cuenta_origen_id or not cuenta_destino_id:
        raise ValueError("Un cambio de divisa necesita cuenta de origen y de destino.")
    if cuenta_origen_id == cuenta_destino_id:
        raise ValueError("El origen y el destino no pueden ser la misma cuenta.")

    validas = _cuentas_validas(conn)
    if cuenta_origen_id not in validas or cuenta_destino_id not in validas:
        raise ValueError("La cuenta indicada no existe o está inactiva.")
    rows = conn.execute(
        "SELECT id, moneda FROM cuentas WHERE id IN (%s, %s)",
        (cuenta_origen_id, cuenta_destino_id),
    ).fetchall()
    moneda_por_id = {r["id"]: r["moneda"] for r in rows}

    monto_origen, monto_destino, cotizacion = derivar_cambio_divisa(
        moneda_por_id[cuenta_origen_id], moneda_por_id[cuenta_destino_id],
        monto_origen=monto_origen, monto_destino=monto_destino, cotizacion=cotizacion,
    )

    nota = (nota or "").strip() or None
    mov_origen = crear_movimiento(
        conn, tipo="ajuste", monto=monto_origen, cuenta_origen_id=cuenta_origen_id,
        fecha=fecha, nota=nota, por=por, cotizacion=cotizacion,
    )
    mov_destino = crear_movimiento(
        conn, tipo="ajuste", monto=monto_destino, cuenta_destino_id=cuenta_destino_id,
        fecha=fecha, nota=nota, por=por, cotizacion=cotizacion,
        movimiento_par_id=mov_origen["id"],
    )
    conn.execute(
        "UPDATE movimientos SET movimiento_par_id = %s WHERE id = %s",
        (mov_destino["id"], mov_origen["id"]),
    )
    return {
        "origen": obtener_movimiento(conn, mov_origen["id"]),
        "destino": mov_destino,
        "cotizacion": cotizacion,
    }


def editar_movimiento(conn, mov_id: int, *, campos: dict, por=None) -> dict:
    """Edita un movimiento NO anulado. Revalida la estructura con el resultado.
    El `tipo` no se cambia."""
    actual = obtener_movimiento(conn, mov_id)
    if not actual:
        raise ValueError("El movimiento no existe.")
    if actual["anulado"]:
        raise ValueError("No se puede editar un movimiento anulado.")
    _exigir_mes_abierto(conn, actual["fecha"])
    if "fecha" in campos:
        _exigir_mes_abierto(conn, campos["fecha"])

    propuesta = dict(actual)
    for k in _CAMPOS_EDITABLES:
        if k in campos:
            propuesta[k] = campos[k]
    monto = int(propuesta.get("monto") or 0)
    validar_estructura_movimiento(
        actual["tipo"], monto, propuesta.get("cuenta_origen_id"),
        propuesta.get("cuenta_destino_id"), propuesta.get("categoria_id"),
    )
    _validar_metodo(propuesta.get("metodo"))
    _validar_cuentas_y_categoria(
        conn, actual["tipo"], propuesta.get("cuenta_origen_id"),
        propuesta.get("cuenta_destino_id"), propuesta.get("categoria_id"),
    )

    sets, params = [], []
    for k in _CAMPOS_EDITABLES:
        if k not in campos:
            continue
        if k == "fecha":
            sets.append("fecha = %s::date")
        elif k == "monto":
            sets.append("monto = %s")
            campos[k] = int(campos[k] or 0)
        elif k == "beneficiario":
            sets.append("beneficiario = %s")
            campos[k] = (campos[k] or "").strip() or None  # mismo saneo que al crear
        else:
            sets.append(f"{k} = %s")
        params.append(campos[k])
    if not sets:
        return actual
    sets.append("updated_by = %s")
    params.append(por)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.append(mov_id)
    conn.execute(f"UPDATE movimientos SET {', '.join(sets)} WHERE id = %s", tuple(params))
    return obtener_movimiento(conn, mov_id)


def actualizar_comprobante(conn, mov_id: int, *, key: str, por=None) -> dict:
    """Persiste la key del comprobante ya subido a storage (el upload en sí es
    infra HTTP, se queda en el route). Pasa por el mismo candado que
    crear/editar/anular — antes el route hacía un UPDATE directo, saltándose
    `_exigir_mes_abierto` y el chequeo de `anulado` (auditoría 2026-07-02)."""
    actual = obtener_movimiento(conn, mov_id)
    if not actual:
        raise ValueError("El movimiento no existe.")
    if actual["anulado"]:
        raise ValueError("No se puede adjuntar un comprobante a un movimiento anulado.")
    _exigir_mes_abierto(conn, actual["fecha"])
    conn.execute(
        "UPDATE movimientos SET comprobante_url = NULL, comprobante_key = %s, "
        "updated_by = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        (key, por, mov_id),
    )
    return obtener_movimiento(conn, mov_id)


def anular_movimiento(conn, mov_id: int, *, motivo, por=None) -> dict:
    """Soft-delete: marca el movimiento como anulado (la plata nunca se borra).
    Exige un motivo. Un movimiento anulado deja de contar para los saldos."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Para anular un movimiento hay que indicar un motivo.")
    actual = obtener_movimiento(conn, mov_id)
    if not actual:
        raise ValueError("El movimiento no existe.")
    if actual["anulado"]:
        return actual
    _exigir_mes_abierto(conn, actual["fecha"])
    conn.execute(
        """UPDATE movimientos
           SET anulado = TRUE, anulado_por = %s, anulado_at = CURRENT_TIMESTAMP, anulado_motivo = %s
           WHERE id = %s""",
        (por, motivo, mov_id),
    )
    return obtener_movimiento(conn, mov_id)
