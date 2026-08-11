# Buzón de propuestas de skills

> **Solo proponer, no aplicar.** Este archivo es el inbox durable de mejoras detectadas durante el uso
> de los skills. La sesión deposita acá; el dueño aprueba (igual que la memoria). El supervisor puede
> validar las propuestas antes de aplicarlas. **Git guarda todo** — no se borra, solo se archiva.
>
> Formato por entrada: `fecha · skill · qué cambiar · por qué`.
> Una vez aprobada una propuesta, marcarla con `✅ aplicada — <PR o commit>`.

---

<!-- Ejemplo de entrada:
2026-06-23 · pendientes · Agregar paso de "cerrar stale issues automáticamente si > 90 días sin actividad y
etiquetados como `someday`" al paso 2 (Triage con evidencia) · Detecté que hay 8 issues con >90 días
sin actividad que bloquean la vista real de la cola activa; el criterio es claro y no requiere criterio
del dueño.
-->

2026-06-24 · pendientes · La nota de "Herramientas" dice "acá **no hay `gh` CLI** → todo por `mcp__github__*`",
pero en la app de Mac (esta sesión) el `gh` CLI **sí está disponible y funciona** (creé el tracker #1029,
listé labels, todo con `gh`). Proponer: cambiar la nota a "usá `gh` CLI cuando esté disponible (app de
Mac/terminal); caé a `mcp__github__*` solo si no lo está" · Por qué: la nota actual desorienta — manda a
usar MCP cuando `gh` es más directo y ya funciona; primer uso real del skill lo destapó.
  ↳ 2026-06-29 · corroboración (retro de iniciativa) · una sesión en la **web/nube** confirma la otra
    mitad: acá `gh` **no** está disponible y hay que caer a `mcp__github__*` sí o sí → la verdad es
    **dependiente del entorno**, lo que valida el wording **condicional** por sobre cualquier absoluto.
  ✅ aplicada — cierre de gobernanza 2026-06-30 (wording condicional en `pendientes/SKILL.md`)

2026-06-29 · mantenimiento · La lista "**nunca se borra**" de motores únicos (sección 2, "Respetar la MEMORIA":
`backend/{reservas,reportes,busqueda,services/branding}/`) quedó atrás de la familia: **omite `contabilidad`
(2026-06-07) y `services/contenido` (2026-06-29)**. Proponer agregarlos · Por qué: lo cazó el barrido de
cross-refs del **retro de iniciativa**; una lista incompleta podría no frenar el borrado de un módulo vivo.
✅ aplicada — cierre de gobernanza 2026-06-30 (`mantenimiento/SKILL.md`)

2026-06-25 · gobernanza · Agregar un check de **"staleness por divergencia" de los manuales de sistema**
(`docs/SISTEMA_*.md`, convención _2026-06-25 — Manuales técnicos por sistema_): detectar si un manual no se
tocó mientras su motor (los paths que referencia) cambió N veces en git → proponer revisarlo en el cierre
de gobernanza. **Detecta + propone, no mantiene solo** (el supervisor por cambio + quien toca el código siguen
siendo el mantenimiento real). · Por qué: hoy los manuales los vigila el supervisor (por cambio) + `check-docs`
(links/estructura), pero **nada detecta el desfase de CONTENIDO**. Un check periódico sería la red de seguridad
que cierra el círculo. ~~Prematuro con 1 solo manual (fotos)~~ — al cierre 2026-06-30 ya hay **9 manuales**
(`ARCA, AUTH, CARRITO, CHECKOUT, CONTENIDO, FACTURACION, FOTOS, IDENTITY, SPECS`) → la condición de diferido
ya no aplica.
✅ aplicada — cierre de gobernanza 2026-06-30 (check agregado al método de `gobernanza/SKILL.md` §2)

