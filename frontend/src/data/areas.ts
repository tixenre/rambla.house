// ── Áreas de Rambla — fuente única ─────────────────────────────────────────────
// Las 3 áreas públicas con su identidad de marca. La consumen el TopBar
// (SECTION_CONFIG), el menú de navegación (AreaMenu), el hub y el SectionBanner.
// Cambiar el color, la ruta o el label de un área se hace acá una sola vez.
//
// - `label`:   nombre con punto, font-display lowercase ("rental.")
// - `desc`:    bajada corta (menú de áreas)
// - `eyebrow`: categoría corta SIN repetir el nombre del área (evita el
//              "RAMBLA escuela. / escuela." repetido — un eyebrow no puede
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
  // La vertical de formación: key `escuela`, ruta `/escuela`, label "escuela.",
  // theming `[data-area="escuela"]`. Las clases que ofrece se siguen llamando
  // "talleres" — la API `/api/talleres` y la tabla `talleres` NO se renombran (un
  // taller es un taller; la escuela los ofrece). `/workshops` redirige a `/escuela`
  // (única redirección; `/talleres` ya no se soporta).
  escuela: {
    label: "escuela.",
    desc: "Talleres y formación",
    eyebrow: "Talleres & formación",
    href: "/escuela",
    bg: "bg-rosa",
    fg: "text-ink",
    accent: "text-rosa",
  },
} as const;

export type AreaKey = keyof typeof AREAS;

/** Las áreas como lista, para iterar (menú de navegación). */
export const AREA_LIST = (Object.keys(AREAS) as AreaKey[]).map((key) => ({ key, ...AREAS[key] }));
