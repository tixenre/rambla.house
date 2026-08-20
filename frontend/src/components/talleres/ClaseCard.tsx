import { ChevronDown } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/design-system/ui/collapsible";
import type { Sesion } from "@/lib/api";
import { parseTemario, type LineaTemario } from "@/lib/talleres/temario";

function fmtFechaCorta(fecha: string): string {
  const d = new Date(fecha + "T12:00:00");
  return d.toLocaleDateString("es-AR", { weekday: "short", day: "numeric", month: "short" });
}

function Bullet({ text, index }: { text: string; index: number }) {
  return (
    <li className="flex items-start gap-3">
      <span className="shrink-0 mt-0.5 w-5 h-5 rounded-full bg-rosa text-ink text-xs font-bold grid place-items-center">
        {index + 1}
      </span>
      <span className="text-sm leading-relaxed text-muted-foreground">{text}</span>
    </li>
  );
}

function TituloTemario({ text }: { text: string }) {
  return <p className="font-semibold text-sm text-ink mt-2 first:mt-0">{text}</p>;
}

// Agrupa bullets consecutivos en un solo <ul> (semántica válida) con un
// título propio entre medio de cada corte — el índice numerado de un bullet
// sigue la posición GLOBAL entre todos los grupos, no se reinicia por grupo.
type Grupo =
  | { tipo: "titulo"; texto: string }
  | { tipo: "bullets"; items: { texto: string; index: number }[] };

function agruparBloques(bloques: LineaTemario[]): Grupo[] {
  const grupos: Grupo[] = [];
  let bulletIdx = 0;
  for (const b of bloques) {
    if (b.tipo === "titulo") {
      grupos.push({ tipo: "titulo", texto: b.texto });
      continue;
    }
    const entry = { texto: b.texto, index: bulletIdx++ };
    const last = grupos[grupos.length - 1];
    if (last?.tipo === "bullets") last.items.push(entry);
    else grupos.push({ tipo: "bullets", items: [entry] });
  }
  return grupos;
}

export function ClaseCard({
  clase,
  numero,
  defaultOpen,
}: {
  clase: Sesion;
  numero: number;
  defaultOpen: boolean;
}) {
  const grupos = agruparBloques(parseTemario(clase.descripcion));
  const horaLabel = clase.hora_fin_str
    ? `${clase.hora_inicio_str} – ${clase.hora_fin_str}`
    : clase.hora_inicio_str;
  // Sin temario/nota/portada no hay nada que expandir — un chevron que abre
  // a un panel vacío es un affordance mentiroso (pedido del dueño). El
  // título propio (ej. "rodaje 1" vs "preproducción 1") sigue siendo info
  // real y se muestra igual, solo que como fila estática.
  const tieneContenido = grupos.length > 0 || !!clase.nota || !!clase.portada_url;

  const encabezado = (
    <>
      <span className="shrink-0 w-8 h-8 rounded-full bg-ink text-background text-sm font-bold grid place-items-center">
        {numero}
      </span>
      <div className="flex-1 min-w-0">
        <p className="font-display text-base font-bold text-ink lowercase tracking-tight">
          {clase.titulo || `Clase ${numero}`}
        </p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {fmtFechaCorta(clase.fecha)}
          {horaLabel && ` · ${horaLabel}`}
        </p>
      </div>
    </>
  );

  if (!tieneContenido) {
    return (
      <div className="flex w-full items-center gap-4 rounded-2xl border border-border/60 px-5 py-4">
        {encabezado}
      </div>
    );
  }

  return (
    <Collapsible
      defaultOpen={defaultOpen}
      className="rounded-2xl border border-border/60 overflow-hidden"
    >
      <CollapsibleTrigger className="group flex w-full items-center gap-4 px-5 py-4 text-left hover:bg-muted/20 transition-colors">
        {encabezado}
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform duration-200 group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="px-5 pb-5 pt-1 flex flex-col gap-4">
          {clase.portada_url && (
            <img
              src={clase.portada_url}
              alt={clase.titulo}
              loading="lazy"
              className="w-full max-h-64 rounded-xl object-cover"
            />
          )}
          {grupos.length > 0 && (
            <div className="flex flex-col gap-1">
              {grupos.map((g, gi) =>
                g.tipo === "titulo" ? (
                  <TituloTemario key={gi} text={g.texto} />
                ) : (
                  <ul key={gi} className="flex flex-col gap-3">
                    {g.items.map((it) => (
                      <Bullet key={it.index} text={it.texto} index={it.index} />
                    ))}
                  </ul>
                ),
              )}
            </div>
          )}
          {clase.nota && <p className="text-sm text-muted-foreground italic">{clase.nota}</p>}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
