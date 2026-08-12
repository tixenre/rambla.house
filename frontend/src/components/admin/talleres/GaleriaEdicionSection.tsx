import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { PhotoGallery, type GalleryFoto } from "@/components/common/PhotoGallery";
import { uploadEdicionFile } from "@/lib/talleres/photos";
import { talleresAdminApi } from "@/lib/admin/api";
import type { EdicionFotoOrdenItem } from "@/lib/admin/api/types";

// Subir todo el FileList de una — el input acepta `multiple` y la UI invita
// a elegir varias — disparaba N requests simultáneos sin tope; un lote de
// ~15-20 fotos agotaba el rate limit de `upload-foto` (20/minuto, backend)
// en la primera ráfaga y tiraba 429. De a tandas chicas, encadenadas.
const UPLOAD_CONCURRENCY = 3;

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
    const fileArray = Array.from(files);
    let fallidas = 0;
    try {
      for (let i = 0; i < fileArray.length; i += UPLOAD_CONCURRENCY) {
        const tanda = fileArray.slice(i, i + UPLOAD_CONCURRENCY);
        const resultados = await Promise.allSettled(
          tanda.map((f) => uploadEdicionFile(edicionId, f)),
        );
        fallidas += resultados.filter((r) => r.status === "rejected").length;
      }
      const subidas = fileArray.length - fallidas;
      if (fallidas === 0) {
        toast.success(subidas === 1 ? "Foto subida" : `${subidas} fotos subidas`);
      } else if (subidas === 0) {
        toast.error("No se pudo subir ninguna foto");
      } else {
        toast.warning(`${subidas} fotos subidas, ${fallidas} con error`, {
          description: "Probá subir de nuevo las que fallaron.",
        });
      }
      if (subidas > 0) onChanged();
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
