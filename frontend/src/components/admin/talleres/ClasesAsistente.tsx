import { useRef, useState } from "react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import type { ClaseBody } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { HoraSelect } from "./HoraSelect";
import { SortableClaseCard } from "./SortableClaseCard";
import { fijarFormatoDeLinea } from "@/lib/talleres/temario";
import { nextDraftId } from "@/lib/talleres/draftId";

export function ClasesAsistente({
  clases,
  onChange,
}: {
  clases: ClaseBody[];
  onChange: (s: ClaseBody[]) => void;
}) {
  // Estado en minutos: 540 = 9:00, 780 = 13:00.
  const [newFecha, setNewFecha] = useState("");
  const [newIni, setNewIni] = useState(540);
  const [newFin, setNewFin] = useState(780);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function addClase() {
    if (!newFecha) {
      toast.error("Ingresá una fecha");
      return;
    }
    if (newIni >= newFin) {
      toast.error("Hora inicio debe ser menor a hora fin");
      return;
    }
    // Se permite repetir fecha (e incluso franja): "Clase 11 y 12 se dictan
    // juntas". El backend rechaza el duplicado EXACTO (fecha+franja+título).
    // Se agrega AL FINAL, sin re-ordenar por fecha — el orden es manual
    // (arrastrás para ubicarla donde corresponda; "Clase N" sale de la
    // posición, no de la fecha).
    onChange([
      ...clases,
      { id: nextDraftId(), fecha: newFecha, hora_inicio_min: newIni, hora_fin_min: newFin },
    ]);
    setNewFecha("");
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIdx = clases.findIndex((c) => c.id === active.id);
    const newIdx = clases.findIndex((c) => c.id === over.id);
    if (oldIdx === -1 || newIdx === -1) return;
    onChange(arrayMove(clases, oldIdx, newIdx));
  }

  function removeAt(idx: number) {
    onChange(clases.filter((_, i) => i !== idx));
  }

  function patchAt(idx: number, patch: Partial<ClaseBody>) {
    onChange(clases.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  }

  const textareaRefs = useRef<Record<number, HTMLTextAreaElement | null>>({});

  function aplicarFormato(idx: number, formato: "titulo" | "bullet") {
    const el = textareaRefs.current[idx];
    if (!el) return;
    const { texto, cursor } = fijarFormatoDeLinea(
      el.value,
      el.selectionStart ?? el.value.length,
      formato,
    );
    patchAt(idx, { descripcion: texto });
    // El re-render de React actualiza `el.value` de forma async — recién ahí
    // se puede restaurar la posición del cursor sin que quede pisada.
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(cursor, cursor);
    });
  }

  async function subirPortada(idx: number, file: File) {
    const clase = clases[idx];
    // Id sintético (draft sin guardar todavía) es negativo — el botón ya
    // está deshabilitado en ese caso, esto es la segunda red.
    if (!clase.id || clase.id < 0) return;
    try {
      const r = await talleresAdminApi.uploadPortadaClase(clase.id, file);
      patchAt(idx, { portada_url: r.url, portada_media_id: r.media_id });
      toast.success("Portada subida");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function quitarPortada(idx: number) {
    const clase = clases[idx];
    if (!clase.id || clase.id < 0) return;
    try {
      await talleresAdminApi.deletePortadaClase(clase.id);
      patchAt(idx, { portada_url: "", portada_media_id: null });
      toast.success("Portada quitada");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Fecha</label>
          <Input
            type="date"
            value={newFecha}
            onChange={(e) => setNewFecha(e.target.value)}
            className="w-[160px]"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Desde</label>
          <HoraSelect value={newIni} onChange={setNewIni} min={0} max={1410} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Hasta</label>
          <HoraSelect value={newFin} onChange={setNewFin} min={30} max={1440} />
        </div>
        <Button variant="outline" size="sm" onClick={addClase} className="gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          Agregar clase
        </Button>
      </div>

      {clases.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
            {clases.length} clase{clases.length !== 1 ? "s" : ""} · publicadas bloquean el estudio
            en esas franjas
          </p>
          {/* F2: cada clase es una card editable — título, descripción (temario,
              1 ítem por línea), nota y portada. La portada requiere clase
              GUARDADA (id real); el resto viaja junto con "Guardar clases".
              Arrastrable: "Clase N" sale de la posición en esta lista, no de
              la fecha (una clase puede ser pedagógicamente la 5ta sin ser la
              5ta cronológica). */}
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={clases.map((c) => c.id!)}
              strategy={verticalListSortingStrategy}
            >
              <div className="flex flex-col gap-2.5">
                {clases.map((s, idx) => (
                  <SortableClaseCard
                    key={s.id}
                    id={s.id!}
                    numero={idx + 1}
                    clase={s}
                    onPatch={(patch) => patchAt(idx, patch)}
                    onRemove={() => removeAt(idx)}
                    onAplicarFormato={(formato) => aplicarFormato(idx, formato)}
                    onSubirPortada={(file) => void subirPortada(idx, file)}
                    onQuitarPortada={() => void quitarPortada(idx)}
                    textareaRef={(el) => {
                      textareaRefs.current[idx] = el;
                    }}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground/60 italic">
          Sin clases. Agregá al menos una (publicada, bloquea el estudio).
        </p>
      )}
    </div>
  );
}
