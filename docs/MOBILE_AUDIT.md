# Auditoría mobile — criterio, checklist + status

> Crítico para launch porque la mayoría del tráfico de un rental viene de móvil
> (clientes consultando desde sets, productoras, etc.). Sin mobile, no hay launch.

## Criterio

**Cada ruta debe tener un layout mobile pensado a propósito, no solo un escalado responsive automático.**

Una ruta cumple el criterio cuando:

1. **Hay un patrón mobile visible en el código** — dual render
   (`md:hidden` / `hidden md:block`), sticky bar, sheet fullscreen, lista
   card-based, etc. *No alcanza* con un grid que colapse por default.
2. **Pasa el checklist** de la sección "Checklist por checkpoint" abajo
   (sin scroll horizontal, tap targets ≥ 44px, texto legible, inputs sin
   zoom iOS, modales que entran en `h-[100dvh]`, imágenes lazy).
3. **Está validada manualmente** en viewport **375×667 (iPhone SE)** —
   el mínimo objetivo del proyecto.
4. **Está marcada 🟢 OK** en las tablas de status de este documento,
   con una nota corta del patrón usado.

Este criterio aplica a **toda ruta nueva** antes de mergear, y a **toda ruta
existente** cada vez que se la toca. El wrapper `<PublicLayout>` provee TopBar
y Footer mobile-aware, pero **no garantiza el criterio** — el contenido de
cada página tiene que cumplirlo por su cuenta.

## Superficie mobile

No todo se renderiza en mobile. El criterio de triage:

- ✅ **Renderiza y funciona bien** → no tocar salvo regresión.
- ⚠️ **Renderiza pero con problemas** → fix o decisión de ocultar.
- ❌ **No renderiza** → fuera del scope mobile (no crear issues).

