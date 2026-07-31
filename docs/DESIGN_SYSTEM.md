# Design System — Rambla Rental

> **Esta es la referencia canónica del design system del repo.** Lo que
> está acá vale para cualquier código en `frontend/src/`. Si una pantalla nueva
> tiene que decidir un color, un tamaño tipográfico, un radio, una
> animación o un texto — empezás acá.
>
> La fuente canónica del design system es este doc + `frontend/src/design-system/` (tokens/tipografía/utilities/
> fuentes en `styles/`; entry `ds-styles.css`; primitivos en `ui/`, composites genéricos en `composites/`).

---

## Filosofía de diseño (la esencia)

> **Esto es el norte.** Los tokens, componentes y reglas de abajo son el _cómo_;
> esta sección es el _por qué_. Toda pantalla nueva — y todo rediseño de una
> existente — se mide contra estos principios antes que contra cualquier detalle.
> Si un principio y una regla puntual chocan, gana el principio (y arreglamos la
> regla). Nacieron del rediseño de **Pedidos** (jun 2026) y se reproducen en
> **toda la web**.

1. **La información se tiene que ver.** El dato que importa va con peso visual
   real: tamaño, contraste y color suficientes. Nada de gris-mono-chiquito para
   lo central. Si el usuario tiene que forzar la vista o entrar a un detalle para
   leer lo básico, está mal. (Contraste WCAG como piso, no como aspiración.)

2. **Mostrá el estado, no lo escondas.** Lo que define una entidad —su estado y
   su plata— va **visible y con el dato concreto**: no "sin seña" en gris, sino
   `Debe $X`; no un tono sutil, sino un pill de color que se lee de un vistazo.
   El estado se **deriva** de la realidad (backend), nunca se inventa un grafo nuevo.

3. **Un foco por pantalla.** Una acción primaria clara y el resto secundario. Dos
   CTAs del mismo peso = el ojo no sabe dónde ir. El "siguiente paso" es único y
   sale del estado real.

4. **Una sola forma de hacer cada cosa.** No tres controles para una acción, no
   dos botones que van al mismo lado. Si hay dos caminos idénticos, sobra uno
   (sacamos el dropdown de estado redundante y el botón "Presupuesto" duplicado).

5. **Lo que más se usa, a mano.** Las acciones frecuentes van arriba y siempre
   visibles, no enterradas al final de un scroll largo (toolbar fija del panel).

6. **Reconocimiento antes que lectura.** Avatares con color determinístico, pills
   de estado, iconos consistentes → se escanea sin leer todo. Quién/qué está
   seleccionado, siempre obvio (tarjeta del cliente, fila resaltada).

7. **Densidad útil, sin ruido ni aire muerto.** Filas que respiran pero compactas,
   columnas alineadas entre sí, nada de huecos enormes en el medio. Un renglón
   denso bien alineado le gana a dos renglones con espacio muerto.

8. **Decí lo que hace.** Labels y copy que prometen exactamente la acción; estados
   vacíos accionables; voz "vos"; precios por `formatARS()`. El nombre del botón
   es lo que pasa al tocarlo.

9. **DS-first: reusar, no recrear.** Los patrones viven en la librería (`ui/`,
   `composites/`, `rental/`, `admin/`) y se **reproducen**, no se recrean inline. Si una
   pieza existe, se usa; si es nueva y reutilizable, se **extrae** (así nacieron
   `PagoBadge` y `ClienteAvatar`). Cero one-offs, cero clases de pill copiadas a mano.

10. **Mobile y accesibilidad no son un extra.** Se diseña para el pulgar y para
    todos: tap targets ≥44px (Apple HIG), inputs ≥16px, `:focus-visible`,
    `aria-label` en icon-buttons, foco atrapado en modales.

11. **El core es sagrado; el diseño es presentación.** Pulir la UI nunca toca el
    cálculo (motor de reservas / plata). La capa visual cambia; la lógica de
    negocio no se altera para que algo "se vea mejor".

**Patrón de referencia (encarna lo de arriba):** una fila que lista una entidad con
estado + plata se lee de un vistazo con **avatar (`ClienteAvatar`) + nombre +
`EstadoBadge` + `PagoBadge` + monto**, alto contraste y jerarquía clara. Es el molde
a reproducir (pedidos, clientes, cobranzas, lo que venga).

---

## Stack real

- **Frontend:** Vite + React 19 + TanStack Router + Tailwind v4 +
  shadcn/Radix UI + lucide-react. **NO Next.js.**
- **Backend:** FastAPI + PostgreSQL en Railway.
- **Fonts:** TT Commons (primary, full axis) + Champ Black (display only)
  vendoreadas en `frontend/src/assets/fonts/`. JetBrains Mono desde Google Fonts.
- **Iconos:** lucide-react, import individual, `strokeWidth` por default
  (no forzamos 1.5 — el kit lo recomienda; en producción mezclamos 2 que
  shadcn usa con 1.5 en piezas branded).
- **Locale:** Spanish (Argentina). Currency: ARS via `formatARS()` de
  `frontend/src/lib/format.ts`.

---

## Tokens en `frontend/src/design-system/styles/`

### Colores (lo que hay hoy)

