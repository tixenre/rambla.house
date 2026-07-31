import { useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";

import type { TallerConcepto, Instructor } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { updateConceptoInstructoresInCache } from "./cache";
import { useConfirm } from "@/components/admin/useConfirm";
import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { Input } from "@/design-system/ui/input";
import { Textarea } from "@/design-system/ui/textarea";
import { Spinner } from "@/design-system/ui/spinner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/design-system/ui/dialog";

/**
 * F3: instructores como entidad — mini-CRUD global + selector (ordenable por
 * agregar/quitar) de quiénes dan ESTE taller. Un instructor puede dar varios
 * talleres (Filmar: mismo instructor en Principiante y Avanzado).
 */
export function InstructoresSection({ concepto }: { concepto: TallerConcepto }) {
  const qc = useQueryClient();
  const [dialogInstructor, setDialogInstructor] = useState<Instructor | "nuevo" | null>(null);

  const { data: todos = [], isLoading } = useQuery({
    queryKey: ["admin", "instructores"],
    queryFn: () => talleresAdminApi.listInstructores(),
    staleTime: 30_000,
  });

  const linkMut = useMutation({
    mutationFn: (ids: number[]) => talleresAdminApi.setTallerInstructores(concepto.id, ids),
    onSuccess: (r) => updateConceptoInstructoresInCache(qc, concepto.id, r.instructores),
    onError: (e) => toast.error((e as Error).message),
  });

  const vinculadosIds = concepto.instructores.map((i) => i.id);
  const disponibles = todos.filter((i) => !vinculadosIds.includes(i.id));

  function agregar(id: number) {
    linkMut.mutate([...vinculadosIds, id]);
  }

  function quitar(id: number) {
    linkMut.mutate(vinculadosIds.filter((x) => x !== id));
  }

  function mover(id: number, dir: -1 | 1) {
    const idx = vinculadosIds.indexOf(id);
    const next = [...vinculadosIds];
    const swapWith = idx + dir;
    if (swapWith < 0 || swapWith >= next.length) return;
    [next[idx], next[swapWith]] = [next[swapWith], next[idx]];
    linkMut.mutate(next);
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground mb-2">
          Instructores de este taller
        </p>
        {concepto.instructores.length === 0 ? (
          <p className="text-sm text-muted-foreground/60 italic">
            Sin instructores vinculados todavía.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {concepto.instructores.map((ins, idx) => (
              <div
                key={ins.id}
                className="flex items-center gap-3 rounded-xl border border-border/50 bg-muted/20 px-3 py-2"
              >
                {ins.foto_url ? (
                  <img
                    src={ins.foto_url}
                    alt={ins.nombre}
                    className="h-9 w-9 rounded-full object-cover shrink-0"
                  />
                ) : (
                  <div className="h-9 w-9 rounded-full bg-muted shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-ink truncate">{ins.nombre}</p>
                  {ins.rol && <p className="text-xs text-muted-foreground truncate">{ins.rol}</p>}
                </div>
                <div className="flex items-center gap-0.5 shrink-0">
                  <IconButton
                    aria-label="Subir"
                    size="sm"
                    disabled={idx === 0}
                    onClick={() => mover(ins.id, -1)}
                  >
                    ↑
                  </IconButton>
                  <IconButton
                    aria-label="Bajar"
                    size="sm"
                    disabled={idx === concepto.instructores.length - 1}
                    onClick={() => mover(ins.id, 1)}
                  >
                    ↓
                  </IconButton>
                  <IconButton
                    aria-label="Editar"
                    size="sm"
                    onClick={() => setDialogInstructor(ins)}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </IconButton>
                  <IconButton
                    aria-label="Quitar del taller"
                    size="sm"
                    onClick={() => quitar(ins.id)}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </IconButton>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        {disponibles.length > 0 && (
          <Select onValueChange={(v) => agregar(Number(v))} disabled={isLoading}>
            <SelectTrigger className="w-[220px]">
              <SelectValue placeholder="Agregar instructor existente…" />
            </SelectTrigger>
            <SelectContent>
              {disponibles.map((i) => (
                <SelectItem key={i.id} value={String(i.id)}>
                  {i.nombre}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={() => setDialogInstructor("nuevo")}
          className="gap-1.5"
        >
          <Plus className="h-3.5 w-3.5" />
          Nuevo instructor
        </Button>
      </div>

      {dialogInstructor !== null && (
        <InstructorDialog
          instructor={dialogInstructor === "nuevo" ? null : dialogInstructor}
          onClose={() => setDialogInstructor(null)}
          onCreated={(nuevo) => agregar(nuevo.id)}
        />
      )}
    </div>
  );
}

function InstructorDialog({
  instructor,
  onClose,
  onCreated,
}: {
  instructor: Instructor | null;
  onClose: () => void;
  onCreated: (i: Instructor) => void;
}) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [form, setForm] = useState({
    nombre: instructor?.nombre ?? "",
    rol: instructor?.rol ?? "",
    descripcion: instructor?.descripcion ?? "",
    instagram: instructor?.instagram ?? "",
    web: instructor?.web ?? "",
    proyectos: instructor?.proyectos ?? "",
  });
  const [pendingFile, setPendingFile] = useState<File | null>(null);

  const saveMut = useMutation({
    mutationFn: async () => {
      const saved = instructor
        ? await talleresAdminApi.updateInstructor(instructor.id, form)
        : await talleresAdminApi.createInstructor(form);
      if (pendingFile) {
        const r = await talleresAdminApi.uploadFotoInstructorPerfil(saved.id, pendingFile);
        saved.foto_url = r.url;
        saved.foto_media_id = r.media_id;
      }
      return saved;
    },
    onSuccess: (saved) => {
      toast.success(instructor ? "Instructor actualizado" : "Instructor creado");
      qc.invalidateQueries({ queryKey: ["admin", "instructores"] });
      // La lista "Instructores de este taller" lee de concepto.instructores,
      // que viene de esta query — sin invalidarla, un nombre/foto editado
      // queda desactualizado en pantalla hasta recargar.
      qc.invalidateQueries({ queryKey: ["admin", "talleres"] });
      if (!instructor) onCreated(saved);
      onClose();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const deleteMut = useMutation({
    mutationFn: () => talleresAdminApi.deleteInstructor(instructor!.id),
    onSuccess: () => {
      toast.success("Instructor eliminado");
      qc.invalidateQueries({ queryKey: ["admin", "instructores"] });
      onClose();
    },
    // 409 esperado si sigue vinculado a algún taller — el mensaje del backend
    // ("Desvinculalo de sus talleres antes de borrarlo") ya es claro.
    onError: (e) => toast.error((e as Error).message),
  });

  async function handleDelete() {
    if (
      !(await confirm({
        title: `¿Eliminar a ${instructor!.nombre}?`,
        description: "Esta acción no se puede deshacer.",
        danger: true,
        confirmLabel: "Eliminar",
      }))
    )
      return;
    deleteMut.mutate();
  }

  const field = (label: string, key: keyof typeof form, opts?: { rows?: number }) => (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
        {label}
      </label>
      {(opts?.rows ?? 1) === 1 ? (
        <Input
          value={form[key]}
          onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
        />
      ) : (
        <Textarea
          rows={opts?.rows}
          value={form[key]}
          onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
          className="resize-y"
        />
      )}
    </div>
  );

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{instructor ? "Editar instructor" : "Nuevo instructor"}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 py-2">
          {field("Nombre", "nombre")}
          {field("Rol", "rol")}
          {field("Descripción breve", "descripcion", { rows: 3 })}
          <div className="grid grid-cols-2 gap-4">
            {field("Instagram", "instagram")}
            {field("Web", "web")}
          </div>
          {field("Proyectos (separados por coma)", "proyectos", { rows: 2 })}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
              Foto
            </label>
            <div className="flex items-center gap-3">
              {instructor?.foto_url && !pendingFile && (
                <img
                  src={instructor.foto_url}
                  alt=""
                  className="h-10 w-10 rounded-full object-cover"
                />
              )}
              {/* eslint-disable-next-line no-restricted-syntax -- input file: no hay componente DS */}
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(e) => setPendingFile(e.target.files?.[0] ?? null)}
                className="text-sm"
              />
            </div>
          </div>
        </div>
        <DialogFooter>
          {instructor && (
            <Button
              variant="ghost"
              onClick={handleDelete}
              disabled={deleteMut.isPending}
              className="mr-auto text-muted-foreground hover:text-destructive gap-2"
            >
              {deleteMut.isPending ? <Spinner size="sm" /> : null}
              Eliminar
            </Button>
          )}
          <DialogClose asChild>
            <Button variant="ghost">Cancelar</Button>
          </DialogClose>
          <Button
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending || !form.nombre.trim()}
            className="gap-2"
          >
            {saveMut.isPending ? <Spinner size="sm" /> : null}
            Guardar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
