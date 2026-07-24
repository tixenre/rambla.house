import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Heading, List } from "lucide-react";

import type { ClaseBody } from "@/lib/admin/api/types";
import { Input } from "@/design-system/ui/input";
import { Textarea } from "@/design-system/ui/textarea";
import { HoraSelect } from "./HoraSelect";
import { cn } from "@/lib/utils";

/**
 * Una clase editable — arrastrable (handle propio, no la card entera: el
 * resto son inputs/textarea que necesitan click/foco normales). "Clase N:"
 * es un label fijo (posición en la lista, la maneja el padre) — el input de
 * título es solo el fragmento libre, no el string completo.
 */
export function SortableClaseCard({
  id,
  numero,
  clase,
  onPatch,
  onRemove,
  onAplicarFormato,
  onSubirPortada,
  onQuitarPortada,
  textareaRef,
}: {
  id: number;
  numero: number;
  clase: ClaseBody;
  onPatch: (patch: Partial<ClaseBody>) => void;
  onRemove: () => void;
  onAplicarFormato: (formato: "titulo" | "bullet") => void;
  onSubirPortada: (file: File) => void;
  onQuitarPortada: () => void;
  textareaRef: (el: HTMLTextAreaElement | null) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
  });
  const style = { transform: CSS.Transform.toString(transform), transition };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "rounded-xl border border-border/50 bg-muted/20 p-3 flex flex-col gap-2 transition-shadow",
        isDragging && "shadow-lg opacity-80",
      )}
    >
      <div className="flex items-center gap-2">
        <button
          {...attributes}
          {...listeners}
          className="cursor-grab text-muted-foreground/60 hover:text-ink p-1 touch-none shrink-0"
          aria-label="Arrastrar para reordenar"
        >
          <GripVertical className="h-4 w-4" />
        </button>
        <span className="text-xs font-mono text-muted-foreground shrink-0">Clase {numero}:</span>
        <Input
          value={clase.titulo ?? ""}
          onChange={(e) => onPatch({ titulo: e.target.value })}
          placeholder="Título (opcional)"
          className="h-8 text-sm flex-1 min-w-0"
        />
        <button
          onClick={onRemove}
          className="h-8 w-8 shrink-0 flex items-center justify-center text-muted-foreground/60 hover:text-destructive transition rounded"
          aria-label="Quitar clase"
        >
          ×
        </button>
      </div>

      {/* Fecha/hora propias de ESTA clase — no atadas a un patrón: un taller
          real tiene clases más largas, en otro día, o reprogramadas. */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="date"
          value={clase.fecha}
          onChange={(e) => onPatch({ fecha: e.target.value })}
          className="h-8 text-xs w-[136px] shrink-0"
        />
        <HoraSelect
          value={clase.hora_inicio_min}
          onChange={(v) => onPatch({ hora_inicio_min: v })}
          min={0}
          max={1410}
          className="h-8 w-[84px] shrink-0 text-xs"
        />
        <span className="text-xs text-muted-foreground shrink-0">–</span>
        <HoraSelect
          value={clase.hora_fin_min}
          onChange={(v) => onPatch({ hora_fin_min: v })}
          min={30}
          max={1440}
          className="h-8 w-[84px] shrink-0 text-xs"
        />
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onAplicarFormato("titulo")}
            className="h-6 w-6 grid place-items-center rounded text-muted-foreground hover:bg-ink/5 hover:text-ink transition"
            title="Marcar la línea del cursor como título"
            aria-label="Marcar la línea del cursor como título"
          >
            <Heading className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => onAplicarFormato("bullet")}
            className="h-6 w-6 grid place-items-center rounded text-muted-foreground hover:bg-ink/5 hover:text-ink transition"
            title="Marcar la línea del cursor como punto"
            aria-label="Marcar la línea del cursor como punto"
          >
            <List className="h-3.5 w-3.5" />
          </button>
          <span className="text-2xs text-muted-foreground/60">
            Título / punteo — aplica a la línea donde está el cursor
          </span>
        </div>
        <Textarea
          ref={textareaRef}
          value={clase.descripcion ?? ""}
          onChange={(e) => onPatch({ descripcion: e.target.value })}
          placeholder="Temario / descripción — un ítem por línea"
          rows={2}
          className="resize-y text-sm"
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={clase.nota ?? ""}
          onChange={(e) => onPatch({ nota: e.target.value })}
          placeholder="Nota (opcional, ej: se dicta junto a la clase 12)"
          className="h-8 text-sm flex-1 min-w-[180px]"
        />
        {clase.portada_url ? (
          <span className="flex items-center gap-1.5 shrink-0">
            <img
              src={clase.portada_url}
              alt="Portada"
              className="h-8 w-12 rounded object-cover border border-border/50"
            />
            <button
              onClick={onQuitarPortada}
              className="text-xs text-muted-foreground hover:text-destructive transition"
            >
              Quitar portada
            </button>
          </span>
        ) : (
          <label
            className={
              clase.id && clase.id > 0
                ? "text-xs font-medium text-ink underline underline-offset-2 cursor-pointer shrink-0"
                : "text-xs text-muted-foreground/50 shrink-0 cursor-not-allowed"
            }
            title={
              clase.id && clase.id > 0
                ? "Subir portada"
                : "Guardá las clases primero para subir portada"
            }
          >
            + Portada
            {/* eslint-disable-next-line no-restricted-syntax -- input file: no hay componente DS */}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              disabled={!clase.id || clase.id < 0}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onSubirPortada(f);
                e.target.value = "";
              }}
            />
          </label>
        )}
      </div>
    </div>
  );
}
