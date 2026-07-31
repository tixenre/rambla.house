import type { ReactNode } from "react";
import { createLazyFileRoute } from "@tanstack/react-router";
import { Megaphone } from "lucide-react";
import { AdminPage } from "@/components/admin/AdminPage";
import { Section } from "@/design-system/composites/Section";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

export const Route = createLazyFileRoute("/admin/marca")({
  component: MarcaPage,
});

function MarcaPage() {
  useDocumentTitle("Marca · Back Office");
  return (
    <AdminPage
      title="Identidad de marca"
      maxW="detail"
      description={
        <>
          Hub canónico de marca. Los contenidos con{" "}
          <span className="text-ink font-medium">TODO</span> están pendientes del dueño.
        </>
      }
    >
      <div className="space-y-8">
        <Section variant="plain" title="Quiénes somos">
          <div className="space-y-3">
            <div className="rounded-xl border border-border bg-surface px-4 py-3">
              <p className="t-eyebrow mb-1">Tagline</p>
              <p className="font-display text-2xl text-ink">Renovamos el alquiler.</p>
            </div>
            <p className="text-sm text-muted-foreground">
              Rambla es la plataforma de alquiler de equipos audiovisuales para producciones en
              Buenos Aires. Catálogo online, precios claros, documentos automáticos — todo desde el
              celular, sin llamadas, sin sorpresas.
            </p>
          </div>
        </Section>

        <Section variant="plain" title="Rental" subtitle="rambla.house/rental">
          <div className="space-y-3">
            <TaglineCard text="Ahora alquilás todo desde la web." />
            <div className="space-y-2">
              <SellingPoint
                title="Encontrá y agregá sin vueltas"
                desc="Catálogo completo con buscador inteligente, filtros por categoría y disponibilidad real. Sumás al carrito en un clic."
              />
              <SellingPoint
                title="Sabés qué incluye cada equipo"
                desc="Los kits muestran exactamente qué viene incluido, ítem por ítem. Sin sorpresas al retirar."
              />
              <SellingPoint
                title="Elegí tus fechas"
                desc="Picker de fechas integrado: el stock se ajusta en tiempo real según tus días."
              />
              <SellingPoint
                title="Tus documentos, sin pedirlos"
                desc="Presupuesto, remito, albarán y packing list disponibles desde tu portal en cuanto confirmamos el pedido."
              />
            </div>
            <p className="text-xs text-muted-foreground border-t border-border pt-3">
              CTA:{" "}
              <span className="font-medium text-ink">
                Probá la web · Cargás tus datos una vez y quedás listo · rambla.house/rental
              </span>
            </p>
          </div>
        </Section>

        <Section variant="plain" title="Estudio" subtitle="rambla.house/estudio">
          <TodoBanner area="Estudio" />
        </Section>

        <Section variant="plain" title="Escuela" subtitle="rambla.house/escuela">
          <TodoBanner area="Escuela" />
        </Section>

        <Section variant="plain" title="Assets canónicos">
          <div className="rounded-xl border border-border overflow-hidden">
            {/* eslint-disable-next-line no-restricted-syntax -- tabla key/value de layout (label↔valor), no es data-table; AdminTable no aplica */}
            <table className="w-full text-sm">
              <tbody>
                {[
                  ["URL producción", "rambla.house"],
                  ["Instagram", "@rambla.rental"],
                  ["Logo (wordmark)", "Generado inline · backend/services/branding/"],
                  ["Isologo", "LogoMark en frontend/src/components/rental/"],
                  ["Colores de marca", "frontend/src/design-system/styles/tokens/colors.css"],
                ].map(([label, value], i) => (
                  <tr key={label} className={i % 2 === 0 ? "bg-surface" : "bg-background"}>
                    <td className="px-4 py-2.5 text-muted-foreground font-mono text-2xs uppercase tracking-wide w-48 shrink-0">
                      {label}
                    </td>
                    <td className="px-4 py-2.5 text-sm text-ink">{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        <Section variant="plain" title="Inventario de features">
          <p className="text-sm text-muted-foreground">
            El listado detallado de features de cara al usuario (seleccionadas para comunicar,
            disponibles y no listas todavía) vive en{" "}
            <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">
              docs/CAMPAÑA_FEATURES.md
            </code>{" "}
            en el repositorio. El skill{" "}
            <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">marca</code> audita
            periódicamente que las features nuevas queden reflejadas ahí.
          </p>
        </Section>
      </div>
    </AdminPage>
  );
}

function TaglineCard({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-3">
      <p className="t-eyebrow mb-0.5">Tagline</p>
      <p className="font-display text-lg text-ink">{text}</p>
    </div>
  );
}

function SellingPoint({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-4 py-3 space-y-0.5">
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="text-xs text-muted-foreground">{desc}</p>
    </div>
  );
}

function TodoBanner({ area }: { area: string }) {
  return (
    <div className="rounded-xl border border-amber/30 bg-amber/10 px-4 py-4 flex items-start gap-3">
      <Megaphone className="h-4 w-4 text-ink mt-0.5 shrink-0" />
      <div>
        <p className="text-sm font-medium text-ink">Pendiente del dueño</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {area} necesita tagline y selling points. Pasale el copy al asistente para que lo cargue
          acá y en <code className="font-mono">docs/MARCA.md</code>.
        </p>
      </div>
    </div>
  );
}
