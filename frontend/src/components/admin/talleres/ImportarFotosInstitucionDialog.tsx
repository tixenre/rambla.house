import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, ImageIcon } from "lucide-react";
import { toast } from "sonner";

import type { Institucion } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { Button } from "@/design-system/ui/button";
import { Spinner } from "@/design-system/ui/spinner";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/design-system/ui/dialog";
import { ListSkeleton } from "@/components/admin/skeletons";
import { cn } from "@/lib/utils";

/**
 * Picker de fotos ya subidas a una institución co-presentadora de este
 * taller, para importarlas a la galería de ESTA edición sin volver a subir
 * el archivo — pedido del dueño 2026-08-19: "no subir las mismas fotos a
 * los dos talleres". Copia por referencia (mismo `url`), NO fusiona las dos
 * galerías: la de la edición sigue siendo la propia (portfolio de ESE
 * curso), esto solo evita el paso manual de descargar+resubir.
 */
export function ImportarFotosInstitucionDialog({
  edicionId,
  instituciones,
  urlsActuales,
  onClose,
  onImported,
}: {
  edicionId: number;
  instituciones: Institucion[];
  // URLs ya presentes en la galería de esta edición — para marcar "ya
  // importada" y evitar el duplicado más probable (doble click / volver a
  // abrir el picker).
  urlsActuales: string[];
  onClose: () => void;
  onImported: () => void;
}) {
  const [activaId, setActivaId] = useState(instituciones[0]?.id ?? 0);
  const [seleccion, setSeleccion] = useState<Set<number>>(new Set());
  const yaImportadas = new Set(urlsActuales);

  const fotosQ = useQuery({
    queryKey: ["admin", "instituciones", activaId, "fotos"],
    queryFn: () => talleresAdminApi.listFotosInstitucion(activaId),
    enabled: activaId > 0,
  });
  const fotos = fotosQ.data?.fotos ?? [];
  // Solo las de ESTA pestaña (institución activa) que no estén ya
  // importadas — "seleccionar todas" opera sobre lo que se ve, no sobre
  // pestañas que el admin ni siquiera abrió.
  const seleccionables = fotos.filter((f) => !yaImportadas.has(f.url));
  const todasSeleccionadas =
    seleccionables.length > 0 && seleccionables.every((f) => seleccion.has(f.id));

  const importMut = useMutation({
    mutationFn: () => talleresAdminApi.importarFotosDeInstitucion(edicionId, Array.from(seleccion)),
    onSuccess: () => {
      toast.success(seleccion.size === 1 ? "Foto importada" : `${seleccion.size} fotos importadas`);
      onImported();
      onClose();
    },
    onError: (e) => toast.error("Error importando", { description: (e as Error).message }),
  });

  function toggle(id: number) {
    setSeleccion((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleTodas() {
    setSeleccion((prev) => {
      const next = new Set(prev);
      const ids = seleccionables.map((f) => f.id);
      if (todasSeleccionadas) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Importar fotos de una institución</DialogTitle>
        </DialogHeader>

        {instituciones.length > 1 && (
          <div className="flex flex-wrap gap-1.5 border-b border-border/50 pb-3">
            {instituciones.map((ins) => (
              <button
                key={ins.id}
                type="button"
                onClick={() => setActivaId(ins.id)}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium transition",
                  ins.id === activaId
                    ? "bg-ink text-background"
                    : "bg-muted/40 text-muted-foreground hover:bg-muted",
                )}
              >
                {ins.nombre}
              </button>
            ))}
          </div>
        )}

        <div className="min-h-[200px]">
          {fotosQ.isLoading && <ListSkeleton rows={2} className="py-2" />}

          {!fotosQ.isLoading && fotos.length === 0 && (
            <div className="flex flex-col items-center gap-2 py-10 text-muted-foreground">
              <ImageIcon className="h-8 w-8 opacity-30" />
              <p className="text-sm">
                Esta institución todavía no tiene fotos en su galería propia.
              </p>
            </div>
          )}

          {fotos.length > 0 && (
            <>
              <div className="flex items-center justify-between pb-2">
                <p className="text-xs text-muted-foreground">
                  {fotos.length} foto{fotos.length === 1 ? "" : "s"}
                </p>
                {seleccionables.length > 0 && (
                  <Button type="button" variant="ghost" size="sm" onClick={toggleTodas}>
                    {todasSeleccionadas ? "Deseleccionar todas" : "Seleccionar todas"}
                  </Button>
                )}
              </div>
              <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
                {fotos.map((foto) => {
                  const yaEsta = yaImportadas.has(foto.url);
                  const selected = seleccion.has(foto.id);
                  return (
                    <button
                      key={foto.id}
                      type="button"
                      onClick={() => !yaEsta && toggle(foto.id)}
                      disabled={yaEsta}
                      title={yaEsta ? "Ya está en la galería de esta edición" : undefined}
                      className={cn(
                        "group relative aspect-square overflow-hidden rounded-xl border transition",
                        yaEsta && "cursor-not-allowed opacity-40",
                        !yaEsta && selected && "border-amber ring-2 ring-amber",
                        !yaEsta && !selected && "hairline hover:border-ink/30",
                      )}
                    >
                      <img
                        src={foto.url}
                        alt=""
                        className="h-full w-full object-cover"
                        loading="lazy"
                      />
                      {yaEsta ? (
                        <div className="absolute inset-x-0 bottom-0 bg-ink/70 px-1.5 py-1 text-center text-2xs font-medium text-background">
                          Ya está
                        </div>
                      ) : (
                        <div
                          className={cn(
                            "absolute inset-0 flex items-center justify-center bg-ink/40 transition-opacity",
                            selected ? "opacity-100" : "opacity-0 group-hover:opacity-100",
                          )}
                        >
                          {selected && (
                            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-amber text-ink">
                              <Check className="h-4 w-4" />
                            </div>
                          )}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          <p className="mr-auto self-center text-xs text-muted-foreground">
            {seleccion.size > 0
              ? `${seleccion.size} seleccionada${seleccion.size === 1 ? "" : "s"}`
              : "Elegí una o más fotos"}
          </p>
          <DialogClose asChild>
            <Button variant="ghost">Cancelar</Button>
          </DialogClose>
          <Button
            onClick={() => importMut.mutate()}
            disabled={seleccion.size === 0 || importMut.isPending}
            className="gap-2"
          >
            {importMut.isPending ? <Spinner size="sm" /> : null}
            Importar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
