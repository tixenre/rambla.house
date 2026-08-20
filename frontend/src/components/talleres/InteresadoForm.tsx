import { useState, type FormEvent } from "react";
import { CheckCircle2 } from "lucide-react";

import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";

/** Form de "avisame cuando haya más fechas" para un taller sold-out sin
 * próxima edición — mismo endpoint que el resto del funnel de talleres
 * (`POST /api/talleres/{slug}/interesado`). Extraído de la página
 * individual (`escuelas.$slug.lazy.tsx`) para reusarlo tal cual en el hub
 * de institución (`TallerHubBlock`) — antes vivía inline y no era
 * importable desde otro módulo. */
export function InteresadoForm({ slug }: { slug: string }) {
  const [form, setForm] = useState({ nombre: "", email: "", telefono: "" });
  const [status, setStatus] = useState<"idle" | "sending" | "ok" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form.nombre.trim() || !form.email.trim()) return;
    setStatus("sending");
    try {
      const res = await fetch(`/api/talleres/${slug}/interesado`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j?.detail ?? `Error ${res.status}`);
      }
      setStatus("ok");
    } catch (err) {
      setErrorMsg((err as Error).message);
      setStatus("error");
    }
  }

  if (status === "ok") {
    return (
      <div className="rounded-2xl border border-verde/40 bg-verde/10 px-5 py-6 text-center">
        <CheckCircle2 className="h-8 w-8 text-verde mx-auto mb-3" strokeWidth={1.5} />
        <p className="font-semibold text-ink">¡Anotado/a!</p>
        <p className="text-sm text-muted-foreground mt-1">Te avisamos cuando haya nuevas fechas.</p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
        Avisame si hay más fechas
      </p>
      <Input
        required
        type="text"
        placeholder="Tu nombre"
        value={form.nombre}
        onChange={(e) => setForm((f) => ({ ...f, nombre: e.target.value }))}
      />
      <Input
        required
        type="email"
        placeholder="Tu email"
        value={form.email}
        onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
      />
      <Input
        type="tel"
        placeholder="Tu teléfono (opcional)"
        value={form.telefono}
        onChange={(e) => setForm((f) => ({ ...f, telefono: e.target.value }))}
      />
      {status === "error" && <p className="text-xs text-destructive">{errorMsg}</p>}
      <Button
        type="submit"
        variant="amber"
        shape="pill"
        disabled={status === "sending"}
        className="w-full py-3.5 text-base font-bold"
      >
        {status === "sending" ? "Enviando…" : "Avisame"}
      </Button>
    </form>
  );
}
