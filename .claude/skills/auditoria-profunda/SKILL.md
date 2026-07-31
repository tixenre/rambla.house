---
name: auditoria-profunda
model: opus
last-reviewed: 2026-07-26
version: 1.0
description: El go-to para AUDITORÍAS PROFUNDAS, exhaustivas y REPETIBLES — cazar fallas (no pulir) en el flujo de reserva y la UI del cliente, anotando todo y abriendo issues. Dos motores con la misma disciplina (1) ROBUSTEZ/SEGURIDAD del backend del flujo de reserva — concurrencia/sobreventa/race, auth/IDOR, integridad de precio, inyección/XSS, descuentos, fechas/horarios, validación de input — probado por API/curl/psql con datos reales; (2) UI MULTI-VIEWPORT — un harness Playwright (Chrome real) que recorre 320→1920, clickea de verdad, mide tap targets/font/contraste/overflow/truncación y GUARDA UN SCREENSHOT por pantalla×tamaño para comparar antes/después. Úsalo cuando el dueño pida "auditá a fondo / profundo", "buscá fallas / bugs", "probá si es seguro", "tocá todos los botones", "probá en varios tamaños", "stress test", "edge cases", "que no se rompa con mucha demanda", o quiera screenshots para comparar. El corazón es el MÉTODO + la LISTA DE CRITERIOS (abajo): verificar antes de reportar, datos reales, etiquetar y limpiar datos de prueba, todo a un test-log + issues, harnesses re-ejecutables. NO es para pulir/arreglar (eso es `pulido-frontend`) ni para salud del repo (`mantenimiento`): este SÓLO encuentra y documenta. El core de reservas es sagrado → read-only sobre la lógica.
---

# auditoria-profunda — cazar fallas a fondo, repetible, con evidencia

Codifica **cómo** se hace una auditoría profunda en Rambla: exhaustiva, con datos reales,
que **verifica antes de afirmar**, **anota todo** (test-log + GitHub issues) y deja
**herramientas re-ejecutables** + **screenshots** para comparar antes/después. Hoy
**buscamos fallas**; el pulido viene después (otra sesión / `pulido-frontend`).

> Pareja con: `pulido-frontend` (rúbrica P-U + arreglar la UI), `mantenimiento` (método
> seguro + tests + core sagrado), `PROTOCOLO.md` (rúbrica).
> El **core de reservas es sagrado**: todo read-only sobre la lógica; se prueba por
> API / UI / DB, no se modifica el motor.

## Regla de oro (heredada)
**Verificá antes de reportar.** Toda falla 🔴 se confirma leyendo el código (las
herramientas Y la intuición mienten). **Honestidad > actividad**: si algo está sólido,
se dice; no se fabrica churn. Si una medición es dudosa (ej. contraste sobre imagen,
hit-area por pseudo-elemento), se marca como "verificar", no se afirma.

**Los hallazgos son HIPÓTESIS, no hechos** (lección 2026-06-22). Varios de una pasada real
resultaron falsos al confirmarlos: el bug del mini-bar estaba en OTRO componente que el
reportado, el "catálogo en blanco" era un artefacto del harness, los overflows de admin
estaban stale (la página ya era un redirect / read-only / 0-overflow) y los contrastes
"1.66/1.73" venían del parser, no eran reales. **Antes de ARREGLAR un hallazgo, re-confirmalo
en el código + EN VIVO.** La extensión **Chrome MCP** es ideal para esto: clickea de verdad,
mide computed styles por JS e inspecciona la red — así se cazaron el N+1 de `/api/cliente/favoritos`
(~90→1) y el artefacto del glob. Quien arregla NO hereda el hallazgo como verdad: lo re-verifica.

## Setup (datos reales, local)
Ver `docs/DEPLOY_RAILWAY.md` → "Iterar local con datos reales": backend `:8000` + vite
`:3000` (fixtures **apagadas**) + clon de staging en Postgres local + **cuenta
verificada** (UPDATE de `dni_validado_at`). Login de cliente por `staging-login`
(`target=cliente, cliente_id`). **Etiquetar** todo dato de prueba (`notas:"EDGE-TEST-*"`)
y **limpiarlo** al final.

---

