/**
 * PhotoGallery — galería de fotos genérica/reusable para el back-office.
 *
 * Pensada para ser adoptada por otras entidades (equipos, etc.) sin cambios.
 * La lógica de upload/delete/reorder vive en el padre; este componente solo
 * renderiza y emite callbacks. Selección múltiple + preview de subida son
 * concerns puramente visuales — viven acá adentro, no repetidos en cada
 * padre (2026-08-20: "ayer borré 40 fotos a mano").
 */

import { useRef, useState } from "react";
import {
  ImageIcon,
  Trash2,
  Star,
  ChevronUp,
  ChevronDown,
  Upload,
  X,
  Check,
  AlertCircle,
} from "lucide-react";
import { Spinner } from "@/design-system/ui/spinner";
import { Checkbox } from "@/design-system/ui/checkbox";
import { Button } from "@/design-system/ui/button";
import { useConfirm } from "@/components/admin/useConfirm";
import { cn, compareFilenames } from "@/lib/utils";

export type GalleryFoto = {
  id: number;
  url: string;
  orden: number;
  es_principal: boolean;
};

type PendingUpload = {
  key: string;
  file: File;
  previewUrl: string;
  status: "pending" | "done" | "error";
  error?: string;
};

type Props = {
  fotos: GalleryFoto[];
  /** El padre sube cada archivo (con la concurrencia/rate-limit que le
   * corresponda) y llama a `onFileSettled` por cada uno que termina —
   * así la preview de ESE archivo puntual se actualiza en tiempo real,
   * sin esperar a que termine el lote entero. */
  onUpload: (
    files: File[],
    onFileSettled: (file: File, ok: boolean, error?: string) => void,
  ) => void | Promise<void>;
  onDelete: (id: number) => void;
  onDeleteMany: (ids: number[]) => void | Promise<void>;
  onReorder: (fotos: GalleryFoto[]) => void;
  onSetPrincipal: (id: number) => void;
  disabled?: boolean;
};

