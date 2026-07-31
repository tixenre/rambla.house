import { AdminSection } from "@/components/admin/AdminSection";
import { Section as SectionComposite } from "@/design-system/composites/Section";

function slugifyForStorage(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Field local — Fase 2 (C30) lo reemplaza por el composite del DS.
export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  // Cada sección es colapsable y persiste su estado por título (slug).
  // Antes era un scroll lineal de ~900 líneas; ahora el dueño abre lo que
  // necesita y deja el resto cerrado. AdminSection ya muestra el título en
  // su propio toggle — el composite va con title="" para no duplicarlo.
  return (
    <AdminSection title={title} storageKey={`estudio:${slugifyForStorage(title)}`}>
      <SectionComposite
        title=""
        className="rounded-2xl bg-surface p-5"
        contentClassName="space-y-4"
      >
        {children}
      </SectionComposite>
    </AdminSection>
  );
}

export function Field({
  label,
  error,
  hint,
  accion,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  /** Acción a la derecha del label (ej. el ✕ que descarta el bloque entero) —
   *  mismo lugar que el slot `actions` del `Section` del DS. */
  accion?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <label className="t-eyebrow">{label}</label>
        {accion && <div className="ml-auto shrink-0">{accion}</div>}
      </div>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
