import { createLazyFileRoute } from "@tanstack/react-router";
import { AdminPage } from "@/components/admin/AdminPage";
import { AlumnosAdminSection } from "@/components/admin/talleres/AlumnosAdminSection";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

export const Route = createLazyFileRoute("/admin/talleres/alumnos")({
  component: AlumnosPage,
});

function AlumnosPage() {
  useDocumentTitle("Alumnos · Back Office");
  return (
    <AdminPage
      title="Alumnos"
      maxW="detail"
      description="Todas las personas inscriptas a un taller, con el taller al que están anotadas."
    >
      <AlumnosAdminSection />
    </AdminPage>
  );
}
