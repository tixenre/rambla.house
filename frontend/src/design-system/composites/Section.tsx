import { type ComponentType, type ReactNode } from "react";
import { cn } from "@/lib/utils";

type SectionProps = {
  /** Título de la sección. String vacío = sin título propio (ej. cuando un
   *  wrapper externo como AdminSection ya lo muestra). */
  title: string;
  /** Bajada opcional. En variant="card" va en texto chico muted; en
   *  variant="plain" va como eyebrow (mono/uppercase/tracked) debajo del título. */
  subtitle?: string;
  /** "card" = con borde+fondo propio (default). "plain" = sin chrome, solo
   *  título + contenido (para páginas ya envueltas en su propia card). */
  variant?: "card" | "plain";
  /** Solo aplica a variant="card". "elevated" = header en tira separada con
   *  borde inferior propio (fondo surface-elevated) — para paneles dentro de
   *  una página ya densa. "default" = título inline arriba del contenido. */
  tone?: "default" | "elevated";
  icon?: ComponentType<{ className?: string }>;
  /** Acción(es) a la derecha del título (ej. un badge de estado, un botón). */
  actions?: ReactNode;
  id?: string;
  className?: string;
  /** className del contenedor de children (default: sin clase en "plain";
   *  "mt-2" en "card"/default; el padding ya lo pone "card"/elevated). */
  contentClassName?: string;
  children: ReactNode;
};

/**
 * Section — composite único de encabezado + contenido para páginas admin.
 *
 * Consolida los 6 wrappers locales "Section" que habían aparecido en el
 * repo (LiquidacionReporte, contabilidad.reporte, marca.lazy, estudio,
 * PedidoPageHelpers + variantes) con formas ligeramente distintas de lo
 * mismo. `StudioBookingForm` (wizard numerado, público) queda afuera a
 * propósito — es un patrón distinto (paso numerado, no un panel admin).
 */
export function Section({
  title,
  subtitle,
  variant = "card",
  tone = "default",
  icon: Icon,
  actions,
  id,
  className,
  contentClassName,
  children,
}: SectionProps) {
  if (variant === "plain") {
    return (
      <section id={id} className={cn("space-y-3", className)}>
        {(title || Icon || actions) && (
          <div className="flex items-center gap-2">
            {Icon && <Icon className="h-4 w-4 text-muted-foreground shrink-0" />}
            <div className="min-w-0">
              {title && <h2 className="font-display text-xl text-ink">{title}</h2>}
              {subtitle && <p className="t-eyebrow mt-0.5">{subtitle}</p>}
            </div>
            {actions && <div className="ml-auto shrink-0">{actions}</div>}
          </div>
        )}
        <div className={contentClassName}>{children}</div>
      </section>
    );
  }

  if (tone === "elevated") {
    return (
      <section id={id} className={cn("rounded-xl border hairline bg-surface-elevated", className)}>
        {(title || Icon || actions) && (
          <div className="flex items-center gap-2.5 px-4 py-3 border-b hairline">
            {Icon && <Icon className="h-[18px] w-[18px] text-muted-foreground shrink-0" />}
            {/* `font-display text-base`, no `font-medium text-sm`: era el único
                de los tres tonos cuyo título usaba la fuente de TEXTO al mismo
                tamaño que su propio contenido — se leía como una línea más del
                panel, no como su encabezado (lo pidió el dueño: "¿podemos
                hacer que estos títulos tengan más jerarquía?"). Queda un
                escalón abajo de `default` (text-lg) y `plain` (text-xl), que
                es lo correcto: `elevated` es el panel anidado y más denso.
                Y `<h2>`, no `<span>`: es un encabezado real — un `span` no le
                daba landmark de sección a un lector de pantalla. */}
            {title && <h2 className="font-display text-base text-ink truncate">{title}</h2>}
            {actions && <span className="ml-auto shrink-0">{actions}</span>}
          </div>
        )}
        <div className={cn("p-4", contentClassName)}>{children}</div>
      </section>
    );
  }

  const hasHeader = Boolean(title || Icon || actions);
  return (
    <section id={id} className={cn("rounded-lg border hairline bg-background p-4", className)}>
      {hasHeader && (
        <div className="flex items-center gap-2 mb-2">
          {Icon && <Icon className="h-4 w-4 text-muted-foreground shrink-0" />}
          {title && <h2 className="font-display text-lg text-ink truncate flex-1">{title}</h2>}
          {actions && <div className="ml-auto shrink-0">{actions}</div>}
        </div>
      )}
      {subtitle && <p className="text-xs text-muted-foreground mb-3">{subtitle}</p>}
      <div className={cn(hasHeader && "mt-2", contentClassName)}>{children}</div>
    </section>
  );
}
