import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { PhotoGallery, type GalleryFoto } from "@/components/common/PhotoGallery";
import { uploadEdicionFile } from "@/lib/talleres/photos";
import { talleresAdminApi } from "@/lib/admin/api";
import { runInBatches } from "@/lib/concurrency";
import type { EdicionFotoOrdenItem, Institucion } from "@/lib/admin/api/types";
import { Button } from "@/design-system/ui/button";
import { ImportarFotosInstitucionDialog } from "./ImportarFotosInstitucionDialog";

// El input acepta `multiple` y la UI invita a elegir varias — disparar todo
// el lote a la vez agotaba el rate limit de `upload-foto` (20/minuto,
// backend) en la primera ráfaga y tiraba 429. De a tandas chicas, encadenadas.
const UPLOAD_CONCURRENCY = 3;
// El borrado es más liviano (sin subir bytes) y el límite de escritura es
// más alto (60/minuto) — tandas más grandes sin riesgo real de 429.
const DELETE_CONCURRENCY = 5;

/**
 * Galería de fotos de una EDICIÓN de taller (portada + galería pública) —
 * espejo de GaleriaSection (Estudio), scoped a `edicionId` en vez del
 * singleton. Confirmado con el dueño: portada+galería son por edición, no
 * por concepto (a diferencia del video hero, que sí es del concepto).
 */
export function GaleriaEdicionSection({
  edicionId,
  fotos,
  instituciones = [],
  onChanged,
}: {
  edicionId: number;
  fotos: Array<{
    id: number;
    url: string;
    orden: number;
    es_principal: boolean;
    created_at: string | null;
    size_bytes: number | null;
  }>;
  // Instituciones co-presentadoras de este taller — si alguna ya tiene fotos
  // propias, se puede importar de ahí en vez de volver a subir el archivo
  // (pedido del dueño 2026-08-19: "no subir las mismas fotos a los dos
  // talleres").
  instituciones?: Institucion[];
  onChanged: () => void;
}) {
  const qc = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);

  async function handleUpload(
    files: File[],
    onFileSettled: (file: File, ok: boolean, error?: string) => void,
  ) {
    // El orden final lo decide la POSICIÓN DE SELECCIÓN del archivo, no
    // quién termina de subir/procesarse primero (con UPLOAD_CONCURRENCY > 1,
    // eso es una carrera — ver comentario en `uploadEdicionFile`).
    const base = fotos.length;
    const items = files.map((file, i) => ({ file, orden: base + i }));
    const { ok, failed } = await runInBatches(
      items,
      UPLOAD_CONCURRENCY,
      ({ file, orden }) => uploadEdicionFile(edicionId, file, orden),
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
      talleresAdminApi.deleteFotoEdicion(id),
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
      <div className="flex items-start justify-between gap-3 mb-4">
        <p className="text-xs text-muted-foreground">
          La foto marcada como principal es la portada de esta edición en la página pública.
        </p>
        {instituciones.length > 0 && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setPickerOpen(true)}
            className="shrink-0"
          >
            Importar de instituciones
          </Button>
        )}
      </div>
      <PhotoGallery
        fotos={fotos}
        onUpload={handleUpload}
        onDelete={(id) => deleteMut.mutate(id)}
        onDeleteMany={handleDeleteMany}
        onReorder={handleReorder}
        onSetPrincipal={handleSetPrincipal}
        disabled={deleteMut.isPending || reorderMut.isPending}
      />
      {pickerOpen && (
        <ImportarFotosInstitucionDialog
          edicionId={edicionId}
          instituciones={instituciones}
          urlsActuales={fotos.map((f) => f.url)}
          onClose={() => setPickerOpen(false)}
          onImported={onChanged}
        />
      )}
    </div>
  );
}
