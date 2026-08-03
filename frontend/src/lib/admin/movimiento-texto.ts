/**
 * movimiento-texto.ts — cómo se LEE un movimiento del libro contable.
 *
 * Función pura (sin JSX) y por eso en `lib/` y no junto al componente que la
 * usa: el gate de CI `react-refresh/only-export-components` no deja exportar
 * helpers desde un archivo que también exporta componentes.
 *
 * Fuente única del texto: la Caja Estudio tenía su propia copia, más pobre —
 * no contemplaba `retiro` ni las dos patas de un cambio de divisa, así que un
 * cambio de dólares se leía "Ajuste" ahí y con su detalle en Movimientos.
 */
import type { Movimiento } from "@/lib/admin/api";

export function descMovimiento(m: Movimiento): string {
  const o = m.cuenta_origen_nombre ?? "—";
  const d = m.cuenta_destino_nombre ?? "—";
  switch (m.tipo) {
    case "gasto":
      return `${m.categoria_nombre ?? "Sin categoría"} · sale de ${o}`;
    case "transferencia":
      return `${o} → ${d}`;
    case "retiro":
      return `Retiro de ${o}`;
    case "aporte":
      return `Aporte a ${d}`;
    default: {
      // Cambio de divisa: cada pata es un `ajuste` con una sola cuenta y
      // `cotizacion` seteada (ver mover-plata.ts / commands/movimientos.py).
      if (m.cotizacion != null) {
        const cta = o !== "—" ? o : d;
        return `Cambio de divisa · ${o !== "—" ? "sale de" : "entra a"} ${cta} (cotización ${m.cotizacion})`;
      }
      return [o !== "—" ? o : null, d !== "—" ? d : null].filter(Boolean).join(" → ") || "Ajuste";
    }
  }
}
