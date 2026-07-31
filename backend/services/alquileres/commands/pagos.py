"""Registro de pagos — Fase 2 del split CQRS-lite de `routes/alquileres/` (#1312).

Move-verbatim desde `routes/alquileres/pagos.py`: el ledger `alquiler_pagos` es
la fuente ÚNICA de "pagado"; acá vive la validación de destinatario/método, el
recálculo del monto pagado y las 3 mutaciones (agregar / agregar combinado /
anular). `routes/alquileres/pagos.py` queda como transporte HTTP fino y delega.

`PagoCreate` se mueve acá (no se queda en routes, a diferencia de
`PagoCombinadoCreate`/`AnularPagoBody`): `_agregar_pago_combinado` la
INSTANCIA como parte de su algoritmo de reparto (no solo la usa como type hint
del wire) — mismo criterio que `SueltoItem` en `services/estudio/commands/reserva.py`.
"""
import logging
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from database import now_ar
from services.alquileres.commands.pedido import _maybe_finalizar
from services.alquileres.queries.detalle import _get_alquiler_detail

logger = logging.getLogger(__name__)

# Pagos: a quién se cobró (destinatario) y cómo (método). Fuente única de los
# valores admitidos — la usan la validación del endpoint y la vista de logs.
# Cualquiera de los tres puede cobrar; el default es Rental (en transferencia).
# Cada destinatario mapea a una caja en Contabilidad (Pablo/Tincho → su caja de
# socio; Rental → Fondo Rental), donde la plata cobrada se atribuye sola.
from contabilidad.constants import COBRADORES as DESTINATARIOS_PAGO  # fuente única
METODOS_PAGO = ("transferencia", "efectivo")
DESTINATARIO_PAGO_DEFAULT = "Rental"
METODO_PAGO_DEFAULT = "transferencia"


class PagoCreate(BaseModel):
    monto:        int = Field(gt=0, le=2_000_000_000)
    concepto:     Optional[str] = Field(default=None, max_length=500)
    fecha:        Optional[str] = Field(default=None, max_length=10)   # YYYY-MM-DD; si no viene usa hoy
    destinatario: Optional[str] = Field(default=None, max_length=20)   # Tincho|Pablo (default Tincho)
    metodo:       Optional[str] = Field(default=None, max_length=20)   # transferencia|efectivo (default transferencia)


def _resolver_destino_metodo(
    destinatario: Optional[str], metodo: Optional[str]
) -> tuple[str, str]:
    """Aplica defaults (Tincho/transferencia) y valida contra los valores admitidos.

    Pieza pura (testeable sin DB): la usa `agregar_pago`. Lanza HTTP 400 si el
    valor explícito no está en la lista permitida.
    """
    d = destinatario or DESTINATARIO_PAGO_DEFAULT
    m = metodo or METODO_PAGO_DEFAULT
    if d not in DESTINATARIOS_PAGO:
        raise HTTPException(400, f"Destinatario inválido. Usar: {', '.join(DESTINATARIOS_PAGO)}")
    if m not in METODOS_PAGO:
        raise HTTPException(400, f"Método inválido. Usar: {', '.join(METODOS_PAGO)}")
    return d, m


def _recalcular_monto_pagado(conn, pedido_id: int):
    """Recalcula monto_pagado atómicamente desde alquiler_pagos.

    Usa UPDATE con subquery (en lugar de SELECT-luego-UPDATE) para evitar
    race conditions cuando dos pagos llegan en paralelo.

    No hace commit — el caller debe commitear inmediatamente después para que
    el UPDATE no quede huérfano si falla algo posterior en la misma transacción.

    `AND NOT anulado`: un pago anulado (soft-delete, #1184) no cuenta para lo
    pagado — mismo criterio que `movimientos` con sus movimientos anulados.
    """
    conn.execute(
        """
        UPDATE alquileres
           SET monto_pagado = (
               SELECT COALESCE(SUM(monto), 0)
                 FROM alquiler_pagos
                WHERE pedido_id = %s AND NOT anulado
           )
         WHERE id = %s
        """,
        (pedido_id, pedido_id),
    )


