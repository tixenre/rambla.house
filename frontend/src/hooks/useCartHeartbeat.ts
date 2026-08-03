import { useEffect } from "react";
import { useCart } from "@/lib/cart-store";
import { authedFetch } from "@/lib/authedFetch";
import { ymd } from "@/lib/rental-dates";

const DEBOUNCE_MS = 2000;

/**
 * Manda el carrito actual al backend. El backend resuelve `cliente_id` desde
 * la cookie de sesión — por eso alcanza con volver a llamar esto cuando el
 * cliente pasa de anónimo a logueado (o cambia de cuenta) para que
 * `carritos_activos.cliente_id` no quede desincronizado, aunque el carrito
 * en sí no haya cambiado.
 */
export function syncCartHeartbeat() {
  const { items, startDate, endDate, startTime, endTime, sessionId } = useCart.getState();

  if (Object.keys(items).length === 0) return;

  const body = {
    session_id: sessionId,
    items: Object.entries(items).map(([equipo_id, cantidad]) => ({
      equipo_id: Number(equipo_id),
      cantidad,
    })),
    // `ymd` (fecha local) y no `toISOString()`: el ISO pasa a UTC y podía
    // correr un día la fecha elegida por el cliente.
    fecha_desde: startDate ? ymd(startDate) : null,
    fecha_hasta: endDate ? ymd(endDate) : null,
    hora_desde: startTime ?? null,
    hora_hasta: endTime ?? null,
  };

  fetch("/api/cart/heartbeat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  }).catch(() => {
    // Silencioso — no bloquea la UX si la red falla
  });
}

export function useCartHeartbeat() {
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;

    const unsubscribe = useCart.subscribe((state, prev) => {
      if (
        state.items !== prev.items ||
        state.startDate !== prev.startDate ||
        state.endDate !== prev.endDate ||
        state.startTime !== prev.startTime ||
        state.endTime !== prev.endTime
      ) {
        clearTimeout(timer);
        timer = setTimeout(syncCartHeartbeat, DEBOUNCE_MS);
      }
    });

    // Cubre el caso común: login con reload completo (Google/passkey/dev-login)
    // remonta este hook con la cookie de sesión ya seteada — resincroniza el
    // carrito persistido sin esperar a que cambien items/fechas.
    authedFetch("/api/cliente/me")
      .then((res) => {
        if (res.ok) syncCartHeartbeat();
      })
      .catch(() => {
        // Anónimo o red caída — nada que resincronizar.
      });

    return () => {
      clearTimeout(timer);
      unsubscribe();
    };
  }, []);
}