## Motor 1 — Robustez / seguridad del flujo de reserva (API · curl · psql)
Cómo: probes `fetch` desde la consola del browser logueado, `curl` en paralelo para
concurrencia real (el browser capea ~6 conexiones), y `psql` para verdad de la DB y
para preparar estados. Crear pedidos de prueba con `notas:"EDGE-TEST-*"`. Ver el
test-log `docs/AUDIT_RESERVA_EDGE_CASES.md` (repro de cada caso).

## Motor 2 — UI multi-viewport (Playwright, Chrome real)
Harness: [`ui-audit.mjs`](./ui-audit.mjs). Corre desde `frontend/`:
```bash
node ../.claude/skills/auditoria-profunda/ui-audit.mjs                 # matriz completa
VIEWPORTS=320,768,1280 ROUTES=/rental,/cliente/portal node ...ui-audit.mjs   # subset
LABEL=before node ...ui-audit.mjs   # baseline → docs/audit-ui-screenshots/before/
```
- **Chrome real** (`channel:"chrome"`) → renderiza los reveals `whileInView` que el
  preview headless deja en blanco (scrollea de verdad para disparar IntersectionObserver
  + lazy images). Soporta **viewports exactos** 320→1920 (lo que una ventana real no baja).
- Mide en página (parser de color por canvas → maneja `oklch` de Tailwind v4) y
  **guarda 1 screenshot por pantalla×tamaño** en `docs/audit-ui-screenshots/<label>/`
  + un `_report.json` con todos los hallazgos → **comparar antes/después**.
- ⚠️ El **contraste del parser es aproximado**: opacidades apiladas (`/40`, `/65`), texto
  sobre imagen y el redondeo oklch dan falsos (esta pasada tiró 1.66/1.73 que no eran). Para
  cualquier contraste que vayas a ARREGLAR, **recalculá del TOKEN** — oklch→sRGB lineal→
  luminancia→WCAG (~15 líneas de node) — y para tints, sobre el color compuesto (verde@10% sobre
  bone). El parser propone candidatos; el número se confirma a mano. Patrón de fix: token de
  texto más oscuro mismo hue/chroma (ej. `--color-verde-ink`, `--color-destructive` a L 0.55).
- Gotcha del layout: en **mobile** scrollea un **contenedor interno**
  (`div.flex-1.overflow-y-auto`), no el document; el harness lo detecta y screenshotea
  ese elemento; en desktop usa `fullPage`. El detector de scroller excluye `nav`/`aside` y
  prefiere el de **mayor área** (no el primero en orden DOM) — sin esto, en `/admin/*` agarraba el
  **sidebar** (tiene su propio `overflow-y:auto`) y las ~90 capturas desktop del back-office quedaban
  recortadas al sidebar en vez del contenido (bug real, 2026-07-25, arreglado en el script).
- ⚠️ **Degradación acumulativa de Chromium en corridas largas:** correr el harness sobre >~15 pantallas
  seguidas en el MISMO browser/tab (ej. `GROUP=admin` completo, ~30 pantallas × 5 viewports) empieza a
  fallar con `Timeout ... waiting for fonts to load` a partir de la captura ~15-16, sin importar qué
  pantalla es — no es la pantalla, es recurso acumulado (memoria/GPU del proceso), agravado por RAM
  limitada de un sandbox. Correr en **lotes de ~10 pantallas o menos** (nuevo `chromium.launch()` por
  lote) — el mismo `LABEL` mergea el `_report.json` entre lotes, no se pierde nada.
- El path de salida se resuelve contra la **raíz del repo** (`git rev-parse --show-toplevel`), no
  relativo a `import.meta.url` — si el harness se copia a otro lugar (necesario en algunos sandboxes
  donde Playwright solo resuelve el módulo ESM dentro de la cadena de `frontend/node_modules`), un path
  relativo a la ubicación del script apuntaría a un lugar equivocado **sin ningún error** (bug real,
  2026-07-25, arreglado en el script).
