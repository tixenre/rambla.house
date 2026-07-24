import { useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";

import type { TallerConcepto, Institucion } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { updateConceptoInstitucionesInCache } from "./cache";
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
 * Instituciones co-presentadoras de un taller (ej. "Rambla" + "Filmar") —
 * mismo patrón que InstructoresSection: mini-CRUD global + selector
 * (ordenable) de qué instituciones co-presentan ESTE taller. Una institución
 * puede co-presentar varios talleres.
 */
export function InstitucionesSection({ concepto }: { concepto: TallerConcepto }) {
  const qc = useQueryClient();
  const [dialogInstitucion, setDialogInstitucion] = useState<Institucion | "nueva" | null>(null);

  const { data: todas = [], isLoading } = useQuery({
    queryKey: ["admin", "instituciones"],
    queryFn: () => talleresAdminApi.listInstituciones(),
    staleTime: 30_000,
  });

  const linkMut = useMutation({
    mutationFn: (ids: number[]) => talleresAdminApi.setTallerInstituciones(concepto.id, ids),
    onSuccess: (r) => updateConceptoInstitucionesInCache(qc, concepto.id, r.instituciones),
    onError: (e) => toast.error((e as Error).message),
  });

  const vinculadasIds = concepto.instituciones.map((i) => i.id);
  const disponibles = todas.filter((i) => !vinculadasIds.includes(i.id));

  function agregar(id: number) {
    linkMut.mutate([...vinculadasIds, id]);
  }

  function quitar(id: number) {
    linkMut.mutate(vinculadasIds.filter((x) => x !== id));
  }

  function mover(id: number, dir: -1 | 1) {
    const idx = vinculadasIds.indexOf(id);
    const next = [...vinculadasIds];
    const swapWith = idx + dir;
    if (swapWith < 0 || swapWith >= next.length) return;
    [next[idx], next[swapWith]] = [next[swapWith], next[idx]];
    linkMut.mutate(next);
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground mb-2">
          Instituciones co-presentadoras
        </p>
        {concepto.instituciones.length === 0 ? (
          <p className="text-sm text-muted-foreground/60 italic">
            Sin instituciones vinculadas todavía.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {concepto.instituciones.map((ins, idx) => (
              <div
                key={ins.id}
                // `surface-elevated`, no `muted`: esta card vive dentro de la
                // sección del concepto, que ya es `bg-surface`.
                className="flex items-center gap-3 rounded-xl border border-border/50 bg-surface-elevated shadow-sm px-3 py-2"
              >
                {ins.logo_url ? (
                  <img
                    src={ins.logo_url}
                    alt={ins.nombre}
                    className="h-9 w-9 rounded-lg object-contain bg-muted/30 shrink-0"
                  />
                ) : (
                  <div className="h-9 w-9 rounded-lg bg-muted shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-ink truncate">{ins.nombre}</p>
                  {ins.descripcion && (
                    <p className="text-xs text-muted-foreground truncate">{ins.descripcion}</p>
                  )}
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
                    disabled={idx === concepto.instituciones.length - 1}
                    onClick={() => mover(ins.id, 1)}
                  >
                    ↓
                  </IconButton>
                  <IconButton
                    aria-label="Editar"
                    size="sm"
                    onClick={() => setDialogInstitucion(ins)}
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
              <SelectValue placeholder="Agregar institución existente…" />
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
          onClick={() => setDialogInstitucion("nueva")}
          className="gap-1.5"
        >
          <Plus className="h-3.5 w-3.5" />
          Nueva institución
        </Button>
      </div>

      {dialogInstitucion !== null && (
        <InstitucionDialog
          institucion={dialogInstitucion === "nueva" ? null : dialogInstitucion}
          onClose={() => setDialogInstitucion(null)}
          onCreated={(nueva) => agregar(nueva.id)}
        />
      )}
    </div>
  );
}

function InstitucionDialog({
  institucion,
  onClose,
  onCreated,
}: {
  institucion: Institucion | null;
  onClose: () => void;
  onCreated: (i: Institucion) => void;
}) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [form, setForm] = useState({
    nombre: institucion?.nombre ?? "",
    descripcion: institucion?.descripcion ?? "",
    instagram: institucion?.instagram ?? "",
    web: institucion?.web ?? "",
  });
  const [pendingFile, setPendingFile] = useState<File | null>(null);

  const saveMut = useMutation({
    mutationFn: async () => {
      const saved = institucion
        ? await talleresAdminApi.updateInstitucion(institucion.id, form)
        : await talleresAdminApi.createInstitucion(form);
      if (pendingFile) {
        const r = await talleresAdminApi.uploadLogoInstitucion(saved.id, pendingFile);
        saved.logo_url = r.url;
        saved.logo_media_id = r.media_id;
      }
      return saved;
    },
    onSuccess: (saved) => {
      toast.success(institucion ? "Institución actualizada" : "Institución creada");
      qc.invalidateQueries({ queryKey: ["admin", "instituciones"] });
      // La lista "Instituciones co-presentadoras" lee de concepto.instituciones,
      // que viene de esta query — sin invalidarla, un nombre/logo editado
      // queda desactualizado en pantalla hasta recargar.
      qc.invalidateQueries({ queryKey: ["admin", "talleres"] });
      if (!institucion) onCreated(saved);
      onClose();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const deleteMut = useMutation({
    mutationFn: () => talleresAdminApi.deleteInstitucion(institucion!.id),
    onSuccess: () => {
      toast.success("Institución eliminada");
      qc.invalidateQueries({ queryKey: ["admin", "instituciones"] });
      onClose();
    },
    // 409 esperado si sigue vinculada a algún taller — el mensaje del backend
    // ("Desvinculala de sus talleres antes de borrarla") ya es claro.
    onError: (e) => toast.error((e as Error).message),
  });

  async function handleDelete() {
    if (
      !(await confirm({
        title: `¿Eliminar ${institucion!.nombre}?`,
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
          <DialogTitle>{institucion ? "Editar institución" : "Nueva institución"}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 py-2">
          {field("Nombre", "nombre")}
          {field("Descripción breve", "descripcion", { rows: 3 })}
          <div className="grid grid-cols-2 gap-4">
            {field("Instagram", "instagram")}
            {field("Web", "web")}
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
              Logo
            </label>
            <div className="flex items-center gap-3">
              {institucion?.logo_url && !pendingFile && (
                <img
                  src={institucion.logo_url}
                  alt=""
                  className="h-10 w-10 rounded-lg object-contain bg-muted/30"
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
          {institucion && (
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
