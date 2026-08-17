import type { ReactNode } from "react";
import type { CuentaPago } from "@/lib/api";

/**
 * Fragmentos (alias/cbu/banco) de UNA cuenta — solo los que vienen con dato
 * (sin esto, un campo vacío dejaba un separador colgando, ej. "CBU: ·",
 * confirmado en vivo). Cada variant preserva el estilo/labels que ya tenía
 * su call site (el de "form" no rotula "Banco:", el de "success" separa con
 * <br/> en vez de " · " — diferencias preexistentes, no una unificación
 * nueva).
 */
function UnaCuenta({ cuenta, variant }: { cuenta: CuentaPago; variant: "form" | "success" }) {
  const fragments: ReactNode[] = [];
  if (cuenta.alias) {
    fragments.push(
      <span key="alias">
        Alias:{" "}
        <span
          className={variant === "form" ? "font-mono font-medium text-ink" : "text-ink font-mono"}
        >
          {cuenta.alias}
        </span>
      </span>,
    );
  }
  if (cuenta.cbu) {
    fragments.push(
      <span key="cbu">
        CBU:{" "}
        <span className={variant === "form" ? "font-mono text-ink" : "text-ink font-mono text-xs"}>
          {cuenta.cbu}
        </span>
      </span>,
    );
  }
  if (cuenta.banco) {
    fragments.push(
      <span key="banco">
        {variant === "success" && "Banco: "}
        {cuenta.banco}
      </span>,
    );
  }
  if (fragments.length === 0) return null;

  return (
    <>
      {fragments.map((f, i) => (
        <span key={i}>
          {i > 0 && (variant === "form" ? " · " : <br />)}
          {f}
        </span>
      ))}
    </>
  );
}

/**
 * Cuentas de cobro — 0+ (lista independiente de la modalidad de pago; el
 * cliente ve todas y elige a cuál transferir). Único lugar que arma esto —
 * reusado en el form de inscripción (bloque previo al envío + pantalla de
 * éxito) y en la página pública "completá tu seña" (`/escuelas/sena/
 * $token`), que no pueden volver a divergir. Con 1 sola cuenta (el caso
 * común hoy), el render es idéntico al de antes — la lista solo aparece con
 * 2+.
 */
export function DatosPago({
  cuentas,
  variant,
}: {
  cuentas: CuentaPago[];
  variant: "form" | "success";
}) {
  const conDatos = cuentas.filter((c) => c.alias || c.cbu || c.banco);
  if (conDatos.length === 0) return null;
  if (conDatos.length === 1) return <UnaCuenta cuenta={conDatos[0]} variant={variant} />;
  return (
    <span className="flex flex-col gap-2">
      {conDatos.map((c, i) => (
        <UnaCuenta key={c.id ?? i} cuenta={c} variant={variant} />
      ))}
    </span>
  );
}
