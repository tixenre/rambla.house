import { AREAS, type AreaKey } from "@/data/areas";

// El hero ya NO repite el nombre del área (el topbar de arriba ya dice
// "RAMBLA <área>." — poner el label de nuevo acá abajo, aunque fuera sin el
// wordmark, seguía leyendo como "escuela." dos veces seguidas). En su lugar,
// el título grande del banner es la PROMESA de la sección — reusa frases ya
// escritas para la misma área en el hub (`routes/index.tsx`), no inventa una
// voz nueva. `AREAS[].label` sigue vivo para el topbar/menú, acá no se usa.
const HEADLINE: Record<AreaKey, string> = {
  rental: "alquilá lo que necesitás.",
  estudio: "un lugar donde pasan cosas.",
  escuela: "talleres y workshops.",
};

const BODY: Record<AreaKey, string> = {
  rental: "Cámaras, lentes, iluminación, audio y soportes. Retiro en el estudio.",
  estudio: "Set con fondo infinito, ciclorama y luz natural. Por hora.",
  escuela: "Clases prácticas de dirección de arte, foto y video. Cupos limitados.",
};

/**
 * Banner de sección: fondo ink + grain, promesa de la sección enorme (no el
 * nombre del área) + bajada. Un banner por cada vertical de Rambla.
 */
export function SectionBanner({
  section,
  className = "",
}: {
  section: AreaKey;
  className?: string;
}) {
  const { eyebrow, accent: color } = AREAS[section];
  const headline = HEADLINE[section];
  const body = BODY[section];

  return (
    <div className={`relative bg-ink overflow-hidden flex flex-col justify-end ${className}`}>
      {/* Grain texture */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage: "radial-gradient(circle, white 1px, transparent 1px)",
          backgroundSize: "5px 5px",
        }}
      />

      {/* Contenido */}
      <div className="relative px-8 sm:px-12 pb-8 sm:pb-12 pt-10 sm:pt-14 flex flex-col gap-3">
        {/* Eyebrow */}
        <p className={`font-mono text-2xs tracking-[0.3em] uppercase ${color} opacity-70`}>
          {eyebrow}
        </p>

        {/* Promesa de la sección (no repite el área — ver comentario arriba) */}
        <p
          className={`font-display font-black lowercase leading-[0.95] tracking-[-0.02em] max-w-xl ${color}`}
          style={{ fontSize: "clamp(1.75rem, 4.5vw, 3rem)" }}
        >
          {headline}
        </p>

        {/* Bajada */}
        <p className="max-w-md text-sm sm:text-base text-white/70 leading-relaxed">{body}</p>
      </div>
    </div>
  );
}
