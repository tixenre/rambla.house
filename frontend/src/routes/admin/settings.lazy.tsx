import { createLazyFileRoute } from "@tanstack/react-router";

import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { AdminPage } from "@/components/admin/AdminPage";
import { AdminSection } from "@/components/admin/AdminSection";
import { ComisionesSection } from "@/components/admin/settings/ComisionesSection";
import { DescuentosJornadaSection } from "@/components/admin/settings/DescuentosJornadaSection";
import { GoogleAnalyticsSection } from "@/components/admin/settings/GoogleAnalyticsSection";
import { CalendarFeedSection } from "@/components/admin/settings/CalendarFeedSection";
import { HorariosSection } from "@/components/admin/settings/HorariosSection";
import { FaqSection } from "@/components/admin/settings/FaqSection";
import { RankingSection } from "@/components/admin/settings/RankingSection";
import { CambioYPreciosSection } from "@/components/admin/settings/CambioYPreciosSection";
import { FacturacionSection } from "@/components/admin/settings/FacturacionSection";

export const Route = createLazyFileRoute("/admin/settings")({
  component: SettingsPage,
});

function SettingsPage() {
  useDocumentTitle("Settings · Back Office");

  return (
    <AdminPage
      title="Settings"
      maxW="detail"
      description="Configuración del sistema y herramientas de mantenimiento."
    >
      <div className="space-y-6">
        <AdminSection title="Descuentos por jornadas" storageKey="settings:descuentos">
          <DescuentosJornadaSection />
        </AdminSection>

        <AdminSection title="Horarios" storageKey="settings:horarios">
          <HorariosSection />
        </AdminSection>

        <AdminSection title="Preguntas frecuentes" storageKey="settings:faq" defaultOpen={false}>
          <FaqSection />
        </AdminSection>

        <AdminSection title="Cambio y precios" storageKey="settings:cambio">
          <CambioYPreciosSection />
        </AdminSection>

        <AdminSection title="Ranking automático" storageKey="settings:ranking" defaultOpen={false}>
          <RankingSection />
        </AdminSection>

        <AdminSection title="Google Analytics" storageKey="settings:ga4" defaultOpen={false}>
          <GoogleAnalyticsSection />
        </AdminSection>

        <AdminSection title="Calendario (feed iCal)" storageKey="settings:ical" defaultOpen={false}>
          <CalendarFeedSection />
        </AdminSection>

        <AdminSection
          title="Reparto de comisiones"
          storageKey="settings:comisiones"
          defaultOpen={false}
        >
          <ComisionesSection />
        </AdminSection>

        <AdminSection
          title="Facturación ARCA"
          storageKey="settings:facturacion"
          defaultOpen={false}
        >
          <FacturacionSection />
        </AdminSection>
      </div>
    </AdminPage>
  );
}
