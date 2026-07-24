import { createLazyFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { estudioAdminApi } from "@/lib/admin/api";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { AdminPage } from "@/components/admin/AdminPage";
import { ListSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";
import { ReservasSection } from "@/components/admin/estudio/ReservasSection";

export const Route = createLazyFileRoute("/admin/estudio/reservas")({
  component: EstudioReservasPage,
});

function EstudioReservasPage() {
  useDocumentTitle("Reservas del Estudio · Back Office");

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
      title="Reservas del Estudio"
      maxW="wide"
      description="Agenda y alta de turnos — el pack/promo y equipos sueltos se cargan acá."
    >
      <ReservasSection estudio={data} />
    </AdminPage>
  );
}
