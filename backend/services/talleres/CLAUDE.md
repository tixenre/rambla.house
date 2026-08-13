# `backend/services/talleres/` — dedup del gate de conflicto con Estudio + economía de talleres

> Invariantes locales. El _por qué_ completo: `docs/DECISIONES.md` (entrada del split, misma fecha
> que esta pasada) y la fundacional _2026-07-24 — `_regenerar_pedidos_taller` = nuevo miembro de la
> familia motor-único (espejo de `_regenerar_pedidos_slot`)_.

**Fase 1 acotada.** Este paquete NO es "todo talleres" — es la lógica de decisión que estaba
**duplicada** en `routes/talleres.py`: el gate de conflicto con Estudio (copiado inline 3 veces), el
INSERT de `ediciones_taller` (copiado byte a byte entre 2 endpoints) y la economía del taller
(`_regenerar_pedidos_taller`). Los endpoints HTTP siguen enteros en `routes/talleres.py` (auth,
conn/commit/rollback, HTTP) y **delegan** a este paquete — mismo patrón que
`crear_reserva_estudio_admin` sigue llamando a `_crear_pedido_estudio` sin haberse movido ella misma.
Quedan afuera a propósito: helpers de lectura/serialización, instructores/instituciones/trabajos/
portada, notificaciones/interesados/KPIs, y **inscripción/seña** (Fase 2 diferida — dominio
ortogonal, ver `docs/DECISIONES.md`).

## Estructura (CQRS-lite, espeja `services/estudio/`/`descuentos/`/`contabilidad/`)

```
services/talleres/
  __init__.py       # barrel (docstring, sin __all__ — no hay re-exports públicos)
  constants.py        # _ADVISORY_NS_TALLER = 5390423 (namespace propio, por edición — NO
                       # comparte namespace con _ADVISORY_NS_ESTUDIO)
  queries/            # LECTURA — nunca mutan
    clases.py            # _row_get, _validar_clases, _validar_modalidades (puras, sin conn)
    economia.py           # _revenue_inscriptos (conn) + _valor_efectivo (pura) — 'porcentaje'
  commands/           # ESCRITURA
    clases.py            # _insert_clases, _upsert_clases, _upsert_modalidades
    ediciones.py           # _gate_conflicto_estudio (dedup del gate ×3) + crear_edicion
                            # (dedup del INSERT de ediciones_taller ×2)
    economia.py             # _regenerar_pedidos_taller (economía del taller)
```

**Invariante commands↔queries (igual que `estudio`/`contabilidad`/`descuentos`):** `commands/` puede
importar de `queries/`; `queries/` **nunca** de `commands/`.

**Desviación documentada respecto a `services/estudio/`:** acá SÍ hay imports `commands/`→
`commands/` (`ediciones.py` importa de `commands/clases.py` y `commands/economia.py`) — no viola la
única regla dura de arriba, pero es distinto del molde de estudio (que no tiene commands
intra-dependientes). Documentado para que el supervisor no lo marque por comparación automática con
el otro paquete.

## Reglas que no se rompen

