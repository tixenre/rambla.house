import { useRef, useState } from "react";
import { Heading, List, Plus } from "lucide-react";
import { toast } from "sonner";

import type { ClaseBody } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Textarea } from "@/design-system/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";
import { HoraSelect } from "./HoraSelect";
import { cn } from "@/lib/utils";
import { fijarFormatoDeLinea } from "@/lib/talleres/temario";

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

// Horarios en MINUTOS desde medianoche (Escuela v2 F1): 510 = 8:30.
function generarClasesSemanales(
  diaSemana: number,
  mesDesde: string,
  mesHasta: string,
  horaInicioMin: number,
  horaFinMin: number,
): ClaseBody[] {
  const [yD, mD] = mesDesde.split("-").map(Number);
  const [yH, mH] = mesHasta.split("-").map(Number);
  const end = new Date(yH, mH, 0);
  const jsDay = (diaSemana + 1) % 7;
  const cur = new Date(yD, mD - 1, 1);
  while (cur.getDay() !== jsDay) cur.setDate(cur.getDate() + 1);
  const result: ClaseBody[] = [];
  while (cur <= end) {
    result.push({
      fecha: cur.toISOString().slice(0, 10),
      hora_inicio_min: horaInicioMin,
      hora_fin_min: horaFinMin,
    });
    cur.setDate(cur.getDate() + 7);
  }
  return result;
}

