import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { PhotoGallery, type GalleryFoto } from "@/components/common/PhotoGallery";
import { uploadInstitucionFile } from "@/lib/talleres/photos";
import { talleresAdminApi } from "@/lib/admin/api";
import { runInBatches } from "@/lib/concurrency";
import type { InstitucionFotoOrdenItem } from "@/lib/admin/api/types";

// Mismo tope que GaleriaEdicionSection: de a tandas chicas, no todo el
// FileList a la vez (agotaba el rate limit de upload-foto en la primera
// ráfaga).
const UPLOAD_CONCURRENCY = 3;
const DELETE_CONCURRENCY = 5;

/**
 * Galería de fotos propia de una INSTITUCIÓN — espejo exacto de
 * `GaleriaEdicionSection`, scoped a `institucionId` en vez de `edicionId`.
 * Pedido del dueño 2026-08-19: "que sea por institución también, así no
 * subo fotos repetidas" — una institución (ej. Filmar) carga su tanda de
 * fotos una sola vez, reusada por todos sus talleres, en vez de repetirla
 * en cada edición. La foto `es_principal` es la "foto destacada" que usa
 * el hero público del hub de institución (`InstitucionPage`).
 */
export function GaleriaInstitucionSection({
  institucionId,
  fotos,
  onChanged,
}: {
  institucionId: number;
  fotos: Array<{ id: number; url: string; orden: number; es_principal: boolean }>;
  onChanged: () => void;
}) {
  const qc = useQueryClient();

  async function handleUpload(
    files: File[],
    onFileSettled: (file: File, ok: boolean, error?: string) => void,
  ) {
    // El orden final lo decide la posición de selección, no quién termina
    // de procesarse primero — ver `uploadEdicionFile`.
    const base = fotos.length;
    const items = files.map((file, i) => ({ file, orden: base + i }));
    const { ok, failed } = await runInBatches(
      items,
      UPLOAD_CONCURRENCY,
      ({ file, orden }) => uploadInstitucionFile(institucionId, file, orden),
      ({ file }, fileOk, error) =>
        onFileSettled(
          file,
          fileOk,
          fileOk ? undefined : ((error as Error)?.message ?? "Error al subir"),
        ),
    );
    if (failed === 0) {
      toast.success(ok === 1 ? "Foto subida" : `${ok} fotos subidas`);
    } else if (ok === 0) {
      toast.error("No se pudo subir ninguna foto");
    } else {
      toast.warning(`${ok} fotos subidas, ${failed} con error`, {
        description: "Probá subir de nuevo las que fallaron.",
      });
    }
    if (ok > 0) onChanged();
  }

  async function handleDeleteMany(ids: number[]) {
    const { ok, failed } = await runInBatches(ids, DELETE_CONCURRENCY, (id) =>
      talleresAdminApi.deleteFotoInstitucion(id),
    );
    if (failed === 0) {
      toast.success(ok === 1 ? "Foto eliminada" : `${ok} fotos eliminadas`);
    } else if (ok === 0) {
      toast.error("No se pudo eliminar ninguna foto");
    } else {
      toast.warning(`${ok} fotos eliminadas, ${failed} con error`);
    }
    if (ok > 0) onChanged();
  }

  const deleteMut = useMutation({
    mutationFn: (id: number) => talleresAdminApi.deleteFotoInstitucion(id),
    onSuccess: () => {
      toast.success("Foto eliminada");
      onChanged();
    },
    onError: (e) => toast.error("Error eliminando", { description: (e as Error).message }),
  });

  const reorderMut = useMutation({
    mutationFn: (items: InstitucionFotoOrdenItem[]) =>
      talleresAdminApi.reorderFotosInstitucion(institucionId, items),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "instituciones"] });
    },
    onError: (e) => toast.error("Error reordenando", { description: (e as Error).message }),
  });

  function handleReorder(reordered: GalleryFoto[]) {
    reorderMut.mutate(
      reordered.map((f) => ({ id: f.id, orden: f.orden, es_principal: f.es_principal })),
    );
  }

  function handleSetPrincipal(id: number) {
    const updated = fotos.map((f) => ({ id: f.id, orden: f.orden, es_principal: f.id === id }));
    reorderMut.mutate(updated);
  }

  return (
    <div>
      <p className="text-xs text-muted-foreground mb-4">
        La foto marcada como principal es la destacada del hero público del hub de esta institución.
      </p>
      <PhotoGallery
        fotos={fotos}
        onUpload={handleUpload}
        onDelete={(id) => deleteMut.mutate(id)}
        onDeleteMany={handleDeleteMany}
        onReorder={handleReorder}
        onSetPrincipal={handleSetPrincipal}
        disabled={deleteMut.isPending || reorderMut.isPending}
      />
    </div>
  );
}