- **El gate es dedup del CÓMO, no re-decisión del CUÁNDO.** `_gate_conflicto_estudio` encapsula
  `_get_estudio_row` + `pg_advisory_xact_lock(_ADVISORY_NS_ESTUDIO, 1)` +
  `verificar_sesiones_disponibles` — pero cada caller (`admin_create_taller`/`admin_create_edicion`/
  `admin_update_edicion`, en `routes/talleres.py`) sigue decidiendo su propio trigger ("nace
  publicada" vs. "transición a publicada", con su condición propia más compleja en el update). No
  mover esa decisión adentro de la función.
- **`_ADVISORY_NS_TALLER` (5390423) ≠ `_ADVISORY_NS_ESTUDIO` (5390413).** Locks sobre recursos
  distintos (una edición de taller vs. el espacio del Estudio) — no fusionar namespaces aunque
  aparezcan en el mismo flujo (`_gate_conflicto_estudio` toma el de Estudio; `_regenerar_pedidos_taller`
  toma el propio, por `edicion_id`).
- **El paquete NO importa de `routes.*`.** `_regenerar_pedidos_taller` recibe `numero_pedido_fn`
  **inyectado** (no importa `_next_numero_pedido` de `routes.alquileres`) — mismo patrón "valor ya
  resuelto como parámetro" de `services/estudio/CLAUDE.md`, extendido acá a una función porque el
  loop necesita un valor fresco por pedido, no uno solo. No reimportar `routes.alquileres` como
  atajo futuro.
- **Mes actual / iteración de meses vía `services/fechas.py`** (`mes_actual_ar`, `iter_meses`,
  `MESES_ES`) — no resolver por import directo de `routes.estudio`/`routes.talleres` (esos
  duplicados se retiraron al mover esta lógica; `routes/estudio.py` también repuntó a
  `services/fechas.py` en el mismo commit).
- **No hay `_borrar_pedidos_futuros_impagos_taller` separado** (a diferencia de estudio, que sí
  extrajo esa pieza) — verificado que en talleres no hay un segundo call-site real que la necesite
  (`admin_delete_edicion` no limpia pedidos futuros, confía en `ON DELETE SET NULL`). Asimetría
  preexistente y documentada, no resuelta acá — no extraer "por simetría" con estudio sin que
  aparezca un segundo consumidor genuino.
- **`valor_estudio_tipo`/`valor_equipos_tipo` ('fijo'|'porcentaje') es un eje ortogonal a `_modo`**
  (2026-08-13): `_modo` sigue decidiendo "cómo se reparte entre meses"; `_tipo` decide "de dónde sale
  el total ANTES de repartirlo" — 'fijo' = tipeado (`valor_estudio`/`valor_equipos`, de siempre);
  'porcentaje' = `_valor_efectivo` aplica `_pct` sobre `_revenue_inscriptos` (SUM de
  `taller_inscripciones.modalidad_monto` no en lista de espera de ESA edición). `_regenerar_pedidos_taller`
  resuelve el valor efectivo de cada eje ANTES de llamar a `_partes` — `_partes`/`_modo` no saben ni
  necesitan saber de dónde salió el total. El revenue se consulta **una sola vez** y se comparte entre
  Estudio/equipos (guard: `if _tipo=='porcentaje' de cualquiera de los dos`) — no dispara la query
  cuando ambos son 'fijo' (el caso común). `routes/talleres.py::_edicion_to_admin_dict` expone el
  mismo preview ya resuelto (`inscriptos_revenue`/`valor_*_efectivo`) para que el admin lo vea SIN que
  el front recalcule nada (el front no calcula plata, MEMORIA 2026-06-29) — el preview refleja el
  último `_pct` GUARDADO, no lo que se está tipeando. El supervisor marca: un `_partes`/`_modo`
  tocado para acomodar 'porcentaje' (no debería hacer falta), un preview de `valor_*_efectivo`
  recalculado en el front, o una query de revenue nueva fuera de `queries/economia.py::_revenue_inscriptos`.
- **Inscripción/seña y los helpers de lectura/serialización quedan fuera a propósito** (Fase 1
  acotada) — no expandir este paquete para "completarlo" sin que haya una duplicación real que lo
  justifique, mismo criterio que dejó fuera "slots fijos" del split de estudio.
- **`crear_edicion` NO incluye el gate adentro** — el caller lo invoca ANTES (mismo orden relativo
  que el código de origen en los 2 call-sites: se verifica disponibilidad antes de tocar
  `talleres`/`ediciones_taller`). No commitea — responsabilidad del route.

El supervisor marca: lógica de gate/economía/validación de clases reimplementada fuera de este
paquete; un import de `routes.*` dentro de `services/talleres/`; un `queries/` importando de
`commands/`; el gate re-inlineado en cualquier call-site nuevo; `_regenerar_pedidos_taller`
resolviendo `numero_pedido`/mes actual/iterador de meses por import directo en vez de vía inyección o
`services.fechas`; un commit dentro de un command (el route es dueño de la transacción).
