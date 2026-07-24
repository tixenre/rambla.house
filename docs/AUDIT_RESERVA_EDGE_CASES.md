# Auditoría de edge cases — flujo de reserva (test log reproducible)

> **Qué es:** catálogo de tests de robustez/seguridad del flujo de reserva, con repro y
> resultado, para **repetir en la tanda de fixes**. Read-only sobre la lógica del core
> (`backend/reservas/` es sagrado). Corrido local con datos reales (clon de staging) —
> setup en `DEPLOY_RAILWAY.md` → "Iterar local con datos reales".
>
> **Cómo correr:** backend local `:8000` + vite `:3000` (fixtures apagadas) + sesión de
> cliente verificada (`staging-login target=cliente cliente_id=209` + bypass de DNI).
> Los probes son `fetch` autenticado desde la consola del browser en `localhost:3000`.
> Pedidos de prueba se etiquetan `notas: "EDGE-TEST-*"` → limpieza:
> `DELETE FROM alquiler_items WHERE pedido_id IN (SELECT id FROM alquileres WHERE notas LIKE 'EDGE-TEST%'); DELETE FROM alquileres WHERE notas LIKE 'EDGE-TEST%';`
>
> Leyenda: ✅ seguro/correcto · 🔴 bug · 🟡 friccion/mejora · 🟢 menor · ℹ️ no testeable.
> Findings consolidados en GitHub issue #965.

Helper usado en los probes:
```js
const post = (b) => fetch('/api/cliente/pedidos',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b),credentials:'include'}).then(async r=>({status:r.status, body: await r.json().catch(()=>null)}));
const cotizar = (b,cred='include') => fetch('/api/cotizar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b),credentials:cred}).then(r=>r.json().catch(()=>null));
const ok = { fecha_desde:'2026-10-06T10:00:00', fecha_hasta:'2026-10-08T12:00:00' }; // mar->jue, horarios válidos
```

---

## Pase 1 — Concurrencia / overlap / stock (alta demanda)