def _agregar_pago(conn, id: int, data: PagoCreate, admin_email: str) -> dict:
    """Lógica de `agregar_pago`, sin FastAPI/decorators — testable directo
    (sin necesitar un `Request` real) y reusable si algún día hace falta desde
    otro lado que no sea el endpoint HTTP.

    `FOR UPDATE`: lockea la fila del pedido para toda la transacción — sin
    esto, un `agregar_pago` y un `anular_pago` concurrentes sobre el MISMO
    pedido pueden pisarse un lost-update en `monto_pagado` (el `UPDATE ...
    SET monto_pagado = (subquery sobre alquiler_pagos)` de
    `_recalcular_monto_pagado` no re-evalúa esa subquery si el segundo
    escritor ya la había planeado antes de que el primero commiteara). Con el
    lock, el segundo espera al primero — su subquery ve el estado ya
    commiteado de `alquiler_pagos`. El caller (el endpoint) hace commit.
    """
    destinatario, metodo = _resolver_destino_metodo(data.destinatario, data.metodo)
    p = conn.execute("SELECT estado FROM alquileres WHERE id=%s FOR UPDATE", (id,)).fetchone()
    if not p:
        raise HTTPException(404, "Pedido no encontrado")
    if p["estado"] in ("cancelado", "borrador"):
        raise HTTPException(400, "No se pueden agregar pagos a un pedido cancelado o en borrador")

    fecha = data.fecha or now_ar().date().isoformat()
    conn.execute("""
        INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (id, data.monto, data.concepto, destinatario, metodo, fecha, admin_email))

    _recalcular_monto_pagado(conn, id)
    _maybe_finalizar(conn, id)
    return _get_alquiler_detail(conn, id)


def _agregar_pago_combinado(conn, id: int, data, admin_email: str) -> dict:
    """Reparte `data.monto` entre `id` (el pedido principal) y sus turnos del
    Estudio vinculados (#1308, "un pago, reparte solo"): primero satura el
    resta del PRINCIPAL, después cada turno por `fecha_desde` ascendente (se
    paga primero lo que vence antes — mismo orden que ya usa
    `_turnos_vinculados` para listarlos en pantalla). Un turno `cancelado`
    queda EXCLUIDO del reparto (nunca participa, nunca bloquea el resto —
    sin este filtro, un solo turno cancelado tumbaría el pago combinado
    completo con el 400 que `_agregar_pago` ya lanza para pedidos
    cancelados). El sobrante, si lo hay tras recorrer todas las filas, se
    acredita SIEMPRE en el PRINCIPAL (nunca en el último turno tocado) — es
    la pantalla donde el admin apretó "Registrar pago" y donde lo espera ver
    (mismo criterio "no esconder el excedente" que MEMORIA 2026-07-02).

    Cada parte del reparto pasa por el `_agregar_pago` YA EXISTENTE, sin
    modificar — nunca se inventa una tabla/concepto de "pago compartido"; el
    `pedido_id` de cada fila de `alquiler_pagos` sigue siendo el real. Todo
    esto es una transacción (el caller hace commit/rollback): funciona sobre
    CUALQUIER pedido — sin turnos vinculados, `turnos` da vacío y el
    comportamiento es idéntico a `_agregar_pago` de siempre (superset
    seguro, no un camino paralelo).

    `data` es un `PagoCombinadoCreate` (routes/alquileres/pagos.py, el
    contrato HTTP) — se lee por atributo (duck typing), no se importa la
    clase acá para no crear un import de este paquete hacia `routes.*` que
    no hace falta (nunca se instancia una acá, solo se leen sus campos)."""
    p = conn.execute(
        "SELECT id, monto_total, monto_pagado, estado FROM alquileres WHERE id=%s FOR UPDATE",
        (id,),
    ).fetchone()
    if not p:
        raise HTTPException(404, "Pedido no encontrado")
    if p["estado"] in ("cancelado", "borrador"):
        raise HTTPException(400, "No se pueden agregar pagos a un pedido cancelado o en borrador")

    turnos = conn.execute(
        "SELECT id, monto_total, monto_pagado FROM alquileres "
        "WHERE pedido_principal_id = %s AND estado <> 'cancelado' "
        "ORDER BY fecha_desde, id",
        (id,),
    ).fetchall()

    filas = [p, *turnos]
    restante = data.monto
    reparto: list[dict] = []
    for fila in filas:
        resta_fila = max(0, (fila["monto_total"] or 0) - (fila["monto_pagado"] or 0))
        aporte = min(restante, resta_fila)
        if aporte <= 0:
            continue
        _agregar_pago(
            conn, fila["id"],
            PagoCreate(
                monto=aporte, concepto=data.concepto, fecha=data.fecha,
                destinatario=data.destinatario, metodo=data.metodo,
            ),
            admin_email,
        )
        reparto.append({"pedido_id": fila["id"], "monto": aporte})
        restante -= aporte

    if restante > 0:
        concepto_excedente = f"{data.concepto} (excedente)" if data.concepto else "(excedente)"
        _agregar_pago(
            conn, id,
            PagoCreate(
                monto=restante, concepto=concepto_excedente, fecha=data.fecha,
                destinatario=data.destinatario, metodo=data.metodo,
            ),
            admin_email,
        )
        reparto.append({"pedido_id": id, "monto": restante, "excedente": True})

    resp = _get_alquiler_detail(conn, id)
    resp["reparto"] = reparto
    return resp


def _anular_pago(conn, id: int, pago_id: int, motivo: str, admin_email: str) -> dict:
    """Lógica de `anular_pago`, sin FastAPI/decorators — ver `_agregar_pago`.

    `FOR UPDATE`: mismo motivo que `_agregar_pago` — serializa contra
    cualquier otro escritor de `monto_pagado` del mismo pedido (agregar/anular
    concurrentes). El caller (el endpoint) hace commit/rollback.
    """
    if not conn.execute("SELECT id FROM alquileres WHERE id=%s FOR UPDATE", (id,)).fetchone():
        raise HTTPException(404, "Pedido no encontrado")
    actualizado = conn.execute(
        """UPDATE alquiler_pagos
           SET anulado = TRUE, anulado_por = %s, anulado_at = CURRENT_TIMESTAMP,
               anulado_motivo = %s
           WHERE id = %s AND pedido_id = %s AND NOT anulado
           RETURNING id""",
        (admin_email, motivo, pago_id, id),
    ).fetchone()
    if not actualizado:
        raise HTTPException(404, "Pago no encontrado (o ya estaba anulado)")

    _recalcular_monto_pagado(conn, id)

    # Si se anuló el pago, puede que ya no esté finalizado → revertir si aplica
    p = conn.execute("SELECT estado, monto_total, monto_pagado FROM alquileres WHERE id=%s", (id,)).fetchone()
    if p and p["estado"] == "finalizado" and (p["monto_pagado"] or 0) < (p["monto_total"] or 0):
        conn.execute("UPDATE alquileres SET estado='devuelto' WHERE id=%s", (id,))

    return _get_alquiler_detail(conn, id)
