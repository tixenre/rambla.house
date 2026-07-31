import { Link } from "@tanstack/react-router";
import { useCart } from "@/lib/cart-store";
import { useState, type ReactNode } from "react";
import { ShoppingBag } from "lucide-react";
import { Button } from "@/design-system/ui/button";
import { RentalDateModal } from "@/components/rental/dates/RentalDateModal";
import { DatePill } from "@/components/rental/dates/DatePill";
import { Logo } from "./Logo";
import { LogoMark } from "./LogoMark";
import { AreaMenu } from "./AreaMenu";
import { AREAS } from "@/data/areas";
import { useClienteSession } from "@/lib/iva";
import { cn } from "@/lib/utils";

// ── Dimensiones compartidas del topbar (fuente única) ──────────────────────────
// Todas las variantes salen del mismo shell → mismo alto y padding en toda la web.
const TOPBAR_H = "h-16";
const TOPBAR_PX = "px-4 md:px-8";

// ── Config por sección ──────────────────────────────────────────────────────────
// Las 3 áreas derivan de la fuente única `AREAS` (label/href/bg); acá solo se suma
// el color del CTA. `cliente` (portal post-login) es propio del topbar, no es un
// área navegable del menú.
const SECTION_CONFIG = {
  rental: { ...AREAS.rental, ctaColor: "bg-ink text-amber hover:opacity-90" },
  estudio: { ...AREAS.estudio, ctaColor: "bg-white text-ink hover:bg-white/90" },
  escuela: { ...AREAS.escuela, ctaColor: "bg-white text-ink hover:bg-white/90" },
  cliente: {
    label: "portal.",
    href: "/cliente/portal",
    bg: "bg-verde",
    ctaColor: "bg-white text-ink hover:bg-white/90",
  },
} as const;

export type Section = keyof typeof SECTION_CONFIG;

const SECTION_DEFAULT_CTA: Record<Section, { label: string; href: string } | null> = {
  rental: null,
  estudio: { label: "Reservar el estudio", href: "/estudio#reserva" },
  escuela: null,
  cliente: null,
};

export type TopBarProps = {
  /**
   * - "default" / "rental": catálogo (dates pill + carrito).
   * - "estudio" / "escuela": topbar de sección + CTA.
   * - "cliente": portal post-login (logo + menú; perfil/salir van en el menú).
   */
  variant?: "default" | "rental" | "estudio" | "escuela" | "cliente";
  /** CTA override para section bars. Si no se pasa se usa el default de la sección. */
  cta?: { label: string; href: string };
};

export function TopBar({ variant = "default", cta }: TopBarProps = {}) {
  if (variant === "cliente") return <ClienteTopBar />;
  if (variant === "estudio") return <SectionTopBar section="estudio" ctaOverride={cta} />;
  if (variant === "escuela") return <SectionTopBar section="escuela" ctaOverride={cta} />;
  // "default" | "rental"
  return <RentalTopBar />;
}

// ── Shell único del topbar ───────────────────────────────────────────────────────
// Estructura compartida: <header> sticky con alto/padding/bg de marca fijos, logo a
// la izquierda, slot central opcional y slot derecho. De acá salen TODAS las barras
// (incluido el catálogo mobile, que lo importa directo con sus propios slots).
export function TopBarShell({
  section,
  center,
  centerClassName = "flex",
  right,
  headerRef,
  labelOverride,
}: {
  section: Section;
  center?: ReactNode;
  /** Clases del contenedor central — el caller decide su visibilidad (ej. "hidden md:flex"). */
  centerClassName?: string;
  right?: ReactNode;
  /** Para medir la altura real del topbar (ej. sticky tops del catálogo mobile). */
  headerRef?: React.Ref<HTMLElement>;
  /** Reemplaza el label del área (ej. el nombre del cliente en el portal). */
  labelOverride?: string;
}) {
  const { bg } = SECTION_CONFIG[section];
  return (
    <header
      ref={headerRef}
      className={cn("sticky top-0 z-[var(--z-topbar)] pt-[env(safe-area-inset-top)]", bg)}
    >
      <div className={cn("flex items-center gap-3", TOPBAR_H, TOPBAR_PX)}>
        {/* Sin label en mobile cuando hay date pill central (no hay espacio). */}
        <SectionLogo section={section} labelMobile={!center} labelOverride={labelOverride} />
        {center && (
          <div className={cn("flex-1 justify-center px-2 min-w-0", centerClassName)}>{center}</div>
        )}
        <div className="ml-auto flex items-center gap-2 shrink-0">
          {right}
          <AreaMenu current={section} />
        </div>
      </div>
    </header>
  );
}

