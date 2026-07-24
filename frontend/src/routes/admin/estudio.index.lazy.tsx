import { createLazyFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { estudioAdminApi } from "@/lib/admin/api";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { AdminPage } from "@/components/admin/AdminPage";
import { ListSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";
import { ConfigForm } from "@/components/admin/estudio/ConfigForm";
import { GaleriaSection } from "@/components/admin/estudio/GaleriaSection";
import { PackSection } from "@/components/admin/estudio/PackSection";
import { PromoSection } from "@/components/admin/estudio/PromoSection";
import { SlotsSection } from "@/components/admin/estudio/SlotsSection";
import { TrabajosSection } from "@/components/admin/estudio/TrabajosSection";

export const Route = createLazyFileRoute("/admin/estudio/")({
  component: EstudioAdminPage,
});

function EstudioAdminPage() {
  useDocumentTitle("Estudio · Back Office");
  const qc = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["admin", "estudio"],
    queryFn: () => estudioAdminApi.get(),
  });

  if (isLoading) {
    return <ListSkeleton />;
  }

  if (isError || !data) {
    return (
      <ErrorState
        title="No se pudo cargar el estudio"
        sub="Hubo un error al traer la configuración del estudio. Probá de nuevo."
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <AdminPage
      title="Estudio"
      maxW="form"
      description="Configuración del espacio, precios y galería de fotos."
    >
      <div className="space-y-8">
        <ConfigForm
          config={data}
          onSaved={() => qc.invalidateQueries({ queryKey: ["admin", "estudio"] })}
        />

        <PromoSection config={data} />

        <PackSection />

        <GaleriaSection
          fotos={data.fotos}
          onChanged={() => qc.invalidateQueries({ queryKey: ["admin", "estudio"] })}
        />

        <TrabajosSection
          trabajos={data.trabajos ?? []}
          onChanged={() => qc.invalidateQueries({ queryKey: ["admin", "estudio"] })}
        />

        <SlotsSection />
      </div>
    </AdminPage>
  );
}
