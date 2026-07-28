import { AREAS, type AreaKey } from "@/data/areas";

// Bajada propia del banner (copy editorial, más larga que `AREAS[].desc` que
// es para el menú) — reusa frases ya escritas para la misma área en el hub
// (`routes/index.tsx`), no inventa una voz nueva.
const TAGLINE: Record<AreaKey, string> = {
  rental: "Alquilá lo que necesitás — retiro en el estudio.",
  estudio: "Un lugar donde pasan cosas: set con ciclorama y luz natural.",
  escuela: "Clases prácticas de dirección de arte, foto y video. Cupos limitados.",
};

/**
 * Banner de sección: fondo ink + grain, label enorme en el color de marca de
 * la sección + bajada. Un banner por cada vertical de Rambla.
 *
 * Sin el wordmark "RAMBLA" (se sacó, #1304-adjacent): el topbar de arriba ya
 * lo muestra pegado al label del área ("RAMBLA escuela.") — repetirlo acá
 * abajo leía como el mismo texto dos veces seguidas. La bajada ocupa ese
 * lugar con información nueva en vez de repetir la marca.
 */
export function SectionBanner({
  section,
  className = "",
}: {
  section: AreaKey;
  className?: string;
}) {
  const { label, eyebrow, accent: color } = AREAS[section];
  const tagline = TAGLINE[section];

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

        {/* Label de sección */}
        <p
          className={`font-display font-black lowercase leading-[0.88] tracking-[-0.02em] ${color}`}
          style={{ fontSize: "clamp(2rem, 6vw, 4rem)" }}
        >
          {label}
        </p>

        {/* Bajada */}
        <p className="max-w-md text-sm sm:text-base text-white/70 leading-relaxed">{tagline}</p>
      </div>
    </div>
  );
}