| # | Test | Repro | Esperado | Resultado |
|---|------|-------|----------|-----------|
| C1 | Race: 8 POST simultáneos, ítem `cantidad 1`, mismas fechas | `Promise.all` 8× ítem 208 | 1×201, resto 409 | 🔴 **1×201, 7×500** (no 409) — sin overbooking pero los perdedores crashean |
| C2 | Race con `cantidad 2` (6 concurrentes qty1) | 6× ítem 207 | 2×201, 4×409 | 🔴 **1×201, 5×500** — sólo 1 de 2 unidades disponibles se reservó |
| C2b | **Same-row lock contention con STOCK de sobra** | 3 concurrentes qty1 sobre ítem 324 (`cantidad 16`) | 3×201 | 🔴 **1×201, 2×500** — 500 por pura contención del `FOR UPDATE`, NO por falta de stock |
| C-seq | Secuencial (sin contención): 3× sobre `cantidad 2` y `cantidad 16` | loop secuencial | 201,201,409 / 201,201,201 | ✅ **perfecto** — el gate sin contención anda impecable |
| C-diff | 2 concurrentes sobre ítems DISTINTOS | 221 + 223 a la vez | 2×201 | ✅ **2×201** — el bug es específico de contención sobre el MISMO ítem |
| C6 | Línea duplicada mismo equipo | items:[{x,1},{x,1}] cantidad 1 | 409 (consolida) | ⏳ cubierto por gate (#102); validado indirecto |

---

## Pase 2 — Auth / sin cuenta / IDOR (seguridad)

| # | Test | Esperado | Resultado |
|---|------|----------|-----------|
| A1 | POST pedido sin cookie (`credentials:'omit'`) | 401/403 | ✅ **401** |
| A2 | GET /api/cliente/me sin cookie | 401 | ✅ **401** |
| A3 | IDOR: GET pedido de cliente 52 estando como 209 | 403/404 | ✅ **404** (no filtra datos ajenos) |
| A3b | IDOR documento: GET `/pedidos/393/remito.pdf` ajeno | 403/404 | ✅ **404** |
| A4 | cotizar sin cuenta | 200 sin descuento cliente | ✅ **200**, `descuento_origen: jornadas` (sin descuento de cliente) |
| A5 | Inyectar `cliente_id:52` en body | ignorado (usa sesión) | ✅ **creado con cliente_id 209** (sesión manda) |

---

## Pase 3 — Integridad de precio (seguridad)

| # | Test | Esperado | Resultado |
|---|------|----------|-----------|
| P1 | precio_jornada=1 en body (ítem 213 $3500) | ignorado, usa catálogo | ✅ **line_precio 3500** (no 1) |
| P2 | precio negativo (-99999) | ignorado | ✅ ignorado (usa catálogo) |
| P3 | **Reservar ítem `visible_catalogo=0` por id** (233 = Dron oculto) | rechazar | 🟡 **201 creado** — no chequea visible_catalogo; ítem oculto/sin precio → pedido $0 |

---

## Pase 4 — Descuentos raros

| # | Test | Esperado | Resultado |
|---|------|----------|-----------|
| D2 | descuento cliente 150% | clamp 100% | ✅ **100%**, neto 0 (no total negativo) |
| D3 | descuento cliente negativo (-10) | clamp 0 | ✅ **0%** (no infla el precio) |
| D4 | descuento por jornadas (1/2/4/7/30/60/120/365) | interpolado, topa | ✅ 0→3→11.8→25→**50% (cap a partir de 30j)**; sin overflow |
| D5 | responsable_inscripto → IVA discriminado | con_iva true | ✅ con_iva, IVA 21% ($735 sobre $3500) |
| D-max | cliente 50% vs jornadas | gana el mayor (no acumulativo) | ✅ `max(cliente, jornadas)` |

> ✅ Pase 4 sin hallazgos — la lógica de descuentos/IVA es robusta (clamps, interpolación, no acumulativo). Restaurado cliente 209 a su estado original.

---

## Pase 5 — Búsqueda (tildes, guiones, typos)

| # | Query | Esperado | Resultado |
|---|-------|----------|-----------|
| S1 | "cámara"/"camara"/"CAMARA" | mismos | ✅ **44/44/44** (acento + case insensible) |
| S2 | "sony"/"SONY" | case-insensitive | ✅ **12/12** |
| S3 | "ronin"/"ronan"/"rnin" | fuzzy/partial | 🟡 ronin=1, **ronan=0, rnin=0** — sin tolerancia a typos |
| S4 | "24-70"/"24 70"/"2470" | match | 🟡 24-70=2, "24 70"=2 ✅; **"2470"=0** (sin separador no matchea) |
| S5 | "f2.8" | match | ✅ 6 |
| S6 | inyección SQL / emoji / no-match | sin crash | ✅ inyección=0 (sin efecto), **🎥=130 (todo)** (normaliza a vacío), zxqwzz=0 → "Sin resultados" |

> Empty state "Sin resultados" presente ✅. Búsqueda del catálogo = substring client-side (`normalize.ts`), accent/case-insensible, sin SQL → injection-safe.

---

## Pase 6 — Fechas raras

| # | Test | Esperado | Resultado |
|---|------|----------|-----------|
| F1 | rango ~153 días (API) | ? | 🟡 **201** — el cap de 120 días es UI-only, la API no lo aplica |
| F8 | far future (2030) | ? | 🟡 **201** — sin tope de horizonte en la API |
| F3 | fecha inválida ("2026-13-40") | 400/422 | ✅ **422** con mensaje de formato ISO |
| F6 | hasta < desde (API) | 400 | ✅ **400** "fecha_hasta debe ser posterior" |
| F7 | date-only sin hora (cliente) | 400/422 | ✅ **400** (00:00 fuera de franja — cliente debe mandar hora) |

---

## Pase 7 — Inyección / input (seguridad)

| # | Test | Esperado | Resultado |
|---|------|----------|-----------|
| I1 | notas con `<script>`/`<img onerror>` | sin XSS | ✅ guardado RAW pero **renderizado escapado**: React (sin `dangerouslySetInnerHTML` en user content) + email HTML `jinja2 autoescape=True` |
| I2 | notas > 500 (API) | truncado/validado | 🟡 **1000 guardado** — el cap de 500 es UI-only, la API no valida largo |
| I3 | SQL injection (search + notas) | sin efecto | ✅ search client-side; backend parametrizado |

---

## Pase 8 — Motor: buffer, horarios límite, ítems mixtos

| # | Test | Esperado | Resultado |
|---|------|----------|-----------|
| B1 | Back-to-back dentro del buffer (12h) | 409 | ✅ **409** "Sin stock" (buffer bloquea) |
| B2 | Gap claro (>buffer) | 201 | ✅ **201** |
| B3 | Retiro 18:00 exacto (límite franja weekday) | 201 | ✅ **201** (18:00 inclusivo) |
| B4 | Retiro 18:30 (pasado el límite) | 400 | ✅ **400** fuera de rango |
| B5 | Pedido con ítem inexistente (213 + 99999) | 404 | ✅ **404** "Equipo 99999 no encontrado" |
| B6 | **cotizar** con ítem inexistente | error/ignora | 🟡 **200** — ignora el ítem inválido en silencio (total como si costara 0) |

> ✅ El motor (buffer `buffer_horas_alquiler=12`, límites de franja inclusivos, validación de existencia en creación) es robusto. Único menor: B6 (cotizar no valida existencia).

## Pase 9 — Input robustness + feature flags

| # | Test | Esperado | Resultado |
|---|------|----------|-----------|
| R1 | equipo_id "abc" (string) | 422 | ✅ **422** int_parsing |
| R2 | equipo_id -5 / 0 | 404/422 | ✅ **404** "no encontrado" |
| R3 | cotizar items:[] / sin field | 200 graceful o 400 | ✅ **200** total 0 (sin crash) |
| R4 | Carrito de 50 ítems distintos | 201, sin lag | ✅ **201** (maneja carrito grande) |
| R5 | Endpoint `/modificacion` con flag UI off | ? | 🟡 **422** (vivo) — `MODIFICAR_PEDIDOS_HABILITADO=false` es **frontend-only**; el endpoint backend sigue accesible por API |

> R5: el feature-gating de "modificar pedidos" vive sólo en el front (`features.ts`). El endpoint valida stock/horarios igual, así que no es hueco de seguridad, pero la feature "apagada" es invocable por API. Probablemente la concurrencia (H1) también lo afecta (comparte `_check_stock`).

## Pase 10 — Re-chequeo post iniciativa Estudio/Talleres (#1283 Fases 5-8 + pedido mensual de taller)

> Corrido contra un seed local MÍNIMO propio (6 equipos, 0 clientes de base — no el clon de
> staging de los pases 1-9), armado ad-hoc para esta pasada. `STAGING_LOGIN_SECRET` no estaba
> seteado en el proceso — se reinició uvicorn para poder usar `staging-login`/`staging-verify`
> con 2 clientes de prueba (`EDGE-TEST Uno/Dos`, verificados vía `identity.kyc`, nunca UPDATE
> manual a `dni_validado_at`). Limpieza verificada al final: `alquileres` volvió a las 6 filas
> originales (153,155,206,208,240,242), `clientes=0`, `auth_sessions=0`.

| # | Test | Repro | Esperado | Resultado |
|---|------|-------|----------|-----------|
| P10-1 | IDOR cruzado, 2 clientes reales (detalle + cancelar + 5 documentos) | Uno crea pedido, Dos intenta las 7 superficies | 404 en las 7 | ✅ **404×7** (control positivo: Uno sobre lo propio → 200) |
| P10-2 | Integridad de precio (`POST /api/cliente/pedidos`, no el admin) | `precio_jornada:1` en el body de un ítem de $45000 | ignorado, usa catálogo | ✅ **45000**, no 1 |
| P10-3 | **Overflow de `precio_jornada` vía admin** (`POST /alquileres`, `PedidoItem` sin cota superior) | `precio_jornada:99999999999999` | 4xx limpio | 🟡 **500 crudo** `NumericValueOutOfRange` — ver H6. Rollback limpio (sin pedido huérfano) |
| P10-4 | Concurrencia/sobreventa, equipo stock=1, 10 curl paralelos reales (no browser) | 10× `POST` mismo ítem | 1×201, resto 409 | ✅ **1×201, 9×409, 0×500** — **H1 confirmado RESUELTO** (advisory lock, MEMORIA 2026-06-22) |
| P10-5 | Guardas de stock (cantidad>stock) + buffer (12h, reconfigurado ad-hoc para esta pasada) | cantidad 3 sobre stock 2; back-to-back dentro del buffer | 409 ambos | ✅ **409/409**, mensajes claros |
| P10-6 | Validación de input (8 sub-casos: cantidad 0/-1/1000, equipo_id string/-5/0, fecha malformada/invertida/pasada) | `POST /api/cliente/pedidos` | 4xx limpio, nunca 500 | ✅ **8/8 limpio** (422/400/404 según caso) |
| P10-7 | Descuentos: `max(cliente, jornadas)`, no aditivo | cliente 30% + tier jornadas 50% (10 días) | 50%, no 80% | ✅ **50%**, `descuento_origen:"jornadas"` |
| P10-8 | XSS en `notas` | `<script>alert(1)</script>` vía preview `?format=html` (el PDF real no se pudo probar, ver nota) | escapado | ✅ **`&lt;script&gt;`**, cero `<script>` crudo |

> **Nota de entorno:** el PDF real (`.../remito` sin `?format=html`) da 500 en este sandbox — no
> es un bug de la app: `backend/pdf.py` pide el browser `chromium_headless_shell`, que no está
> instalado acá (solo el `chromium` normal, usado por `ui-audit.mjs`). El preview `?format=html`
> (el mismo HTML antes de rasterizar) sí se pudo ejercitar y confirma el escapado — no se probó
> el rasterizado en sí. Anotado para no re-perder tiempo con esto en la próxima pasada local.

> **P10-1/2/4/6/7/8 reconfirman hallazgos de pases anteriores** (A3/A3b, P1, C1/C2, R1/R2, D-max,
> I1) contra datos frescos — sin drift. **P10-3 es hallazgo nuevo** (H6, abajo). El resto de los
> hallazgos abiertos (H2 ya arreglado por otra iniciativa, H3/H4/H5) no se re-testeó en esta
> pasada — seguir usando los pases 1-9 como referencia para esos.

## Hallazgos (consolidado)

### H1 · 🔴 ALTA · Bookings concurrentes del MISMO ítem → 500 INTERMITENTE (aun con stock de sobra)
- **Qué:** requests que tocan el `SELECT … FOR UPDATE` del mismo equipo a la vez → **una fracción variable crashea con 500** (no 409, no 201). Es un **race intermitente**, NO determinístico: con `cantidad 16` y 3 concurrentes, distintas corridas dieron `1×201+2×500`, `2×201+1×500`, etc.; ítems distintos o multi-ítem a veces dan `2×201`. Secuencial: **siempre impecable** (201/201/409). → La firma (resultado variable corrida a corrida) es un **race en el manejo de conexión/transacción del pool bajo contención del lock**, no un error de lógica.
- **Integridad: SEGURA** — nunca sobrevende (el lock protege el stock) **y los 500 hacen rollback limpio: cero pedidos huérfanos** (verificado: cada tag EDGE-TEST tiene exactamente las filas = cantidad de 201). Lo roto es sólo la **robustez/UX bajo concurrencia**: en un pico de demanda sobre un equipo popular, clientes simultáneos reciben 500 y **no pueden reservar stock disponible**.
- **Dónde:** lock en `backend/reservas/gate.py:175` (`SELECT cantidad FROM equipos WHERE id=? FOR UPDATE`, plain — sin NOWAIT ni lock_timeout). No es pool exhaustion (pool=25, threadpool=21). No hay statement/lock_timeout en `database/core.py`. El crash es Python-level en el camino de espera del lock / manejo de transacción de `create_pedido` (no se pudo capturar el traceback: el log `/tmp/rambla-backend.log` está block-buffered; el fix session debe reiniciar uvicorn con `-u` o mirar logs de Railway).
- **Verificar en prod:** reproducido en local (un solo proceso uvicorn + ThreadedConnectionPool + threadpool). Si prod corre 1 worker, golpea a usuarios reales; con N workers podría degradar distinto. **Confirmar el modelo de workers de Railway.**
- **Severidad real (load test):** vía browser el cap de ~6 conexiones lo enmascaraba. Con **15 curl en paralelo** directo a `:8000` sobre un ítem `cantidad 16` (todos deberían dar 201): **2×201, 13×500 (~87% falla)**. O sea bajo demanda real concurrente sobre un equipo popular, **la mayoría de los intentos fallan con 500** aunque haya stock.
- **Repro (browser, enmascarado):** `Promise.all(Array.from({length:3},()=>post({...ok, items:[{equipo_id:324,cantidad:1}]})))`. **Repro real (bash):** mintear cookie con `staging-login` y disparar 15 `curl … &` en paralelo a `/api/cliente/pedidos` → tally de http codes.
- **Fix sugerido (otra sesión):** capturar el traceback; envolver el camino del gate para que la contención degrade a 409/`503 reintentá` en vez de 500; revisar manejo de transacción/conexión del pool cuando un request bloquea en el lock.

### H2 · 🟡 MEDIA · `POST /api/cliente/pedidos` no chequea `visible_catalogo` → reservar ítems ocultos por id
- **Qué:** el endpoint sólo valida que el equipo EXISTA (`SELECT precio_jornada FROM equipos WHERE id=?` → 404 si no existe), pero **no** filtra `visible_catalogo=1`. Por API se pudo crear (201) un pedido para el ítem **233 "Dron DJI Mini 5 Pro"** (`visible_catalogo=0`, `precio_jornada` NULL) → pedido con **total $0**. La UI sólo muestra ítems visibles, así que es **API-only**, pero es un gap de autorización + permite reservar gratis equipos internos/no listados enumerando ids.
- **Dónde:** `backend/routes/cliente_portal/pedidos.py` (~línea 80-89, el lookup de precios) no exige `visible_catalogo=1` ni `precio_jornada IS NOT NULL`.
- **Fix sugerido:** rechazar (404/400) si `visible_catalogo<>1` o `es_recurso_interno` o sin precio.

### H3 · 🟡 BAJA · Búsqueda del catálogo sin tolerancia a typos
- "ronin"=1 pero **"ronan"/"rnin"=0**. La búsqueda del catálogo es substring client-side (`normalize.ts`), accent/case-insensible pero **no fuzzy** — un cliente que escribe mal el modelo no encuentra nada. Existe `backend/busqueda/` (pg_trgm fuzzy) pero **no se usa para el catálogo**. Además "2470" (sin separador) no matchea "24-70". **Fix:** considerar usar el motor fuzzy del back, o trigram client-side.

### H4 · 🟢 MENOR · Límites de UI no replicados en la API (defensa en profundidad)
- Caps que sólo viven en la UI, no en el endpoint cliente: **rango ≤120 días** (API acepta 153+), **horizonte futuro** (API acepta 2030), **notas ≤500 chars** (API guarda 1000), **cantidad** (ver issue #965 H1: 0/neg/≥1000 → 500). Ninguno es crítico, pero conviene validar server-side también.
- Menor UX: query que normaliza a vacío (emoji `🎥`) → muestra **todo** el catálogo en vez de "sin resultados".

### ✅ Seguridad que está SÓLIDA (verificado)
- Auth requerido (401 sin cookie), sin IDOR de pedidos ni de documentos (404 ajeno), `cliente_id` del body ignorado (manda la sesión), **inyección de precio imposible** (usa precio del catálogo), **XSS-safe** (React escapa + email autoescape), **SQL-injection-safe**. Sin sobreventa bajo concurrencia (H1 es robustez, no integridad; **rollback limpio, cero huérfanos**). Validación de fechas backend correcta (formato/orden/franja, buffer 12h, límites de franja inclusivos). Descuentos robustos (clamps/IVA/no-acumulativo). **Cancelar** libera stock (disponible 1→0→1, re-book OK) y **sin IDOR en cancelar** (404 ajeno).

### H5 · 🟢 MENOR · Otros
- **Idempotencia:** double-submit secuencial del mismo carrito crea pedidos duplicados si hay stock (la UI lo mitiga deshabilitando el botón al enviar). Sin idempotency key en la API.
- **cotizar ignora ítems inexistentes** en silencio (B6) — total como si costaran 0.

### H6 · 🟡 MEDIA · `PedidoItem.precio_jornada` sin cota superior → 500 crudo vía admin (Pase 10, P10-3)
- **Qué:** `precio_jornada` (`routes/alquileres/modelos.py::PedidoItem`) solo valida "no negativo" (`validate_precio`) — a diferencia de `descuento_manual_monto` en el mismo archivo, que SÍ tiene un tope explícito (`>= 2_147_483_647` rechazado) con un comentario que dice literalmente que existe para evitar este mismo problema (cierre de la auditoría de contabilidad, 2026-07-02). `alquiler_items.precio_jornada` es `INTEGER` (tope Postgres 2147483647); un valor mayor (probado: `99999999999999`) rompe ese tope en el INSERT y ni `create_pedido` ni `update_alquiler_items` traducen la excepción (`map_pg_errors` está en contabilidad/pagos/facturación/productoras/clientes pero no en `routes/alquileres/`) → cae cruda al handler global → **500** con `{"detail":"NumericValueOutOfRange: integer out of range"}` expuesto tal cual en local (en Railway el body sería genérico, pero el 500 igual ocurre).
- **Alcance:** solo admin puede mandar `precio_jornada` arbitrario (`POST /alquileres`, `PUT /alquileres/{id}/items`) — el endpoint del cliente (`POST /api/cliente/pedidos`) ignora el valor del body y usa el precio del catálogo (P10-2), así que no es explotable por un cliente. Confirmado que NO deja pedidos huérfanos (rollback limpio).
- **Fix sugerido:** mismo patrón que `_validar_descuento_manual_monto` — un `field_validator` en `PedidoItem.precio_jornada` que rechace `>= 2_147_483_647` con un mensaje 422 claro.

---

## Qué NO se cubrió (para futuras pasadas)
- **Estudio (`/estudio`)**: reusa el mismo motor de reservas (equipo "centinela" + gate) → **muy probablemente sufre el mismo H1** bajo concurrencia. No se probó por API (flujo más complejo). Pendiente.
- **Flujo de modificación** real (el endpoint está vivo pero la UI lo apaga) — sólo se probó su existencia.
- **Cancelación por cliente**, side-effects de **emails/PDFs** reales, multi-tab/stale state, y un test de carga sostenida (más allá de 8 concurrentes).

## Propuestas de mejora de UX (nuevas)
- **Concurrencia (raíz de H1):** que la contención degrade a un mensaje claro ("alguien está reservando este equipo, reintentá") con auto-retry, en vez de 500. Es lo que más se va a notar en demanda real.
- **Disponibilidad honesta en mobile:** el badge debe decir disponible-para-tus-fechas, no stock total (issue #965).
- **Búsqueda tolerante a typos** (usar el motor fuzzy del back, o trigram client-side) — hoy "godox" mal escrito no encuentra nada.
- **Feedback del tope de stock:** cuando el `+` se deshabilita por llegar al máximo, mostrar "Máximo disponible (N)".
- **Cotización del mini-bar = total real** (con descuento), hoy muestra el bruto (issue #965).
- **Validaciones server-side espejo de la UI** (cantidad 1-999, rango ≤120d, notas ≤500) → respuestas 4xx limpias en vez de 500, y defensa si la UI falla.
