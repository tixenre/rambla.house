---
name: pulido-frontend
model: opus
last-reviewed: 2026-08-14
version: 1.2
description: El go-to para AUDITAR y MEJORAR una pantalla/flujo del front que YA EXISTE y funciona, pero "está raro", no se ve bien, o se puede pulir. Flujo completo de calidad de experiencia — diagnosticar (rúbrica front-end, ejes P-U de PROTOCOLO) → rutear por riesgo → mejorar DS-first en 4 lentes (UX · UI/estética · modularización · performance) → verificar (preview_* tools + mobile gate + a11y + perf) → trackear página-por-página. Úsalo cuando el dueño diga "pulí la UX/UI", "esta pantalla está rara / no me cierra", "optimizá el flujo de X", "que se vea perfecto / más lindo", "mejorá la experiencia de X", "está lento el front", "modularizá esta pantalla", "auditá la UI de X con criterios de UX", o cuando detectes fricción/inconsistencia visual mientras trabajás. NO es para diseñar desde cero (eso es Claude Design), ni para salud del repo / código muerto / seguridad (skill `mantenimiento`). Este skill DIAGNOSTICA qué falla en la experiencia y lo PULE de a poco — el corazón NO es una lista de fixes, sino el MÉTODO: recorrer la pantalla en vivo con rúbrica → rutear por riesgo → reusar/extender la librería del DS (nunca one-offs) → verificar contra el render real (preview tools), mobile y accesibilidad → no romper el core de reservas. Método seguro + tests + supervisor en `mantenimiento`.
---

# pulido-frontend — auditar y pulir el front, pantalla por pantalla

Codifica **cómo** se sube la calidad de experiencia de Rambla sin romper nada y sin
churn de bajo valor: no la lista de lo que ya se pulió, sino el **método** para que cada
pasada de UX/UI futura sea rigurosa, consistente con el design system y segura. Es la
contraparte de front-end del par `PROTOCOLO` (rúbrica) + `mantenimiento` (método) que
ya existe para el backend.

## Dónde encaja (no dupliques: delegá)

Dos skills de front-end en la capa activa, un skill de código. Elegí por el **disparador**, no por el tema:

| Skill | Pregunta que responde | Entrada → Salida |
|---|---|---|
| **`pulido-frontend`** (este) | "esta pantalla **anda pero no está buena** — encontrá qué falla y mejorala, sistemático" | ruta en vivo + el DS → hallazgos UX/UI/perf/a11y → fixes in-place chicos **o** brief a Claude Design para un rediseño grande |
| `design-system` | "el DS está drifting / auditá el DS completo" | auditoría sistémica, dashboard `/ds`, propone issues — solo lee, no edita |
| `mantenimiento` | "**auditá/limpiá el repo** sin romper" | el repo → código sano (muerto/seguridad/ramas/issues/split) |

Qué reusás (NO lo re-expliques acá):

- **Verificación visual** → `preview_*` tools (screenshot, snapshot, inspect, eval). Son la fuente
  canónica para ver el render real en el browser preview. Para rutas autenticadas (admin/portal) usá
  **staging-login** + browser real en staging, o entorno local con BD clonada (MEMORIA *2026-06-20*).
- **Librería del DS y reuse-first** — chequear si el primitivo ya existe antes de crearlo; extraer
  a `src/design-system/{ui,kit} + src/components/{rental,admin}` + tokens en `src/design-system/styles/`.
  No inventar componentes sueltos.
- **Método seguro** (rutear por riesgo, red de tests, commits atómicos, supervisor, el dueño prueba
  en staging) → `mantenimiento`. La regla de oro **"verificá antes de actuar"** y **"honestidad >
  actividad"** valen igual acá.
- **Rúbrica** → `docs/PROTOCOLO.md`. El backend se diagnostica con los ejes A-O; el **front-end con
  los ejes P-U** (agregados ahí por este skill). El mobile gate de PROTOCOLO es obligatorio.
