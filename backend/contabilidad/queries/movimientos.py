"""Lectura del libro de movimientos (#809). Nunca muta — ver `commands/movimientos.py`."""


def listar_movimientos(conn, *, tipo=None, cuenta_id=None, categoria_id=None,
                       desde=None, hasta=None, beneficiario=None,
                       incluir_anulados=False, limit=500) -> list[dict]:
    """Movimientos con nombres de cuenta/categoría resueltos, filtrables. Más
    nuevos primero. Por defecto excluye los anulados."""
    from database import row_to_dict

    sql = """
        SELECT m.id, m.tipo, m.monto, m.cuenta_origen_id, m.cuenta_destino_id,
               m.categoria_id, m.metodo, m.fecha, m.nota, m.beneficiario,
               m.comprobante_url, m.es_rendicion, m.rendicion_mes,
               m.anulado, m.anulado_motivo, m.created_by, m.created_at,
               m.cotizacion, m.movimiento_par_id,
               co.nombre AS cuenta_origen_nombre,
               cd.nombre AS cuenta_destino_nombre,
               COALESCE(co.moneda, cd.moneda) AS moneda,
               gc.nombre AS categoria_nombre
        FROM movimientos m
        LEFT JOIN cuentas co ON co.id = m.cuenta_origen_id
        LEFT JOIN cuentas cd ON cd.id = m.cuenta_destino_id
        LEFT JOIN gasto_categorias gc ON gc.id = m.categoria_id
        WHERE 1=1
    """
    params: list = []
    if not incluir_anulados:
        sql += " AND m.anulado = FALSE"
    if tipo:
        sql += " AND m.tipo = %s"
        params.append(tipo)
    if cuenta_id:
        sql += " AND (m.cuenta_origen_id = %s OR m.cuenta_destino_id = %s)"
        params.extend([cuenta_id, cuenta_id])
    if categoria_id:
        sql += " AND m.categoria_id = %s"
        params.append(categoria_id)
    if beneficiario:
        sql += " AND m.beneficiario = %s"
        params.append(beneficiario)
    if desde:
        sql += " AND m.fecha >= %s::date"
        params.append(desde)
    if hasta:
        sql += " AND m.fecha <= %s::date"
        params.append(hasta)
    sql += " ORDER BY m.fecha DESC, m.id DESC LIMIT %s"
    params.append(min(int(limit or 500), 2000))
    return [row_to_dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def obtener_movimiento(conn, mov_id: int) -> dict | None:
    from database import row_to_dict
    row = conn.execute(
        """SELECT id, tipo, monto, cuenta_origen_id, cuenta_destino_id, categoria_id,
                  metodo, fecha, nota, beneficiario, comprobante_url, comprobante_key, es_rendicion,
                  rendicion_mes, anulado, anulado_motivo, created_by, created_at,
                  cotizacion, movimiento_par_id
           FROM movimientos WHERE id = %s""",
        (mov_id,),
    ).fetchone()
    return row_to_dict(row) if row else None


def gastos_por_categoria(conn, desde=None, hasta=None, incluir_ajustado=False) -> list[dict]:
    """Σ de gastos en PESOS (no anulados) agrupados por categoría, en la ventana.
    Para el tablero / P&L (que es en ARS). Filtra por la moneda de la caja de
    origen: un gasto pagado desde una caja USD NO se suma al P&L en pesos (no se
    mezclan monedas). Más gastado primero.

    `incluir_ajustado=True` (Estadísticas, toggle de IPC) suma `monto_ajustado`:
    cada gasto deflactado por el mes en que se pagó (`services/ipc.py::IPC_FACTOR_CTE`,
    "pesos de hoy"), EN ORIGEN antes de sumar por categoría — no post-suma. Aditivo:
    los callers existentes (P&L/tablero) no lo piden y no cambian."""
    from database import row_to_dict
    if incluir_ajustado:
        from services.ipc import IPC_FACTOR_CTE

        sql = f"""
            WITH {IPC_FACTOR_CTE}
            SELECT gc.nombre AS categoria, COALESCE(SUM(m.monto), 0) AS monto,
                   COALESCE(SUM(m.monto * COALESCE(ipf.factor, 1)), 0) AS monto_ajustado
            FROM movimientos m
            JOIN gasto_categorias gc ON gc.id = m.categoria_id
            JOIN cuentas co ON co.id = m.cuenta_origen_id
            LEFT JOIN ipc_factor ipf ON ipf.mes = to_char(m.fecha, 'YYYY-MM')
            WHERE m.tipo = 'gasto' AND m.anulado = FALSE AND co.moneda = 'ARS'
        """
    else:
        sql = """
            SELECT gc.nombre AS categoria, COALESCE(SUM(m.monto), 0) AS monto
            FROM movimientos m
            JOIN gasto_categorias gc ON gc.id = m.categoria_id
            JOIN cuentas co ON co.id = m.cuenta_origen_id
            WHERE m.tipo = 'gasto' AND m.anulado = FALSE AND co.moneda = 'ARS'
        """
    params: list = []
    if desde:
        sql += " AND m.fecha >= %s::date"
        params.append(desde)
    if hasta:
        sql += " AND m.fecha <= %s::date"
        params.append(hasta)
    sql += " GROUP BY gc.nombre ORDER BY monto DESC"
    return [row_to_dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def cobros_mensuales(conn, desde=None, hasta=None, cobrador=None) -> list[dict]:
    """Cobros de pedidos (de `alquiler_pagos`) agregados por mes — una línea por
    mes con el total cobrado. Es la cara READ-ONLY de los cobros dentro de la vista
    unificada de movimientos: la plata entra, pero se carga desde el pedido (Pagos),
    no se edita acá. Mismo recorte que los saldos (clean start por fecha del alquiler
    `fecha_desde >= LIQUIDACION_INICIO`, destinatario asignado). Si `cobrador` se pasa,
    solo los de ese cobrador. Devuelve filas {mes:'YYYY-MM', monto, cantidad} más
    nuevas primero."""
    from database import row_to_dict
    from reportes.liquidacion import LIQUIDACION_INICIO

    sql = """
        SELECT to_char(ap.fecha, 'YYYY-MM') AS mes,
               COALESCE(SUM(ap.monto), 0) AS monto,
               COUNT(*) AS cantidad
        FROM alquiler_pagos ap
        JOIN alquileres al ON al.id = ap.pedido_id
        WHERE ap.destinatario IS NOT NULL AND NOT ap.anulado AND al.fecha_desde >= %s::date
    """
    params: list = [LIQUIDACION_INICIO]
    if cobrador:
        sql += " AND ap.destinatario = %s"
        params.append(cobrador)
    if desde:
        sql += " AND ap.fecha::date >= %s::date"
        params.append(desde)
    if hasta:
        sql += " AND ap.fecha::date <= %s::date"
        params.append(hasta)
    sql += " GROUP BY 1 ORDER BY 1 DESC"
    return [row_to_dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def beneficiarios_usados(conn) -> list[str]:
    """Beneficiarios ya usados (distintos, no anulados), para el autocompletado del
    formulario — así "Jimena" se elige en vez de reescribirse."""
    rows = conn.execute(
        """SELECT DISTINCT beneficiario FROM movimientos
           WHERE beneficiario IS NOT NULL AND beneficiario <> '' AND NOT anulado
           ORDER BY beneficiario"""
    ).fetchall()
    return [r["beneficiario"] for r in rows]
