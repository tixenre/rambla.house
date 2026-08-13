import type { Sesion } from "@/lib/api";
import { parseTemario } from "@/lib/talleres/temario";
import { ClaseCard } from "./ClaseCard";
import { SeccionCard } from "./SeccionCard";

const TITULO_GENERICO_RE = /^Clase \d+$/;

/** Sin temario/nota/portada y con un título tipo "Clase N" (o vacío), una
 * clase no tiene nada propio que mostrar — solo repetiría fecha/hora, que ya
 * están en el calendario de arriba. */
function esClaseGenerica(clase: Sesion): boolean {
  const titulo = clase.titulo.trim();
  const tituloGenerico = titulo === "" || TITULO_GENERICO_RE.test(titulo);
  return (
    tituloGenerico &&
    parseTemario(clase.descripcion).length === 0 &&
    !clase.nota &&
    !clase.portada_url
  );
}

/**
 * Timeline de clases, colapsables. El orden es el que ya trae la API
 * (`orden, id` — manual, no la fecha: el admin puede arrastrar una clase a
 * donde corresponda pedagógicamente, no siempre coincide con la cronología).
 * `defaultOpen` es data-driven: con pocas clases (Jime, 2) quedan todas
 * abiertas como antes — cero regresión; con muchas (Filmar, 12-13) colapsan
 * salvo la primera.
 *
 * Si NINGUNA clase tiene contenido propio (temario/nota/portada/título real)
 * la sección entera no aporta nada sobre el calendario — no se muestra.
 */
export function ProgramaSection({ clases }: { clases: Sesion[] }) {
  if (clases.length === 0) return null;
  if (clases.every(esClaseGenerica)) return null;

  return (
    <SeccionCard eyebrow="Programa">
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
    </SeccionCard>
  );
}