- ⚠️ **`admin-pedido-nuevo` NO es de solo lectura:** navegar a `/admin/pedidos/nuevo` (aunque sea solo
  para un screenshot) **crea un pedido real** en la base (`estado:"borrador"`, sin cliente, $0) — hay un
  `useEffect` en el mount que llama `createPedido` y redirige al editor. Si se visita esta pantalla, sumar
  su limpieza (`DELETE /api/alquileres/{id}` de los borradores creados) al checklist de limpieza final —
  no asumir que navegar = solo-lectura. Se identifican por `cliente_id NULL + monto_total 0 +
  fecha_desde/hasta = hoy/mañana` si no quedaron tageados.

### Cobertura — TODA la web cliente (registro de pantallas)
El harness recorre estas pantallas × **10 viewports** (320·360·375·414·640·768·1024·1280·1440·1920),
desktop **y** mobile. `grid` vs `list` son **variantes por URL** (`?view=grid|list`).

| name (= archivo) | path | qué |
|---|---|---|
| `hub` | `/` | landing hub (3 cards rental/estudio/escuela) |
| `rental-grid` | `/rental?view=grid` | catálogo, vista grid |
| `rental-list` | `/rental?view=list` | catálogo, vista lista |
| `estudio` | `/estudio` | landing del estudio |
| `escuela` | `/escuela` | escuela / talleres (hub) |
| `equipo-detail` | `/equipo/213` | ficha de equipo (la ruta fetchea por **id**; `/equipo/<slug>` crudo sin id = "no encontrado") |
| `login` / `registro` | `/cliente/login` · `/cliente/registro` | auth |
| `portal` | `/cliente/portal` | portal cliente (tab Pedidos) |
| `perfil` | `/cliente/perfil` | perfil |
| `faq` · `terminos` · `privacidad` | `/preguntas-frecuentes` · `/terminos` · `/privacidad` | legales/info |

### Back-office `/admin/*` (`GROUP=admin node ...ui-audit.mjs`)
~30 pantallas: dashboard, pedidos (+detalle/nuevo), equipos (+editar/nuevo/calidad/categorías/marcas/specs),
clientes, contabilidad (index/cuentas/movimientos/liquidación/reporte/glosario), pagos, estadísticas,
estudio, talleres, solicitudes, settings, email-templates, dataio, diseño, novedades, specs, unidades.
**Auth admin:** la sesión la resuelve `is_admin_email(email)`. El **cliente 209 (dueño) tiene
`is_admin=true`** → se reusa esa sesión para auditar admin (no hace falta otra). El `staging-login`
target=admin mintea `STAGING_LOGIN_EMAIL`, que **debe estar en `ADMIN_EMAILS`** (en este local NO lo está
→ daría `is_admin=false`; por eso se usa la del dueño). Prioridad mobile (ISSUE_LABELS): `/admin/pedidos`
y `/admin` (dashboard) los usa el dueño desde el celu.

**Estados interactivos** (`ui-states.mjs`): modal de fechas, sheet de Marca/Filtros, carrito
abierto, card expandida, pedido del portal expandido, popup de documentos.

**Estados de error / vacío / dinámicos** (`ui-edge.mjs`): usa **route interception** de Playwright
(`page.route` → 500 / `{items:[]}`) para forzar fallos/vacíos **sin tocar el backend**: catálogo en
error, catálogo/portal vacíos, cotizar 500, tabs del portal (Notif/Perfil), discovery sheet mobile,
y el **panel de verificación** (`VERIF=1`, correr con el cliente NO verificado por psql). Captura un
snippet del texto visible para juzgar el estado. (Ampliar acá a medida que aparezcan estados nuevos.)
- ⚠️ **Gotcha del glob (2026-06-22):** el matcher de `page.route` tiene que apuntar al **XHR**
  (regex `/\/api\/equipos\?/`), NO a un glob amplio `**/api/equipos**`: en dev Vite sirve el
  **módulo fuente** `/src/lib/admin/api/equipos.ts`, que ese glob también matchea → lo interceptás
  con JSON, se rompe el import y la página queda **en blanco**. Eso disparó una falsa alarma de
  "catálogo roto" que NO pasa en prod (ahí no se sirven módulos fuente). Acotá siempre al request real.

