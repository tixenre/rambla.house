// ── Áreas de Rambla — fuente única ─────────────────────────────────────────────
// Las 3 áreas públicas con su identidad de marca. La consumen el TopBar
// (SECTION_CONFIG), el menú de navegación (AreaMenu), el hub y el SectionBanner.
// Cambiar el color, la ruta o el label de un área se hace acá una sola vez.
//
// - `label`:   nombre con punto, font-display lowercase ("rental.")
// - `desc`:    bajada corta (menú de áreas)
// - `eyebrow`: categoría corta SIN repetir el nombre del área (evita el
//              "RAMBLA estudio. / estudio." repetido — un eyebrow no puede
//              decir lo mismo que el label que tiene justo debajo)
// - `href`:    root del área
// - `bg`:      clase de fondo de marca (topbar)
// - `fg`:      color de texto legible sobre `bg` (logo/contenido sobre el color)
// - `accent`:  color de marca como texto (wordmark/label en el SectionBanner)

export const AREAS = {
  rental: {
    label: "rental.",
    desc: "Alquiler de equipos",
    eyebrow: "Equipos audiovisuales",
    href: "/rental",
    bg: "bg-amber",
    fg: "text-ink",
    accent: "text-amber",
  },
  estudio: {
    label: "estudio.",
    desc: "Set de foto y video",
    eyebrow: "Foto & video",
    href: "/estudio",
    bg: "bg-estudio",
    fg: "text-ink",
    accent: "text-estudio",
  },
  // La vertical de formación: key `escuela`, ruta `/escuela` (SIN CAMBIOS — key/
  // href/`[data-area="escuela"]` siguen singular, solo cambia el label visible).
  // Label "escuelas." (plural, 2026-07-30): Rambla no ES la escuela, aloja
  // distintas entidades/talleres adentro — "escuela." (singular) sonaba a que
  // Rambla fuera la única. Las clases que ofrece se siguen llamando "talleres"
  // — la API `/api/talleres` y la tabla `talleres` NO se renombran (un taller es
  // un taller; la escuela los ofrece). `/workshops` redirige a `/escuela` (única
  // redirección; `/talleres` ya no se soporta).
  escuela: {
    label: "escuelas.",
    desc: "Talleres y workshops",
    eyebrow: "Formación",
    href: "/escuela",
    bg: "bg-rosa",
    fg: "text-ink",
    accent: "text-rosa",
  },
} as const;

export type AreaKey = keyof typeof AREAS;

/** Las áreas como lista, para iterar (menú de navegación). */
export const AREA_LIST = (Object.keys(AREAS) as AreaKey[]).map((key) => ({ key, ...AREAS[key] }));