- **Rediseño grande desde cero** (no pulido incremental) → se escribe un **brief**
  (`docs/design-brief-<feature>.md`), lo toma **Claude Design** en otro proyecto, y la implementación
  vuelve como task de este skill. Este skill **decide** cuándo hace falta eso (ver paso 2).

## El flujo: diagnosticar → rutear → mejorar → verificar → trackear

### 1 · DIAGNOSTICAR (read-only) — recorrer la pantalla con la rúbrica

No se toca nada todavía. Se **ve** la pantalla viva y se mapea la deuda de experiencia con los
**ejes P-U** de [`docs/PROTOCOLO.md`](../../../docs/PROTOCOLO.md):

- **P · UX / flujo** — ¿se completa la tarea sin fricción? pasos de más, callejones, **una sola
  forma de hacer cada cosa** (no 3 controles para 1 acción), labels que **prometen lo que hacen**.
- **Q · Jerarquía visual** — un solo foco primario por pantalla, el dato clave anclado, lectura
  clara, aire. (Dos CTAs del mismo peso = el ojo no sabe dónde ir.)
- **R · Consistencia con el DS** — tokens (cero hex/escala genérica), componentes reusados (no
  one-offs), spacing/eyebrows/tipografía consistentes, estados canónicos (`EstadoBadge`/`EmptyState`/skeleton).
- **S · Accesibilidad** — contraste WCAG (¡amber sobre blanco es borderline!), tap targets ≥44px,
  inputs ≥16px, `:focus-visible`, `aria-label` en icon-buttons, focus-trap en modales, orden de foco.
- **T · Performance percibida** — LCP mobile, lazy de imágenes/rutas, skeleton que espeja el layout
  (cero CLS), memo **solo con lag medido**, payloads, nada de trabajo pesado en el render path.
- **U · Estética / acabado** — alineación, ritmo, densidad, micro-interacciones canónicas, copy (voz
  "vos", precios por `formatARS()`, empty states accionables), pulido de detalle.

**Cómo VER (no adivinar):**

- **Ruta pública** → `preview_*` tools: `preview_screenshot` (desktop + `preview_resize` para mobile
  390px), `preview_snapshot` para estructura, `preview_inspect` para valores de CSS/theming,
  `preview_eval` para medir contrastes reales vía canvas (oklch → sRGB por pixel sampling, no creerle
  al `getComputedStyle` que devuelve oklch en algunos browsers — ver MEMORIA *2026-06-22*).
- **Sin `preview_*` disponible** (sesión CLI/remota, sin panel de preview) → el fallback es un script
  Playwright puntual (`chromium.launch` + `staging-login` vía `context.request.post` para rutas
  autenticadas + `page.screenshot` desktop/mobile), mismo patrón que `staging-login` +
  `@playwright/test` ya establecido (MEMORIA *2026-06-20*) — mismo resultado, sin depender de tooling
  que no todos los entornos tienen.
- **Estados internos** (editor, modal, dark) → `preview_click` + `preview_fill` + `preview_eval` para
  evaluar JS de React.
- **Ruta autenticada (admin/portal) o que use datos/assets reales** → los fixtures no alcanzan: los bugs
  de theming/datos no se ven con mocks (caso testigo: el wordmark custom del admin se veía amber sobre los
  topbars de color, invisible con el SVG bundleado local). Dos caminos, ambos vía **`staging-login`**
  (`target:"cliente"|"admin"`; MEMORIA *2026-06-19*, secreto en env, **nunca** en el repo): (a) recorrer
  **staging** con browser real; (b) **montar el entorno local con datos reales** —backend local + **BD de
  staging clonada a Postgres local** (dump read-only) + staging-login— y verificar en vivo
  (MEMORIA *2026-06-20 — Iteración local con datos reales*; setup en `docs/DEPLOY_RAILWAY.md`).
  **Nunca** apuntar el backend local a la base remota. Caso testigo: la auditoría de **Pedidos** (staging)
  y el pulido del **portal cliente** (clon local, impersonando un cliente).
- **Mobile es obligatorio** — viewport real 375×667 (`preview_resize 390`) — no alcanza leer clases `hidden sm:*`.

