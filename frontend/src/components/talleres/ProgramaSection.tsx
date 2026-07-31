import type { Sesion } from "@/lib/api";
import { ClaseCard } from "./ClaseCard";

/**
 * Timeline de clases, colapsables. El orden es el que ya trae la API
 * (`orden, id` — manual, no la fecha: el admin puede arrastrar una clase a
 * donde corresponda pedagógicamente, no siempre coincide con la cronología).
 * `defaultOpen` es data-driven: con pocas clases (Jime, 2) quedan todas
 * abiertas como antes — cero regresión; con muchas (Filmar, 12-13) colapsan
 * salvo la primera.
 */
export function ProgramaSection({ clases }: { clases: Sesion[] }) {
  if (clases.length === 0) return null;

  return (
    <section>
      <p className="font-mono text-2xs tracking-[0.25em] uppercase text-rosa mb-4">Programa</p>
      <div className="flex flex-col gap-3">
        {clases.map((clase, i) => (
          <ClaseCard
            key={i}
            clase={clase}
            numero={i + 1}
            defaultOpen={clases.length <= 4 || i === 0}
          />
        ))}
      </div>
    </section>
  );
}
