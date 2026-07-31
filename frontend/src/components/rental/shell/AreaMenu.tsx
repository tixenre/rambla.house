import { useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import {
  Menu,
  ArrowRight,
  Check,
  Home,
  User,
  LogOut,
  HelpCircle,
  MessageCircle,
  FileText,
  Package,
  ClipboardList,
  Bell,
} from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetTrigger,
  SheetTitle,
  SheetClose,
} from "@/design-system/ui/sheet";
import { useClienteSession, invalidateClienteSession } from "@/lib/iva";
import { authedFetch } from "@/lib/authedFetch";
import { whatsappUrl } from "@/data/contact";
import { AREA_LIST, type AreaKey } from "@/data/areas";
import { cn } from "@/lib/utils";

const SECONDARY = [
  { label: "Preguntas frecuentes", href: "/preguntas-frecuentes", icon: HelpCircle },
  { label: "Términos", href: "/terminos", icon: FileText },
];

// Espeja las 4 solapas del portal (cliente.portal.tsx: Pedidos/Listas/Notificaciones/Perfil).
const PORTAL_TABS = [
  { tab: "pedidos", label: "Mis pedidos", icon: Package },
  { tab: "listas", label: "Mis listas", icon: ClipboardList },
  { tab: "notificaciones", label: "Notificaciones", icon: Bell },
  { tab: "perfil", label: "Mi perfil", icon: User },
] as const;

/**
 * Menú de navegación entre áreas (hamburguesa + sheet lateral).
 * Vive a la derecha del topbar en todas las áreas. Reúsa la identidad del hub:
 * las 3 áreas como ítems de color, el área actual marcada. Incluye Inicio, acceso
 * al portal cliente y links secundarios.
 */
export function AreaMenu({
  current,
  tone = "onColor",
}: {
  current?: AreaKey | "cliente";
  /** Estilo del botón según el fondo: "onColor" (topbar de marca, botón blanco
   *  translúcido) o "onLight" (fondo hueso como la landing, botón ink sólido). */
  tone?: "onColor" | "onLight";
}) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { data: clienteSession } = useClienteSession();
  const isLogged = !!clienteSession;

  async function handleLogout() {
    await authedFetch("/auth/logout", { method: "POST" }).catch(() => {});
    invalidateClienteSession();
    setOpen(false);
    navigate({ to: "/cliente/login" });
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <button
          type="button"
          aria-label="Menú de navegación"
          className={cn(
            "grid h-11 w-11 shrink-0 place-items-center rounded-full transition",
            tone === "onLight"
              ? "bg-ink text-background hover:bg-ink/90"
              : "bg-white/25 text-white hover:bg-white/40",
          )}
        >
          <Menu className="h-5 w-5" />
        </button>
      </SheetTrigger>
      <SheetContent side="right" className="w-[88vw] max-w-sm overflow-y-auto p-0">
        <SheetTitle className="sr-only">Navegación entre áreas</SheetTitle>

        <div className="flex flex-col gap-6 p-5 pt-12">
          {/* Áreas */}
          <div className="flex flex-col gap-2">
            {AREA_LIST.map((a) => {
              const active = current === a.key;
              return (
                <SheetClose asChild key={a.key}>
                  <Link
                    to={a.href}
                    className={cn(
                      "group flex items-center justify-between gap-3 rounded-2xl px-4 py-3.5 transition",
                      a.bg,
                      a.fg,
                      active
                        ? "ring-2 ring-ink/70 ring-offset-2 ring-offset-background"
                        : "hover:brightness-105",
                    )}
                  >
                    <span className="min-w-0">
                      <span className="font-display text-lg font-black lowercase leading-none">
                        {a.label}
                      </span>
                      <span className="mt-1 block text-xs opacity-70">{a.desc}</span>
                    </span>
                    {active ? (
                      <Check className="h-5 w-5 shrink-0" />
                    ) : (
                      <ArrowRight className="h-5 w-5 shrink-0 transition-transform group-hover:translate-x-0.5" />
                    )}
                  </Link>
                </SheetClose>
              );
            })}
          </div>

          {/* Inicio + cuenta del cliente */}
          <div className="flex flex-col gap-1 border-t hairline pt-4">
            <SheetClose asChild>
              <Link
                to="/"
                className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-ink transition hover:bg-muted"
              >
                <Home className="h-4 w-4 shrink-0 text-muted-foreground" />
                Inicio
              </Link>
            </SheetClose>
            {isLogged ? (
              <>
                {/* Las 4 solapas del portal, cada una con su propia entrada — el
                    menú es la navegación principal en mobile (no solo un atajo al
                    perfil): sin esto, pedidos/listas/notificaciones quedaban solo
                    detrás del bottom-nav del portal, que el dueño no descubría. */}
                {PORTAL_TABS.map((t) => (
                  <SheetClose asChild key={t.tab}>
                    <Link
                      to="/cliente/portal"
                      search={{ tab: t.tab }}
                      className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-ink transition hover:bg-muted"
                    >
                      <t.icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                      {t.label}
                    </Link>
                  </SheetClose>
                ))}
                <button
                  type="button"
                  onClick={handleLogout}
                  className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-ink transition hover:bg-muted text-left"
                >
                  <LogOut className="h-4 w-4 shrink-0 text-muted-foreground" />
                  Salir
                </button>
              </>
            ) : (
              <SheetClose asChild>
                <Link
                  to="/cliente"
                  className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-ink transition hover:bg-muted"
                >
                  <User className="h-4 w-4 shrink-0 text-muted-foreground" />
                  Ingresar
                </Link>
              </SheetClose>
            )}
          </div>

          {/* Links secundarios */}
          <div className="flex flex-col gap-1 border-t hairline pt-4">
            <a
              href={whatsappUrl("Hola! Tengo una consulta.")}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-ink transition hover:bg-muted"
            >
              <MessageCircle className="h-4 w-4 shrink-0 text-muted-foreground" />
              Consultanos por WhatsApp
            </a>
            {SECONDARY.map((s) => (
              <SheetClose asChild key={s.href}>
                <Link
                  to={s.href}
                  className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-ink transition hover:bg-muted"
                >
                  <s.icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  {s.label}
                </Link>
              </SheetClose>
            ))}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
