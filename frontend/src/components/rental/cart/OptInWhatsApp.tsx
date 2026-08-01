/**
 * OptInWhatsApp.tsx — consentimiento del cliente para recibir avisos por WhatsApp.
 *
 * Autocontenido a propósito: lee y guarda su propio estado contra `/api/cliente/me`
 * (el mismo endpoint que el perfil), así se puede montar donde haga falta sin
 * cablear props por toda la cadena del checkout.
 *
 * Meta exige consentimiento **demostrable**: se prende con un acto explícito del
 * cliente y nunca se infiere de que haya cargado un teléfono. El backend además
 * guarda cuándo se registró (`whatsapp_opt_in_at`).
 */
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { authedFetch } from "@/lib/authedFetch";

export function OptInWhatsApp({ className }: { className?: string }) {
  const [valor, setValor] = useState<boolean | null>(null); // null = todavía cargando
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    let vivo = true;
    void (async () => {
      try {
        const res = await authedFetch("/api/cliente/me");
        if (!res.ok) return;
        const me = (await res.json()) as { whatsapp_opt_in?: boolean | null };
        if (vivo) setValor(Boolean(me.whatsapp_opt_in));
      } catch {
        /* si no se pudo leer, no mostramos el control (no inventamos un default) */
      }
    })();
    return () => {
      vivo = false;
    };
  }, []);

  async function cambiar(next: boolean) {
    const previo = valor;
    setValor(next); // optimista: el check responde al toque
    setGuardando(true);
    try {
      const res = await authedFetch("/api/cliente/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ whatsapp_opt_in: next }),
      });
      if (!res.ok) throw new Error(`Error ${res.status}`);
    } catch {
      setValor(previo); // se revierte: no queremos mostrar un consentimiento que no se guardó
      toast.error("No pudimos guardar tu preferencia. Probá de nuevo.");
    } finally {
      setGuardando(false);
    }
  }

  if (valor === null) return null; // sin dato todavía: no parpadeamos un check en falso

  return (
    <label className={`flex cursor-pointer items-start gap-2.5 ${className ?? ""}`}>
      <input
        type="checkbox"
        checked={valor}
        disabled={guardando}
        onChange={(e) => void cambiar(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 rounded border-hairline accent-ink"
      />
      <span className="text-sm text-ink">
        Avisame por WhatsApp
        <span className="mt-0.5 block text-xs text-muted-foreground">
          Te escribimos solo por tu reserva: cuando la recibimos, cuando se confirma y los
          recordatorios de retiro y devolución. Lo podés desactivar cuando quieras.
        </span>
      </span>
    </label>
  );
}
