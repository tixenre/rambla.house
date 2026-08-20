import { CheckCircle2, ExternalLink } from "lucide-react";

/** Link al comprobante de pago de una inscripción — mismo ícono/estilo en
 * cualquier tabla que liste inscripciones (`InscripcionesSection`, scoped a
 * una edición; `AlumnosAdminSection`, vista global "Alumnos"). */
export function ComprobanteLink({ url }: { url: string | null }) {
  if (!url) return <span className="text-muted-foreground/50 text-xs">—</span>;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-ink hover:text-ink transition"
    >
      <CheckCircle2 className="h-3.5 w-3.5 text-verde-ink" strokeWidth={1.5} />
      <ExternalLink className="h-3 w-3" />
    </a>
  );
}
