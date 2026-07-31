---
name: marca
description: Gobernador de la identidad de marca y el inventario de features — audita si las features reales de la app están documentadas en docs/MARCA.md y docs/CAMPAÑA_FEATURES.md, detecta features nuevas sin comunicar y selling points stale, propone actualizaciones y borradores de copy. Disparadores: "actualizá el marketing", "qué features no están comunicadas?", "hay features nuevas sin documentar?", "el marketing está al día?", "auditá la marca", "qué hay de nuevo desde la última campaña?", "qué features tiene la web?". NO rediseña la home (→ pulido-frontend), NO gestiona el catálogo de equipos (→ catalogo), NO escribe copy sin aprobación del dueño.
model: opus
last-reviewed: 2026-06-23
version: 1.0
---

# marca — gobernador de marca e inventario de features

El contenido de marca de Rambla vive en dos fuentes: [`docs/MARCA.md`](../../../docs/MARCA.md)
(identidad y selling points) y [`docs/CAMPAÑA_FEATURES.md`](../../../docs/CAMPAÑA_FEATURES.md)
(inventario detallado de features). Este skill verifica que lo que existe en el código tenga reflejo
en esos docs — y que lo que dicen los docs siga siendo verdad en el producto.

## Dónde encaja (no dupliques: delegá)

| Skill | Pregunta que responde | Zona |
|---|---|---|
| **`marca`** (este) | "¿el marketing está al día con el producto?" | Features documentadas vs. reales; selling points vigentes |
| `catalogo` | "¿los equipos están completos?" | Completitud de datos del catálogo (fotos, precios, specs) |
| `pulido-frontend` | "¿esta pantalla está bien?" | UX/UI de una pantalla específica |
| `auditoria-profunda` | "¿tiene fallas?" | Bugs en vivo, edge cases |
| `design-system` | "¿el DS está sano?" | Tokens, componentes, drift visual |

## El método: inventariar → cruzar → proponer

### 1 · Inventariar features reales (leer código)

```bash
# Rutas públicas del frontend (TanStack Router)
grep -rn "path:" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v __pycache__ | head -40

# Grupos de endpoints del backend
find backend/ -name "*.py" | xargs grep -l "@router\|APIRouter" | grep -v __pycache__ | head -20
```

Leer `frontend/src/App.tsx` o el archivo de rutas principal para listar páginas activas:
- **Público:** `/`, `/equipo/$slug`, `/categoria/$slug`, `/estudio`, `/escuela/$slug`, `/preguntas-frecuentes`
- **Portal cliente:** `/cliente/portal`, `/cliente/pedidos/$id`, `/cliente/perfil`
- **Rental flow:** `/rental`

Para cada ruta/feature: ¿está en `docs/CAMPAÑA_FEATURES.md` (§ Seleccionadas, § Posibilidades o § No listas todavía)?

### 2 · Cruzar con identidad de marca (`docs/MARCA.md`)

Leer `docs/MARCA.md` completo. Verificar:

**2a. TODOs del dueño**
```bash
grep -n "TODO" docs/MARCA.md
```
¿Quedan `[TODO]` sin completar en las áreas de Estudio o Workshops?

**2b. Selling points vigentes**
Para cada selling point del rental (y de las áreas que el dueño complete):
- ¿La feature que describe sigue existiendo en el código?
- ¿Cambió la URL, el nombre o el comportamiento?

**2c. Áreas nuevas**
¿Hay rutas en el código de áreas no documentadas en `docs/MARCA.md`?

### 3 · Proponer actualizaciones (borradores — no aplicar)

Para cada gap detectado, generar un borrador:

**Feature nueva sin documentar:**
```
Nueva feature detectada: <ruta/feature>
Propuesta para CAMPAÑA_FEATURES.md § Posibilidades:
"• <nombre corto>
  <1-2 líneas de descripción en voz de Rambla>"
```

**Selling point stale:**
```
Selling point a revisar: "<texto del selling point>"
Motivo: <qué cambió en el código>
Propuesta: actualizar a "<texto revisado>" o retirar
```

**TODO pendiente:**
```
Recordatorio para el dueño: docs/MARCA.md § <Área> aún tiene [TODO]
Preguntas para completarlo:
- ¿Cuál es el tagline del área?
- ¿Cuáles son los 3-5 selling points?
```

**No edita `docs/MARCA.md` ni `docs/CAMPAÑA_FEATURES.md` sin aprobación explícita del dueño.**

## Reporte de salida

```
MARCA — <fecha>
───────────────
Fuentes: docs/MARCA.md · docs/CAMPAÑA_FEATURES.md (fechado: <fecha del doc>)

TODOs pendientes del dueño:
  🔴 Estudio — sin tagline ni selling points en docs/MARCA.md
  🔴 Workshops — ídem

Features en código no documentadas:
  🟡 <feature> — existe en /ruta pero no está en CAMPAÑA_FEATURES.md

Selling points a revisar:
  🟡 "<selling point>" — la feature cambió / ya no existe como antes

✅ Rental: tagline + 5 selling points documentados
✅ CAMPAÑA_FEATURES.md refleja el estado del producto (sin gaps nuevos)

Propuestas para aprobación del dueño:
  1. Agregar "<feature X>" a CAMPAÑA_FEATURES.md § Posibilidades
  2. Borrador de selling point para Estudio (esperando input del dueño)
```

## Regla de oro

**Los docs de marca son del dueño.** El skill detecta y propone — nunca edita sin aprobación.
Un selling point que el dueño escribió con intención puede parecer stale al leerlo del código
(ej. si la ruta cambió de nombre pero la feature existe) → confirmar antes de marcar como obsoleto.

**Honestidad > actividad.** Si todo está en orden, el reporte lo dice. No fabricar gaps ni propuestas
innecesarias.

## Anti-objetivos

- **Rediseñar la home o pantallas** → `pulido-frontend`.
- **Completitud del catálogo de equipos** → `catalogo`.
- **Buscar bugs de negocio** → `auditoria-profunda`.
- **Escribir copy final** → propone borradores; el dueño edita y aprueba.
- **Gestionar assets (fotos de instagram, videos)** → fuera de scope; el dueño los maneja.

## Auto-mejora (correr al cerrar cada uso)

¿Cambió la estructura de rutas del frontend (nuevo área, nueva sección)? ¿El dueño completó los
TODOs de Estudio/Workshops → actualizar la sección del método? ¿Los borradores de selling point
que propuse fueron bien recibidos o el dueño los reescribió totalmente?

Si **SÍ** → anotar en [`docs/PROPUESTAS_SKILLS.md`](../../../docs/PROPUESTAS_SKILLS.md).
Si **NO** → no fabriques churn. **Honestidad > actividad.**

## Cheatsheet

```
Disparadores: "actualizá el marketing", "features no comunicadas?", "el marketing está al día?",
              "auditá la marca", "qué hay de nuevo desde la última campaña?", "qué features tiene?"

Fuentes:
  docs/MARCA.md              → identidad, taglines, selling points, voz/tono, assets
  docs/CAMPAÑA_FEATURES.md   → inventario detallado (seleccionadas / posibilidades / no listas)

3 pasos:
  1. Inventariar features reales (rutas frontend + endpoints backend)
  2. Cruzar con MARCA.md (TODOs, selling points stale, áreas nuevas)
  3. Proponer borradores → dueño aprueba → sesión edita los docs

Nunca editar MARCA.md ni CAMPAÑA_FEATURES.md sin aprobación explícita.
```