// ── Logo compuesto: isologo (mobile) / wordmark (desktop) + label de área ─────────
// El logo ES la navegación de vuelta al root del área. Siempre blanco sobre el color.
export function SectionLogo({
  section,
  labelMobile = true,
  labelOverride,
}: {
  section: Section;
  /** Mostrar el label del área en mobile. False cuando el topbar ya tiene un
   *  control central (date pill) que no deja espacio. */
  labelMobile?: boolean;
  /** Reemplaza el label por defecto del área (ej. nombre del cliente). */
  labelOverride?: string;
}) {
  const { label: defaultLabel, href } = SECTION_CONFIG[section];
  const label = labelOverride ?? defaultLabel;
  return (
    <Link
      to={href}
      className="inline-flex items-center sm:items-end gap-2 sm:gap-2.5 group shrink-0"
    >
      {/* Mobile: isologo (R) mono — blanco sobre el color del área */}
      <LogoMark className="sm:hidden text-white h-10 w-10" />
      {/* Desktop: wordmark completo */}
      <Logo linkTo={null} size="sm" color="text-white" className="max-sm:hidden" />
      <span
        className={cn(
          "font-display font-black lowercase leading-none text-white text-base",
          !labelMobile && "max-sm:hidden",
        )}
      >
        {label}
      </span>
    </Link>
  );
}

// ── TopBar de secciones (estudio / escuela): logo + CTA ─────────────────────────
function SectionTopBar({
  section,
  ctaOverride,
}: {
  section: Section;
  ctaOverride?: { label: string; href: string };
}) {
  const { ctaColor } = SECTION_CONFIG[section];
  const cta = ctaOverride ?? SECTION_DEFAULT_CTA[section];
  return (
    <TopBarShell
      section={section}
      right={
        cta && (
          <a
            href={cta.href}
            className={cn(
              // Oculto en mobile: el CTA ya vive en el hero + barra sticky inferior.
              "hidden sm:inline-flex items-center gap-1.5 rounded-full px-5 py-2 text-sm font-bold transition shrink-0",
              ctaColor,
            )}
          >
            {cta.label}
          </a>
        )
      }
    />
  );
}

// ── TopBar del rental (catálogo): dates pill central + carrito + sesión ───────────
// Fondo amber sólido (color del área) → controles en blanco/ink para contrastar.
function RentalTopBar() {
  const { startDate, endDate, startTime, endTime, setDrawerOpen, totalItems, days } = useCart();
  const [dateModalOpen, setDateModalOpen] = useState(false);
  const count = totalItems();
  const jornadas = days();

  const datesPill = (
    <DatePill
      startDate={startDate}
      endDate={endDate}
      startTime={startTime}
      endTime={endTime}
      jornadas={jornadas}
      onClick={() => setDateModalOpen(true)}
    />
  );

  const actions = (
    // Carrito solo desktop (en mobile vive en MobileStickyBar / CartMiniBar).
    // El acceso cliente se movió al menú (AreaMenu).
    <Button
      variant="primary"
      shape="pill"
      onClick={() => setDrawerOpen(true, "bottom")}
      className="hidden md:inline-flex relative"
      aria-label={`Carrito (${count})`}
    >
      <ShoppingBag className="h-4 w-4" />
      {count > 0 && <span className="tabular-nums">{count}</span>}
      <span>{count > 0 ? (count === 1 ? "ítem" : "ítems") : "Tu rental"}</span>
    </Button>
  );

  return (
    <>
      <RentalDateModal open={dateModalOpen} onOpenChange={setDateModalOpen} />
      <TopBarShell
        section="rental"
        center={datesPill}
        centerClassName="hidden md:flex"
        right={actions}
      />
    </>
  );
}

// ── TopBar del portal cliente: logo + menú ────────────────────────────────────────
// Mi perfil y Salir viven en el menú (AreaMenu), igual que el acceso cliente.
// El label se personaliza con el nombre del cliente logueado ("rambla tincho.");
// sin sesión (ej. /cliente/login) cae al "portal." por defecto.
function ClienteTopBar() {
  const { data: clienteSession } = useClienteSession();
  const firstName = clienteSession?.nombre?.trim().split(" ")[0];
  const label = firstName ? `${firstName.toLowerCase()}.` : undefined;
  return <TopBarShell section="cliente" labelOverride={label} />;
}
