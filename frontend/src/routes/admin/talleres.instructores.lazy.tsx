import { createLazyFileRoute } from "@tanstack/react-router";
import { AdminPage } from "@/components/admin/AdminPage";
import { InstructoresAdminSection } from "@/components/admin/talleres/InstructoresAdminSection";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

export const Route = createLazyFileRoute("/admin/talleres/instructores")({
  component: ProfesoresPage,
});

function ProfesoresPage() {
  useDocumentTitle("Profesores · Back Office");
  return (
    <AdminPage
      title="Profesores"
      maxW="detail"
      description="Perfil de cada instructor y los talleres que dicta."
    >
      <InstructoresAdminSection />
    </AdminPage>
  );
}