| Token                 | Valor                   | Uso                                    |
| --------------------- | ----------------------- | -------------------------------------- |
| `--amber`             | `#FAB428`               | Brand accent, hero bg, hover highlight |
| `--amber-soft`        | `amber @ 18%`           | Tinted bg, focus ring fill             |
| `--amber-hot`         | `#FFCC55`               | Paso claro para amber-tape pattern     |
| `--ink`               | `oklch(0.14 0.01 60)`   | Primary text, buttons, body            |
| `--ink-pure`          | `#000000`               | Hero display text, print               |
| `--background` (bone) | `oklch(0.985 0.005 90)` | Page background                        |
| `--surface`           | `oklch(0.97 0.008 85)`  | Cards, panels                          |
| `--surface-elevated`  | `oklch(1 0 0)`          | Elevated cards, inputs, modales        |
| `--hairline`          | `ink @ 12%`             | Borders, dividers                      |
| `--muted-foreground`  | `oklch(0.42 0.01 70)`   | Secondary text, eyebrows               |
| `--rosa`              | `#ED7BAD`               | Status palette                         |
| `--azul`              | `#1097DB`               | Status palette (Presupuesto)           |
| `--verde`             | `#009971`               | Status palette (Confirmado) — charts/montos/bandas |
| `--verde-ink`         | `oklch(0.48 0.125 166.4)` | Texto de estado verde sobre tints (AA); NO el verde de marca |
| `--azul-ink`          | `oklch(0.48 0.14 239)`  | Texto de estado azul/info sobre tints (AA); hermano de `verde-ink`; NO el azul de marca |
| `--naranja`           | `#E9552F`               | Status palette (Warning) — mismo hue que `--color-estudio`, tokens separados |
| `--destructive`       | `oklch(0.55 0.22 27)`   | Errors/delete/Cancelado — AA texto-sobre-claro y blanco-sobre-rojo (era 0.62, #971) |
| `--color-estudio`     | `#E9552F`               | Accent del Estudio — mismo hue que `--naranja`, token propio (ver §Accent por área) |
| `--area-accent`       | `var(--color-amber)` por defecto | Accent de marketing del área activa — resuelve por `[data-area]` (ver §Accent por área) |
| `--area-accent-soft`  | tint 18% del accent     | Fondo tintado del área activa (radio activo, badge bg) |
| `--area-accent-hot`   | versión clara del accent | Hover highlight del área activa |

**Regla del color (accent por área):** la página es **bone + ink + `--area-accent`** — el accent
de marketing resuelve por área activa (ver §Accent por área abajo). Sin contexto de área, el
accent es `amber` (identidad global de Rambla). La paleta secundaria (rosa/azul/verde/naranja)
**sólo** para status de pedido y gráficos — nunca en superficies de marketing. **Focus rings,
estados de UI, badges del kit y back-office → amber fijo** (no se tematizan por área).

**Orden de gráficos** (siempre): amber → azul → naranja → verde → rosa.

**Texto sobre tints de marca (AA):** un color de marca usado como TEXTO sobre su propio tint
(`text-verde` sobre `bg-verde/10` ≈ 3.2:1, o blanco sobre el naranja del hub ≈ 2.4:1) suele
fallar AA. El fix **no** es tocar el color de marca (rompe charts/montos/fondos), sino: (a) un
**token de texto más oscuro**, mismo hue/chroma, menor L — `--verde-ink` (0.48), `--azul-ink`
(0.48), `--destructive` ya a 0.55 — aplicado al TEXTO dejando el tint; o (b) sobre fondo de marca sólido, texto **ink
opaco** (no blanco translúcido). El verde de WhatsApp (`#25D366` + blanco) es **excepción
tier-4 a propósito** (identidad de marca) — no se "arregla". Decisión: 2026-06-22.

Las utilities Tailwind correspondientes (`bg-amber`, `text-ink`,
`border-hairline`, `bg-rosa/10`, etc.) las genera Tailwind v4 directo de
estos tokens vía el bloque `@theme` de `frontend/src/design-system/styles/tokens/colors.css`.

#### Tiers de color (de dónde puede salir un color)

Todo color en `frontend/src/` tiene que venir de uno de estos cuatro tiers. Nada de
Tailwind genérico (`bg-slate-100`, `text-blue-700`, …) ni hex crudo
ad-hoc por pantalla — esa es la deuda que se barrió en
[#584](https://github.com/tixenre/rental/issues/584). **El guardrail de
ESLint ya está activo** (`no-restricted-syntax` en `eslint.config.js`):
una clase de escala genérica (`text-green-700`, `bg-blue-500`, …) en
`className` **rompe el lint** (bloqueante en CI).

| Tier                         | Para qué                                                        | De dónde sale                                                                                                                                                                                                                                        |
| ---------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. Marca**                 | Identidad                                                       | `amber`, `amber-soft`, `amber-hot`, `ink`, `ink-pure`, `background`, `surface`, `muted`, `hairline`, … (tokens)                                                                                                                                      |
| **2. Status**                | Estados semánticos (pedido, pago, éxito/error/info, delta +/−)  | `azul`, `verde`, `rosa`, `naranja`, `destructive` (tokens). Mapeo: éxito/positivo → `verde`; error/negativo → `destructive`; info → `azul`; aviso → `amber`/`naranja`                                                                                |
| **3. Categórico**            | Distinguir N ítems de una taxonomía donde 4 colores no alcanzan | **Paletas centralizadas y nombradas**, no inline. Ej.: `AVATAR_COLORS` (avatares de cliente), `kindFor` en `/admin/novedades` (tipos de changelog). Pueden usar hues fuera de la paleta de marca porque su función es la distinción, no la identidad |
| **4. Excepción de terceros** | Affordances reconocibles de marcas externas                     | Verde WhatsApp (`#25D366`), colores del logo de Google (`#EA4335/#4285F4/#FBBC05/#34A853`). Documentadas acá, allow-listed en el guardrail                                                                                                           |

**Regla:** colores genéricos/hex sólo se permiten en tiers 3 y 4, y ahí
viven en constantes centralizadas y documentadas — nunca sueltos en una
pantalla. Cualquier otro color sale de un token (tiers 1-2).

#### Accent por área (`[data-area]` cascade)

Cada sección pública tiene su propio accent de marketing. El mecanismo:

1. `PublicLayout.tsx` inyecta `data-area="<area>"` en el div raíz según el `variant` del topbar.
2. `tokens/colors.css` define `--area-accent` / `--area-accent-soft` / `--area-accent-hot` en `:root`
   (default → amber) y los sobreescribe en `[data-area="estudio"]` (→ `--color-estudio`).
3. Los componentes consumen `var(--area-accent)` vía Tailwind arbitrary values
   (`bg-[var(--area-accent)]`) sin saber en qué área están.

**Límites del theming:**
- `--area-accent` gobierna **solo** el accent de marketing de la sección pública.
- Focus rings, estados de UI cross-app (`border-amber/60`), badges del kit (`EstadoBadge`/`PagoBadge`),
  back-office y la paleta de status → **amber/status fijos, nunca por área**.
- `--color-estudio` (`#E9552F`) y `--color-naranja` (`#E9552F`) comparten el mismo valor hex pero
  son **tokens separados con semánticas distintas**: estudio = marketing, naranja = status Warning.
  **No usar `--color-naranja` donde debería ir `--color-estudio`** — el supervisor lo marca.

**`EstudioBand` (componente de la landing rental):** usa `data-area="estudio"` en su `<section>` raíz
para activar el cascade localmente (nested override), sin que el layout padre lo necesite saber.

Regla viva: _2026-06-26 — Theming por área_ en [`MEMORIA.md`](MEMORIA.md).

**Cómo exceptuar (tiers 3 y 4):** envolvé la constante con
`/* eslint-disable no-restricted-syntax */` … `/* eslint-enable */` (o
`// eslint-disable-next-line no-restricted-syntax` en una línea) **con un
comentario que diga qué tier es y por qué**. Para un archivo que es entero
una marca de terceros (ej. `WhatsAppButton.tsx`) hay un override por archivo
en `eslint.config.js`. El hex de terceros (WhatsApp `#25D366`, logo de
Google) no lo agarra la regla — pero igual va documentado acá.

La escala genérica `amber-NNN` de Tailwind (`text-amber-700`, etc.) **también está prohibida** por el guardrail — `amber` fue sumado a `GENERIC_COLOR_RE` en el PR #590 junto al barrido completo de usos. Usar `text-amber`, `bg-amber/10`, `border-amber/30` (tokens de marca), o `text-ink` cuando el texto va sobre fondo amber.

### Tipografía

```css
--font-display: "Champ Black", "TT Commons", ui-sans-serif, ...;
--font-sans: "TT Commons", ui-sans-serif, -apple-system, ...;
--font-mono: "JetBrains Mono", ui-monospace, monospace;
```

**Escala base subida (2026-07)** — la app se sentía chica comparada con la
competencia. `tokens/typography.css` redefine la escala default de Tailwind:

```css
--text-xs: 0.8125rem; /* 13px (antes 12) */
--text-xs--line-height: calc(1.125 / 0.8125); /* 18px absolutos */
--text-sm: 0.9375rem; /* 15px (antes 14) */
--text-sm--line-height: calc(1.25 / 0.9375); /* 20px absolutos — igual que antes, cero drift vertical */
```

**Escala extendida** (mismo archivo). Cubre tamaños frecuentes del codebase que
antes iban como `text-[Npx]` mágico:

```css
--text-3xs: 0.5625rem; /* 9px  — micro-labels: counts, badges → text-3xs */
--text-2xs: 0.625rem; /* 10px — el px más frecuente del codebase → text-2xs */
--text-15: 0.9375rem; /* 15px — ahora IDÉNTICO a text-sm; alias óptico legado de los call sites existentes → text-15 */
--text-22: 1.375rem; /* 22px — display headings (entre text-xl y text-2xl) → text-22 */
```

> Sin token para 11px: usá `text-xs` (13px, imperceptible a toda DPI). La
> escala se consume como utility Tailwind (`text-2xs`, `text-15`, …) — la
> genera Tailwind v4 de estos tokens.

**Reglas:**

- **Champ Black** = SÓLO para hero taglines (`.t-display-1`/`.t-display-2`)
  y el `.wordmark` del logo. Headings de UI, body, labels → TT Commons.
- **Display text siempre `lowercase`**. _"un lugar donde pasan cosas."_
- **Headings de UI** en Title Case normal con TT Commons.
- **Eyebrows / chrome / numbers** → JetBrains Mono, uppercase, tracking
  ancho. _`CATÁLOGO · 187 EQUIPOS · MAR DEL PLATA`_.
- **Numbers** tabulares siempre que aparezcan (precios, fechas, counts,
  IDs). Tailwind: `tabular-nums` o nuestra utility `.tabular`.
- **`text-2xs`/`text-3xs` (10px/9px) solo para micro-labels decorativos, NO
  interactivos** (badges de conteo, eyebrows puntuales, chips de marca). Un
  valor que se lee, un warning, o el texto de un botón/acción nunca va acá —
  sube a `text-xs` como mínimo (ver `Pill` más abajo: default `text-xs`,
  `size="compact"` es la excepción para tablas muy densas).

**Guardrail tipográfico (CI):** `eslint.config.js` bloquea los tamaños de fuente
mágicos en `className` — `text-[Npx]`, `text-[Nrem]` y `text-[Nem]` (regla
`no-restricted-syntax`, regex `MAGIC_SIZE_RE`). Usá los tokens del DS
(`text-3xs`/`text-2xs`/`text-xs`/`text-sm`/`text-15`/`text-base`/`text-22`…); un
tamaño óptico sin equivalente va con `eslint-disable-line` + comentario del por qué.

### Radii

```css
--radius-sm: 8px /* inputs, chips chicos */ --radius-md: 10px
  /* buttons, icon containers */ --radius-lg: 12px /* cards (default) */ --radius-xl: 16px
  /* feature blocks */ --radius-2xl: 20px /* studio CTA hero */ --radius-3xl: 24px /* — */
  --radius-4xl: 28px /* — */ /* + rounded-full = 9999px para pills, filter chips, CTAs */;
```

> No hay `--radius` base: la escala arranca en `--radius-sm`. Viven en
> `tokens/typography.css` (junto a las fuentes), expuestos como `rounded-sm`…`rounded-4xl`.

### Z-index (project-specific, NO el genérico del kit)

```css
--z-topbar: 50 /* TopBar sticky */ --z-topbar-amber: 49 /* Variante amber-on-scroll del topbar */
  --z-scrim: 60 /* Overlays (cart drawer, modal scrim) */ --z-drawer: 61
  /* Drawer/sheet contents sobre el scrim */ --z-cart-strip: 45 /* Cart mini bar bottom-fixed */
  --z-cat-bar: 40 /* Category bar sticky */ --z-sub-toolbar: 30
  /* Sub-toolbar (search + filters bajo el topbar) */;
```

> **No usamos** el ladder genérico del kit (`--z-raised/dropdown/sticky/modal/toast/tooltip`).
> Si una pantalla nueva necesita un z-index, primero mirá si hace match
> con alguno de los siete arriba — `--z-scrim` y `--z-drawer` son los más
> reusables.

### Shadows — opt-in al brand tint

Cuatro tokens nuevos para sombras tintadas con `oklch` del ink (en vez
del negro puro de las shadow defaults de Tailwind, que choca con el
bone+ink cálido del sistema). Las utilities `shadow-sm`/`shadow-md`/
etc. de Tailwind siguen funcionando con sus defaults; el tint es opt-in
vía `var()`:

```tsx
className = "shadow-sm"; // Tailwind default (sin cambios)
className = "shadow-[var(--shadow-md)]"; // brand-tinted opt-in
```

```css
--shadow-sm: 0 1px 2px oklch(0.18 0.01 60 / 6%);
--shadow-md: 0 4px 12px oklch(0.18 0.01 60 / 8%), 0 1px 3px oklch(0.18 0.01 60 / 5%);
--shadow-lg: 0 12px 32px oklch(0.18 0.01 60 / 10%), 0 2px 8px oklch(0.18 0.01 60 / 6%);
--shadow-xl: 0 24px 56px oklch(0.18 0.01 60 / 12%), 0 6px 16px oklch(0.18 0.01 60 / 8%);
```

Mapeo: `sm` → cards en reposo · `md` → dropdowns + hover lift · `lg` →
toasts + FABs · `xl` → modales + dialogs.

**Sombras signature siguen siendo inline** (no son tokens — son únicas
de un componente):

- `shadow-[0_-8px_32px_-8px_rgba(0,0,0,0.15)]` → CartMiniBar (sube)
- `shadow-[0_-12px_24px_-8px_rgba(0,0,0,0.08)]` → CartMiniBar preview hover

### Motion — duraciones + easings canónicos

```css
--duration-fast: 120ms; /* press states, button bumps */
--duration-base: 200ms; /* hover transitions, color changes */
--duration-slow: 350ms; /* entry animations, slide-up */
--duration-xslow: 550ms; /* fly-to-cart, hero reveals */

--ease-default: cubic-bezier(0.32, 0.72, 0, 1); /* snappy settle, drawer */
--ease-out-brand: cubic-bezier(0, 0, 0.2, 1); /* standard decel */
--ease-bounce: cubic-bezier(0.34, 1.56, 0.64, 1); /* overshoot, badge pop */
```

`--duration-xslow` matchea exactamente la `duration: 0.55` del
FlyToCartLayer. `--ease-default` es el del CartDrawer Framer Motion.
`--ease-bounce` es la signature del badge pop al sumar al carrito.
`--duration-xslow` también lo usa el `<Spinner>` para su velocidad de rotación.

Uso opt-in:

```tsx
className = "transition duration-[var(--duration-fast)] ease-[var(--ease-default)]";
```

Como están en `@theme`, Tailwind v4 también genera las clases directo:
`duration-xslow`, `ease-default`, `ease-out-brand`, `ease-bounce`.

**El sistema de motion es híbrido, a propósito** — no se exige tokenizar todo:

- **Tokens** (`--duration-*` / `--ease-*`) para las **durations signature**: la
  velocidad del `<Spinner>` (`xslow`), el fly-to-cart, el settle del drawer, el
  badge pop. Son las que definen el "feel" de la marca.
- **Utilities de Tailwind** (`duration-200`, `ease-out`, etc.) para las
  **transiciones triviales** (hover de color, fades simples). No hace falta un
  token para cada `transition`.

### Spacing — Tailwind ya cubre

**NO se crean tokens `--space-*`.** Tailwind v4 ya provee `p-1`…`p-96`
sobre base 4px, e introducir `--space-*` sería redundante y rompería la
intuición de devs que conocen Tailwind. Referencia rápida:

| Tailwind        | px  | Uso típico                 |
| --------------- | --- | -------------------------- |
| `p-1` `gap-1`   | 4   | Stepper button gap         |
| `p-2` `gap-2`   | 8   | Chip rail gap, inline pill |
| `p-3` `gap-3`   | 12  | Card body, button gap      |
| `p-4` `gap-4`   | 16  | Drawer item, **padding default de `card`/`card-elevated`** |
| `p-6` `gap-6`   | 24  | Section grande, dialogs    |
| `p-8` `gap-8`   | 32  | Hero mobile                |
| `p-12` `gap-12` | 48  | Hero desktop, container    |

---

## Recipes tipográficas

Defined as utility classes en `frontend/src/design-system/styles/utilities.css`:

```
.t-display-1   /* Champ Black, clamp(3.5rem, 9vw, 8.5rem), lh 0.9, lowercase */
.t-display-2   /* Champ Black, clamp(2.25rem, 5vw, 4rem), lh 1 */
.t-h1          /* TT Commons 700, 30px (1.875rem) */
.t-h2          /* TT Commons 700, 24px (1.5rem) */
.t-h3          /* TT Commons 600, 18px (1.125rem) */
.t-body        /* TT Commons 400, 16px, lh 1.55 */
.t-small       /* TT Commons 400, 15px, muted */
.t-mono        /* JetBrains Mono, tabular-nums */
.t-eyebrow     /* JetBrains Mono 500, 10px, tracking 0.2em, uppercase, muted */
.tabular       /* font-variant-numeric: tabular-nums */
.wordmark      /* Champ Black, lowercase, tracking 0.01em, ss01, lh 0.9 */
.grain         /* dot-grain texture overlay, 5% opacity (oklch ink @ 0.05) */
```

## Hit-area / tap targets (≥44px, HIG)

Utilidades canónicas en `frontend/src/design-system/styles/utilities.css` para llevar el área **tocable** a 44px
**sin agrandar el visual** (generalizan el `::before` que vivía en StepperPill — fuente única):

```
.hit-area-44      /* ::before transparente 44×44 centrado — botones-ícono aislados */
.hit-area-inline  /* ::before que extiende SÓLO el alto a 44px — links/chips de texto en fila */
```

- **Gotcha (importante):** el `::before` se **solapa entre vecinos** en `flex-wrap` o filas
  apiladas (dos hit-areas de 44px con gap chico → zona de click ambigua). Ahí **NO** uses el
  `::before`: usá **`min-h-11`** (agranda la caja, sin solape), gateado a mobile si en desktop
  hay mouse — ej. `min-h-11 md:min-h-0` para el sidebar admin (Sheet táctil en mobile / fijo en
  desktop) o las celdas del calendario.
- El elemento debe ser `position:relative` (las clases lo setean). **OJO** con elementos ya
  `absolute`: forzar `relative` los rompe → ahí poné el `before:` inline directo (no la clase).

---

## Componentes — ubicaciones canónicas

| Categoría                                          | Dónde vive                | Notas                                                                                                                                  |
| -------------------------------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **Primitivas UI** (Button, Input, Dialog, …) | `frontend/src/design-system/ui/*`     | shadcn/Radix base + variants de marca (`primary`, `amber`). Naming shadcn: `default` no se renombra (ver Button abajo). El panel/card es la **utility** `card`/`card-elevated` (abajo), no un componente `Card` — se podó (0 adopción real, era solo la vitrina).                |
| **Componentes de aplicación (`rental/`)**          | `frontend/src/components/rental/*` | EquipmentCard, TopBar/Footer (`shell/`), CartMiniBar (`cart/`) integrados con queries + estado.                                                            |
| **Componentes admin**                              | `frontend/src/components/admin/*`  | Tablas, modales, sidebar del back-office.                                                                                              |
| **Piezas de marca** (en `ui/`)                     | `frontend/src/design-system/ui/*`     | `Pill`, `EstadoBadge`, `PagoBadge`, `ClienteAvatar`, `Field` (+ `types.ts`). Presentacionales con paleta de marca; viven planas junto a los primitivos shadcn (antes en `kit/`, **disuelto en `ui/`**). `EstadoBadge` es la única fuente del repo. |
| **Composites** (`composites/`)                     | `frontend/src/design-system/composites/*` | Combinaciones genéricas y reusables, **sin dominio**: `EmptyState` (estado "nada para mostrar"), `Chequeos` (lista de validaciones ok/falla), `Section` (encabezado + contenido de panel), `StatCard` (label + valor grande + meta). La capa entre primitivos y organismos de negocio. |
| **Otras presentacionales** (`rental/`)             | `frontend/src/components/rental/*`     | Con dominio de equipos: `AddonPills`, `PriceBlock` (`equipment/shared/`), `ViewToggle`. No son librería pura. |

### Button (`frontend/src/design-system/ui/button.tsx`)

```tsx
import { Button } from "@/design-system/ui/button";

// variants: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link"
//         | "primary" | "amber" | "on-accent"
// sizes:    "default" (h-9) | "sm" (h-8) | "lg" (h-10) | "icon" (h-9 w-9)
// shape:    "rounded" (default) | "pill"

<Button variant="default">Reservar</Button>
<Button variant="primary" shape="pill">Solicitar rental</Button>
<Button variant="amber" shape="pill" asChild><a href="/estudio">→</a></Button>
// on-accent: CTA sobre fondo ink o accent — fondo bone, texto ink
<Button variant="on-accent">Ver catálogo</Button>
```

> **No renombrar `default` a `primary`** — eso rompería decenas de
> `<Button variant="default">` que existen hoy. Las variantes de marca
> (`primary` = fondo ink que invierte a amber en hover; `amber` = siempre amber,
> sin inversión; + el axis `shape`) entran como **adición**, no como reemplazo.

> **CTA primario = ink + texto hueso (bone), NO dorado.** En reposo el
> `variant="primary"` es **fondo ink + texto bone** (`bg-ink text-background`) e
> **invierte a `--area-accent` en hover** (`hover:bg-[var(--area-accent)] hover:text-ink`).
> El texto en reposo es hueso a propósito — **decisión de marca explícita del dueño
> (2026-06-22)**, NO un bug. No "arreglarlo" a texto dorado: el accent del hover
> se tiñe por área (ver §Accent por área).
>
> `variant="amber"` siempre muestra el accent activo (`bg-[var(--area-accent)]`) sin
> inversión — en estudio aparece naranja, en rental/global aparece amber.
>
> `variant="on-accent"` es para CTAs sobre fondos con color fuerte (ink o accent):
> fondo bone (`bg-background shadow-sm`) + texto ink, hover invierte a ink/bone.
> Ejemplo: CartMiniBar sobre fondo ink, botones en heroes de marketing.

### Pill (`frontend/src/design-system/ui/Pill.tsx`) — frontera con `count-badge`

**Fuente única** de la forma pill (`rounded-full border`, tonos semánticos vía prop
`tone`). `EstadoBadge`/`PagoBadge` derivan de acá — cualquier badge nuevo también,
nunca copiar las clases a mano.

**Frontera Pill vs. `count-badge`/botón:** `Pill` renderiza un `<span>` — **display
puro**, sin `onClick`/foco/teclado. Úsalo para un **estado semántico pasivo**
(badge de estado, tag informativo) que el usuario no clickea. Si el chip necesita
ser **clickeable/seleccionable** (un filtro, un toggle, un selector), no lo envuelvas
en `Pill` — perdés semántica de foco/teclado — usá `<Button>` (con `variant`/`size`/
`shape` overrideados vía `className` si hace falta calzar la forma) o, si es un
contador circular compacto tipo badge de carrito, `count-badge` (abajo). El
supervisor marca un `Pill` con `onClick` agregado a mano, o un chip clickeable
implementado como `<span>` en vez de `<button>`/`Button`.

### EstadoBadge

**Fuente única**: `frontend/src/design-system/ui/EstadoBadge.tsx`, con la paleta
secundaria oficial de marca (`bg-azul/10`, `bg-verde/10`, …).

Usado por `/cliente/portal` (PR E1) **y por el admin** (`/admin/pedidos`
list + `/admin/pedidos/$id` detalle, PR E2). El admin pasa el prop opcional
`label` para preservar su alias visible "presupuesto → Solicitado": el texto
se overridea, pero el color sale del map por `estado` (presupuesto → azul,
paleta de marca documentada). Los mappings inline viejos (`ESTADO_CLASS`,
`ESTADO_PILL`) con Tailwind genéricos quedaron eliminados.

Pendiente (follow-up, issue #575): el helper compartido `pedidoEstadoVariant`
(`clientes.lazy`, `CalendarioWidget`) todavía mapea a variants de shadcn
`Badge` — consolidar con `EstadoBadge` es una decisión visual aparte
(rows de historial / leyenda de calendario, contextos distintos a los chips
de pedido).

### PagoBadge

**Fuente única**: `frontend/src/design-system/ui/PagoBadge.tsx`. Hermano de `EstadoBadge`:
mientras ese muestra el **estado del pedido**, este muestra la **cobranza con el
monto** — `Pagado` (verde) · `Debe $X` (rojo si urgente = retirado/entregado,
ámbar si no) · `Seña $X` (cotización con seña). Idea tomada de cómo Booqable hace
visible el "Estado del pago". Props: `pagado`, `total`, `estado`. Devuelve `null`
cuando no aplica (cotización sin seña, o pedido sin monto) — el caller no necesita
placeholder. Pensado para **cualquier superficie que liste pedidos** (admin list,
portal cliente, dashboards): no reimplementar el cálculo "sin seña/debe/pagado"
inline, usar este chip.

### ClienteAvatar

**Fuente única**: `frontend/src/design-system/ui/ClienteAvatar.tsx`. Círculo con foto opcional
o iniciales y color **determinístico por nombre** (hash sobre paleta acotada de tokens, todos
con buen contraste) → el mismo nombre siempre cae en el mismo color, para
reconocimiento visual rápido en listas/headers (idea de Booqable). Props: `nombre`, `src?` (foto
con fallback a iniciales si falla la carga), `className` (tamaño + tipografía). Reusable en admin
y portal. No crear avatares ad-hoc con `bg-ink` inline.

### Spinner / loading (`frontend/src/design-system/ui/spinner.tsx`)

Primitivo canónico de carga. Consolida los 34 `<Loader2 className="animate-spin …" />` del repo.

```tsx
import { Spinner } from "@/design-system/ui/spinner";

<Spinner />            // md (size-5, 20px) por default
<Spinner size="xs" /> // size-3 (12px) — inline en chips/badges chicos
<Spinner size="sm" /> // size-4 (16px) — para usar dentro de Button
<Spinner size="lg" /> // size-6 (24px) — para estados de página completa
```

Velocidad: usa `--duration-xslow` (550ms/vuelta). El `Button` acepta `loading={true}` para
mostrar el Spinner automáticamente y deshabilitar el botón hasta que la acción termine:

```tsx
import { Button } from "@/design-system/ui/button";

<Button loading={isPending}>Guardar</Button>
```

No crear spinners con `Loader2` suelto — siempre `<Spinner>`.

### IconButton (`frontend/src/design-system/ui/icon-button.tsx`)

Wrapper de `buttonVariants` con `aria-label` **obligatorio** a nivel de tipos — sin él TypeScript
rechaza el prop. Cuatro tamaños calibrados para HIG (≥44px tap target en el `lg`):

```tsx
import { IconButton } from "@/design-system/ui/icon-button";

<IconButton aria-label="Cerrar" onClick={onClose}><X /></IconButton>
// sizes: "xs" (h-7) | "sm" (h-8) | "md" (h-9, default) | "lg" (h-11, HIG tap target)
// variant: cualquier ButtonProps["variant"] — default = "ghost"
```

No usar `<button>` crudo para icon-buttons — `IconButton` lo reemplaza en todos los contextos.

### ModalBackdrop (`frontend/src/design-system/ui/modal-backdrop.tsx`)

Backdrop de fixed overlay canónico para modales hechos a mano (no-Radix). Usa `onPointerDown`
(no `onClick`) para evitar cierre accidental al soltar el drag dentro del modal.

```tsx
import { ModalBackdrop } from "@/design-system/ui/modal-backdrop";

<ModalBackdrop onClose={onDismiss}>
  <div className="...">contenido del modal</div>
</ModalBackdrop>
// ModalBackdrop incluye fixed inset-0 + z-50 + bg-black/60 — no wrappear con otro backdrop.
```

### `card` / `card-elevated` (utility CSS en `utilities.css`)

Receta única de panel con borde+fondo — reemplaza el `rounded-(md|lg|xl) border
hairline bg-(background|surface)` (y su variante `bg-surface-elevated`) que
aparecía copy-pasteado por el admin. `@utility` (no `@layer utilities`), así
soporta variantes (`hover:card`, `dark:card`…). **Sin padding en la receta** —
el default es `p-4`, cada consumidor lo agrega (o lo pisa: dialogs/drawers
usan otro). Solo para **paneles estáticos** — un `<input>`/`<select>`/
`<button>` que comparta la misma forma visual NO usa `card` (mezclaría la
semántica de "panel" con la de "control"); esos quedan con las clases sueltas.

```tsx
<div className="card p-4">…</div>              // bg-surface
<div className="card-elevated p-4">…</div>      // bg-surface-elevated
```

### `.px-portal` (utility CSS en `utilities.css`)

Padding horizontal del card portal (1rem mobile · 1.125rem ≥sm). Reemplaza el `px-4 sm:px-[18px]`
disperso en rutas del portal cliente:

```tsx
<div className="px-portal">…</div>  // en vez de px-4 sm:px-[18px]
```

### SegmentedControl (`frontend/src/design-system/ui/segmented-control.tsx`)

Toggle de opciones mutuamente exclusivas. Fuente única — reemplaza las implementaciones manuales
con `<button>` por fila:

```tsx
import { SegmentedControl } from "@/design-system/ui/segmented-control";

// variant "default" — botones separados, fondo ink en activo (back-office)
<SegmentedControl
  value={preset}
  onChange={setPreset}
  options={[{ value: "sena", label: "Seña 50%" }, { value: "saldo", label: "Saldo total" }]}
/>

// variant "pill" — track capsule conectado (toggle Mes/Semana en CalendarioWidget)
<SegmentedControl variant="pill" value={view} onChange={setView}
  options={[{ value: "mes", label: "Mes" }, { value: "semana", label: "Semana" }]} />
```

### CountBadge (`frontend/src/design-system/ui/count-badge.tsx`)

Contador circular compacto: `bg-ink text-amber`, oculto si `count ≤ 0`, máx visible "99+".

```tsx
import { CountBadge } from "@/design-system/ui/count-badge";

<CountBadge count={activeFilters} className="ml-1.5" />  // sm (h-4) por default
<CountBadge count={n} size="md" />  // md (h-5), para contextos más grandes
```

### QtyInput (`frontend/src/design-system/ui/qty-input.tsx`)

Stepper editable canónico: `−` / `<input number>` / `+`. Controla min/max con clamping y
puede mostrar estado de error (overstock).

```tsx
import { QtyInput } from "@/design-system/ui/qty-input";

<QtyInput value={cant} onChange={setCant} min={1} />
<QtyInput value={cant} onChange={setCant} min={1} max={stock} error={cant > stock} />
// size="sm" (h-7, compacto para solicitudes) | "md" (h-9, default)
```

### AdminPage (`frontend/src/components/admin/AdminPage.tsx`)

Chrome único de página del back-office: eyebrow (del grupo de la ruta en
`adminNav` por default) + `t-h1` + descripción + acciones + back-link.

```tsx
import { AdminPage } from "@/components/admin/AdminPage";

<AdminPage title="Unidades" actions={<Button>Nueva</Button>}>…</AdminPage>
// maxW: preset de ancho — form (3xl) · detail (4xl) · list (6xl) · wide (7xl, default)
<AdminPage title="Reporte mensual" maxW="detail">…</AdminPage>
// layout="fullHeight": ocupa el viewport bajo el topbar (flex column, header
// shrink-0, children en flex-1 min-h-0 con su propio scroll) — para
// master-detail. NO aplica maxW (ancho completo).
<AdminPage title="Pedidos" layout="fullHeight">…</AdminPage>
```

### Section (`frontend/src/design-system/composites/Section.tsx`)

Encabezado + contenido único para paneles admin — consolida los 6 wrappers locales
"Section" (`LiquidacionReporte`, `contabilidad.reporte`, `marca.lazy`, `estudio`,
`PedidoPageHelpers` + variantes) que habían aparecido con formas ligeramente
distintas de lo mismo.

```tsx
import { Section } from "@/design-system/composites/Section";

<Section title="Cliente" subtitle="Datos de contacto">…</Section>
// variant="plain": sin chrome propio (para páginas ya envueltas en su card)
<Section variant="plain" title="Assets canónicos">…</Section>
// tone="elevated" (solo variant="card"): header en tira separada, para paneles
// dentro de una página ya densa (ej. el editor de pedidos)
<Section variant="card" tone="elevated" icon={User} title="Cliente" actions={<Badge />}>…</Section>
// title="" suprime el header propio — para cuando un wrapper externo (ej.
// AdminSection, colapsable) ya lo muestra
<Section title="" className="bg-surface" contentClassName="space-y-4">…</Section>
```

`StudioBookingForm` (wizard numerado, público) queda como excepción documentada —
es un patrón distinto (paso numerado, no un panel admin).

### StatCard (`frontend/src/design-system/composites/StatCard.tsx`)

Label + valor grande + meta opcional, para KPIs de dashboards admin y del portal
cliente — consolida las 8 variantes locales que habían aparecido en el repo
(`rental/StatCard`, `media.lazy`, `admin/index.lazy`, `LiquidacionReporte::Kpi`,
`EquiposTableHelpers::KpiCard`, y los `Stat` de `MantenimientoEquipoDialog` /
`HistorialEquipoDialog` / `DashboardUsoDialog`).

```tsx
import { StatCard } from "@/design-system/composites/StatCard";

<StatCard label="Facturado 2026" value="$1.240.000" meta="pedido R-1039" />
// icon: ComponentType (como Section), NO un nodo ya renderizado
<StatCard icon={DollarSign} label="En juego" value={fmtArs(pipeline)} meta="Pipeline estimado" />
// tone: default | warn (amber) | destructive (rojo, ej. mantenimiento vencido)
<StatCard label="Huérfanos" value={n} tone={n > 0 ? "warn" : "default"} />
// size: "lg" (default, dashboards) | "md" (tile compacto dentro de un dialog)
<StatCard label="Eventos" value={total} size="md" />
```

El valor converge a `font-display font-black text-3xl` en `size="lg"` (antes esto
variaba entre `text-base`/`text-lg`/`text-2xl`/`text-3xl` según el archivo) — un
achique deliberado de la variante `size="md"` (antes hasta `text-2xl`) a cambio de
una sola forma consistente en los tiles compactos de los dialogs de equipos.

### Componentes presentacionales (`frontend/src/components/rental/`)

> **OJO — ubicación.** Estas piezas viven en `frontend/src/components/rental/`
> (una, en `equipment/shared/`), **no en la librería pura** (`ui/` / `composites/`)
> porque tienen dominio de equipos. (`EmptyState`/`StatCard`, que eran genéricos,
> se movieron a `design-system/composites/`.)

- `AddonPills` (`rental/AddonPills.tsx`) — items "incluye" sobre rows de equipo.
- `PriceBlock` (`rental/equipment/shared/PriceBlock.tsx`) — precio + tarifa display.
- `ViewToggle` (`rental/ViewToggle.tsx`) — segmented control con pill deslizante (diferente al
  `SegmentedControl` del `ui/`: este tiene animación de slider, ese tiene fondo ink sólido).

El primitivo `Input` vive en **`frontend/src/design-system/ui/input.tsx`**.

### FieldLabel (`frontend/src/design-system/ui/Field.tsx`)

Label suelto en voz eyebrow (mono/uppercase/tracked) — para cuando un form denso
(filtros, grillas compactas) quiere esa voz en vez del `label` plano que ya trae
`Field`. Consolida las 4 copias locales que habían aparecido en el repo
(`StudioBookingForm`, `pagos.lazy`, `facturas.lazy` — este último con un `<div>`
y tracking `0.15em`, convergido — y `PedidoPageHelpers`, que envolvía el control
con una API distinta, `<FieldLabel label="...">`).

```tsx
import { FieldLabel } from "@/design-system/ui/Field";

// sin envolver el control — sibling, no wrapper
<div className="space-y-1">
  <FieldLabel>Desde</FieldLabel>
  <Input type="date" value={desde} onChange={...} />
</div>
```

### Form (`frontend/src/design-system/ui/form.tsx`) — huérfano intencional

Wrapper `react-hook-form` + `zod` (`FormItem`/`FormLabel`/`FormControl`/
`FormDescription`/`FormMessage`, pinta el error solo en `destructive`). **0
consumidores hoy** — casi todo el back-office usa `useState` + `Field` (la
molécula label+control+hint/error, más liviana para el volumen de forms chicos
del repo) — y eso está bien, **no** es deuda a resolver. Se mantiene como el
**default documentado** para el día que aparezca un form grande con validación
cruzada de campos donde RHF+zod realmente paguen (ver "Nada de hotfixes" / no
migrar forms existentes solo para adoptarlo). Tiene specimen en la vitrina
(`ds-catalog`) — por eso no lo agarra el radar de huérfanos-sin-uso.

### SearchInput (`frontend/src/design-system/ui/search-input.tsx`)

Buscador único: lupa a la izquierda + `Input` del DS + botón de limpiar opcional —
consolida las 9 copias que habían aparecido en el repo con variantes ligeramente
distintas de icono/padding/posición.

```tsx
import { SearchInput } from "@/design-system/ui/search-input";

<SearchInput value={q} onValueChange={setQ} placeholder="Buscar…" />
<SearchInput value={q} onValueChange={setQ} clearable placeholder="Buscar…" />
// debounceMs + onDebouncedChange: drivea una query sin una por cada tecla
// (value/onValueChange siguen siendo instantáneos para el input visible)
<SearchInput
  value={search}
  onValueChange={setSearch}
  debounceMs={250}
  onDebouncedChange={runSearch}
  placeholder="Buscar…"
/>
// wrapperClassName va al <div> contenedor (ej. flex-1 en una toolbar);
// className sigue yendo al <input>, como en Input
<SearchInput value={q} onValueChange={setQ} wrapperClassName="flex-1" />
```

> **Patrón de lista de pedidos (Booqable-inspired, 2026-06):** una fila se lee de
> un vistazo con **avatar (`ClienteAvatar`) + nombre + `EstadoBadge` + `PagoBadge`
> + monto**, alto contraste y jerarquía clara. Es el patrón a reproducir en el
> resto de la web cuando se listan entidades con estado + plata.

La vitrina viva del DS es la pestaña **"Design System"** de `/admin/diseno`
(back-office, con guard de admin): muestra TODA la librería agrupada por capas
(fundamentos → primitivos → composites → secciones → páginas → flujos) para QA
visual. La ruta vieja `/kit-preview` quedó como **redirect** a esa pestaña.

### TopBar — navegación modular por área (`frontend/src/components/rental/TopBar.tsx`)

La web tiene áreas con identidad propia (rental · estudio · escuela · portal cliente)
+ el hub (`/`). **Todas las barras salen de un único shell**, no de topbars ad-hoc por
pantalla. Es la aplicación de la Filosofía a la navegación: una sola forma de hacerlo,
reusar no recrear.

- **`TopBarShell`** — el shell único: `<header>` sticky con **mismo alto, padding y logo**
  para todas las variantes. Recibe `section`, slots (`center`, `right`), y opcionales
  (`headerRef`, `labelOverride`). De acá salen rental / estudio / escuela / cliente.
- **Color de marca por área** — el topbar usa el `bg`/`accent` declarado en **`frontend/src/data/areas.ts`**
  (`label/desc/href/color`), consumida por el topbar **y** el menú. El resto de la página recibe
  el accent via `--area-accent` (cascade `[data-area]`, ver §Accent por área). No duplicar la
  lista de áreas en otro lado.
- **Logo themeable** — sobre el color del área el logo va **blanco**: el wordmark
  (`Logo`) **normaliza sus fills a `currentColor`** (atributo `fill=` y `<style>`), así el
  SVG custom del admin también se tiñe; en mobile se usa el **isologo mono** (`LogoMark`,
  silueta `currentColor` + R recortada) que funciona sobre cualquier color. **Nunca**
  hardcodear el color de un asset de marca que deba adaptarse al contexto.
- **Navegación entre áreas** — vive en un **menú hamburguesa** (`AreaMenu`, sheet con la
  identidad del hub: áreas con su color + Inicio + acceso/portal + links). No tabs sueltas
  ni un switcher escondido en el logo.
- **Mobile simplifica** — el label del área aparece **solo si hay lugar** (se oculta cuando
  hay un control central como el date pill); las acciones redundantes (CTA de sección,
  perfil/salir del portal) **se mueven al menú**; el logo va a la izquierda. La landing (`/`)
  no lleva topbar; el login del portal usa el **mismo** topbar que el portal.

Regla viva: _TopBar modular por área (2026-06-20)_ en [`MEMORIA.md`](MEMORIA.md). El
supervisor marca un topbar que no salga del shell, una lista de áreas duplicada, o un
asset de marca con color hardcodeado donde deba ser themeable.

---

## Mobile — reglas críticas

```html
<!-- 1. viewport-fit=cover siempre -->
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
```

```css
/* 2. Safe areas — usar env(safe-area-inset-*) */
.topbar {
  padding-top: env(safe-area-inset-top);
}
.bottom-bar {
  padding-bottom: calc(0.75rem + env(safe-area-inset-bottom));
}
.cart-drawer {
  max-height: 85dvh;
  padding-bottom: env(safe-area-inset-bottom);
}

/* 3. Tap highlight transparente — usar el del :active propio */
* {
  -webkit-tap-highlight-color: transparent;
}

/* 4. Anti-zoom de iOS — inputs ≥ 16px */
input,
textarea,
select {
  font-size: max(16px, 1em);
}

/* 5. Drawer overscroll — no propagar el scroll del body */
.cart-drawer,
.bottom-sheet {
  overscroll-behavior: contain;
}

/* 6. Full-height usar dvh, no vh */
.modal,
.full-screen {
  height: 100dvh;
}
```

**Touch targets:** mínimo 44×44px en cualquier elemento interactivo. Si
un chip es chico, extendé el hit area con `padding` o pseudo-element
`::before`, no agrandés el chip visible.

**Thumb zone:** los CTAs primarios (Reservar, Confirmar, Agregar)
**en la mitad inferior** de la pantalla. Nunca en el top 22% — ahí va
chrome y navegación, no acciones críticas.

---

## Focus y accesibilidad

```css
/* Siempre :focus-visible, nunca :focus crudo. Fuente única: utilities.css */
:focus-visible {
  outline: 2px solid var(--color-amber);
  outline-offset: 2px;
  border-radius: 2px;
}
/* Inputs / campos de forma: mismo outline, offset más ajustado (1px) */
input:focus-visible,
textarea:focus-visible,
select:focus-visible {
  outline: 2px solid var(--color-amber);
  outline-offset: 1px;
}
```

> **Doble capa del foco, una sola fuente de verdad.** El **foco visible canónico**
> es el `outline` amber de **2px** del `:focus-visible` global en
> `styles/utilities.css` — aplica a todo elemento enfocable, sin que cada
> componente lo repita. El `focus-visible:ring-1 ring-ring` que traen algunos
> primitivos shadcn (ej. `Button`) es **decorativo encima**, no la fuente. Siempre
> `focus-visible:` — **nunca** `focus:` crudo (dispararía en click de mouse, no
> solo en teclado).

**Contraste WCAG:**

- ink sobre amber = 7.2:1 (AAA)
- amber sobre ink = 7.2:1 (AAA)
- ink sobre bone = 16.4:1 (AAA)

Los tres pares principales pasan AAA con holgura. No hay excusa para
romperlos — si un texto no se lee, usá `ink` sobre lo que sea.

---

## Micro-interactions

**Press state — vive en el primitivo `Button`, no en un `button:active` global.**
`buttonVariants` (`ui/button.tsx`) trae `active:scale-[0.97]`, así que el bump al
apretar aplica a **todo lo que use `<Button>`** (cualquier variante). No hay regla
CSS global de `button:active`. Si un control que no es `<Button>` necesita el
press, replicá la clase `active:scale-[0.97]`.

```tsx
// ui/button.tsx — extracto de buttonVariants
"… transition [transition-duration:var(--duration-base)] active:scale-[0.97] …";
```

**Card hover lift** — usá la utility Tailwind directo (`hover:-translate-y-0.5
hover:shadow-[var(--shadow-md)]`). No hay clase `.card-interactive` en el repo.

**Reverse signature (ink ↔ amber):** los botones primarios de marca
(`variant="amber"` o el `default` cuando se hace el upgrade) invierten
fondo y texto en hover. _"Pasa el mouse y se prende."_

**Cart count bump:** cuando se agrega un equipo al carrito, el badge del
contador hace `scale [1, 1.25, 0.95, 1]` (ease bounce, ~200ms). Spec
real en `frontend/src/components/rental/CartMiniBar.tsx`.

**+1 fly to cart:** específico de Rambla. Componente
implementado: `frontend/src/components/rental/FlyToCartLayer.tsx`. Curva canónica
`cubic-bezier(0.22, 1, 0.36, 1)`, duración 550ms.

**TopBar amber-on-scroll:** específico de Rambla.
Mecánica: CSS variable `--amber-pct` calculada por la página, el header
hace `color-mix(in oklch, amber X%, background 92% alpha)`. Snap a 65%
del progreso del hero invierte logo + date pill + user button.

---

## Voz y tono (copy rules)

- **Siempre "vos"** (voseo rioplatense). _Reservá, elegí, confirmá._
  Nunca _usted_, nunca _tú_.
- **Minúsculas en wordmark, taglines y heroes.** Title Case normal en
  headings de UI.
- **Punto final en taglines y titulares de hero.** No `!`, no `…`.
  _"un lugar donde pasan cosas."_
- **Precios:** `$ 24.500` ($ con espacio, punto como separador de
  miles). Siempre vía `formatARS()`.
- **Fechas:** `lun 2 jun.` (formato corto), `lun 2 → jue 5 jun.` (rangos).
- **Jornadas:** `3 J` (compact en cards), `3 jornadas` (full).
- **Errores:** específicos y en primera persona del usuario.
  _"Ingresá un correo válido."_ (no _"Error: email inválido"_).
- **Empty states:** accionables. _"No hay equipos para estas fechas."_
  (no _"No se encontraron resultados"_).
- **Sin emoji** en UI de producción. Excepciones (como glifos, no como
  emoji): `✨` via `<Sparkles />` de lucide en el badge addon; `★` literal
  en "destacado".

---

## Skeleton / loading

Componente canónico `<Skeleton>` (`frontend/src/design-system/ui/skeleton.tsx`) — un `div`
con `animate-pulse rounded-md bg-primary/10`. No hay clase `.skeleton` ni
`@keyframes shimmer` propios: el pulse sale de `animate-pulse` de Tailwind.

```tsx
import { Skeleton } from "@/design-system/ui/skeleton";

<Skeleton className="h-9 w-32" />; // dale el tamaño/forma del bloque real
```

**Regla:** el skeleton **espeja el layout del componente real** (vía `className`)
para no generar CLS (Content Layout Shift) al hidratar.

**Regla de cuándo usar qué:** una **página/sección completa** cargando (fetch inicial,
sin datos previos en pantalla) → `Skeleton` (o los presets `TableSkeleton`/`ListSkeleton`/
`CardGridSkeleton` de `components/admin/skeletons.tsx`, el default de `QueryState`) con el
shape del contenido real. Una **acción puntual** (submit de un form, un botón, un fetch
chico dentro de una pantalla ya renderizada) → `Spinner` (`<Button loading={true}>` lo
integra solo). **Nunca texto plano** ("Cargando…", "Cargando equipo…") como estado de
carga de página — no comunica forma ni tamaño, y genera un salto de layout cuando llega
la data real. El supervisor marca un "Cargando…" de texto plano reintroducido en un
loading de página nuevo.

---

## Dark mode

El repo ya tiene tokens semánticos (`--background`, `--surface`,
`--foreground`, etc.) que auto-switchean con la clase `.dark` o
`data-theme="dark"` en `<html>`. **Amber se queda como accent en ambos
modos** — no se ajusta.

Hoy la app **no expone un toggle** público de dark mode (la mayoría del
contenido es bone + amber por diseño). Si se agrega, no requiere
adaptar componentes que ya usan los tokens semánticos correctamente.

---

## Print

```css
@media print {
  .nav,
  .topbar,
  .sidebar,
  [data-no-print] {
    display: none !important;
  }
  body {
    background: white;
    color: #000000;
    font-size: 11pt;
  }
  .wordmark {
    color: #fab428;
  }
  @page {
    margin: 20mm;
    size: A4;
  }
}
```

Útil para presupuestos / remitos / contratos que el dueño imprime
ocasionalmente.

---

## Patterns que nunca se rompen

1. **Nunca un substitute de Google Fonts para TT Commons o Champ Black.**
   Las fuentes vendoreadas en `frontend/src/assets/fonts/` son las del manual oficial
   de marca.
2. **Champ Black sólo para display.** No para headings de UI, no para
   labels, no para body, no para botones. Mapeo explícito del h1: el h1 de una
   página **admin** es `t-h1` (TT Commons, vía `AdminPage`) — "headings de UI";
   el h1 de una página **pública** (catálogo, ficha, landing) es `font-display`
   (Champ Black) — "display". No hay una tercera forma.
3. **Nunca hardcodear hex.** Siempre `var(--amber)`, `bg-amber`,
   `text-ink`. Si el color que necesitás no tiene token, hablalo antes
   de inventar.
4. **Lucide icons individualmente.** `import { Camera, Search } from
"lucide-react"` — nunca `import * from "lucide-react"`. Tree-shaking
   funciona pero el patrón individual es más explícito.
5. **Todos los precios vía `formatARS()`.** Nunca formato manual con
   `.toLocaleString()` ad-hoc.
6. **`dvh` no `vh`** para elementos full-height en mobile. iOS Safari
   redimensiona el viewport con la barra de URL — `vh` salta, `dvh` no.
7. **`viewport-fit=cover` + `env(safe-area-inset-*)`** en toda pantalla
   con topbar o bottom bar sticky.
8. **El core de reservas es sagrado** (MEMORIA: barra de calidad).
   Cero overlap de pedidos; cualquier cambio en disponibilidad pasa por
   el motor de reservas existente, no se reimplementa.

---

## Source-of-truth ladder (cuando algo está en varios lados)

1. **`frontend/src/design-system/styles/tokens/*.css`** — los tokens que el build de
   producción usa (`colors.css`, `typography.css`, `shadows.css`, `motion.css`,
   `z-index.css`). Si Tailwind v4 genera `bg-amber` es porque `--color-amber`
   vive en `tokens/colors.css`. El entry que los cablea es
   `frontend/src/design-system/ds-styles.css`, consumido por `frontend/src/styles.css` (que solo
   importa el DS + define vars de runtime y alias planos transicionales).
2. **`frontend/src/design-system/{ui,composites}/*`** y **`frontend/src/components/{rental,admin}/*`** —
   los componentes que renderean en producción (primitivos + piezas de marca en
   `design-system/`, componentes de negocio en `components/`).
3. **Este doc (`docs/DESIGN_SYSTEM.md`)** — explica el por qué.

En cada PR de UI: si tocás algo en (1) o (2), tocá también (3) si
corresponde. El supervisor cuida que no quede drift silencioso.

---

## Cómo leer este doc

- **Sos un dev que va a tocar UI**: leé "Tokens", "Componentes", la
  sección del componente que vas a tocar, y "Patterns que nunca se
  rompen" antes de empezar.
- **Sos PM/diseñador iterando en Claude Design**: leé "Voz y tono",
  "Mobile rules", y revisá la pestaña **"Design System"** de `/admin/diseno` para ver los componentes en vivo.
- **Sos sesión de Claude Code arrancando**: leé "Stack real", "Tokens",
  "Patterns que nunca se rompen", y `docs/MEMORIA.md` para criterio.

Si dudás cómo aplicar algo, leé el código real en `frontend/src/design-system/{ui,composites}/*`
(primitivos + piezas de marca) o `frontend/src/components/{rental,admin}/*` (componentes de
negocio) — casi siempre hay un ejemplo vivo.
