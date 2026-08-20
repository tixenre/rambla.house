/**
 * useEquipoFotos — concern de la galería multi-foto del form de equipos (edit mode).
 *
 * Extraído verbatim de `EquipoFormDialog.tsx` (split de god-module, Frente E del
 * skill `mantenimiento`). Encapsula query + mutaciones + handlers de la galería,
 * decoupled del estado del form (react-hook-form). Cero cambio de comportamiento.
 */
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  getEquipoFotos,
  uploadEquipoFoto,
  deleteEquipoFoto,
  reorderEquipoFotos,
  type EquipoFoto,
  type EquipoFotoOrdenItem,
} from "@/lib/equipment/equipoFotos";
import { type GalleryFoto } from "@/components/common/PhotoGallery";
import { runInBatches } from "@/lib/concurrency";
import type { Equipo } from "@/lib/admin/api";

// Espejo de GaleriaEdicionSection (talleres) / GaleriaSection (estudio): de
// a tandas chicas para no agotar el rate limit de `upload-foto`
// (20/minuto, backend) con un lote grande de una sola vez.
const UPLOAD_CONCURRENCY = 3;
const DELETE_CONCURRENCY = 5;

export function useEquipoFotos(initial: Equipo | null | undefined, open: boolean) {
  const qc = useQueryClient();

  const fotosQ = useQuery({
    queryKey: ["admin", "equipo-fotos", initial?.id],
    queryFn: () => getEquipoFotos(initial!.id),
    enabled: !!initial?.id && open,
  });
  const fotos: GalleryFoto[] = (fotosQ.data ?? []).map((f: EquipoFoto) => ({
    id: f.id,
    url: f.url,
    orden: f.orden,
    es_principal: f.es_principal,
  }));

  const deleteFotoMut = useMutation({
    mutationFn: (fotoId: number) => deleteEquipoFoto(initial!.id, fotoId),
    onSuccess: () => {
      toast.success("Foto eliminada");
      void qc.invalidateQueries({ queryKey: ["admin", "equipo-fotos", initial?.id] });
      void qc.invalidateQueries({ queryKey: ["admin", "equipos"] });
    },
    onError: (e) => toast.error("Error eliminando foto", { description: (e as Error).message }),
  });

  const reorderFotoMut = useMutation({
    mutationFn: (items: EquipoFotoOrdenItem[]) => reorderEquipoFotos(initial!.id, items),
    onSuccess: (data) => {
      qc.setQueryData(["admin", "equipo-fotos", initial?.id], data.fotos);
    },
    onError: (e) => toast.error("Error reordenando fotos", { description: (e as Error).message }),
  });

  async function handleGalleryUpload(
    files: File[],
    onFileSettled: (file: File, ok: boolean, error?: string) => void,
  ) {
    if (!initial?.id) return;
    const equipoId = initial.id;
    const { ok, failed } = await runInBatches(
      files,
      UPLOAD_CONCURRENCY,
      (file) => uploadEquipoFoto(equipoId, file),
      (file, fileOk, error) =>
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
    if (ok > 0) {
      await qc.invalidateQueries({ queryKey: ["admin", "equipo-fotos", equipoId] });
      void qc.invalidateQueries({ queryKey: ["admin", "equipos"] });
    }
  }

  async function handleGalleryDeleteMany(ids: number[]) {
    if (!initial?.id) return;
    const equipoId = initial.id;
    const { ok, failed } = await runInBatches(ids, DELETE_CONCURRENCY, (fotoId) =>
      deleteEquipoFoto(equipoId, fotoId),
    );
    if (failed === 0) {
      toast.success(ok === 1 ? "Foto eliminada" : `${ok} fotos eliminadas`);
    } else if (ok === 0) {
      toast.error("No se pudo eliminar ninguna foto");
    } else {
      toast.warning(`${ok} fotos eliminadas, ${failed} con error`);
    }
    if (ok > 0) {
      void qc.invalidateQueries({ queryKey: ["admin", "equipo-fotos", equipoId] });
      void qc.invalidateQueries({ queryKey: ["admin", "equipos"] });
    }
  }

  function handleGalleryReorder(reordered: GalleryFoto[]) {
    reorderFotoMut.mutate(
      reordered.map((f) => ({ id: f.id, orden: f.orden, es_principal: f.es_principal })),
    );
  }

  function handleGallerySetPrincipal(id: number) {
    const updated = fotos.map((f) => ({ id: f.id, orden: f.orden, es_principal: f.id === id }));
    reorderFotoMut.mutate(updated);
  }

  return {
    fotos,
    handleGalleryUpload,
    handleGalleryDeleteMany,
    handleGalleryReorder,
    handleGallerySetPrincipal,
    onDelete: (id: number) => deleteFotoMut.mutate(id),
    mutating: deleteFotoMut.isPending || reorderFotoMut.isPending,
  };
}
