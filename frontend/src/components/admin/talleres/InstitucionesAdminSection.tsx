/**
 * InstitucionesAdminSection — CRUD standalone de instituciones
 * co-presentadoras (ej. "Filmar"), sin tener que entrar a un taller
 * primero (pedido del dueño 2026-08-19: "tener una sección de
 * instituciones en talleres, así puedo editar eso sin entrar a un
 * taller"). Reusa el mismo `InstitucionDialog` que ya usaba
 * `InstitucionesSection` (nombre/descripción/instagram/web/logo — CRUD
 * completo, delete incluido) — acá se le suma la galería propia de fotos
 * (`GaleriaInstitucionSection`), expandible por fila.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ImageIcon, Pencil, Plus } from "lucide-react";

import type { Institucion } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { InstitucionDialog } from "./InstitucionesSection";
import { GaleriaInstitucionSection } from "./GaleriaInstitucionSection";
import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { Input } from "@/design-system/ui/input";
import { ListSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { cn } from "@/lib/utils";

export function InstitucionesAdminSection() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [dialogInstitucion, setDialogInstitucion] = useState<Institucion | "nueva" | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const listQ = useQuery({
    queryKey: ["admin", "instituciones"],
    queryFn: () => talleresAdminApi.listInstituciones(),
    staleTime: 30_000,
  });

  const instituciones = listQ.data ?? [];
  const filtered = search.trim()
    ? instituciones.filter((i) => i.nombre.toLowerCase().includes(search.trim().toLowerCase()))
    : instituciones;

  return (
    <section className="card p-4 space-y-3">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-lg text-ink">Instituciones</h2>
          <p className="text-sm text-muted-foreground">
            Perfil (nombre, descripción, redes, logo) y galería de fotos de cada institución
            co-presentadora — independiente de entrar a un taller puntual.
          </p>
        </div>
        <Button size="sm" onClick={() => setDialogInstitucion("nueva")} className="gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          Nueva institución
        </Button>
      </header>

      <Input
        placeholder="Buscar institución…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="h-9 max-w-xs"
      />

      {listQ.isLoading && <ListSkeleton rows={4} className="py-2" />}
      {listQ.error && (
        <ErrorState error={listQ.error} onRetry={() => listQ.refetch()} className="py-6" />
      )}

      {!listQ.isLoading && !listQ.error && filtered.length === 0 && (
        <EmptyState
          icon={<ImageIcon className="h-6 w-6" />}
          title={search ? "Sin resultados" : "Sin instituciones todavía"}
          sub={
            search
              ? "Probá con otro nombre."
              : "Se crean acá o desde la pestaña Instituciones de un taller."
          }
        />
      )}

      {!listQ.isLoading && filtered.length > 0 && (
        <div className="border hairline rounded-md divide-y divide-muted/40">
          {filtered.map((ins) => {
            const expanded = expandedId === ins.id;
            return (
              <div key={ins.id}>
                <button
                  type="button"
                  onClick={() => setExpandedId(expanded ? null : ins.id)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/30 transition"
                >
                  {ins.logo_url ? (
                    <img
                      src={ins.logo_url}
                      alt={ins.nombre}
                      className="h-9 w-9 rounded-lg object-contain bg-muted/30 shrink-0"
                    />
                  ) : (
                    <div className="h-9 w-9 rounded-lg grid place-items-center bg-muted text-xs font-medium text-muted-foreground shrink-0">
                      {ins.nombre.trim().charAt(0).toUpperCase() || "?"}
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-ink truncate">{ins.nombre}</p>
                    {ins.descripcion && (
                      <p className="text-xs text-muted-foreground truncate">{ins.descripcion}</p>
                    )}
                  </div>
                  <IconButton
                    aria-label={`Editar ${ins.nombre}`}
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      setDialogInstitucion(ins);
                    }}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </IconButton>
                  <ChevronDown
                    className={cn(
                      "h-4 w-4 text-muted-foreground shrink-0 transition-transform",
                      expanded && "rotate-180",
                    )}
                  />
                </button>
                {expanded && (
                  <div className="px-3 pb-4 pt-1 border-t hairline bg-surface">
                    <InstitucionFotos institucionId={ins.id} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {dialogInstitucion !== null && (
        <InstitucionDialog
          institucion={dialogInstitucion === "nueva" ? null : dialogInstitucion}
          onClose={() => setDialogInstitucion(null)}
          onCreated={() => qc.invalidateQueries({ queryKey: ["admin", "instituciones"] })}
        />
      )}
    </section>
  );
}

/** Carga perezosa de la galería — solo la institución expandida pega a
 * /fotos, no las N de la lista completa. */
function InstitucionFotos({ institucionId }: { institucionId: number }) {
  const qc = useQueryClient();
  const fotosQ = useQuery({
    queryKey: ["admin", "instituciones", institucionId, "fotos"],
    queryFn: () => talleresAdminApi.listFotosInstitucion(institucionId),
  });

  if (fotosQ.isLoading) return <ListSkeleton rows={1} className="py-2" />;
  if (fotosQ.error) {
    return <ErrorState error={fotosQ.error} onRetry={() => fotosQ.refetch()} className="py-4" />;
  }

  return (
    <GaleriaInstitucionSection
      institucionId={institucionId}
      fotos={fotosQ.data?.fotos ?? []}
      onChanged={() =>
        qc.invalidateQueries({ queryKey: ["admin", "instituciones", institucionId, "fotos"] })
      }
    />
  );
}
