# Rambla — Identidad de marca

> **El hub canónico de marca.** Acá vive el _por qué_ de Rambla: quiénes somos, qué comunicamos
> por área, la voz/tono y los assets. La lista detallada de features de cara al usuario vive en
> [`docs/CAMPAÑA_FEATURES.md`](CAMPAÑA_FEATURES.md) — no se duplica acá. El skill `marca` audita
> que las features reales de la app estén reflejadas en ambos docs.

---

## Quiénes somos

**Rambla** es la plataforma de alquiler de equipos audiovisuales para producciones en Buenos Aires.
Renovamos la forma de alquilar: catálogo online, precios claros, documentos automáticos y todo
desde el celular — sin llamadas, sin sorpresas.

**Tagline canónico:** _Renovamos el alquiler._

---

## Áreas

### Rental — rambla.house/rental

> Alquiler de equipos audiovisuales: cámaras, lentes, iluminación, audio y accesorios.

**Tagline:** _Ahora alquilás todo desde la web._

**Selling points (placas @rambla.rental):**

1. **Encontrá y agregá sin vueltas**
   Catálogo completo con buscador inteligente, filtros por categoría y disponibilidad real. Sumás al
   carrito en un clic.

2. **Sabés qué incluye cada equipo**
   Los kits muestran exactamente qué viene incluido, ítem por ítem. Sin sorpresas al retirar.

3. **Elegí tus fechas**
   Picker de fechas integrado: el stock se ajusta en tiempo real según tus días.

4. **Tus documentos, sin pedirlos**
   Presupuesto, remito, albarán y packing list disponibles desde tu portal en cuanto confirmamos el
   pedido.

5. **CTA:** _Probá la web · Cargás tus datos una vez y quedás listo · rambla.house/rental_

---

### Estudio — rambla.house/estudio

> Alquiler por horas del espacio físico para producciones fotográficas y audiovisuales.

**Color de área:** `#E9552F` (naranja cálido — token `--color-estudio`; mismo hue que `--naranja` status pero con semántica de marketing, ver `DESIGN_SYSTEM.md §Accent por área`).

<!-- TODO: el dueño completa tagline + selling points del Estudio -->
<!-- Sugerencia: qué hace único al estudio (ciclorama, superficie, amenities, ubicación, packs de equipos opcionales) -->

---

### Escuela — rambla.house/escuela

> Talleres y capacitaciones sobre técnica audiovisual, iluminación, postproducción y más.

<!-- TODO: el dueño completa tagline + selling points de la Escuela -->
<!-- Sugerencia: para quién son, qué aprenden, quién los da, cuándo son -->

---

## Voz y tono

La voz de Rambla sigue las guías en [`docs/DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) § Voz/Tono:
- **Claro y directo** — sin jerga técnica innecesaria
- **Útil** — el cliente entiende qué gana, no solo qué existe
- **Sin exagerar** — "encontrá sin vueltas", no "la plataforma más innovadora del sector"
- **En argentino** — "alquilás", "elegís", "probá"

---

## Assets canónicos

| Asset | Valor |
|---|---|
| URL producción | `rambla.house` |
| Instagram | `@rambla.rental` |
| Logo (wordmark) | generado inline desde `backend/services/branding/` — no hay imagen estática |
| Isologo (mark) | ídem — `LogoMark` en `frontend/src/components/rental/` |
| Colores de marca | tokens en `frontend/src/design-system/styles/tokens/colors.css` |

---

## Inventario de features

El listado completo de features de cara al usuario —seleccionadas para comunicar, disponibles pero
no priorizadas, y no listas todavía— vive en:

→ [`docs/CAMPAÑA_FEATURES.md`](CAMPAÑA_FEATURES.md) (fechado 2026-06-08, curado por el dueño)

El skill `marca` verifica periódicamente que las features nuevas en código queden reflejadas ahí.
