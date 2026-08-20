/**
 * InstructoresAdminSection — listado global de instructores ("Profesores"
 * en el sidebar) con los talleres que dicta cada uno, sin tener que entrar
 * a un taller primero. Mismo patrón que `InstitucionesAdminSection`: reusa
 * el CRUD (`InstructorDialog`) que ya usaba `InstructoresSection` scoped a
 * un taller — acá se le suma la vista cross-taller.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Users } from "lucide-react";

import type { Instructor } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { InstructorDialog } from "./InstructoresSection";
import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { Input } from "@/design-system/ui/input";
import { Pill } from "@/design-system/ui/Pill";
import { ListSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";
import { EmptyState } from "@/design-system/composites/EmptyState";

export function InstructoresAdminSection() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [dialogInstructor, setDialogInstructor] = useState<Instructor | "nuevo" | null>(null);

  const listQ = useQuery({
    queryKey: ["admin", "instructores"],
    queryFn: () => talleresAdminApi.listInstructores(),
    staleTime: 30_000,
  });

  const instructores = listQ.data ?? [];
  const filtered = search.trim()
    ? instructores.filter((i) => i.nombre.toLowerCase().includes(search.trim().toLowerCase()))
    : instructores;

  return (
    <section className="card p-4 space-y-3">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-lg text-ink">Profesores</h2>
          <p className="text-sm text-muted-foreground">
            Perfil (nombre, rol, redes, foto) de cada instructor y los talleres que dicta —
            independiente de entrar a un taller puntual.
          </p>
        </div>
        <Button size="sm" onClick={() => setDialogInstructor("nuevo")} className="gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          Nuevo profesor
        </Button>
      </header>

      <Input
        placeholder="Buscar profesor…"
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
          icon={<Users className="h-6 w-6" />}
          title={search ? "Sin resultados" : "Sin profesores todavía"}
          sub={
            search
              ? "Probá con otro nombre."
              : "Se crean acá o desde la pestaña Instructores de un taller."
          }
        />
      )}

      {!listQ.isLoading && filtered.length > 0 && (
        <div className="border hairline rounded-md divide-y divide-muted/40">
          {filtered.map((ins) => (
            <div key={ins.id} className="flex items-center gap-3 px-3 py-2.5">
              {ins.foto_url ? (
                <img
                  src={ins.foto_url}
                  alt={ins.nombre}
                  className="h-9 w-9 rounded-full object-cover shrink-0"
                />
              ) : (
                <div className="h-9 w-9 rounded-full grid place-items-center bg-muted text-xs font-medium text-muted-foreground shrink-0">
                  {ins.nombre.trim().charAt(0).toUpperCase() || "?"}
                </div>
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-ink truncate">{ins.nombre}</p>
                {ins.rol && <p className="text-xs text-muted-foreground truncate">{ins.rol}</p>}
              </div>
              <div className="flex flex-wrap items-center gap-1.5 max-w-[45%] justify-end">
                {(ins.talleres ?? []).length === 0 ? (
                  <span className="text-xs text-muted-foreground/60 italic">Sin talleres</span>
                ) : (
                  ins.talleres!.map((t) => (
                    <Pill key={t.id} tone="neutral" className="shrink-0">
                      {t.nombre}
                    </Pill>
                  ))
                )}
              </div>
              <IconButton
                aria-label={`Editar ${ins.nombre}`}
                size="sm"
                onClick={() => setDialogInstructor(ins)}
              >
                <Pencil className="h-3.5 w-3.5" />
              </IconButton>
            </div>
          ))}
        </div>
      )}

      {dialogInstructor !== null && (
        <InstructorDialog
          instructor={dialogInstructor === "nuevo" ? null : dialogInstructor}
          onClose={() => setDialogInstructor(null)}
          onCreated={() => qc.invalidateQueries({ queryKey: ["admin", "instructores"] })}
        />
      )}
    </section>
  );
}
