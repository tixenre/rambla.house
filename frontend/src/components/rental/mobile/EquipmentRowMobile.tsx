import { ChevronDown, ChevronRight, Plus } from "lucide-react";
import { type Equipment } from "@/data/equipment";
import { cn } from "@/lib/utils";
import { StepperPill } from "@/components/rental/equipment/shared/StepperPill";
import { PriceBlock } from "@/components/rental/equipment/shared/PriceBlock";
import { FavButton } from "@/components/rental/equipment/shared/FavButton";
import { ShareButton } from "@/components/rental/equipment/shared/ShareButton";
import { useClienteSession, aplicaIva } from "@/lib/iva";
import { EquipoFoto } from "@/components/rental/EquipoFoto";
import { CatIcon } from "./shared";

/* ── EquipmentRowMobile ──────────────────────────────────────────── */
interface EquipmentRowMobileProps {
  eq: Equipment;
  inCart: number;
  isExpanded: boolean;
  jornadas: number;
  fechaDesde: Date | null;
  onTap: () => void;
  onAdd: (delta: number) => void;
  onFicha: () => void;
}

export function EquipmentRowMobile({
  eq,
  inCart,
  isExpanded,
  jornadas,
  fechaDesde,
  onTap,
  onAdd,
  onFicha,
}: EquipmentRowMobileProps) {
  const { data: clienteSession } = useClienteSession();
  const conIva = aplicaIva(clienteSession?.perfil_impuestos);

  // Stock derivado de eq.cantidad (en mobile no se pasa disponibilidad por fecha).
  const sinStock = eq.cantidad === 0;
  const pocoStock = eq.cantidad != null && eq.cantidad > 0 && eq.cantidad <= 2;
  const reachedMax = eq.cantidad != null && inCart >= eq.cantidad;

  // Nombre público: `eq.name` ya es el nombre público canónico —
  // `backendToEquipment` lo deriva vía `buildPublicName` (single source of
  // truth: usa `nombre_publico` del backend, que ya incluye la marca, con
  // fallback al nombre interno). No re-concatenar `eq.brand` acá: duplicaba
  // la marca en los equipos con template configurado.
  const nombrePublico = eq.name;

  const quickFacts = (
    eq.specsDestacados && eq.specsDestacados.length > 0
      ? eq.specsDestacados
      : [
          eq.montura && { label: "Montura", value: eq.montura },
          eq.formato && { label: "Formato", value: eq.formato },
          eq.resolucion && { label: "Resolución", value: eq.resolucion },
          eq.peso && { label: "Peso", value: eq.peso },
          eq.alimentacion && { label: "Alimentación", value: eq.alimentacion },
        ].filter((x): x is { label: string; value: string } => !!x)
  ).slice(0, 4);

  return (
    <div
      className={cn(
        "mb-1.5 overflow-hidden rounded-lg border transition-all duration-150",
        isExpanded
          ? "border-ink/40 bg-accent/30"
          : inCart > 0
            ? "border-amber/60 bg-amber-soft/30"
            : sinStock
              ? "hairline opacity-50"
              : "hairline bg-card",
      )}
    >
      {/* Main row */}
      <div
        className="flex cursor-pointer select-none items-center gap-2.5 p-[10px_12px_10px_10px]"
        style={{ WebkitTapHighlightColor: "transparent" }}
        onClick={onTap}
      >
        {/* Thumb cuadrado 1:1 + FavButton */}
        <div className="relative shrink-0">
          <div className="flex aspect-square w-12 items-center justify-center overflow-hidden rounded-md bg-white text-muted-foreground">
            <EquipoFoto
              foto={eq}
              alt={nombrePublico}
              sizes="48px"
              blur={false}
              loading="lazy"
              className="h-full w-full object-contain p-1.5"
              fallback={<CatIcon cat={eq.category} size={20} />}
            />
          </div>
          <FavButton itemId={String(eq.id)} size="sm" className="absolute -right-1.5 -top-1.5" />
        </div>

        {/* Info */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 font-mono text-2xs uppercase leading-none tracking-[0.1em] text-muted-foreground">
            <span className="min-w-0 truncate">{eq.category}</span>
            {/* Solo el estado accionable (agotado) en el listado; el stock bajo
                queda para el panel expandido y la ficha, evitando ruido. */}
            {sinStock && (
              <span className="shrink-0 whitespace-nowrap text-destructive">· agotado</span>
            )}
          </div>
          <div className="mt-0.5 flex items-start gap-1.5">
            <span className="line-clamp-2 font-sans text-15 font-bold leading-[1.2] text-ink">
              {nombrePublico}
            </span>
            <ChevronDown
              className={cn(
                "mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
                isExpanded && "rotate-180",
              )}
            />
          </div>
        </div>

        <PriceBlock
          perDay={eq.pricePerDay}
          jornadas={fechaDesde ? jornadas : 0}
          qty={inCart || 1}
          conIva={conIva}
          size="sm"
          align="right"
          className="shrink-0"
        />

        {/* Action */}
        <div onClick={(e) => e.stopPropagation()}>
          {inCart > 0 ? (
            <StepperPill
              qty={inCart}
              onIncrement={() => onAdd(1)}
              onDecrement={() => onAdd(-1)}
              maxReached={reachedMax}
              size="md"
            />
          ) : (
            <button
              type="button"
              aria-label={`Agregar ${nombrePublico}`}
              disabled={sinStock}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full border hairline bg-background text-ink transition-colors hover:border-amber hover:bg-amber active:scale-90 disabled:cursor-not-allowed disabled:opacity-40"
              onClick={(e) => {
                e.stopPropagation();
                if (sinStock) return;
                onAdd(1);
                onTap(); // also expand
              }}
            >
              <Plus size={16} />
            </button>
          )}
        </div>
      </div>

      {/* Expansion panel */}
      {isExpanded && (
        <div
          className="border-t px-3.5 py-3"
          style={{
            borderTop: "1px dashed color-mix(in oklch, var(--amber) 50%, var(--hairline))",
            background: "color-mix(in oklch, var(--amber) 5%, var(--background))",
            animation: "expand-in 0.18s ease-out",
          }}
        >
          {/* Total */}
          <div className="mb-2.5 flex items-baseline justify-between border-b border-hairline pb-2.5">
            <PriceBlock
              perDay={eq.pricePerDay}
              jornadas={fechaDesde ? jornadas : 0}
              qty={inCart || 1}
              conIva={conIva}
              size="lg"
            />
            {inCart > 1 ? (
              <span className="font-mono text-xs uppercase tracking-[0.15em] text-muted-foreground">
                {inCart} unidades
              </span>
            ) : pocoStock ? (
              <span className="font-mono text-xs uppercase tracking-[0.15em] text-amber">
                {/* Rental, no e-commerce: mostramos el stock como dato neutro
                    ("1 disponible"), no escasez tipo "última unidad" — tener 1
                    unidad es lo normal acá. El stepper ya capa en el stock. */}
                {eq.cantidad} {eq.cantidad === 1 ? "disponible" : "disponibles"}
              </span>
            ) : null}
          </div>

          {/* Includes — 2 columnas */}
          {eq.includes && eq.includes.length > 0 && (
            <div className="mb-2">
              <div className="mb-1.5 t-eyebrow">Incluye</div>
              <div className="grid grid-cols-2 gap-1">
                {eq.includes.map((item, i) => (
                  <span
                    key={i}
                    className="rounded-full border border-hairline bg-card px-2.5 py-0.5 font-sans text-xs text-ink"
                  >
                    <svg
                      width="8"
                      height="8"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="3"
                      strokeLinecap="round"
                      className="inline mr-1 align-middle"
                    >
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                    {item.qty ?? 1}× {item.name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Specs destacados (top 4) */}
          {quickFacts.length > 0 && (
            <div className="mb-2.5 flex flex-wrap gap-1">
              {quickFacts.map((f) => {
                const hasValue = !!f.value?.trim();
                return (
                  <span
                    key={f.label}
                    className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-card px-2 py-0.5 font-sans text-xs"
                  >
                    <span className="font-mono uppercase tracking-wider text-xs text-muted-foreground">
                      {f.label}
                    </span>
                    {hasValue && <span className="font-medium text-ink">{f.value}</span>}
                  </span>
                );
              })}
            </div>
          )}

          {/* Ficha link + compartir — antes compartir solo vivía adentro de la
              ficha (2 toques: expandir la fila, después "Ver ficha técnica").
              En desktop, ShareButton ya está a mano en la card sin expandir
              nada (EquipmentCard.tsx) — acá queda a 1 toque, mismo botón
              compartido, sin recrear la lógica (ver @/lib/share). */}
          <div className="flex items-center justify-between gap-2">
            <button
              className="inline-flex items-center gap-1 font-sans text-xs font-semibold text-ink border-b border-b-ink pb-px hover:text-amber hover:border-amber transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                onFicha();
              }}
            >
              Ver ficha técnica
              <ChevronRight size={12} />
            </button>
            <div onClick={(e) => e.stopPropagation()}>
              <ShareButton item={eq} size="sm" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