**Salida** = hallazgos en formato `pantalla:zona | eje | 🔴/🟡/🟢 | qué | propuesta`. Igual que el
backend, **todo 🔴 se confirma leyendo el código** antes de reportarlo (un agente exagera o se queda
corto). Esto es lo que produjo el audit de Pedidos; es la entrada de los pasos siguientes.

### 2 · RUTEAR por riesgo (mismo criterio que `mantenimiento`)

El cuidado es proporcional al radio de explosión. Clasificá cada hallazgo:

| Tipo | Qué es | Camino |
|---|---|---|
| **Pulido in-place chico** | label, color/token mal, spacing, aria, copy, lazy de una imagen | fix directo → `dev` (commit atómico) |
| **Refactor de componente** | extraer un one-off a la librería, unificar un patrón duplicado | reuse-first; red de tests; puede ir a `dev` si no cambia conducta |
| **Rediseño de pantalla/flujo** | la pantalla necesita repensarse (no parchar) | **brief → Claude Design**; rama + PR; por fases si es grande (v2 al lado de v1) |
| **Toca lo que ve el cliente / core de reservas / plata** | rutas cliente, estados de pedido, disponibilidad | **rama + PR + supervisor + aviso**; el motor de reservas es sagrado, el pulido es **presentación**, no toca el cálculo |

Regla de ruteo (de la MEMORIA *2026-06-08 — Workflow de cambios*): trivial/normal → `dev` directo;
grande / sensible / core de reservas / lo que ve el cliente → rama (`claude/<desc>`) + PR. **Nunca a
`main` directo. No mergear con CI en rojo.**

**Excepción dura: un número de plata recién EXPUESTO no es diferible.** La regla "un bug del motor se
reporta, no se arregla acá" (ver Anti-objetivos) asume que el bug ya era visible antes del pulido. Si
la pasada **hace VISIBLE un número que antes estaba oculto** (ej: unificar filas expone un subtotal
que antes no se mostraba) y ese número resulta incorrecto, diferirlo shippea un dato de plata mal —
peor que no mostrar nada. Ahí: arreglalo en la misma pasada (con test), o no mostrés el número
todavía. Caso real: unificar "qué incluye" con "Equipos" expuso que el Estudio cotizaba precio de
lista en vez de la tarifa negociada persistida — se arregló en la misma pasada.

> **La máquina de estados de la UI se DERIVA, no se inventa.** El
> "siguiente paso" / qué transición ofrecer sale de (a) lo que la pantalla ya hace y (b) las
> precondiciones que valida el backend (`ESTADOS_VALIDOS` + checks en `routes/alquileres.py`). El flujo
> feliz lo guía la UI; el backend es la red que rechaza lo inválido. No hardcodees un grafo nuevo.

### 3 · MEJORAR — DS-first, en 4 lentes

Reuse-first **siempre**: antes de escribir, mirá si el primitivo ya existe (`Button`, `EstadoBadge`,
`PriceBlock`, `StatCard`, `EmptyState`, `StepperPill`, `Input`/`SearchInput`/`FieldLabel`…). Si existe
→ reusalo. Si el pulido necesita una pieza nueva reutilizable → **extraela a la librería**, no la
inlinees. Si un patrón está copiado en lista + editor → extraé **un** componente compartido (evita
drift). Las 4 lentes:

- **UX** — un solo modelo mental por acción; labels que ejecutan lo que dicen; menos pasos; empty/loading/
  error states accionables; el "siguiente paso" único y derivado del estado real.
- **UI / estética** — todo color de un token (tier 1-2; tiers 3-4 solo en constantes centralizadas;
  el guardrail de ESLint `no-restricted-syntax` bloquea escala genérica/hex); un `Section`/`RailSection`
  con padding consistente; eyebrows y tipografía por recipe; jerarquía con aire; micro-interacciones
  canónicas (press scale, hover lift, `--ease-*`).
- **Modularización** — partir god-components, extraer subcomponentes con frontera neta, mover lógica
  sensible a un hook único (caso `usePedidoDraft`: un solo camino de escritura para lista y editor).
  Move-verbatim cuando sea estructura pura; cambio de conducta = red de tests + aviso.