### Nomenclatura de evidencia (para saber "cuál es cuál")
- Carpeta por corrida: `docs/audit-ui-screenshots/<LABEL>/` (gitignored; regenerable).
- Un PNG por pantalla×viewport: **`<name>__<viewport>.png`** (ej. `rental-grid__1280.png`, `perfil__375.png`).
- `_report.json` = todas las mediciones; **`_INDEX.md`** = tabla legible pantalla→screenshot→flags
  (tap<44 / font / contraste / overflow / hScroll) para mapear cada captura a sus hallazgos.
- Convención de LABEL: `before` / `after` para comparar una corrida contra otra tras los fixes.
- Subsets: `SCREENS=hub,perfil` · `ROUTES=/rental?view=list` · `VIEWPORTS=320,768,1280`.

---

## 📋 LISTA DESCRIPTIVA DE CRITERIOS / BUGS QUE SE BUSCAN
> Para analizar y **expandir** con el tiempo. Cada ítem = una clase de falla con su chequeo.

### A · UI / experiencia (Motor 2)
1. **Tap target < 44×44** (HIG / MEMORIA 2026-06-05). Medir rect; descontar hit-area por
   pseudo (`::before` absoluto con offsets negativos) y padding. Reincidentes: corazón
   favorito, dots de carrusel, flechas, X de cerrar, pills de fecha/carrito.
2. **Input font-size < 16px** → iOS Safari hace zoom al enfocar. (search, selects de hora.)
3. **Texto ilegible por tamaño** — labels < ~11px (ej. "Ver sólo X" a 10px, footer 10px).
4. **Contraste < AA** (4.5:1 texto normal, 3:1 grande). Parser real (canvas). **Saltear
   texto sobre imagen** (no medible vs sólido) y marcar para chequeo manual.
5. **Scroll horizontal / overflow** — `scrollWidth > viewport`, excluyendo h-scrollers
   intencionales (tabs). Romper layout en anchos extremos.
6. **Texto truncado que esconde info** — nombres cortados con `…` (¿se entiende el equipo?).
7. **Responsive en toda la matriz** 320·360·375·414·640·768·1024·1280·1440·1920 (bordes de
   breakpoint sm640/md768/lg1024/xl1280 donde más rompe; layouts distintos mobile/desktop).
8. **Botones que no andan** — clickear de verdad y verificar cambio de estado / navegación;
   hrefs correctos; `div` con onClick que deberían ser `<button>` (a11y/teclado).
9. **Consistencia** — label del CTA igual en desktop/mobile, tamaños de control
   estandarizados, tokens del DS (sin hex/escala ad-hoc), estados canónicos.
10. **Feedback / estados** — loading, error, empty-state ("Sin resultados"), confirmaciones,
    números de plata visibles y correctos en cada superficie (mini-bar vs drawer vs portal).
10b. **Estados de ERROR/VACÍO de API** (vía route interception, sin tocar el backend) — que un
    `/api/...` 500 o `{items:[]}` muestre un estado **graceful con reintento**, NO una pantalla en
    blanco. Distinguir vacío-por-filtro-client (suele estar OK) de vacío/error-de-servidor (suele
    fallar). Probar catálogo, portal, cotizar.
10c. **Intersticiales / interrupciones** — onboarding ("¿cómo querés ver el catálogo?"), popups de
    "documentos nuevos", banners; que no se encadenen ni tapen acciones en la primera carga.
11. **Copy** — claridad, voz "vos", precios por `formatARS()`, mensajes que no confundan
    (ej. "0 jornadas" cuando el mínimo es 1).
12. **Performance percibida** — LCP mobile, lazy de imágenes, reveal que no deje contenido
    invisible, CLS al hidratar.

### B · Robustez / seguridad del flujo de reserva (Motor 1)
13. **Concurrencia / race / sobreventa** — N requests en paralelo (curl) sobre el mismo ítem;
    exactamente el stock disponible debe ganar; el resto **409 limpio** (no 500); sin
    overbooking; sin pedidos huérfanos en los fallos (rollback).
14. **Guardas de stock** — `cantidad < demanda` → 409; **presupuesto reserva** stock;
    **buffer** entre alquileres; expansión **recursiva** de kits/composiciones (forward+backward).
15. **Auth** — endpoints sensibles 401 sin cookie. **IDOR** — leer/cancelar/descargar
    documentos de pedidos de OTRO cliente → 403/404. **Inyección de `cliente_id`/rol** en el
    body → ignorada (manda la sesión).