export function PhotoGallery({
  fotos,
  onUpload,
  onDelete,
  onDeleteMany,
  onReorder,
  onSetPrincipal,
  disabled = false,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const confirm = useConfirm();
  const [pending, setPending] = useState<PendingUpload[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

  const uploading = pending.some((p) => p.status === "pending");

  function movePhoto(index: number, dir: -1 | 1) {
    const next = [...fotos];
    const swapIdx = index + dir;
    if (swapIdx < 0 || swapIdx >= next.length) return;
    [next[index], next[swapIdx]] = [next[swapIdx], next[index]];
    const reindexed = next.map((f, i) => ({ ...f, orden: i }));
    onReorder(reindexed);
  }

  function toggleSelected(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleFilesPicked(fileList: FileList) {
    // El picker nativo no garantiza que el FileList venga en el orden de
    // selección del usuario (varía por OS/browser) — se ordena por nombre
    // así la galería queda en el orden que el nombre de archivo sugiere
    // (ej. subir 01.jpg...013.jpg desde Finder termina en ese mismo orden,
    // no en el que el browser haya listado los paths seleccionados).
    const files = Array.from(fileList).sort((a, b) => compareFilenames(a.name, b.name));
    const withPreview: PendingUpload[] = files.map((file) => ({
      key: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
      file,
      previewUrl: URL.createObjectURL(file),
      status: "pending",
    }));
    setPending((prev) => [...prev, ...withPreview]);

    await onUpload(files, (file, ok, error) => {
      setPending((prev) =>
        prev.map((p) => (p.file === file ? { ...p, status: ok ? "done" : "error", error } : p)),
      );
    });

    // Al cerrar el lote: lo que salió bien ya está reflejado en `fotos` (el
    // padre refetchea) — sale del strip. Los errores quedan visibles hasta
    // que el usuario los descarte a mano.
    setPending((prev) => {
      prev.filter((p) => p.status !== "error").forEach((p) => URL.revokeObjectURL(p.previewUrl));
      return prev.filter((p) => p.status === "error");
    });
  }

  function dismissPending(key: string) {
    setPending((prev) => {
      const target = prev.find((p) => p.key === key);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((p) => p.key !== key);
    });
  }

  async function handleBulkDelete() {
    if (selected.size === 0) return;
    const ok = await confirm({
      title: `¿Borrar ${selected.size} foto${selected.size === 1 ? "" : "s"}?`,
      description: "Esta acción no se puede deshacer.",
      danger: true,
      confirmLabel: "Borrar",
    });
    if (!ok) return;
    setBulkDeleting(true);
    try {
      await onDeleteMany(Array.from(selected));
      setSelected(new Set());
    } finally {
      setBulkDeleting(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Upload trigger */}
      <div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) {
              void handleFilesPicked(e.target.files);
              e.target.value = "";
            }
          }}
          disabled={disabled || uploading}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={disabled || uploading}
          className={cn(
            "flex w-full items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-sm transition",
            "border-border text-muted-foreground hover:border-ink hover:text-ink",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {uploading ? (
            <>
              <Spinner size="sm" />
              Subiendo…
            </>
          ) : (
            <>
              <Upload className="h-4 w-4" />
              Subir fotos (podés elegir varias)
            </>
          )}
        </button>
      </div>

      {/* Preview de la subida en curso: aparece apenas se eligen los
          archivos (antes de que termine de subir cualquiera) y cada uno se
          marca en tiempo real a medida que termina o falla. */}
      {pending.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {pending.map((p) => (
            <div
              key={p.key}
              className={cn(
                "relative overflow-hidden rounded-xl border bg-surface",
                p.status === "error" ? "border-destructive" : "hairline",
              )}
            >
              <div className="aspect-square w-full overflow-hidden">
                <img
                  src={p.previewUrl}
                  alt=""
                  className={cn(
                    "h-full w-full object-cover transition-opacity",
                    p.status === "pending" && "opacity-50",
                  )}
                />
              </div>
              <div className="absolute inset-0 flex items-center justify-center">
                {p.status === "pending" && <Spinner size="sm" />}
                {p.status === "done" && (
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-background/90 text-verde shadow">
                    <Check className="h-4 w-4" />
                  </div>
                )}
                {p.status === "error" && (
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-background/90 text-destructive shadow">
                    <AlertCircle className="h-4 w-4" />
                  </div>
                )}
              </div>
              {p.status === "error" && (
                <>
                  <button
                    type="button"
                    onClick={() => dismissPending(p.key)}
                    title="Descartar"
                    className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-lg bg-background/90 shadow hover:bg-background"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                  <p className="absolute inset-x-0 bottom-0 truncate bg-destructive/90 px-1.5 py-0.5 text-2xs text-white">
                    {p.error || "Error al subir"}
                  </p>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Selección múltiple */}
      {fotos.length > 0 && (
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={() =>
              setSelected(
                selected.size === fotos.length ? new Set() : new Set(fotos.map((f) => f.id)),
              )
            }
            className="text-xs font-medium text-muted-foreground hover:text-ink underline-offset-2 hover:underline"
          >
            {selected.size === fotos.length
              ? "Deseleccionar todas"
              : `Seleccionar todas (${fotos.length})`}
          </button>
          {selected.size > 0 && (
            <div className="flex items-center gap-3">
              <span className="text-xs text-muted-foreground">
                {selected.size} seleccionada{selected.size === 1 ? "" : "s"}
              </span>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={handleBulkDelete}
                loading={bulkDeleting}
                disabled={disabled}
              >
                <Trash2 className="h-3.5 w-3.5" />
                Borrar
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Grid de thumbnails */}
      {fotos.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {fotos.map((foto, idx) => (
            <div
              key={foto.id}
              className={cn(
                "group relative overflow-hidden rounded-xl border bg-surface",
                foto.es_principal ? "border-amber ring-1 ring-amber" : "hairline",
                selected.has(foto.id) && "ring-2 ring-primary",
              )}
            >
              <button
                type="button"
                onClick={() => toggleSelected(foto.id)}
                disabled={disabled}
                className="block aspect-square w-full overflow-hidden appearance-none border-0 bg-transparent p-0 disabled:cursor-not-allowed"
                aria-pressed={selected.has(foto.id)}
                aria-label={selected.has(foto.id) ? "Deseleccionar foto" : "Seleccionar foto"}
              >
                <img src={foto.url} alt="" className="h-full w-full object-cover" loading="lazy" />
              </button>

              {/* Checkbox + badge principal, misma fila arriba-izquierda */}
              <div className="absolute left-2 top-2 flex items-center gap-1.5">
                <Checkbox
                  checked={selected.has(foto.id)}
                  onCheckedChange={() => toggleSelected(foto.id)}
                  disabled={disabled}
                  className="h-5 w-5 rounded border-none bg-background/90 shadow"
                  aria-label="Seleccionar foto"
                />
                {foto.es_principal && (
                  <div className="flex items-center gap-1 rounded-full bg-amber px-2 py-0.5 text-2xs font-semibold uppercase tracking-wide text-ink">
                    <Star className="h-2.5 w-2.5 fill-current" />
                    Principal
                  </div>
                )}
              </div>

              {/* Controles superpuestos. En táctil (sin hover) van SIEMPRE
                  visibles — si no, en mobile no hay forma de borrar/reordenar.
                  En desktop (hover disponible) se revelan al pasar el mouse.
                  El contenedor es `pointer-events-none` SIEMPRE (no solo
                  cuando está invisible): es `absolute inset-0`, tapa TODA la
                  card incluido el botón de selección y el checkbox de abajo
                  — sin esto, ningún click de selección llegaba nunca (ni
                  siquiera con opacity-0, que no saca el elemento del hit-test).
                  Cada botón individual reactiva `pointer-events-auto` para
                  seguir siendo clickeable él solo. */}
              <div className="pointer-events-none absolute inset-0 flex flex-col justify-between p-1.5 opacity-100 transition-opacity [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100">
                {/* Arriba: borrar (a la derecha; el checkbox+badge ocupan la izquierda) */}
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => onDelete(foto.id)}
                    disabled={disabled || uploading}
                    title="Eliminar"
                    className="pointer-events-auto flex h-7 w-7 items-center justify-center rounded-lg bg-background/90 text-destructive shadow hover:bg-destructive hover:text-white disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                {/* Abajo: reordenar + marcar principal */}
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => movePhoto(idx, -1)}
                    disabled={disabled || uploading || idx === 0}
                    title="Mover arriba"
                    className="pointer-events-auto flex h-7 w-7 items-center justify-center rounded-lg bg-background/90 shadow hover:bg-background disabled:opacity-30"
                  >
                    <ChevronUp className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => movePhoto(idx, 1)}
                    disabled={disabled || uploading || idx === fotos.length - 1}
                    title="Mover abajo"
                    className="pointer-events-auto flex h-7 w-7 items-center justify-center rounded-lg bg-background/90 shadow hover:bg-background disabled:opacity-30"
                  >
                    <ChevronDown className="h-3.5 w-3.5" />
                  </button>
                  {!foto.es_principal && (
                    <button
                      type="button"
                      onClick={() => onSetPrincipal(foto.id)}
                      disabled={disabled || uploading}
                      title="Marcar como principal"
                      className="pointer-events-auto ml-auto flex h-7 w-7 items-center justify-center rounded-lg bg-background/90 shadow hover:bg-amber hover:text-ink disabled:opacity-50"
                    >
                      <Star className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {fotos.length === 0 && pending.length === 0 && (
        <div className="flex flex-col items-center gap-2 card py-8 text-muted-foreground">
          <ImageIcon className="h-8 w-8 opacity-30" />
          <p className="text-sm">Sin fotos todavía</p>
        </div>
      )}
    </div>
  );
}
