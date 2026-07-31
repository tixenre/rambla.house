import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Video } from "lucide-react";
import { toast } from "sonner";

import type { TallerConcepto, Trabajo } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { Input } from "@/design-system/ui/input";
import { Spinner } from "@/design-system/ui/spinner";
import { useConfirm } from "@/components/admin/useConfirm";
import { EmptyState } from "@/design-system/composites/EmptyState";

/**
 * F4c: trabajos pasados del taller — SOLO links de YouTube, sin testimonios/
 * reseñas (decisión del dueño). Prueba social de una escuela de cine.
 */
export function TrabajosSection({ concepto }: { concepto: TallerConcepto }) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [nuevoTitulo, setNuevoTitulo] = useState("");
  const [nuevoUrl, setNuevoUrl] = useState("");

  function invalidar() {
    qc.invalidateQueries({ queryKey: ["admin", "talleres"] });
  }

  const crearMut = useMutation({
    mutationFn: () =>
      talleresAdminApi.crearTrabajo(concepto.id, { titulo: nuevoTitulo, youtube_url: nuevoUrl }),
    onSuccess: () => {
      toast.success("Trabajo agregado");
      setNuevoTitulo("");
      setNuevoUrl("");
      invalidar();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const eliminarMut = useMutation({
    mutationFn: (trabajoId: number) => talleresAdminApi.eliminarTrabajo(trabajoId),
    onSuccess: () => {
      toast.success("Trabajo eliminado");
      invalidar();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  async function handleEliminar(t: Trabajo) {
    if (
      !(await confirm({
        title: `¿Eliminar "${t.titulo || t.youtube_url}"?`,
        description: "Esta acción no se puede deshacer.",
        danger: true,
        confirmLabel: "Eliminar",
      }))
    )
      return;
    eliminarMut.mutate(t.id);
  }

  return (
    <div className="flex flex-col gap-4">
      {concepto.trabajos.length === 0 ? (
        <EmptyState
          icon={<Video className="h-6 w-6" />}
          title="Sin trabajos todavía"
          sub="Links de YouTube de lo producido en ediciones pasadas — prueba social sin testimonios."
        />
      ) : (
        <div className="grid sm:grid-cols-2 gap-3">
          {concepto.trabajos.map((t) => (
            <div
              key={t.id}
              className="flex items-center gap-3 rounded-xl border border-border/50 bg-muted/20 px-3 py-2"
            >
              {t.poster_url ? (
                <img
                  src={t.poster_url}
                  alt=""
                  className="h-12 w-20 rounded-md object-cover shrink-0"
                />
              ) : (
                <div className="h-12 w-20 rounded-md bg-muted shrink-0 flex items-center justify-center">
                  <Video className="h-4 w-4 text-muted-foreground" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-ink truncate">
                  {t.titulo || "(sin título)"}
                </p>
                <a
                  href={t.youtube_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-muted-foreground truncate hover:text-ink transition block"
                >
                  {t.youtube_url}
                </a>
              </div>
              <IconButton
                aria-label="Eliminar trabajo"
                size="sm"
                onClick={() => handleEliminar(t)}
                className="text-muted-foreground hover:text-destructive shrink-0"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </IconButton>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-col sm:flex-row gap-2 pt-1">
        <Input
          value={nuevoTitulo}
          onChange={(e) => setNuevoTitulo(e.target.value)}
          placeholder="Título (opcional)"
          className="sm:w-48"
        />
        <Input
          value={nuevoUrl}
          onChange={(e) => setNuevoUrl(e.target.value)}
          placeholder="https://www.youtube.com/watch?v=..."
          className="flex-1"
        />
        <Button
          variant="outline"
          onClick={() => crearMut.mutate()}
          disabled={crearMut.isPending || !nuevoUrl.trim()}
          className="gap-1.5 shrink-0"
        >
          {crearMut.isPending ? <Spinner size="xs" /> : <Plus className="h-3.5 w-3.5" />}
          Agregar
        </Button>
      </div>
    </div>
  );
}
