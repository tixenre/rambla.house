import { createLazyFileRoute } from "@tanstack/react-router";
import { AdminPage } from "@/components/admin/AdminPage";
import { InstitucionesAdminSection } from "@/components/admin/talleres/InstitucionesAdminSection";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

export const Route = createLazyFileRoute("/admin/talleres/instituciones")({
  component: InstitucionesPage,
});

function InstitucionesPage() {
  useDocumentTitle("Instituciones · Back Office");
  return (
    <AdminPage
      title="Instituciones"
      maxW="detail"
      description="Perfil y galería de fotos de las instituciones co-presentadoras de talleres."
    >
      <InstitucionesAdminSection />
    </AdminPage>
  );
}