2026-06-30 · calidad-tests · Caso testigo: un test que compara fechas contra `now_ar()` (hora de Argentina, la
convención del repo) debe construir sus fechas con `now_ar().date()`, **NO** con `datetime.date.today()` (UTC en
CI) → si no, falla ~00:00–03:00 UTC (UTC ya es el día siguiente que AR). Sumarlo como gotcha de "tests frágiles /
edge cases de fecha" · Por qué: apareció como **flake real** en `test_check_fechas_pasada_cliente` (#1131) — tapó
el CI verde de un cambio no relacionado y costó un diagnóstico; el test usaba un reloj distinto al del código bajo
prueba. Patrón repetible en cualquier test de fechas (now_ar es la convención en todo el backend).
  ↳ 2026-06-30 · corroboración (retro #1136) · el mismo anti-patrón apareció en **código de producción**, no solo
    tests: `tablero.mes_actual()`, `movimientos._mes_de_fecha` y `pagos.py` usaban `date.today()` (UTC) donde debía
    ir `now_ar()`. Se corrigieron en #1136 (vía `services.fechas.mes_actual_ar`). El gotcha **se generaliza**: "el
    ahora/hoy del repo es `now_ar()`, nunca `date.today()`" — vale para prod y tests. Patrón repetido → señal fuerte.
  ✅ aplicada — cierre de gobernanza 2026-06-30 (caso testigo 3d en `calidad-tests/SKILL.md`)

2026-06-30 · mantenimiento · Método: para decidir **qué consolidar en un módulo fuente-única** (y qué dejar en su
motor), despachar un **workflow de lectores paralelos** que clasifiquen cada uso por categoría —
PRIMITIVA-DAL / DOMINIO-MOTOR / DISPLAY-FORMATO / CANDIDATO-CONSOLIDAR. La clasificación hace el corte objetivo:
solo los CANDIDATO se mueven; el dominio de cada motor se queda. · Por qué: en el retro de `services/fechas` (#1136)
este barrido (4 lectores sobre reservas/precios/alquileres/portal/jobs/reportes/contabilidad/auth/ical/pdf) cazó
los candidatos reales (ventana de modificación, horarios) y **descartó con fundamento** los falsos (buffer→reservas,
jornadas→precios) — evitó mover lógica de dominio por "parece fecha". Repetible para cualquier consolidación grande.
✅ aplicada — cierre de gobernanza 2026-06-30 (método sumado a "Más allá del código muerto" en `mantenimiento/SKILL.md`)

2026-06-30 · mantenimiento · Gotcha de verify al **cambiar el contrato de props de un componente compartido**:
(a) el `tsc` local con **cache incremental** puede dar OK falso tras un merge (no rechequea todo) → correr fresco
(`rm tsconfig.tsbuildinfo`) o `tsc -b --force`; (b) el CI de un PR **mergea con el `dev` actual**, que puede tener
**call-sites nuevos** aparecidos después de tu último merge → re-mergear `dev` y re-verificar antes de cerrar. ·
Por qué: en #1136 un 3er call-site de `CartDrawerView` (`catalogo-organismos.tsx`) llegó de `dev` después del merge
→ `tsc` local pasó (cache) pero el CI del PR falló; costó 2 vueltas de CI. Pasó **dos veces** en la misma sesión
(dev se movió 3×). Sumar a la disciplina de "verificar antes de cantar verde".
✅ aplicada — cierre de gobernanza 2026-06-30 (gotcha en `mantenimiento/SKILL.md` Frente E + puntero en
`pulido-frontend/SKILL.md` §4 VERIFICAR, porque también aplica fuera de splits)

2026-06-30 · design-system · Caso testigo (autoría de specimens de la vitrina): un componente de
producción afinado para su contenedor real —`content-visibility` + `aspect-ratio` + intrinsic-size
(ej. `EquipmentCard`: `aspect-square` + `content-visibility:auto` con `contain-intrinsic-size 280px`,
pensado para la grilla **angosta** del catálogo)— se **rompe visualmente** en el lienzo genérico
(ancho) de la vitrina: la foto cuadrada se dispara (~600px) y las cards se solapan. Regla a sumar al
método: al embeber un componente real en la vitrina, **espejar las restricciones de su contenedor de
producción** (ancho de grilla / columnas), no un grid genérico ancho. · Por qué: el specimen de
`EquipmentCard` se shippeó a staging con las cards pisándose (`grid-cols-1→sm:2→xl:3`, demasiado
ancho); lo cazó el **dueño visualmente**, no los checks estáticos (tsc/eslint/prettier no ven layout,
y la ruta `/admin/diseño` es admin-gated → no se renderiza local). Fix `f465a18d`: espejar
`categoria.$slug.tsx` (`grid-cols-2→md:4` + cap de ancho). Repetible para cualquier futuro specimen de
un componente container-coupled.
✅ aplicada — cierre de gobernanza 2026-06-30 (caso testigo 3d en `design-system/SKILL.md`)

2026-07-14 · pulido-frontend · Al verificar un cambio de LAYOUT (grid-column spanning, posicionamiento
absoluto/relativo, algo que no es solo color/texto), preferir medición estructural por JS
(`getComputedStyle`, `getBoundingClientRect`, leer `gridColumn`/`gridRow` computados) por sobre
scrollear + comparar screenshots — sumar el screenshot solo al final, con el viewport agrandado
(`resize_window` a una altura que contenga todo el contenido) en vez de scrollear un viewport chico. ·
Por qué: verificando el calendario admin (barras multi-día + color por estado), `computer scroll`
tiró timeouts falsos repetidos (el scroll SÍ se aplicaba pero la tool reportaba error) y hubo un
desfasaje real entre las coordenadas de `getBoundingClientRect()`/clicks y el recorte del screenshot
(un elemento medido en `top:180` aparecía en la mitad inferior de la imagen) — varios intentos
perdidos antes de confirmar el fix por JS (`gridColumn` computado + `backgroundColor` variando por
estado real, cambiando un estado de prueba y viendo el color reaccionar) y recién después un
screenshot limpio agrandando la ventana a 1280×1400. La medición por JS hubiera confirmado el fix en
el primer intento.
✅ aplicada — cierre de gobernanza 2026-07-26 (gotcha sumado a `pulido-frontend/SKILL.md` §4 VERIFICAR)

2026-07-25 · auditoria-profunda · **Bug real en `ui-audit.mjs`**: el detector de "scroller interno"
(`[...document.querySelectorAll("*")].find(el => overflow-y auto/scroll && scrollHeight>clientHeight+200)`)
toma el PRIMER elemento scrolleable en orden DOM — en `/admin/*` eso es el **sidebar** (tiene su propio
`overflow-y:auto` para su lista de nav), no el contenido principal. Resultado: **las ~90 capturas
desktop (768/1280/1440) de las ~30 pantallas admin muestran SOLO el sidebar**, recortadas — verificado
comparando `admin-talleres__1280.png` (solo sidebar) contra `admin-talleres__375.png` (contenido real,
correcto — a esos anchos el sidebar se colapsa/oculta, no compite). La medición (`tap_lt44`/`font_lt_min`/
etc, vía `page.evaluate`) sigue siendo válida — es SOLO el PNG el que queda inútil como evidencia visual.
Proponer: excluir contenedores de navegación (`nav`, `aside`, o un contenedor cuyo ancho sea mucho menor
al viewport) del detector, o preferir el scroller de MAYOR área en vez del primero en orden DOM. · Por
qué: sin este fix, cualquier auditoría de `/admin/*` en desktop cree tener evidencia visual y en
realidad audita el sidebar 30 veces.
✅ aplicada — cierre de gobernanza 2026-07-26 (detector unificado en `ui-audit.mjs`: excluye
`nav`/`aside`/`[role=navigation]` y prefiere el de mayor área, vía `window.__findAuditScroller`
inyectado una sola vez con `page.addInitScript` — antes duplicado en `scrollLoad` y `main`)

2026-07-25 · auditoria-profunda · **Degradación acumulativa real**: correr el harness sobre >~15
pantallas seguidas en el MISMO browser/tab (`GROUP=admin` completo, ~30 pantallas × 5 viewports = 150
screenshots) empieza a fallar con `Timeout 30000ms exceeded... waiting for fonts to load` a partir de
la captura ~15-16, sin importar qué pantalla es (probado: pasó en la secuencia dashboard→pedidos→
pedido-detalle→**pedido-nuevo** una vez, y en equipos→equipo-editar→equipo-nuevo→**equipos-calidad**
otra vez — mismo síntoma, screens distintos). Aislado: cada pantalla sola (browser fresco) captura en
<300ms sin error, incluso replicando el `scrollLoad()` exacto del harness. No es una pantalla rota — es
recurso acumulado (memoria/GPU del proceso Chromium) en una sesión larga, probablemente agravado por la
RAM limitada de un sandbox. Proponer: documentar como default correr en lotes de ~10 pantallas o menos
por invocación (nuevo `chromium.launch()` por lote), no la matriz completa de una sola corrida — mismo
`LABEL` mergea el `_report.json` entre lotes, así que no se pierde nada. · Por qué: sin saberlo, una
corrida completa de `GROUP=admin` pierde ~80% de las capturas por este techo, y el primer intento se
reportaría como "la mayoría de las pantallas admin rotas" cuando en realidad es un límite de la corrida.
✅ aplicada — cierre de gobernanza 2026-07-26 (nota de método sumada a `auditoria-profunda/SKILL.md`)

2026-07-25 · auditoria-profunda · El harness asume su propia ubicación en disco para resolver la carpeta
de salida (relativo tipo `../../../docs/audit-ui-screenshots` desde `.claude/skills/auditoria-profunda/`).
Si se copia/ejecuta desde otro path (necesario en este sandbox: `playwright` solo resuelve por ESM si el
script vive dentro de la cadena de ancestros de `frontend/node_modules`, así que hubo que copiar el
harness a `frontend/tmp_*.mjs` para poder correrlo), el path relativo apunta a un lugar completamente
distinto (en este caso, `/home/docs/...` en vez de `/home/user/rental/docs/...`) **sin ningún error** —
las capturas se guardan igual, solo que en el lugar equivocado. Proponer: resolver el path de salida
contra la raíz del repo (`git rev-parse --show-toplevel`) en vez de relativo a `import.meta.url`. · Por
qué: se pudo recuperar moviendo los archivos a mano porque se revisó explícitamente, pero es un modo de
falla silencioso — alguien que no revise podría reportar "no generó nada" cuando en realidad generó todo
en otro lado.
✅ aplicada — cierre de gobernanza 2026-07-26 (`REPO` resuelto vía `git rev-parse --show-toplevel` en
`ui-audit.mjs`, con fallback al método relativo si git no está disponible)

2026-07-25 · auditoria-profunda · Gotcha de método: navegar a `/admin/pedidos/nuevo` (aunque sea solo
para un screenshot, sin tocar nada) **crea un pedido real en la base** (`estado:"borrador"`, sin cliente,
$0) — es un `useEffect` en el mount que llama `createPedido` y redirige al editor. Correr el harness
sobre esa pantalla 2 veces (una corrida fallida + un retry) dejó 7 pedidos huérfanos que había que
identificar y limpiar aparte al final (no quedan tageados `EDGE-TEST`, hay que reconocerlos por
`cliente_id NULL + monto_total 0 + fecha_desde/hasta = hoy/mañana`). Proponer: sumar esta nota al Motor 2
del skill — si se visita esta pantalla, sumar su limpieza (`DELETE /api/alquileres/{id}` de los
borradores creados) al checklist de limpieza final, no asumir que navegar = solo-lectura. · Por qué: es
un side-effect real de UNA visita a una pantalla que en cualquier otra parte del sitio sería inocua —
fácil de perder en la limpieza si no se sabe de antemano.
✅ aplicada — cierre de gobernanza 2026-07-26 (gotcha sumado al Motor 2 de `auditoria-profunda/SKILL.md`)

2026-07-25 · mantenimiento · La nota de Frente A ("no hay linter de Python en CI") está stale —
`backend/ruff.toml` existe y `ruff` corre pineado (0.15.18) como gate de CI. (Nota: el agente de Frente A
de esta misma pasada dijo "no lo escribo, necesita aprobación del dueño" — pero el propio encabezado de
este archivo dice que la sesión **deposita** libremente acá y el dueño aprueba **aplicar**, no depositar;
corrigiendo ese malentendido de paso.) · Por qué: la sección "Inventario con herramientas" del skill
sigue recomendando instalar ruff manualmente como si no estuviera ya en el pipeline — desactualiza el
paso 1 del Frente A.
✅ aplicada — cierre de gobernanza 2026-07-26 (nota corregida en `mantenimiento/SKILL.md` Frente A ·
paso 1: `ruff` ya corre en CI con ruleset conservador, este barrido usa un ruleset más amplio)

2026-07-29 · pulido-frontend · Tensión no cubierta: "el bug de plata se reporta, no se arregla en la
pasada de pulido" **deja de aplicar cuando el propio pulido hace VISIBLE un número que antes estaba
oculto**. Caso testigo: al unificar las filas de "qué incluye este turno" con las de "Equipos", la fila
"Espacio" pasó a mostrar su subtotal — y ahí se vio que `GET /admin/estudio/reservas/cotizar` calculaba
SIEMPRE el precio de lista (`precio_hora * horas`) aunque el guardado persistiera la tarifa negociada
que el admin tipea. Diferirlo habría significado shippear una línea que muestra un número distinto al
que se cobra (peor que antes, cuando esa fila no mostraba nada). Proponer: agregar al paso 2 (RUTEAR)
que si un cambio de presentación EXPONE un número de plata que antes no se veía, el fix del número deja
de ser diferible — o se arregla en la misma pasada (con test), o no se muestra el número. · Por qué: la
regla actual, leída literal, empuja a shippear un dato incorrecto a la vista.

2026-07-29 · pulido-frontend · Gotcha de verificación: al medir alineación por JS (`getBoundingClientRect`,
como ya recomienda el paso 4), **scopear el selector a la sección bajo prueba**. Un selector global
(`document.querySelectorAll("li")` + clase del subtotal) barrió filas de TRES secciones distintas de la
página —cada una en un contenedor de ancho distinto— y devolvió "no alinean" cuando las filas que
importaban sí alineaban: un falso negativo que costó una vuelta de diagnóstico. Proponer: sumar al paso 4
"medí dentro del contenedor de la sección (`section.querySelectorAll(...)`), no en `document`". · Por qué:
el paso 4 ya empuja a medir por JS en vez de screenshot, pero no advierte que el alcance del selector es
justo donde se cuela el falso negativo.

2026-08-10 · pulido-frontend · El paso 1 (Diagnosticar) asume las tools `preview_*`
(`preview_screenshot`/`preview_resize`/`preview_snapshot`/`preview_inspect`/`preview_eval`) como el único
camino para "ver la pantalla viva". En esta sesión (Claude Code remoto/CLI, sin esas tools) no existían —
la auditoría de `/admin/talleres` se hizo igual, armando a mano un script Playwright chico (mismo patrón
que `staging-login` + `@playwright/test` ya establecido en MEMORIA *2026-06-20*) para navegar y capturar
desktop+mobile. Funcionó bien, pero es repetir a mano un paso que el skill da por garantizado. Proponer:
en el paso 1, aclarar que `preview_*` es el camino cuando está disponible (Claude Code interactivo/web con
panel de preview); en su ausencia, el camino es un script Playwright puntual (`chromium.launch` +
`staging-login` vía `context.request.post`, capturas con `page.screenshot`) — mismo resultado, sin
depender de tooling que no todos los entornos tienen. · Por qué: el skill se invoca desde cualquier
sesión (interactiva, remota, CLI); asumir un tooling específico sin decir la alternativa hace que cada
sesión sin `preview_*` tenga que redescubrir el mismo patrón de reemplazo.