| Componente / Sección | Estado mobile | Notas |
|---|---|---|
| MobileStickyBar | ✅ solo mobile | Fechas + búsqueda + filtros |
| TopBar mobile | ✅ logo centrado + icono usuario | |
| EquipmentRow (list) | ✅ thumb cuadrado, precio inline | |
| EquipmentCard (grid) | ✅ 2 cols mobile | Responsive utils a revisar (#5) |
| RentalDateModal | ✅ `h-[100dvh]` | |
| CartDrawer | ✅ full-width | |
| CategoryMosaic | ✅ renderiza | |
| Footer | ✅ mobile compacto | |
| BrandCarousel | ❌ oculto (`hidden sm:block`) | Ocultado mayo 2026 — no queda bien sin flechas |
| CarouselRow arrows | ❌ `hidden sm:flex` | El contenido del carrusel puede ser visible |
| ListFilters (panel) | ❌ `hidden md:block` | En mobile usa MobileFiltersSheet |
| TopBar pill de fechas | ❌ `hidden md:flex` | En mobile está en MobileStickyBar |
| TopBar acciones desktop | ❌ `hidden md:flex` | |
| Footer desktop | ❌ `hidden md:block` | |
| Precio columna desktop | ❌ `hidden sm:block` | En mobile está inline |

---

## Label `mobile`

Todos los issues relacionados con la experiencia mobile llevan la label
`mobile` en GitHub. Alcance:

- ✅ Incluye: rutas y componentes del cliente (`/`, `/equipo/*`, `/cliente/*`, `/estudio`, `/escuela/*`)
- ✅ Incluye: `/admin/pedidos`, `/admin/dashboard` (el dueño los usa desde el celu)
- ❌ Excluye: el resto del admin por ahora

Ver convención completa en `docs/ISSUE_LABELS.md`.

```bash
gh issue list --state open --label "mobile"
```

---

## Cómo evaluar contra el criterio

### Manual (rápido, sin setup)

1. Abrir Chrome → DevTools (F12) → toggle device toolbar (Cmd+Shift+M).
2. Elegir viewport: **iPhone SE** (375×667), **iPhone 14 Pro** (393×852), **Pixel 7** (412×915).
3. Recorrer todas las páginas listadas abajo, marcando cada checkpoint.
4. Reportar cualquier problema nuevo como issue con label `bug,priority:high`.

### Automatizado (en CI)

**Playwright** con viewport iPhone SE (375×667) corre como **smoke test en cada PR** —
`.github/workflows/mobile-smoke.yml` (specs en `e2e/`). Caza regresiones gruesas (scroll
horizontal, rutas que no montan), **no reemplaza** la validación visual del gate de abajo.

---

## Checklist por checkpoint

Para cada página, verificar **todos** estos puntos antes de marcar como OK:

| | Checkpoint | Cómo verificarlo |
|---|---|---|
| ☐ | Sin scroll horizontal | El `scrollWidth` no excede el `innerWidth` |
| ☐ | Todos los botones ≥ 44px (`h-11 w-11`) | Tocar con el dedo sin precisión, fácil. Norma 2026-06-05 (Apple HIG); componentes legacy en 40px migran vía #745 |
| ☐ | Textos legibles | Tamaño ≥ 14px para texto base, ≥ 16px para inputs |
| ☐ | Inputs no zoomean al focus | iOS hace zoom si font-size < 16px |
| ☐ | Imágenes escalan bien | `object-contain` o `object-cover`, no se distorsionan |
| ☐ | Modales caben | `max-h-[90dvh]` o `h-[100dvh]` con overflow-y scroll |
| ☐ | Carrito accesible | Botón siempre visible (sticky bottom o header) |
| ☐ | Fechas accesibles | El selector se abre y permite elegir sin trabarse |
| ☐ | Imágenes con `loading="lazy"` | Performance — solo carga lo que se ve |
| ☐ | Touch feedback | `:active` con cambio visible al tocar |

---

## Páginas a auditar

### Públicas

| Página | URL | Status | Notas |
|---|---|---|---|
| Landing hub | `/` | 🟡 Nuevo | Hub de tres áreas (rental / estudio / escuela). TopBar default. Verificar cards y spacing mobile. |
| Catálogo (grid) | `/rental` | 🟢 OK | Movido de `/` a `/rental` (antes /catalogo). Hero escala (text-5xl→7xl→[7rem]). MobileStickyBar + CartMiniBar. |
| Catálogo (list mode) | `/rental` con toggle list | 🟢 OK | Row simplificado post-PR #111. Sin expand inline. |
| Ficha de equipo | `/equipo/{id}` | 🟢 OK | Precio sticky bottom `md:hidden` + galería responsive. Code audit post-#249 confirma 🟢. |
| El Estudio | `/estudio` | 🟡 Verificar | Galería 2 cols mobile, grids responsive. **Validar hero `text-[14vw]` en 375px** — ~52px multilínea, riesgo de desborde (sin resolver, fuera del alcance de la grilla semanal de abajo). Grilla semanal del selector de fechas (`EstudioWeekGrid`, paso "¿Cuándo?") validada en vivo en 375px con datos reales: carrusel de 7 chips de día + lista vertical de franjas sin scroll horizontal accidental (`scrollWidth === innerWidth`), tap targets de los chips confirmados en 44×44 (`::before` de `hit-area-44`), franjas de la lista `min-h-11`. Resto del código OK. |
| Escuela (listado) | `/escuela` | 🟢 OK | TopBar rosa + SectionBanner + cards horizontales que se apilan en mobile. Validado 390px sin scroll horizontal (F5, #1278). |
| Taller (detalle) | `/escuela/{slug}` | 🟢 OK | TopBar rosa con CTA "Inscribirme" + `TallerCTABar` sticky bottom mobile (mismo patrón que `MobileBookBar` de `/estudio`, `pb-24 lg:pb-0` en el contenido). Programa colapsable, form con T&C + drag&drop. Validado 390px: sin scroll horizontal (`scrollWidth===innerWidth`, 0 elementos overflow), tap targets medidos en vivo (encontrado y corregido un CTA en 40px, ahora 44px). F5, #1278. |
| Completar seña | `/escuela/sena/{token}` | 🟢 OK | Página nueva (F5, #1278) — consume el link tokenizado que manda el mail de "se liberó un cupo" (F4b). Card centrada `max-w-md`, mismo patrón de dropzone drag&drop que el form principal. Maneja 404 (link inválido) y 410 (oferta no vigente) con `EmptyState`, sin pantalla en blanco. |
| Preguntas frecuentes | `/preguntas-frecuentes` | 🟢 OK | Accordion + layout `max-w-3xl`. Code audit post-#249 confirma 🟢. |
| Términos | `/terminos` | 🟢 OK | Página legal trivial (lectura centrada). `px-4 md:px-6`, `max-w-3xl`. |
| Privacidad | `/privacidad` | 🟢 OK | Página legal trivial. Mismo patrón que `/terminos`. |
| Login cliente | `/cliente/login` | 🟢 OK | Card centrada con `<Logo />` (post-#246). Form trivial (solo OAuth). |
| Registro cliente | `/cliente/registro` | 🟢 OK | Form en card centrada `max-w-sm`, `grid-cols-1 sm:grid-cols-2`, submit `w-full py-2.5`. Regla CSS global cubre anti-zoom iOS. Code audit confirma 🟢. |
| 404 (NotFound) | cualquier ruta inexistente | 🟢 OK | Layout centrado en `<PublicLayout>` post-#246. Botón `rounded-full px-5 py-2.5` (~40px). |

### Admin (prioritario mobile)

| Página | URL | Status | Notas |
|---|---|---|---|
| Pedidos | `/admin/pedidos` (lista) | 🟢 OK | Dual render: `md:hidden` mobile cards (`AdminCard`) + `hidden md:block` tabla desktop. FAB nuevo pedido `h-14 w-14`. Code audit confirma 🟢. |
| Pedidos | `/admin/pedidos/$id` | 🟢 OK | Layout responsive (`grid-cols-1 lg:grid-cols-[...]`), ActionMenu sheet mobile, botón primario sticky `sm:hidden fixed bottom-0`. Tap targets +/- cantidad subidos a `h-9 sm:h-7` (este PR). |
| Dashboard | `/admin/dashboard` | 🟢 OK | Dialog `max-h-[92vh]` + stats `grid-cols-2 sm:grid-cols-4`. Las 4 tablas (Top alquilados, Sin movimiento, Por cobrar, Por categoría) tienen variante mobile card-based `md:hidden` + tabla desktop `hidden md:block` (este PR). |

### Portal cliente

| Página | URL | Status | Notas |
|---|---|---|---|
| Lista de pedidos | `/cliente/portal` | 🟢 OK | Acordeón expandible + DocPreviewModal `h-full sm:h-auto`. Code audit post-#246 confirma 🟢. |
| Perfil | `/cliente/perfil` | 🟢 OK | Header sticky + sub-header amarillo + form `grid-cols-1 sm:grid-cols-2`. Nombre/apellido tienen `text-base sm:text-sm` explícito. Submit `w-full py-3` (~48px). |

### Componentes críticos

| Componente | Status | Notas |
|---|---|---|
| TopBar | 🟢 OK | Logo PNG (PR #105), botón user 40px (este PR). |
| MobileStickyBar | 🟢 OK | Fechas + search + filtros. Tap targets 40px. |
| RentalDateModal | 🟢 OK | `h-[100dvh] sm:h-auto sm:max-h-[90dvh]`. |
| CartDrawer | 🟢 OK | `h-[100dvh] w-full max-w-md`. |
| EquipmentCard | 🟡 Verificar | Botones +/- son h-7 (28px) pero adentro de pill con padding. |
| EquipmentRow | 🟢 OK | Botones h-9 mobile, h-7 desktop. Imagen lazy (este PR). |
| Footer | 🟢 OK | Layout mobile-first (PR #79). |

---

## Hallazgos pendientes (polish, baja prioridad)

El detalle de fixes históricos vive en el commit history; lo pendiente se trackea en **GitHub
Issues** con label `mobile`. Polish abierto conocido:

| | |
|---|---|
| Tap targets en cards/rows (+/- buttons) | h-7 (28px) dentro de pill con padding — funcional pero podríamos ir a h-9. Bajo prioridad. |
| Touch feedback en botones | Falta `:active` con animación clara. UX polish. |

---

## Re-auditar cuando (gate de merge)

Esta sección define **cuándo no se puede mergear** sin haber validado mobile:

- **En cada PR** que toque rutas cliente, `/admin/pedidos` o `/admin/dashboard`
  (gate explícito de merge — ver [`PROTOCOLO.md`](PROTOCOLO.md) → Mobile pass + gate). Sin
  auditoría mobile validada, el PR queda en draft.
- Se agregue una página nueva → agregarla a la tabla de páginas, evaluarla
  contra el criterio, marcar 🟢/🟡/🔴.
- Se cambie el diseño de TopBar, Cart, DateModal o Footer (componentes
  globales) — re-validar todas las rutas que los usan.
- Se actualice Tailwind o shadcn (puede romper sizing).
- Antes de cada deploy a producción si hubo cambios de UI.
- Como rutina general: cada 2-4 semanas.

Mantener este doc actualizado con cada fix.
