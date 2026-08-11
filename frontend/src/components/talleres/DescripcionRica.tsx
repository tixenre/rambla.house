import { parseDescripcionRica } from "@/lib/talleres/descripcionRica";

/** Renderiza descripción/público objetivo del taller con jerarquía real
 * (títulos, párrafos, listas numeradas con sub-viñetas) en vez de un bloque
 * de texto plano — ver `lib/talleres/descripcionRica.ts` para el formato. */
export function DescripcionRica({ texto, className = "" }: { texto: string; className?: string }) {
  if (!texto) return null;
  const bloques = parseDescripcionRica(texto);

  return (
    <div className={`flex flex-col gap-4 ${className}`}>
      {bloques.map((b, i) => {
        if (b.tipo === "titulo") {
          return (
            <p key={i} className="font-display text-xl font-bold text-ink lowercase tracking-tight">
              {b.texto}
            </p>
          );
        }
        if (b.tipo === "parrafo") {
          return (
            <p key={i} className="leading-relaxed">
              {b.texto}
            </p>
          );
        }
        return (
          <ol key={i} className="flex flex-col gap-3">
            {b.items.map((item, ii) => (
              <li key={ii} className="flex flex-col gap-1.5">
                <div className="flex items-start gap-3">
                  <span className="shrink-0 mt-0.5 w-5 h-5 rounded-full bg-rosa text-ink text-xs font-bold grid place-items-center">
                    {ii + 1}
                  </span>
                  <span className="font-semibold text-ink leading-relaxed">{item.texto}</span>
                </div>
                {item.subitems.length > 0 && (
                  <ul className="flex flex-col gap-1.5 pl-8">
                    {item.subitems.map((sub, si) => (
                      <li key={si} className="flex items-start gap-2 text-sm leading-relaxed">
                        <span className="shrink-0 mt-2 w-1 h-1 rounded-full bg-muted-foreground/60" />
                        {sub}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
        );
      })}
    </div>
  );
}
