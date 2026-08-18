"""Motor de disponibilidad del Estudio — talleres, slots y centinela.

Tests unitarios de las funciones de lectura que implementan la regla
"el sistema de reservas es independiente de la gobernanza":
  - _taller_bloqueante / _slot_bloqueante / _centinela_libre
  - _estudio_disponible (engine unificada)
  - verificar_sesiones_disponibles

Todos usan FakeConn — sin Postgres, sin fixtures de DB.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

pytestmark = pytest.mark.unit


def _en(dias: int) -> date:
    """Fecha relativa a HOY, no hardcodeada — evita que un test quede stale
    semanas después de escribirlo (bug real: `date(2026, 8, 15)` quedó en el
    pasado y `verificar_sesiones_disponibles` la empezó a saltear —ver
    docstring de esa función—, rompiendo `test_verificar_sesiones_primera_
    conflicto_lanza_409` sin que nadie tocara el código)."""
    return date.today() + timedelta(days=dias)


# ── Helpers de FakeConn ───────────────────────────────────────────────────────


class FakeRow(dict):
    """dict con interfaz .keys() compatible con las funciones del módulo."""
    def keys(self):
        return super().keys()


class FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeConn:
    """Conexión simulada con respuestas configurables por índice de llamada."""

    def __init__(self, responses: list):
        """responses: lista de resultados en orden de ejecución (cada uno puede
        ser None, un FakeRow o una lista de FakeRows)."""
        self._responses = list(responses)
        self._calls: list[tuple] = []
        self._idx = 0

    def execute(self, sql: str, params=()):
        self._calls.append((sql.strip(), params))
        resp = self._responses[self._idx] if self._idx < len(self._responses) else []
        self._idx += 1
        if resp is None:
            return FakeCursor([])
        if isinstance(resp, list):
            return FakeCursor(resp)
        return FakeCursor([resp])


# ── Fixtures comunes ──────────────────────────────────────────────────────────


def _estudio(buffer_horas=0):
    return {"equipo_id": 99, "buffer_horas": buffer_horas}


def _desde(year, month, day, hour):
    return datetime(year, month, day, hour, 0, 0)


def _hasta(year, month, day, hour):
    return datetime(year, month, day, hour, 0, 0)


# ── _taller_bloqueante ────────────────────────────────────────────────────────


def test_taller_bloqueante_solapa():
    from services.estudio.queries.disponibilidad import _taller_bloqueante
    # Sesión 10-14, franja 12-16 → solapa
    conn = FakeConn([[FakeRow(nombre="Taller X", hora_inicio_min=600, hora_fin_min=840)]])
    result = _taller_bloqueante(conn, _desde(2026, 8, 1, 12), _hasta(2026, 8, 1, 16))
    assert result == "Taller X"


def test_taller_bloqueante_no_solapa():
    from services.estudio.queries.disponibilidad import _taller_bloqueante
    # Sesión 10-14, franja 14-16 → no solapa (half-open: fin==inicio OK)
    conn = FakeConn([[FakeRow(nombre="Taller X", hora_inicio_min=600, hora_fin_min=840)]])
    result = _taller_bloqueante(conn, _desde(2026, 8, 1, 14), _hasta(2026, 8, 1, 16))
    assert result is None


def test_taller_bloqueante_no_solapa_antes():
    from services.estudio.queries.disponibilidad import _taller_bloqueante
    # Sesión 14-18, franja 10-14 → no solapa
    conn = FakeConn([[FakeRow(nombre="Taller Y", hora_inicio_min=840, hora_fin_min=1080)]])
    result = _taller_bloqueante(conn, _desde(2026, 8, 1, 10), _hasta(2026, 8, 1, 14))
    assert result is None


def test_taller_bloqueante_sin_sesiones():
    from services.estudio.queries.disponibilidad import _taller_bloqueante
    # La query no devuelve filas → libre
    conn = FakeConn([[]])
    result = _taller_bloqueante(conn, _desde(2026, 8, 1, 10), _hasta(2026, 8, 1, 14))
    assert result is None


def test_taller_bloqueante_exclude_taller_id():
    """Con exclude_taller_id, la query recibe el ID como parámetro NULL-safe.
    Simulamos que la query devuelve vacío (DB filtró correctamente)."""
    from services.estudio.queries.disponibilidad import _taller_bloqueante
    conn = FakeConn([[]])  # la DB ya excluyó el taller
    result = _taller_bloqueante(
        conn, _desde(2026, 8, 1, 10), _hasta(2026, 8, 1, 14), exclude_taller_id=7
    )
    assert result is None
    # Verificar que se pasó el exclude_taller_id como parámetro
    sql, params = conn._calls[0]
    assert 7 in params


def test_taller_bloqueante_hora_fin_24():
    """Sesión que termina a medianoche (hora_fin=24) con franja 22-24."""
    from services.estudio.queries.disponibilidad import _taller_bloqueante
    conn = FakeConn([[FakeRow(nombre="Nocturno", hora_inicio_min=1200, hora_fin_min=1440)]])
    result = _taller_bloqueante(conn, _desde(2026, 8, 1, 22), _hasta(2026, 8, 2, 0))
    assert result == "Nocturno"


# ── _slot_bloqueante ──────────────────────────────────────────────────────────


def test_slot_bloqueante_solapa():
    from services.estudio.queries.disponibilidad import _slot_bloqueante
    # Slot mié 10-14, franja mié 12-16 → solapa
    # 2026-07-29 es miércoles (weekday=2)
    conn = FakeConn([[FakeRow(id=1, cliente="Cliente A", hora_desde=10, hora_hasta=14)]])
    desde = _desde(2026, 7, 29, 12)
    hasta = _hasta(2026, 7, 29, 16)
    result = _slot_bloqueante(conn, desde, hasta)
    assert result == "Cliente A"


def test_slot_bloqueante_no_solapa():
    from services.estudio.queries.disponibilidad import _slot_bloqueante
    conn = FakeConn([[FakeRow(id=1, cliente="Cliente A", hora_desde=10, hora_hasta=14)]])
    desde = _desde(2026, 7, 29, 14)
    hasta = _hasta(2026, 7, 29, 18)
    result = _slot_bloqueante(conn, desde, hasta)
    assert result is None


def test_slot_bloqueante_exclude_slot_id():
    """El exclude_slot_id se pasa como parámetro al query."""
    from services.estudio.queries.disponibilidad import _slot_bloqueante
    conn = FakeConn([[]])  # DB filtró
    desde = _desde(2026, 7, 29, 10)
    hasta = _hasta(2026, 7, 29, 14)
    result = _slot_bloqueante(conn, desde, hasta, exclude_slot_id=5)
    assert result is None
    sql, params = conn._calls[0]
    assert 5 in params


# ── _centinela_libre ──────────────────────────────────────────────────────────


def test_centinela_libre_ignora_pedidos_derivados_taller_y_estudio_fijo():
    """Candado del fix del bug real reportado por el dueño (pedido #445): el
    WHERE de `_centinela_libre` tiene que excluir `p.tipo IN ('taller',
    'estudio_fijo')` — esos dos son pedidos DERIVADOS/contables cuyas fechas
    NO representan la franja real ocupada (taller guarda el mes calendario
    completo; estudio_fijo, solo la primera ocurrencia semanal). Su bloqueo
    real ya lo hacen `_taller_bloqueante`/`_slot_bloqueante`, ANTES en
    `_estudio_disponible`. Si alguien remueve el filtro, este test lo caza
    por el SQL — mismo patrón que `test_taller_bloqueante_filtra_edicion_activa`."""
    from services.estudio.queries.disponibilidad import _centinela_libre
    conn = FakeConn([FakeRow(cnt=0)])
    _centinela_libre(conn, 99, _desde(2026, 8, 15, 10), _hasta(2026, 8, 15, 12), buffer_horas=0)
    sql, _params = conn._calls[0]
    assert "p.tipo NOT IN ('taller', 'estudio_fijo')" in sql


# ── _estudio_disponible ───────────────────────────────────────────────────────


def test_estudio_disponible_libre():
    """Sin bloqueadores → (True, None)."""
    from services.estudio.queries.disponibilidad import _estudio_disponible
    # slot sin filas → taller sin filas → centinela libre (cnt=0)
    conn = FakeConn([[], [], FakeRow(cnt=0)])
    estudio = _estudio(buffer_horas=0)
    libre, motivo = _estudio_disponible(
        conn, estudio, _desde(2026, 8, 1, 10), _hasta(2026, 8, 1, 14)
    )
    assert libre is True
    assert motivo is None


def test_estudio_disponible_bloquea_slot():
    """Slot bloqueante → (False, motivo con 'slot fijo')."""
    from services.estudio.queries.disponibilidad import _estudio_disponible
    conn = FakeConn([[FakeRow(id=1, cliente="X", hora_desde=9, hora_hasta=15)]])
    estudio = _estudio()
    libre, motivo = _estudio_disponible(
        conn, estudio, _desde(2026, 7, 29, 10), _hasta(2026, 7, 29, 14)
    )
    assert libre is False
    assert "slot fijo" in motivo
    assert "X" in motivo


def test_estudio_disponible_bloquea_taller():
    """Taller bloqueante → (False, motivo con 'taller')."""
    from services.estudio.queries.disponibilidad import _estudio_disponible
    # slot vacío → taller con sesión solapada
    conn = FakeConn([[], [FakeRow(nombre="Workshop", hora_inicio_min=540, hora_fin_min=900)]])
    estudio = _estudio()
    libre, motivo = _estudio_disponible(
        conn, estudio, _desde(2026, 8, 1, 10), _hasta(2026, 8, 1, 14)
    )
    assert libre is False
    assert "taller" in motivo
    assert "Workshop" in motivo


def test_estudio_disponible_bloquea_centinela():
    """Centinela ocupado → (False, motivo con 'franja')."""
    from services.estudio.queries.disponibilidad import _estudio_disponible
    # slot vacío → taller vacío → centinela ocupado (cnt=1)
    conn = FakeConn([[], [], FakeRow(cnt=1)])
    estudio = _estudio()
    libre, motivo = _estudio_disponible(
        conn, estudio, _desde(2026, 8, 1, 10), _hasta(2026, 8, 1, 14)
    )
    assert libre is False
    assert motivo


def test_estudio_disponible_orden_slot_primero():
    """El slot se chequea PRIMERO; si bloquea, el taller ni se consulta."""
    from services.estudio.queries.disponibilidad import _estudio_disponible
    conn = FakeConn([[FakeRow(id=1, cliente="A", hora_desde=9, hora_hasta=15)]])
    estudio = _estudio()
    libre, motivo = _estudio_disponible(
        conn, estudio, _desde(2026, 7, 29, 10), _hasta(2026, 7, 29, 14)
    )
    assert libre is False
    # Solo se hizo 1 query (el slot bloqueó, no llegó al taller)
    assert len(conn._calls) == 1


# ── verificar_sesiones_disponibles ────────────────────────────────────────────


def test_verificar_sesiones_libres():
    """Todas las sesiones libres → no lanza excepción."""
    from services.estudio.queries.disponibilidad import verificar_sesiones_disponibles
    sesiones = [
        {"fecha": _en(7), "hora_inicio_min": 540, "hora_fin_min": 780},
        {"fecha": _en(14), "hora_inicio_min": 540, "hora_fin_min": 780},
    ]
    # Cada sesión: slot vacío + taller vacío + centinela libre (3 queries × 2 = 6)
    conn = FakeConn([[], [], FakeRow(cnt=0)] * 2)
    estudio = _estudio()
    verificar_sesiones_disponibles(conn, estudio, sesiones)  # No debe lanzar


def test_verificar_sesiones_primera_conflicto_lanza_409():
    """Primera sesión conflicto → HTTPException 409 inmediato."""
    from fastapi import HTTPException
    from services.estudio.queries.disponibilidad import verificar_sesiones_disponibles
    primera = _en(7)
    sesiones = [
        {"fecha": primera, "hora_inicio_min": 540, "hora_fin_min": 780},
        {"fecha": _en(14), "hora_inicio_min": 540, "hora_fin_min": 780},
    ]
    # Primera sesión: slot bloquea
    conn = FakeConn([
        [FakeRow(id=1, cliente="Fijo", hora_desde=8, hora_hasta=14)],  # slot bloquea
    ])
    estudio = _estudio()
    with pytest.raises(HTTPException) as exc:
        verificar_sesiones_disponibles(conn, estudio, sesiones)
    assert exc.value.status_code == 409
    assert primera.strftime("%d/%m/%Y") in str(exc.value.detail)


def test_verificar_sesiones_salta_pasadas():
    """Sesiones anteriores a hoy se saltean sin consultar la DB."""
    from services.estudio.queries.disponibilidad import verificar_sesiones_disponibles
    sesiones = [
        {"fecha": date(2020, 1, 1), "hora_inicio_min": 540, "hora_fin_min": 780},  # pasada
        {"fecha": date(2020, 1, 2), "hora_inicio_min": 540, "hora_fin_min": 780},  # pasada
    ]
    conn = FakeConn([])  # si se hiciera alguna query, fallaría (lista vacía)
    estudio = _estudio()
    verificar_sesiones_disponibles(conn, estudio, sesiones)  # No debe lanzar ni consultar


def test_verificar_sesiones_segunda_conflicto():
    """Si la primera sesión está libre pero la segunda bloquea, lanza 409 para la segunda."""
    from fastapi import HTTPException
    from services.estudio.queries.disponibilidad import verificar_sesiones_disponibles
    desde_futuro = _en(7)
    segunda = _en(14)
    sesiones = [
        {"fecha": desde_futuro, "hora_inicio_min": 540, "hora_fin_min": 780},
        {"fecha": segunda, "hora_inicio_min": 540, "hora_fin_min": 780},
    ]
    # Primera sesión: libre (slot vacío, taller vacío, centinela libre)
    # Segunda sesión: taller bloquea
    conn = FakeConn([
        [], [], FakeRow(cnt=0),                   # sesión 1: libre
        [],                                        # sesión 2: slot vacío
        [FakeRow(nombre="Otro", hora_inicio_min=480, hora_fin_min=840)],  # sesión 2: taller bloquea
    ])
    estudio = _estudio()
    with pytest.raises(HTTPException) as exc:
        verificar_sesiones_disponibles(conn, estudio, sesiones)
    assert exc.value.status_code == 409
    assert segunda.strftime("%d/%m/%Y") in str(exc.value.detail)


# ── Overlap cruzado ───────────────────────────────────────────────────────────


def test_taller_vs_slot_bloquea():
    """Un taller no puede ocupar un horario donde ya hay un slot fijo."""
    from services.estudio.queries.disponibilidad import verificar_sesiones_disponibles
    # Slot fijo lunes 10-18
    sesiones = [{"fecha": _en(7), "hora_inicio_min": 600, "hora_fin_min": 1080}]
    conn = FakeConn([
        [FakeRow(id=2, cliente="Slot Fijo", hora_desde=9, hora_hasta=19)],
    ])
    estudio = _estudio()
    with pytest.raises(Exception) as exc:
        verificar_sesiones_disponibles(conn, estudio, sesiones)
    assert "slot fijo" in str(exc.value.detail).lower()


def test_taller_vs_reserva_web_bloquea():
    """Un taller no puede ocupar un horario donde ya hay una reserva web (centinela)."""
    from services.estudio.queries.disponibilidad import verificar_sesiones_disponibles
    sesiones = [{"fecha": _en(7), "hora_inicio_min": 600, "hora_fin_min": 840}]
    conn = FakeConn([[], [], FakeRow(cnt=1)])  # slot vacío, taller vacío, centinela ocupado
    estudio = _estudio()
    with pytest.raises(Exception) as exc:
        verificar_sesiones_disponibles(conn, estudio, sesiones)
    assert exc.value.status_code == 409


def test_taller_vs_taller_bloquea():
    """Dos talleres que solapan en la misma fecha son detectados."""
    from services.estudio.queries.disponibilidad import verificar_sesiones_disponibles
    sesiones = [{"fecha": _en(7), "hora_inicio_min": 600, "hora_fin_min": 840}]
    # El taller existente (excluído con exclude_taller_id) no bloquea, pero hay otro
    conn = FakeConn([
        [],  # slot vacío
        [FakeRow(nombre="Taller Existente", hora_inicio_min=540, hora_fin_min=960)],  # taller bloquea
    ])
    estudio = _estudio()
    with pytest.raises(Exception) as exc:
        verificar_sesiones_disponibles(conn, estudio, sesiones, exclude_taller_id=5)
    assert "taller" in str(exc.value.detail).lower()


# ── _sesiones_de_slot ─────────────────────────────────────────────────────────


def test_sesiones_de_slot_genera_correctas():
    """Slot los miércoles de julio 2026 genera las 4/5 fechas del mes."""
    from routes.estudio import _sesiones_de_slot
    slot = {
        "dia_semana": 2,  # miércoles
        "mes_desde": "2026-07",
        "mes_hasta": "2026-07",
        "hora_desde": 18,
        "hora_hasta": 22,
    }
    sesiones = _sesiones_de_slot(slot)
    # Miércoles de julio 2026: 1, 8, 15, 22, 29
    fechas = [s["fecha"] for s in sesiones]
    assert len(fechas) == 5
    assert all(d.weekday() == 2 for d in fechas)
    assert all(s["hora_inicio_min"] == 1080 for s in sesiones)
    assert all(s["hora_fin_min"] == 1320 for s in sesiones)
    assert fechas[0] == date(2026, 7, 1)
    assert fechas[-1] == date(2026, 7, 29)


def test_sesiones_de_slot_rango_dos_meses():
    """Slot en rango de 2 meses incluye los miércoles de ambos meses."""
    from routes.estudio import _sesiones_de_slot
    slot = {
        "dia_semana": 2,
        "mes_desde": "2026-07",
        "mes_hasta": "2026-08",
        "hora_desde": 10,
        "hora_hasta": 14,
    }
    sesiones = _sesiones_de_slot(slot)
    meses = {s["fecha"].month for s in sesiones}
    assert 7 in meses and 8 in meses
    assert len(sesiones) > 5


# ── Medias horas (Escuela v2 F1) ──────────────────────────────────────────────


def _desde_min(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, 0)


def test_taller_bloqueante_media_hora_conflicto():
    """Clase 8:30–12:30 (510–750 min) vs pedido de estudio 12:00–14:00 → conflicto
    (el modelo viejo de horas enteras no podía representar este caso)."""
    from services.estudio.queries.disponibilidad import _taller_bloqueante
    conn = FakeConn([[FakeRow(nombre="Principiante", hora_inicio_min=510, hora_fin_min=750)]])
    result = _taller_bloqueante(
        conn, _desde_min(2026, 9, 5, 12, 0), _desde_min(2026, 9, 5, 14, 0)
    )
    assert result == "Principiante"


def test_taller_bloqueante_media_hora_libre():
    """Clase 8:30–12:30 vs pedido 12:30–14:00 → libre (half-open, borde exacto)."""
    from services.estudio.queries.disponibilidad import _taller_bloqueante
    conn = FakeConn([[FakeRow(nombre="Principiante", hora_inicio_min=510, hora_fin_min=750)]])
    result = _taller_bloqueante(
        conn, _desde_min(2026, 9, 5, 12, 30), _desde_min(2026, 9, 5, 14, 0)
    )
    assert result is None


def test_taller_bloqueante_filtra_edicion_activa():
    """Candado del fix de bloqueo fantasma: el WHERE exige `e.activo = TRUE`
    (una edición desactivada/borrador NO bloquea el estudio). Si alguien
    remueve el filtro, este test lo caza por el SQL."""
    from services.estudio.queries.disponibilidad import _taller_bloqueante
    conn = FakeConn([[]])
    _taller_bloqueante(conn, _desde(2026, 8, 1, 10), _hasta(2026, 8, 1, 14))
    sql, _params = conn._calls[0]
    assert "e.activo = TRUE" in sql
    assert "t.activo = TRUE" in sql


def test_verificar_sesiones_409_formatea_hhmm():
    """El mensaje del 409 muestra los horarios como HH:MM (8:30, no '510')."""
    from fastapi import HTTPException
    from services.estudio.queries.disponibilidad import verificar_sesiones_disponibles
    sesiones = [{"fecha": _en(7), "hora_inicio_min": 510, "hora_fin_min": 750}]
    conn = FakeConn([
        [FakeRow(id=1, cliente="Fijo", hora_desde=8, hora_hasta=14)],  # slot bloquea
    ])
    estudio = _estudio()
    with pytest.raises(HTTPException) as exc:
        verificar_sesiones_disponibles(conn, estudio, sesiones)
    assert exc.value.status_code == 409
    assert "08:30" in str(exc.value.detail)
    assert "12:30" in str(exc.value.detail)


def test_verificar_sesiones_media_hora_contra_slot_borde():
    """Clase 12:30–16:30 contra slot fijo que termina 12 (hs) → libre: la
    conversión ×60 de _sesiones_de_slot y los minutos de la clase comparan
    en la MISMA unidad (candado de la doble unidad transitoria)."""
    from services.estudio.queries.disponibilidad import verificar_sesiones_disponibles
    sesiones = [{"fecha": _en(7), "hora_inicio_min": 750, "hora_fin_min": 990}]
    # slot 9–12 hs (en su tabla, horas): 540–720 min → NO solapa con 750–990
    conn = FakeConn([
        [FakeRow(id=1, cliente="Fijo", hora_desde=9, hora_hasta=12)],  # no solapa
        [],                # taller vacío
        FakeRow(cnt=0),    # centinela libre
    ])
    estudio = _estudio()
    verificar_sesiones_disponibles(conn, estudio, sesiones)  # no lanza
