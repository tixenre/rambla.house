import { createLazyFileRoute } from "@tanstack/react-router";
import { AdminPage } from "@/components/admin/AdminPage";
import { SinEnviarAdminSection } from "@/components/admin/talleres/SinEnviarAdminSection";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

export const Route = createLazyFileRoute("/admin/talleres/sin-enviar")({
  component: SinEnviarPage,
});

function SinEnviarPage() {
  useDocumentTitle("Sin enviar · Back Office");
  return (
    <AdminPage
      title="Sin enviar"
      maxW="detail"
      description="Personas que empezaron a inscribirse a un taller y no llegaron a mandar el formulario."
    >
      <SinEnviarAdminSection />
    </AdminPage>
  );
}
