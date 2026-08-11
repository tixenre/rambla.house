import { useState } from "react";
import { createLazyFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Users } from "lucide-react";

import { talleresAdminApi } from "@/lib/admin/api/talleres";
import type { EdicionAdmin, TallerConcepto } from "@/lib/admin/api/types";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { Button } from "@/design-system/ui/button";
import { AdminPage } from "@/components/admin/AdminPage";
import { ListSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { TallerConceptoRow } from "@/components/admin/talleres/TallerConceptoRow";
import { NuevoConceptoDialog } from "@/components/admin/talleres/NuevoConceptoDialog";
import { NuevaEdicionDialog } from "@/components/admin/talleres/NuevaEdicionDialog";

export const Route = createLazyFileRoute("/admin/talleres/")({
  component: TalleresAdminPage,
});

function TalleresAdminPage() {
  useDocumentTitle("Talleres — Admin");
  const qc = useQueryClient();
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [nuevoOpen, setNuevoOpen] = useState(false);
  const [nuevaEdicionConcepto, setNuevaEdicionConcepto] = useState<TallerConcepto | null>(null);

  const {
    data: conceptos = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["admin", "talleres"],
    queryFn: () => talleresAdminApi.list(),
    staleTime: 0,
  });

  function handleNuevoConceptoSuccess(created: TallerConcepto) {
    qc.setQueryData(["admin", "talleres"], (prev: TallerConcepto[] | undefined) =>
      prev ? [created, ...prev] : [created],
    );
    setNuevoOpen(false);
    setExpandedId(created.id);
  }

  function handleDeleteConcepto(conceptoId: number) {
    qc.setQueryData(["admin", "talleres"], (prev: TallerConcepto[] | undefined) =>
      prev?.filter((c) => c.id !== conceptoId),
    );
    setExpandedId((id) => (id === conceptoId ? null : id));
  }

  function handleNuevaEdicionSuccess(created: EdicionAdmin) {
    qc.setQueryData(["admin", "talleres"], (prev: TallerConcepto[] | undefined) =>
      prev?.map((c) =>
        c.id === nuevaEdicionConcepto?.id
          ? {
              ...c,
              ediciones: [...c.ediciones, created].sort(
                (a, b) => a.numero_edicion - b.numero_edicion,
              ),
            }
          : c,
      ),
    );
    setNuevaEdicionConcepto(null);
  }

  return (
    <AdminPage
      title="Talleres"
      description={
        conceptos.length > 0
          ? `${conceptos.length} concepto${conceptos.length !== 1 ? "s" : ""} · ${conceptos.reduce((s, c) => s + c.ediciones.length, 0)} ediciones`
          : undefined
      }
      actions={
        <Button size="sm" className="gap-2" onClick={() => setNuevoOpen(true)}>
          <Plus className="h-4 w-4" />
          Nuevo taller
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        {/* Loading skeleton */}
        {isLoading && <ListSkeleton rows={3} />}

        {/* Error */}
        {isError && <ErrorState error={error} onRetry={refetch} />}

        {/* Lista */}
        {conceptos.length > 0 && (
          <div className="flex flex-col gap-2">
            {conceptos.map((concepto) => (
              <TallerConceptoRow
                key={concepto.id}
                concepto={concepto}
                expanded={expandedId === concepto.id}
                onToggle={() => setExpandedId(expandedId === concepto.id ? null : concepto.id)}
                onNuevaEdicion={(c) => setNuevaEdicionConcepto(c)}
                onDelete={handleDeleteConcepto}
              />
            ))}
          </div>
        )}

        {conceptos.length === 0 && !isLoading && !isError && (
          <EmptyState
            icon={<Users className="h-6 w-6" />}
            title="No hay talleres todavía"
            sub="Creá el primero para que aparezca en la web."
          >
            <Button size="sm" onClick={() => setNuevoOpen(true)} className="gap-2">
              <Plus className="h-4 w-4" />
              Crear el primero
            </Button>
          </EmptyState>
        )}

        <NuevoConceptoDialog
          open={nuevoOpen}
          onClose={() => setNuevoOpen(false)}
          onSuccess={handleNuevoConceptoSuccess}
        />

        <NuevaEdicionDialog
          concepto={nuevaEdicionConcepto}
          open={nuevaEdicionConcepto !== null}
          onClose={() => setNuevaEdicionConcepto(null)}
          onSuccess={handleNuevaEdicionSuccess}
        />
      </div>
    </AdminPage>
  );
}