export function ClasesAsistente({
  tipo,
  onTipoChange,
  clases,
  onChange,
}: {
  tipo: string;
  onTipoChange: (t: string) => void;
  clases: ClaseBody[];
  onChange: (s: ClaseBody[]) => void;
}) {
  // Estado en minutos: 540 = 9:00, 780 = 13:00.
  const [newFecha, setNewFecha] = useState("");
  const [newIni, setNewIni] = useState(540);
  const [newFin, setNewFin] = useState(780);
  const [diaSemana, setDiaSemana] = useState(0);
  const [mesDesde, setMesDesde] = useState("");
  const [mesHasta, setMesHasta] = useState("");
  const [semIni, setSemIni] = useState(540);
  const [semFin, setSemFin] = useState(780);

  function addIntensivo() {
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
    onChange(
      [...clases, { fecha: newFecha, hora_inicio_min: newIni, hora_fin_min: newFin }].sort((a, b) =>
        a.fecha.localeCompare(b.fecha),
      ),
    );
    setNewFecha("");
  }

  function generateSemanal() {
    if (!mesDesde || !mesHasta) {
      toast.error("Ingresá ambos meses");
      return;
    }
    if (mesDesde > mesHasta) {
      toast.error("El mes desde debe ser anterior al hasta");
      return;
    }
    if (semIni >= semFin) {
      toast.error("Hora inicio debe ser menor a hora fin");
      return;
    }
    const generated = generarClasesSemanales(diaSemana, mesDesde, mesHasta, semIni, semFin);
    const existingDates = new Set(generated.map((g) => g.fecha));
    const kept = clases.filter((s) => !existingDates.has(s.fecha));
    onChange([...kept, ...generated].sort((a, b) => a.fecha.localeCompare(b.fecha)));
    toast.success(`${generated.length} clases generadas`);
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
    if (!clase.id) return; // el botón está deshabilitado sin id, doble red
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
    if (!clase.id) return;
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
      <div className="flex items-center gap-3">
        <span className="text-xs font-mono uppercase tracking-wider text-muted-foreground shrink-0">
          Tipo
        </span>
        <Select value={tipo} onValueChange={onTipoChange}>
          <SelectTrigger className="w-[180px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="intensivo">Intensivo</SelectItem>
            <SelectItem value="semanal">Semanal</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {tipo === "intensivo" && (
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
          <Button variant="outline" size="sm" onClick={addIntensivo} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            Agregar fecha
          </Button>
        </div>
      )}

      {tipo === "semanal" && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">Día</label>
            <Select value={String(diaSemana)} onValueChange={(v) => setDiaSemana(Number(v))}>
              <SelectTrigger className="w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DIAS.map((d, i) => (
                  <SelectItem key={i} value={String(i)}>
                    {d}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">Desde (mes)</label>
            <Input
              type="month"
              value={mesDesde}
              onChange={(e) => setMesDesde(e.target.value)}
              className="w-[140px]"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">Hasta (mes)</label>
            <Input
              type="month"
              value={mesHasta}
              onChange={(e) => setMesHasta(e.target.value)}
              className="w-[140px]"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">Desde</label>
            <HoraSelect value={semIni} onChange={setSemIni} min={0} max={1410} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">Hasta</label>
            <HoraSelect value={semFin} onChange={setSemFin} min={30} max={1440} />
          </div>
          <Button variant="outline" size="sm" onClick={generateSemanal} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            Generar
          </Button>
        </div>
      )}

      {clases.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
            {clases.length} clase{clases.length !== 1 ? "s" : ""} · publicadas bloquean el estudio
            en esas franjas
          </p>
          {/* F2: cada clase es una card editable — título, descripción (temario,
              1 ítem por línea), nota y portada. La portada requiere clase
              GUARDADA (id); el resto viaja junto con "Guardar clases". */}
          <div className="flex flex-col gap-2.5">
            {clases.map((s, idx) => (
              <div
                key={s.id ?? `nueva-${idx}`}
                className="rounded-xl border border-border/50 bg-muted/20 p-3 flex flex-col gap-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  {/* Fecha/hora propias de ESTA clase — no atadas al patrón del
                      generador: un taller real tiene clases más largas, en otro
                      día, o reprogramadas. El backend ya trata cada clase como
                      fila independiente (sin cambios ahí). */}
                  <Input
                    type="date"
                    value={s.fecha}
                    onChange={(e) => patchAt(idx, { fecha: e.target.value })}
                    className="h-8 text-xs w-[136px] shrink-0"
                  />
                  <HoraSelect
                    value={s.hora_inicio_min}
                    onChange={(v) => patchAt(idx, { hora_inicio_min: v })}
                    min={0}
                    max={1410}
                    className="h-8 w-[84px] shrink-0 text-xs"
                  />
                  <span className="text-xs text-muted-foreground shrink-0">–</span>
                  <HoraSelect
                    value={s.hora_fin_min}
                    onChange={(v) => patchAt(idx, { hora_fin_min: v })}
                    min={30}
                    max={1440}
                    className="h-8 w-[84px] shrink-0 text-xs"
                  />
                  <Input
                    value={s.titulo ?? ""}
                    onChange={(e) => patchAt(idx, { titulo: e.target.value })}
                    placeholder={`Clase ${idx + 1}: título`}
                    className="h-8 text-sm flex-1 min-w-[140px]"
                  />
                  <button
                    onClick={() => removeAt(idx)}
                    className="h-8 w-8 shrink-0 flex items-center justify-center text-muted-foreground/60 hover:text-destructive transition rounded"
                    aria-label="Quitar clase"
                  >
                    ×
                  </button>
                </div>
                <div className="flex flex-col gap-1">
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => aplicarFormato(idx, "titulo")}
                      className="h-6 w-6 grid place-items-center rounded text-muted-foreground hover:bg-ink/5 hover:text-ink transition"
                      title="Marcar la línea del cursor como título"
                      aria-label="Marcar la línea del cursor como título"
                    >
                      <Heading className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => aplicarFormato(idx, "bullet")}
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
                    ref={(el) => {
                      textareaRefs.current[idx] = el;
                    }}
                    value={s.descripcion ?? ""}
                    onChange={(e) => patchAt(idx, { descripcion: e.target.value })}
                    placeholder="Temario / descripción — un ítem por línea"
                    rows={2}
                    className="resize-y text-sm"
                  />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    value={s.nota ?? ""}
                    onChange={(e) => patchAt(idx, { nota: e.target.value })}
                    placeholder="Nota (opcional, ej: se dicta junto a la clase 12)"
                    className="h-8 text-sm flex-1 min-w-[180px]"
                  />
                  {s.portada_url ? (
                    <span className="flex items-center gap-1.5 shrink-0">
                      <img
                        src={s.portada_url}
                        alt="Portada"
                        className="h-8 w-12 rounded object-cover border border-border/50"
                      />
                      <button
                        onClick={() => quitarPortada(idx)}
                        className="text-xs text-muted-foreground hover:text-destructive transition"
                      >
                        Quitar portada
                      </button>
                    </span>
                  ) : (
                    <label
                      className={
                        s.id
                          ? "text-xs font-medium text-ink underline underline-offset-2 cursor-pointer shrink-0"
                          : "text-xs text-muted-foreground/50 shrink-0 cursor-not-allowed"
                      }
                      title={
                        s.id ? "Subir portada" : "Guardá las clases primero para subir portada"
                      }
                    >
                      + Portada
                      {/* eslint-disable-next-line no-restricted-syntax -- input file: no hay componente DS */}
                      <input
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        className="hidden"
                        disabled={!s.id}
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) void subirPortada(idx, f);
                          e.target.value = "";
                        }}
                      />
                    </label>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground/60 italic">
          Sin clases. Agregá al menos una (publicada, bloquea el estudio).
        </p>
      )}
    </div>
  );
}
