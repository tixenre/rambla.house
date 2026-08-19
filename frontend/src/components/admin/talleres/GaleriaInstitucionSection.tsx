import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { PhotoGallery, type GalleryFoto } from "@/components/common/PhotoGallery";
import { uploadInstitucionFile } from "@/lib/talleres/photos";
import { talleresAdminApi } from "@/lib/admin/api";
import type { InstitucionFotoOrdenItem } from "@/lib/admin/api/types";

// Mismo tope que GaleriaEdicionSection: de a tandas chicas, no todo el
// FileList a la vez (agotaba el rate limit de upload-foto en la primera
// ráfaga).
const UPLOAD_CONCURRENCY = 3;

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
  const [uploading, setUploading] = useState(false);

  async function handleUpload(files: FileList) {
    setUploading(true);
    const fileArray = Array.from(files);
    let fallidas = 0;
    try {
      for (let i = 0; i < fileArray.length; i += UPLOAD_CONCURRENCY) {
        const tanda = fileArray.slice(i, i + UPLOAD_CONCURRENCY);
        const resultados = await Promise.allSettled(
          tanda.map((f) => uploadInstitucionFile(institucionId, f)),
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
        onReorder={handleReorder}
        onSetPrincipal={handleSetPrincipal}
        uploading={uploading}
        disabled={deleteMut.isPending || reorderMut.isPending}
      />
    </div>
  );
}