- **Performance** — `loading="lazy"` en imágenes, lazy de rutas pesadas, skeleton que espeja layout
  (cero CLS), `useMemo`/`memo` **solo si hay lag medido** (memo sin problema medido = deuda, no
  calidad), payloads chicos, nada bloqueante en el render. LCP mobile es el norte.

Todo cambio respeta `docs/DESIGN_SYSTEM.md` (tokens, componentes, voz/tono, mobile rules, "patterns
que nunca se rompen") — es la fuente canónica.

### 4 · VERIFICAR — render-compare + mobile + a11y + perf

Nada se da por bueno sin verlo:

- **Render-compare** — capturá la **ruta real** (desktop + mobile con `preview_screenshot` + `preview_resize`) y compará contra el antes. Para rutas autenticadas, verificá con screenshots en staging.
- **Cambios de LAYOUT (grid-column spanning, posicionamiento absoluto/relativo) — medí por JS, no por
  scroll+screenshot.** Preferí medición estructural (`getComputedStyle`, `getBoundingClientRect`, leer
  `gridColumn`/`gridRow` computados) por sobre scrollear + comparar capturas; sumá el screenshot solo al
  final, con el viewport agrandado (`resize_window` a una altura que contenga todo) en vez de scrollear un
  viewport chico. Caso testigo: verificando el calendario admin (barras multi-día + color por estado),
  `computer scroll` tiró timeouts falsos repetidos (el scroll SÍ se aplicaba pero la tool reportaba error) y
  hubo un desfasaje real entre las coordenadas de `getBoundingClientRect()`/clicks y el recorte del
  screenshot — la medición por JS (`gridColumn` computado + `backgroundColor` reaccionando a un cambio de
  estado real) confirmó el fix al primer intento, sin necesitar el screenshot para verificar.
  **Escopeá el selector a la sección bajo prueba** — un `document.querySelectorAll(...)` global puede
  barrer filas de varias secciones distintas (cada una en su propio contenedor) y devolver un falso
  negativo. Caso real: un selector global sobre `li` + la clase del subtotal mezcló 3 secciones de la
  misma página y reportó "no alinean" cuando las filas que importaban sí alineaban — costó una vuelta
  de diagnóstico. Medí dentro del contenedor (`section.querySelectorAll(...)`), no en `document`.
- **Mobile gate (obligatorio, 375×667)** — el checklist de `PROTOCOLO`: sin scroll horizontal, tap
  targets ≥44px, inputs ≥16px, modales en `100dvh`, CTAs primarios en thumb-zone (mitad inferior),
  imágenes `lazy`. El smoke de CI (`mobile-smoke.yml`) corre solo, **no reemplaza** la validación visual.
- **Accesibilidad** — contraste de cada par texto/fondo (oscurecé o engrosá el amber sobre blanco si no
  pasa AA), `:focus-visible`, `aria-label` en icon-buttons, foco atrapado y autofocus en la acción
  primaria de modales.
- **Perf budget** — sin CLS al hidratar, sin regresión de LCP, lazy donde corresponde.
- **Suite + gates de CI** — `npx prettier --check` (bloqueante), `npx tsc --noEmit`, `npx eslint <archivos>`
  (no `eslint .` completo — cuelga en macOS; por archivos o esperá CI), `npm run build`, `npm run check:routes`
  (si tocaste ruteo: una lista con sub-rutas va como `.index`). Si tocaste el **contrato de props de un
  componente compartido**: `tsc` con cache incremental puede dar OK falso (corré fresco,
  `rm tsconfig.tsbuildinfo`) y el CI del PR mergea con el `dev` actual — que puede traer call-sites
  nuevos aparecidos después de tu último merge local; re-mergeá y re-verificá antes de cerrar
  (gotcha detallado en `mantenimiento`).

### 5 · TRACKEAR + cerrar

- **Página-por-página, no sprint.** El tablero de migración al DS vive en
  [#612](https://github.com/tixenre/rental/issues/612) (pantalla × estado). Cada pasada de pulido
  marca su fila en la misma PR — así "sabemos dónde estamos" y elegimos la próxima por prioridad.
- Hallazgos no atendidos → **GitHub Issues** con labels (`docs/ISSUE_LABELS.md`). Los 🔴 de a11y o de
  algo que ve el cliente → PR propia.
- **Commits atómicos** (Conventional Commits en español: `feat(admin):`, `fix(front):`, `refactor(scope):`),
  body con "lo que se dejó a propósito".
- **Supervisor** antes de abrir/mergear PR (instrucción de `CLAUDE.md`).
- **Plan de prueba en lenguaje claro** para el dueño ("andá a /X, hacé Y, tenés que ver Z") — el dueño
  prueba en **staging**, no lee diffs.

## Regla de oro (heredada, vale igual acá)

**Verificá antes de actuar — y "mejorar" puede empeorar.** Un rediseño puede romper un flujo que
funcionaba, un "lo hago más lindo" puede bajar el contraste o sacar un affordance. Ante la duda, se
**deja, se propone como issue, y se reporta** — no se reescribe a ciegas. **Honestidad > actividad:**
si una pantalla ya está bien, la respuesta correcta es decirlo, no fabricar churn. El gate del dueño
es *probar en staging*; "no romper la experiencia" pesa más que "cuánto la pulimos".

## Anti-objetivos (cuándo NO es este skill)

- **Diseñar una pantalla desde cero** → Claude Design (otro proyecto), entra por brief.
- **Auditoría sistémica del DS** (drift de tokens, reimplementaciones en toda la app) → `design-system`.
- **Código muerto / seguridad / ramas / issues / split de god-modules de backend** → `mantenimiento`.
- **Tocar el cálculo de reservas/plata** → sagrado; el pulido es presentación. Un bug del motor se
  reporta y va con plan + Opus + test, nunca dentro de una pasada de pulido.

## Cheatsheet

```
0. DIAGNOSTICAR (read-only): recorrer la pantalla VIVA (preview_screenshot --both / staging-login)
   con la rúbrica front-end (PROTOCOLO ejes P-U) + mobile 390px
   → hallazgos pantalla:zona | eje | 🔴/🟡/🟢 | qué | propuesta   (confirmar cada 🔴 en el código)

1. RUTEAR por riesgo:
   pulido chico → dev directo · refactor de componente → reuse-first + tests
   rediseño de pantalla → brief → Claude Design (rama+PR, por fases)
   cliente / core de reservas / plata → rama+PR + supervisor + aviso (el motor es sagrado)

2. MEJORAR DS-first, 4 lentes: UX (flujo/labels/un solo modelo) · UI/estética (tokens/aire/
   componentes) · modularización (extraer a la librería, hook único) · performance (lazy/memo
   medido/cero CLS/LCP). Reuse-first · reusar siempre antes de crear.

3. VERIFICAR: preview_screenshot (desktop+mobile) · mobile gate 390 · a11y (contraste/targets/
   aria/foco, medir con canvas si browser devuelve oklch) · perf budget ·
   prettier+tsc+eslint+build (+ check:routes si tocaste ruteo)

4. TRACKEAR: marcar fila en #612 (misma PR) · issues con labels · commits atómicos →
   supervisor → plan de prueba → el dueño prueba en staging
```

## Auto-mejora (correr al cerrar cada uso)

Preguntate, crítico: ¿alguna regla me desorientó o quedó vieja porque el repo cambió? ¿pegué un
gotcha que merece ser "caso testigo"? ¿overlap con otro skill? ¿repetí a mano un paso que debería
estar codificado acá?

Si **SÍ** → anotá la propuesta en [`docs/PROPUESTAS_SKILLS.md`](../../../docs/PROPUESTAS_SKILLS.md)
(formato: `fecha · skill · qué cambiar · por qué`). Proponés, no aplicás — el dueño aprueba, igual
que la memoria; el supervisor puede validar.

Si **NO** → no fabriques churn. **Honestidad > actividad.**
