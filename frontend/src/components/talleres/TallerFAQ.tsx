import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/design-system/ui/accordion";
import type { Taller } from "@/lib/api";

/**
 * FAQ del taller — va DESPUÉS de la inscripción (mata objeciones sin
 * interponer fricción antes del CTA). Solo si hay preguntas cargadas.
 */
export function TallerFAQ({ faqs }: { faqs: Taller["faqs"] }) {
  if (faqs.length === 0) return null;

  return (
    <section>
      <p className="font-mono text-2xs tracking-[0.25em] uppercase text-rosa mb-4">
        Preguntas frecuentes
      </p>
      <Accordion type="single" collapsible className="rounded-2xl border border-border/60 px-5">
        {faqs.map((f, i) => (
          <AccordionItem key={i} value={String(i)} className="border-border/50 last:border-b-0">
            <AccordionTrigger className="text-ink hover:no-underline">
              {f.pregunta}
            </AccordionTrigger>
            <AccordionContent className="text-muted-foreground leading-relaxed">
              {f.respuesta}
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </section>
  );
}
