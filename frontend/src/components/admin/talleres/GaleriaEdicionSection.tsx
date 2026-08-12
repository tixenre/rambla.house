import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { PhotoGallery, type GalleryFoto } from "@/components/common/PhotoGallery";
import { uploadEdicionFile } from "@/lib/talleres/photos";
import { talleresAdminApi } from "@/lib/admin/api";
import type { EdicionFotoOrdenItem } from "@/lib/admin/api/types";

/**
 * Galería de fotos de una EDICIÓN de taller (portada + galería pública) —
 * espejo de GaleriaSection (Estudio), scoped a `edicionId` en vez del
 * singleton. Confirmado con el dueño: portada+galería son por edición, no
 * por concepto (a diferencia del video hero, que sí es del concepto).
 */
export function GaleriaEdicionSection({
  edicionId,
  fotos,
  onChanged,
}: {
  edicionId: number;
  fotos: Array<{ id: number; url: string; orden: number; es_principal: boolean }>;
  onChanged: () => void;
}) {
  const qc = useQueryClient();
  const [uploading, setUploading] = useState(false);

  async function handleUpload(files: FileList) {
    setUploading(true);
    try {
      const uploads = Array.from(files).map((f) => uploadEdicionFile(edicionId, f));
      await Promise.all(uploads);
      toast.success(files.length === 1 ? "Foto subida" : `${files.length} fotos subidas`);
      onChanged();
    } catch (e) {
      toast.error("Error subiendo foto", { description: (e as Error).message });
    } finally {
      setUploading(false);
    }
  }

  const deleteMut = useMutation({
    mutationFn: (id: number) => talleresAdminApi.deleteFotoEdicion(id),
    onSuccess: () => {
      toast.success("Foto eliminada");
      onChanged();
    },
    onError: (e) => toast.error("Error eliminando", { description: (e as Error).message }),
  });

  const reorderMut = useMutation({
    mutationFn: (items: EdicionFotoOrdenItem[]) =>
      talleresAdminApi.reorderFotosEdicion(edicionId, items),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "talleres"] });
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
        La foto marcada como principal es la portada de esta edición en la página pública.
      </p>
      <PhotoGallery
        fotos={fotos}
        onUpload={handleUpload}
        onDelete={(id) => deleteMut.mutate(id)}
        onReorder={handleReorder}
        onSetPrincipal={handleSetPrincipal}
        uploading={uploading}
        disabled={deleteMut.isPending || reorderMut.isPending}
      />
    </div>
  );
}