16. **Integridad de precio** — `precio_jornada` del body ignorado; siempre el del catálogo.
17. **Validación de input** — cantidad fuera de rango (0/neg/≥1000), float, ids string/neg/0,
    fechas malformadas, rango invertido, ambas-o-ninguna → **4xx limpio, nunca 500**.
18. **Descuentos** — clamp 0–100%, interpolación por jornadas, IVA (RI vs monotributo),
    no acumulativo (`max(cliente, jornadas)`).
19. **Búsqueda** — tildes/sin tildes, mayúsc/minúsc, typos (¿fuzzy?), guiones/sin separador,
    inyección SQL, emoji/sólo-símbolos, empty-state. (Catálogo = substring client-side.)
20. **Fechas / horarios** — jornadas `ceil(Δ/24h)` mín 1; franja habilitada por día de
    semana (retiro Y devolución, límites inclusivos); tope de rango / horizonte; pasado.
21. **XSS / inyección** — `notas`/inputs con `<script>`; render escapado (React + email
    `autoescape`); SQL parametrizado.
22. **Gates de visibilidad / estado** — `visible_catalogo` (¿se reservan ítems ocultos por
    id?), verificación de identidad (Didit), feature flags **frontend-only** (endpoint vivo).
23. **Manejo de errores** — degradar a 4xx con mensaje vs 500 crudo; no corromper datos en
    el fallo; límites de la UI replicados server-side (defensa en profundidad).

### C · Método / disciplina (ambos motores)
24. **Datos reales** (clon staging, fixtures off, cuenta verificada) — los bugs de
    theming/stock/plata **no se ven con mocks**.
25. **Verificar el origen en el código** antes de reportar; distinguir **user-facing** vs
    **sólo-por-API/bypass** (ej. el stepper topea el stock, pero la API no).
26. **Concurrencia REAL** con curl paralelo (el browser capea ~6).
27. **Etiquetar + limpiar** datos de prueba (`EDGE-TEST-*`); restaurar estados tocados
    (descuento/perfil/verificación del cliente).
28. **Anotar todo** → test-log (`docs/AUDIT_*`) con repro + **GitHub issues** con labels
    (`docs/ISSUE_LABELS.md`) + **screenshots** de cada bug de UI para comparar.
29. **Herramientas re-ejecutables** (este `ui-audit.mjs`) → baseline `before` vs `after`.
30. **Severidad honesta** — 🔴 roto/inseguro · 🟡 fricción · 🟢 menor · ✅ sólido. Marcar lo
    no-medible ("verificar a mano") en vez de inventar un número.

---

## Salidas
- **Test-logs**: `docs/AUDIT_RESERVA_EDGE_CASES.md` (backend), `docs/AUDIT_UI_MULTIVIEWPORT.md` (UI).
- **Screenshots + report**: `docs/audit-ui-screenshots/<label>/` (re-generables; local, no se commitean salvo pedido).
- **Issues**: uno de tracking por tanda (ej. #965), con checklist + repro + screenshots; labels obligatorias.
- **Veredicto** en lenguaje claro: qué está sólido (no tocar), qué romper-y-pulir después, ruteado por riesgo.

## Cuándo NO
- Pulir/arreglar lo encontrado → `pulido-frontend` (UI) / fix con tests.
- Salud del repo (código muerto, ramas, deps, split) → `mantenimiento`.
- Tocar el motor de reservas → sagrado; un bug del motor se reporta con repro + va con Opus + test.

## Auto-mejora (correr al cerrar cada uso)

Preguntate, crítico: ¿alguna regla me desorientó o quedó vieja porque el repo cambió? ¿pegué un
gotcha que merece ser "caso testigo"? ¿overlap con otro skill? ¿repetí a mano un paso que debería
estar codificado acá?

Si **SÍ** → anotá la propuesta en [`docs/PROPUESTAS_SKILLS.md`](../../../docs/PROPUESTAS_SKILLS.md)
(formato: `fecha · skill · qué cambiar · por qué`). Proponés, no aplicás — el dueño aprueba, igual
que la memoria; el supervisor puede validar.

Si **NO** → no fabriques churn. **Honestidad > actividad.**
