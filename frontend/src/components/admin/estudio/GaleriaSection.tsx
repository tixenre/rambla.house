import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { PhotoGallery, type GalleryFoto } from "@/components/common/PhotoGallery";
import { uploadStudioFile } from "@/lib/studio/photos";
import { estudioAdminApi, type EstudioConfig, type FotoOrdenItem } from "@/lib/admin/api";
import { runInBatches } from "@/lib/concurrency";
import { Section } from "./shared";

// Espejo de GaleriaEdicionSection (talleres): de a tandas chicas para no
// agotar el rate limit de `upload-foto` (20/minuto, backend) con un lote
// grande de una sola vez.
const UPLOAD_CONCURRENCY = 3;
const DELETE_CONCURRENCY = 5;

export function GaleriaSection({
  fotos,
  onChanged,
}: {
  fotos: Array<{
    id: number;
    url: string;
    orden: number;
    es_principal: boolean;
    created_at: string | null;
    size_bytes: number | null;
  }>;
  onChanged: () => void;
}) {
  const qc = useQueryClient();

  async function handleUpload(
    files: File[],
    onFileSettled: (file: File, ok: boolean, error?: string) => void,
  ) {
    // El orden final lo decide la posición de selección, no quién termina
    // de procesarse primero — ver `uploadStudioFile`.
    const base = fotos.length;
    const items = files.map((file, i) => ({ file, orden: base + i }));
    const { ok, failed } = await runInBatches(
      items,
      UPLOAD_CONCURRENCY,
      ({ file, orden }) => uploadStudioFile(file, orden),
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
      estudioAdminApi.deleteFoto(id),
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
    mutationFn: (id: number) => estudioAdminApi.deleteFoto(id),
    onSuccess: () => {
      toast.success("Foto eliminada");
      onChanged();
    },
    onError: (e) => toast.error("Error eliminando", { description: (e as Error).message }),
  });

  const reorderMut = useMutation({
    mutationFn: (items: FotoOrdenItem[]) => estudioAdminApi.reorderFotos(items),
    onSuccess: (data) => {
      qc.setQueryData(["admin", "estudio"], (old: EstudioConfig | undefined) =>
        old ? { ...old, fotos: data.fotos } : old,
      );
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
    <Section title="Galería de fotos">
      <p className="text-xs text-muted-foreground mb-4">
        La primera foto marcada como principal aparece en el hero de la página pública.
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
    </Section>
  );
}
