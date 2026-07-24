# Sistema: Finanzas/Flujo — el módulo orquestador + el mapa cruzado de todos los motores que tocan dinero

> Manual técnico **cruzado** (fuente única del **cómo se conecta la plata entre motores**) — y del
> módulo orquestador `backend/services/finanzas_flujo/` (mismo patrón 1:1 manual↔módulo que
> `SISTEMA_CARRITO.md`↔`services/carrito/`). Cada motor individual ya tiene su propio manual/
> invariantes (`backend/contabilidad/CLAUDE.md`, `backend/reservas/CLAUDE.md`,
> `docs/SISTEMA_FACTURACION.md`, `docs/SISTEMA_CARRITO.md`) — **este doc no los repite**, los
> referencia y muestra cómo encajan. Las reglas de criterio y el _porqué_ viven en
> `MEMORIA.md`/`DECISIONES.md`. Índice maestro en `MANIFIESTO.md` §8.
>
> **Origen:** nace de la auditoría 2026-07-02 (post fix #405 + auditoría de `contabilidad/`), a
> pedido del dueño ante el miedo de "drift de plata" — demasiados lugares tocan dinero y no había
> un mapa único de quién gobierna qué número, ni una implementación real de ese mapa (solo
> documentación). Verificado con 6 auditorías paralelas sobre los motores no cubiertos por la
> auditoría de `contabilidad/` (precios ×2, reportes/liquidación, facturación, el camino de
> congelamiento de precio, y un trace end-to-end + estado de la reconciliación) — y descubrió, de
> paso, que el fix original del bug #405 (#1181) nunca se mergeó a `dev`/`main`. El dueño pidió que
> el mapa fuera **código real, no solo prosa** → nace `services/finanzas_flujo/` (Fase 1 de la hoja
> de ruta que sigue a esta auditoría).

## Qué resuelve

Nadie recalcula "el mismo número" dos veces por caminos independientes. Cada pregunta de plata
tiene **un solo motor dueño**; el resto **consume**, nunca reimplementa — y desde Fase 1, ese
"consume" pasa por un único punto de entrada de código: `backend/services/finanzas_flujo/`.

## El módulo orquestador: `backend/services/finanzas_flujo/`

Facade de **solo lectura** — no reimplementa ni reemplaza ningún motor (`precios`,
`reportes/liquidacion`, `contabilidad`, `facturacion` siguen siendo dueños de su lógica). Expone una
API única y estable para "preguntar un número de plata"; nunca escribe (las mutaciones siguen
pasando por cada motor directo: `create_pedido_retry`, `contabilidad.commands.*`, rutas de
`alquiler_pagos`).

```
backend/services/finanzas_flujo/
  pedido.py   → desglose_de_pedido(conn, pedido) -> dict   [Fase 1, implementado]
                OWNA: fixea el bug de cobro_modo. Delega en services.precios.calcular_total.
  liquidacion.py, contabilidad.py, facturacion.py, reconciliacion.py → fases siguientes
```

**Candado:** `backend/tests/test_finanzas_flujo_source_scan.py` — verifica que `pdf_templates.py`
usa el helper cobro_modo-aware (no reimplementa la multiplicación) y que
`services/facturacion/engine.py` importa la fachada (no `routes.alquileres` directo — un service no
debe depender de un route).

## Fuente única de cada número

| Pregunta | Motor dueño | Función/archivo | Quién consume |
| --- | --- | --- | --- |
| ¿Cuánto cuesta un ítem por jornada? | `backend/services/precios.py` | `precio_jornada_efectivo` | cotizar, crear, editar, carrito (`readiness.py`), catálogo (listado/ficha) |
| ¿Cuál es el total de un pedido (al cotizar)? | `backend/services/precios.py` | `calcular_total` | `/api/cotizar`, creación, portal cliente |
| ¿Cuál es el total YA CONFIRMADO de un pedido? | `alquileres.monto_total` | snapshot congelado (`_apply_pedido_items`/`_recalcular_total_pedido`, `routes/alquileres/core.py`) | detalle de pedido, reportes, facturación — **nunca se recalcula contra catálogo** |
| ¿Cuánto se cobró de un pedido? | `alquiler_pagos` | única tabla (`routes/alquileres/pagos.py`) | `monto_pagado` (cache derivado), liquidación, contabilidad |
| ¿Hay stock/está disponible? | `backend/reservas/` | motor sagrado | gate único `create_pedido_retry` |
| ¿Qué % de lo facturado es de Rambla vs. de un dueño de equipo? | `backend/reportes/liquidacion.py` + `comisiones.py` | `liquidar`, `repartir` | `contabilidad` (`partes_socios`, llama literal a `liquidar`), reporte mensual |
| ¿A qué economía pertenece la plata de un pedido del Estudio? | `equipos.dueno` (por ítem) + `contabilidad.constants.{COBRADORES,PARTES}` | centinela `dueno='Estudio'`, promo `dueno='Rambla'`, suelto → su dueño real | `liquidar`/`filas_atribucion` (genérico, sin caso especial), `pyl.ganancia_neta` (`parte_estudio`), rendición (netting a 4 partes) |
| ¿Cuánta plata tiene Rambla en sus cajas / cuánto le debe cada socio? | `backend/contabilidad/` | `queries/saldos.py::calcular_saldos` | tablero, reporte mensual |
| ¿La factura discrimina IVA correctamente? | `backend/services/facturacion/` (`docs/SISTEMA_FACTURACION.md`) | `arca_fe/comprobante.py` | deriva de `monto_total`/`iva_monto` ya persistidos — **no recalcula** |
| ¿Qué ve el cliente en pantalla? | — | — | **nunca calcula**: solo renderiza lo que el backend ya resolvió (regla dura, `MEMORIA.md` 2026-06-29) — con **una excepción confirmada**, ver Hallazgos |

## Los motores (referencia, no reimplementación)

- **`backend/reservas/`** — disponibilidad/stock/overlap. Sagrado, `contabilidad`/`reportes` no lo tocan.
- **`backend/services/precios.py`** — precio por jornada/combo/total. Único resolutor; 4 call-sites
  reales lo llaman (`core.py:854,1024,259`, `cotizacion.py:140`), ninguno reimplementa la fórmula.
- **`backend/services/carrito/`** (`docs/SISTEMA_CARRITO.md`) — la intención del cliente; pide precio
  a `precios`, hace handoff a `create_pedido_retry`. No decide plata ni stock.
- **`alquiler_pagos`** (`routes/alquileres/pagos.py`) — el cobro. Actor + soft-delete desde la
  auditoría de `contabilidad` (2026-07-02): `created_by`/`anulado`/`anulado_por`/`anulado_motivo`.
- **`backend/reportes/`** (`CLAUDE.md` propio) — liquidación (reparto de comisiones por dueño de
  equipo) + su propio cierre mensual (`liquidacion_cierres`, **distinto** del cierre de
  `contabilidad`) + reconciliación (semáforo, ver abajo).
- **`backend/contabilidad/`** (`CLAUDE.md` propio) — la plata interna: cajas, cuenta corriente de
  socios, movimientos, P&L, su propio cierre mensual (`movimientos` bloqueados). **Consume**
  `reportes.liquidacion.liquidar()` para `partes_socios` — no recalcula el reparto. Desde #1283
  (Fases 3-4), **"Estudio" es una economía separada más**: 4to cobrador/parte (`COBRADORES`/`PARTES`),
  con su propia caja real (`Caja Estudio`, `tipo='fondo'`) — mismo mecanismo que Rambla/Fondo Rambla,
  sin caso especial en ningún consumidor genérico (`filas_atribucion`, `_netting`, `calcular_saldos`).
- **`backend/services/facturacion/`** (`docs/SISTEMA_FACTURACION.md`) — Factura A/B/C, IVA, ARCA.
  Deriva de `monto_total`/`iva_monto` ya persistidos; la Nota de Crédito usa el snapshot de la
  factura ORIGINAL (no el pedido en vivo), para no quedar descuadrada ante ARCA si el precio cambió.

## El semáforo de reconciliación (dos capas + alerta proactiva)

- `reportes/reconciliacion.py::reconciliar` — `GET /admin/reportes/reconciliacion` (pagados-sin-
  ledger, `monto_pagado` divergente, sobrepagados, mes cerrado desactualizado, dueños no canónicos,
  **desglose de pedido divergente** — Fase 2, ver abajo).
- `contabilidad/queries/reconciliacion.py::reconciliar` — `GET /admin/contabilidad/reconciliacion`
  (saldos negativos, movimientos a cuenta inactiva, pagos sin cobrador válido) — **hereda** el de
  arriba, no lo duplica.
- **`services/finanzas_flujo/reconciliacion.py::estado`** (Fase 2, #1184) — la fachada que une los
  dos en un solo `ok`. Primer consumidor: **`jobs/reconciliacion.py::chequear_reconciliacion_y_alertar`**,
  corrido 1×/día desde `jobs/scheduler.py` (mismo thread in-process que ya corre
  `enviar_recordatorios_retiro`/`purgar_cuentas_livianas_stale`) — si `ok=False`, manda un mail resumen
  a `settings.admin_emails`. **Ya no es 100% manual**: el dueño se entera sin tener que abrir el
  dashboard. El job solo avisa, no repara nada.
- **Chequeo nuevo (Fase 2):** `desglose_divergente` en `reportes/reconciliacion.py` — compara
  `alquileres.monto_total` persistido contra el desglose recalculado con el precio de línea YA
  PERSISTIDO de cada ítem (vía `finanzas_flujo.pedido.desglose_de_pedido`, NO el de catálogo). Es la
  red genérica que hubiera cazado el patrón del bug #405 sin depender de que el dueño notara un
  reporte puntual.

## Candados (tests que fijan la garantía)

- `backend/tests/test_contabilidad_db.py` / `test_contabilidad_movimientos.py` — motor de
  contabilidad (soft-delete, candado de mes, validación tipo-cuenta).
- `backend/tests/test_carrito_precio_efectivo.py` — source-scan: los 3 caminos de plata persistida
  (cotizar/crear/modificar) usan `precio_jornada_efectivo`, ninguno reinlinea el switch de combo.
- `backend/tests/test_reportes_cierres_db.py` — cierre de la liquidación.
- `backend/tests/test_finanzas_flujo_pedido.py` — desglose de pedido, cobro_modo-aware (Fase 1).
- `backend/tests/test_finanzas_flujo_source_scan.py` — PDF y facturación pasan por la fachada.
- `backend/tests/test_finanzas_flujo_reconciliacion.py` — el semáforo unificado (`estado`) delega bien
  en los dos `reconciliar()` (Fase 2).
- `backend/tests/test_jobs_reconciliacion.py` — el job de alerta manda mail solo cuando `ok=False`, a
  cada admin, y nunca propaga un fallo de envío (Fase 2).
- `backend/tests/test_reportes_liquidacion_db.py::test_reconciliacion_caza_desglose_divergente_del_pedido`
  — el chequeo `desglose_divergente` caza un `monto_total` que no coincide con el desglose recalculado
  del precio de línea persistido (Fase 2).
- Facturación: candados propios en `docs/SISTEMA_FACTURACION.md`.

## Hallazgos de la auditoría cruzada (2026-07-02) — iniciativa #1184 CERRADA (2026-07-03)

Verificado con 6 auditorías paralelas independientes (no solo lectura de código — cruzando
call-sites reales). Priorizado por impacto real, no por tier de origen. **Todos los ítems marcados
✅/~~tachado~~ están resueltos y mergeados a `dev`** (tracking #1184, cerrado 2026-07-03). Lo que
queda abierto son los ítems 5 (parcial, alcance acotado a propósito), 6 (aclarado con el dueño: NO es
un bug — el descuento ganador depende de cliente+fechas, no hay forma de mostrar un número confiable
antes del carrito; la forma exacta de comunicarlo, ej. un aviso sin número, queda abierta si se
quiere explorar), 7 (dormido), y 11/13/14 (bajo impacto, documentados) — ninguno es un bug activo
conocido hoy.

### 🚨 Descubrimiento crítico de proceso (no de código) — ✅ RESUELTO
**El PR #1181 — el fix ORIGINAL del bug #405 (editor de pedidos cotizando con precio de catálogo en
vez del precio de línea congelado) —** se creyó sin mergear al momento de esta auditoría, pero
**sí se mergeó a `dev` el mismo día** (commit `9cc4924`, 2026-07-05) — `respetar_precio_item` está
presente y activo en `backend/routes/alquileres/cotizacion.py`. **El bug #405 está resuelto, no
activo.** Corrección registrada en `MEMORIA.md` (entrada 2026-07-02, "Auditoría cruzada de plata").

### Bugs reales (activos hoy)
1. ~~**`_enriquecer_pedido_con_total` (`routes/alquileres/core.py`) ignora `cobro_modo`**~~ —
   **RESUELTO (Fase 1, `services/finanzas_flujo/pedido.py::desglose_de_pedido`).** Una línea
   personalizada `cobro_modo='fijo'` (ej. flete, #805) se multiplicaba igual por jornadas en este
   desglose de *display*, en los 6 lugares reales que lo usan: detalle de pedido (admin y portal
   cliente), 2 generadores de PDF/mail, y **`services/facturacion/engine.py`** (el motor de
   facturación real). `_enriquecer_pedido_con_total` ahora es un wrapper que delega en la fachada;
   `services/facturacion/engine.py` migró a importarla directo (ya no depende de `routes.alquileres`).
   Candado: `test_finanzas_flujo_pedido.py` (unit, 5 casos) + `test_finanzas_flujo_source_scan.py`.
2. ~~**Mismo bug en el PDF**~~ — **RESUELTO (Fase 1).** `pdf_templates.py` reimplementaba
   `precio_jornada × cantidad × jornadas` desde cero, sin `cobro_modo`. Ahora `_pedido_html`/
   `_sum_bruto` usan el helper `_bruto_item_pdf` (mismo criterio que `bruto_linea`). Candado:
   `test_pdf_helpers.py::TestBrutoItemPdf` + el source-scan de arriba.
3. ~~**`routes/facturacion.py` (`enviar_mail_factura`)**~~ — **RESUELTO (Fase 4).** Consultaba
   `c.owner_email`, columna que no existe en `clientes` (vive en otra tabla) — rompía con
   `UndefinedColumn` cada vez que un admin usaba "enviar factura por mail". Fix: `c.owner_email` →
   `c.email`. **Segundo bug encontrado detrás del primero**: `Attachment(..., content_type=...)` — el
   kwarg real del dataclass es `mimetype` (confirmado contra los otros 3 usos de `Attachment` en el
   repo) — nunca se había ejecutado esa línea porque el query de email crasheaba antes. Sin el primer
   fix, el segundo bug seguía dejando la función completamente rota. Candado:
   `test_facturacion_routes.py::test_enviar_mail_factura_no_rompe_con_undefined_column` +
   `test_enviar_mail_factura_400_si_sin_email`.
4. ~~**`reportes/liquidacion.py::filas_atribucion`**~~ — **RESUELTO (Fase 5, #1184).** Si
   `suma_items = 0` pero `monto_total > 0` (ítems con subtotal 0, ej. 100% descuento a nivel ítem), el
   prorrateo daba `NULL` (vía `NULLIF`) → se trataba como 0 → la plata de ese pedido **desaparecía en
   silencio** del reporte de liquidación, sin que ningún chequeo de reconciliación lo detectara. Fix:
   `CASE WHEN t.suma_items = 0 THEN al.monto_total / t.cant_items ELSE ... END` — reparte el
   `monto_total` en **partes iguales** entre los ítems del pedido (no hay base real de prorrateo
   cuando todos los subtotales son 0; repartir parejo es el fallback más neutral, no arbitrario hacia
   un dueño). Candado: `test_reportes_liquidacion_db.py::test_suma_items_cero_no_pierde_plata`
   (Postgres real, un pedido con 2 ítems subtotal 0 confirma que el total del reporte sigue incluyendo
   su `monto_total` completo).
5. **Front — reimplementaba el cálculo de línea en vez de leer lo que ya calculó el backend** (viola
   "el front no calcula plata", 2026-06-29):
   - ~~`PedidoPageCards.tsx` vs `PedidoPageHelpers.tsx` (editor admin)~~ — **RESUELTO (Fase 1)**:
     ambos importan `subtotalDraftItem` desde `usePedidoDraft.ts` — ya no pueden divergir, llaman
     literalmente a la misma función.
   - `CartDrawerView.tsx`/`CartMiniBarView.tsx` (carrito público) — **pendiente, fuera de Fase 1**
     (requiere threadear el objeto `Cotizacion` completo a 3 call-sites, cambio de mayor alcance; el
     carrito público hoy no tiene líneas `cobro_modo='fijo'`, así que es solo riesgo de staleness de
     precio cacheado, no el bug concreto). Documentado como fase futura opcional.
   - En ambos casos lo persistido/cobrado sigue siendo correcto — es el número que se MUESTRA el que
     puede no coincidir.
6. **`frontend/src/lib/pricing.ts`** — ✅ **aclarado con el dueño (2026-07-05), NO es un bug.** Sigue
   siendo pura multiplicación (`perDay × jornadas × qty`, sin descuento); lo usa `PriceBlock` (la
   pieza canónica de precio del catálogo, `equipment/shared/`), así que el precio que ve el cliente en
   la card/ficha no incluye descuentos, mientras el total real al cotizar/confirmar sí. Motivo: los
   descuentos NO son acumulables (gana el mayor entre cliente/jornadas/manual) y cuál gana depende de
   **quién** está mirando y **cuántos días** eligió — ninguno de los dos se conoce en el catálogo. Mostrar
   el descuento por jornadas solo (sin saber si el de cliente es mayor) sería mostrar un número que
   después puede no cumplirse. **Decisión: el catálogo muestra precio de lista; el descuento real
   aparece recién en el carrito**, una vez que el sistema conoce cliente + fechas. Explorar un aviso
   sin número (ej. "puede tener descuento") queda como mejora opcional futura, no como fix pendiente.

### Bug dormido (no activo hoy, pero listo para revivir)
7. **`PedidoPage.tsx` (editor de pedido del portal CLIENTE)** — mismo patrón que el bug original
   #405: no usa `respetarPrecioItem: true`, recotiza contra catálogo en vez del precio de línea
   congelado. Hoy inalcanzable porque `MODIFICAR_PEDIDOS_HABILITADO = false`
   (`frontend/src/lib/features.ts`). Si ese flag se reactiva alguna vez, revive el bug en el portal
   cliente — **y dado que #1181 tampoco se mergeó, el editor ADMIN también sigue expuesto hoy**.

### Robustez / concurrencia (mismo patrón ya arreglado en `contabilidad`, sin mitigar acá)
8. ✅ **RESUELTO (Fase 3, #1184).** `reportes/cierres.py::cerrar_mes`/`reabrir_mes` — no tenían
   `pg_advisory_xact_lock` (mismo tipo de carrera ya cerrada en `contabilidad`, 2026-07-02). Fix:
   `_lock_mes(conn, mes)` (mismo parseo `'YYYY-MM'`→`YYYYMM`, namespace **propio**
   `_ADVISORY_NS_REPORTES_MES = 5390421` — NO comparte namespace con `_ADVISORY_NS_CONTAB_MES` a
   propósito, son cierres independientes sobre invariantes distintos) al inicio de ambas funciones.
   Candado: `test_reportes_cierres_db.py::test_lock_serializa_cerrar_mes_concurrente` (Postgres real,
   dos conexiones + `threading.Event` — confirma que una segunda conexión que intenta `cerrar_mes` del
   mismo mes queda bloqueada hasta que la primera libera el lock, no corren en paralelo).
9. ✅ **RESUELTO (Fase 2, #1184).** Reconciliación 100% manual — el riesgo de gobernanza más directo:
   nada avisaba proactivamente si algo se desincronizaba. Fix: `services/finanzas_flujo/reconciliacion.py::estado`
   (une los dos `reconciliar()`) + `jobs/reconciliacion.py::chequear_reconciliacion_y_alertar` corrido
   1×/día desde el scheduler in-process — manda mail a `settings.admin_emails` si `ok=False`. Suma
   además el chequeo `desglose_divergente` (ver arriba) — la red genérica que hubiera cazado #405 sola.

### Seguridad / limpieza (bajo impacto, documentado para no perderlo)
10. ✅ **RESUELTO (Fase 6, #1184).** `routes/reportes.py` — sin `@limiter.limit` en los endpoints de
    escritura (cerrar/reabrir mes, enviar mail) — mismo gap ya cerrado en `contabilidad.py`/`pagos.py`.
    Fix: `@limiter.limit(ADMIN_WRITE_LIMIT)` en `enviar_reporte_mail`, `cerrar_mes_liquidacion`,
    `reabrir_mes_liquidacion`.
11. `/api/cotizar`, rama de línea personalizada (`equipo_id=None`) — no chequea `es_admin` en ese
    punto específico del código (aunque los endpoints que sí persisten ya exigen `require_admin` por
    fuera). Bajo riesgo real hoy; vale la pena que quede explícito si se toca ese código.
12. ~~**N+1 en `services/carrito/readiness.py`**~~ — **RESUELTO.** `precios_catalogo_para_reserva`
    (creación real de pedido del cliente, no solo preview) resolvía el gate de visibilidad + el
    precio de cada ítem del carrito uno por uno. Nueva `services.precios.precios_efectivos_batch`
    (mezcla equipos simples + combos en 2 queries totales, `= ANY(%s)` — mismo patrón ya probado de
    `precios_combo_batch`/`tipos_equipo_batch`, NO el `IN (...)` armado a mano que #643 revirtió en
    `/api/cotizar`) + el gate de visibilidad batcheado (`_equipos_visibles_catalogo`, mismo predicado
    que `equipo_visible_catalogo`, sin duplicar el SQL). Candado:
    `test_precios_batch_db.py` (Postgres real, confirma resultado byte-idéntico al ítem-por-ítem para
    un mix simple+combo). `services/carrito/activos.py` (heartbeat del carrito, autosave) **sigue
    ítem-por-ítem a propósito** — ya evaluado y aceptado (MEMORIA 2026-07-03: carrito de un heartbeat
    es chico, no hot-path). El de `/api/cotizar` sigue siendo DELIBERADO (mismo motivo, incidente #643)
    — ninguno de los dos es un hallazgo pendiente.
13. `ingresos_derivados` (contabilidad) vs. `SALDADO_CTE` (liquidación) — dos queries SQL
    independientes sobre `alquiler_pagos` (percibido vs. devengado, intencional) que podrían divergir
    si el criterio de filtrado de una cambia sin replicarse en la otra. Documentado, no roto hoy.
14. **`PedidoItem.precio_jornada` sin guardarraíl propio** — la garantía "el cliente no decide el
    precio" depende 100% de que el caller use el resolutor correcto (hoy los 2 callers de cliente lo
    hacen bien), no de un candado mecánico en el modelo. Candidato a un test source-scan como
    `test_carrito_precio_efectivo.py`, pero para "todo constructor de `PedidoItem` pasa por un
    resolutor de precio conocido".

**Lo que está BIEN hecho (confirmado, no solo ausencia de bug):** comisiones con `validar_modelo`
que fuerza sumar 100%; `SALDADO_CTE` ya filtra `NOT anulado`; IVA en `Decimal` con `assert
total==neto+iva`; sin secretos hardcodeados en facturación (`ARCA_MASTER_KEY` por env, certs con
Fernet); sin IDOR en factura de cliente; `create_pedido_retry` persiste la plata de forma atómica
(una transacción, un commit); el cliente portal descarta el precio que manda el body y resuelve
100% server-side con gate `visible_catalogo`; cotas de `descuento_pct`/`cantidad` en múltiples capas
(clamp 1-999 en 3 lugares espejados, `descuento_pct` 0-100 en Pydantic Y en la fórmula pura); `IVA`
calculado sobre el neto post-descuento, no sobre el bruto (regresión #502 cubierta por test);
`test_carrito_precio_efectivo.py` hace *source-scan* real (no solo unit test) verificando que
ningún consumidor reinlinea el switch de combo — candado poco común de ver, efectivo contra el
drift #635; el N+1 de `/api/cotizar` es un trade-off DELIBERADO y documentado (revertido tras un
incidente real en prod), no un descuido.

---

_Reglas/criterio en MEMORIA: **auditoría cruzada de plata (2026-07-02)**. Motores
referenciados: `backend/contabilidad/CLAUDE.md`, `backend/reservas/CLAUDE.md`,
`docs/SISTEMA_FACTURACION.md`, `docs/SISTEMA_CARRITO.md`. Iniciativa: #1184 (CERRADA 2026-07-03)._
