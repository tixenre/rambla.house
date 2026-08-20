// ── Navegación del back-office — fuente única ──────────────────────────────────
// La estructura del menú del admin vive acá UNA sola vez, agrupada por dominio.
// La consumen: el `AdminSidebar` (grupos + items), el breadcrumb del `AdminPage`
// (resuelve grupo + título por URL) y el command palette `Cmd+K` (índice de rutas).
// Es el espejo admin de `src/data/areas.ts` para el lado público: cambiar el orden,
// el label o el grupo de una entrada se hace acá, no en cada consumidor.
//
// Materializa el principio "una sola forma / reusar no recrear" (DESIGN_SYSTEM.md):
// no duplicar la lista de rutas en sidebar, breadcrumb y palette por separado.

import {
  LayoutDashboard,
  ClipboardList,
  ShoppingCart,
  Users,
  UserCog,
  Clapperboard,
  CalendarClock,
  GraduationCap,
  Inbox,
  Package,
  ShieldCheck,
  FolderTree,
  Building2,
  Landmark,
  Database,
  Ruler,
  Wallet,
  BarChart3,
  Calculator,
  TrendingUp,
  BookOpen,
  Palette,
  Megaphone,
  Sparkles,
  HardDriveDownload,
  Settings,
  AlertTriangle,
  MessagesSquare,
  type LucideIcon,
} from "lucide-react";

export type AdminNavItem = {
  /** Texto visible en el sidebar y en el breadcrumb (hoja). */
  title: string;
  url: string;
  icon: LucideIcon;
  /** Match exacto de ruta activa (solo el index del admin). */
  exact?: boolean;
};

export type AdminNavGroup = {
  /** Id estable (key de estado open/closed). */
  id: string;
  /** Label del grupo (SidebarGroupLabel + crumb padre del breadcrumb). */
  label: string;
  /** Si el grupo arranca expandido. SISTEMA arranca colapsado (uso esporádico). */
  defaultOpen: boolean;
  items: AdminNavItem[];
};

/**
 * Estructura del menú por dominio. Orden = prioridad de uso:
 * OPERACIÓN (diario) arriba → SISTEMA (config, mensual) al fondo y colapsado.
 */
export const ADMIN_NAV: AdminNavGroup[] = [
  {
    id: "operacion",
    label: "Operación",
    defaultOpen: true,
    items: [
      { title: "Dashboard", url: "/admin", icon: LayoutDashboard, exact: true },
      { title: "Pedidos", url: "/admin/pedidos", icon: ClipboardList },
      { title: "Carritos activos", url: "/admin/carritos", icon: ShoppingCart },
      { title: "Clientes", url: "/admin/clientes", icon: Users },
      // Al lado de Clientes (#1251 Fase 2) — antes en Finanzas, desconectada:
      // el dueño no la encontraba al buscar dónde gestionar cuentas/entidades.
      { title: "Productoras", url: "/admin/productoras", icon: Building2 },
    ],
  },
  {
    id: "estudio",
    label: "Estudio",
    defaultOpen: true,
    items: [
      { title: "Reservas", url: "/admin/estudio/reservas", icon: CalendarClock },
      { title: "Estudio", url: "/admin/estudio", icon: Clapperboard, exact: true },
    ],
  },
  {
    id: "talleres",
    label: "Talleres",
    defaultOpen: true,
    items: [
      { title: "Talleres", url: "/admin/talleres", icon: GraduationCap, exact: true },
      { title: "Instituciones", url: "/admin/talleres/instituciones", icon: Landmark },
      { title: "Alumnos", url: "/admin/talleres/alumnos", icon: Users },
      { title: "Sin enviar", url: "/admin/talleres/sin-enviar", icon: Inbox },
      { title: "Profesores", url: "/admin/talleres/instructores", icon: UserCog },
    ],
  },
  {
    id: "inventario",
    label: "Inventario",
    defaultOpen: true,
    items: [
      { title: "Equipos", url: "/admin/equipos", icon: Package },
      { title: "Calidad", url: "/admin/equipos/calidad", icon: ShieldCheck },
      { title: "Categorías", url: "/admin/equipos/categorias", icon: FolderTree },
      { title: "Marcas", url: "/admin/equipos/marcas", icon: Building2 },
      { title: "Specs", url: "/admin/specs", icon: Database },
      { title: "Unidades", url: "/admin/unidades", icon: Ruler },
    ],
  },
  {
    id: "finanzas",
    label: "Finanzas",
    defaultOpen: true,
    items: [
      // Finanzas = Tablero + Cuentas + Rendición fundidos en una pantalla
      // (2026-08-03); /cuentas y /rendicion redirigen acá.
      { title: "Finanzas", url: "/admin/contabilidad", icon: Wallet, exact: true },
      // Los cobros de pedidos viven dentro de Movimientos (fila mensual desplegable);
      // /admin/pagos sigue accesible como "ver ledger completo" desde ese detalle.
      { title: "Movimientos", url: "/admin/contabilidad/movimientos", icon: ClipboardList },
      // Economía separada del Estudio (caja + movimientos + rendición propia) —
      // vive en Finanzas, no en "Estudio y talleres": es una vista de plata,
      // no de operación (mismo criterio que Productoras vs. Clientes, #1251).
      { title: "Caja Estudio", url: "/admin/contabilidad/estudio", icon: Clapperboard },
      { title: "Reporte mensual", url: "/admin/contabilidad/reporte", icon: BarChart3 },
      { title: "Liquidación", url: "/admin/contabilidad/liquidacion", icon: Calculator },
      { title: "Estadísticas", url: "/admin/estadisticas", icon: TrendingUp },
      { title: "Facturas ARCA", url: "/admin/facturas", icon: ClipboardList },
      { title: "Emisores ARCA", url: "/admin/facturacion/emisores", icon: Settings },
      { title: "Glosario", url: "/admin/contabilidad/glosario", icon: BookOpen },
    ],
  },
  {
    id: "sistema",
    label: "Sistema",
    defaultOpen: false,
    items: [
      // Comunicación agrupa los DOS canales (mail + WhatsApp) y los eventos: qué
      // le decimos al cliente y por dónde sale. WhatsApp no lleva entrada propia —
      // es un canal de este módulo, no una sección aparte.
      { title: "Comunicación", url: "/admin/comunicacion", icon: MessagesSquare },
      { title: "Assets y diseño", url: "/admin/diseno", icon: Palette },
      { title: "Marca", url: "/admin/marca", icon: Megaphone },
      { title: "Novedades", url: "/admin/novedades", icon: Sparkles },
      { title: "Media", url: "/admin/media", icon: Database },
      { title: "Datos y backups", url: "/admin/dataio", icon: HardDriveDownload },
      { title: "Settings", url: "/admin/settings", icon: Settings },
      { title: "Errores del servidor", url: "/admin/errores", icon: AlertTriangle },
    ],
  },
];

/**
 * Índice plano de todas las rutas del admin, con su grupo — para el breadcrumb
 * (`AdminPage`) y el command palette. Derivado de `ADMIN_NAV`: una sola verdad.
 */
export type AdminRoute = AdminNavItem & { group: string };

export const ADMIN_ROUTES: AdminRoute[] = ADMIN_NAV.flatMap((g) =>
  g.items.map((it) => ({ ...it, group: g.label })),
);

/**
 * Resuelve la ruta del admin que mejor matchea un pathname, para el breadcrumb.
 * Elige el match más específico (la URL más larga que sea prefijo del path),
 * así `/admin/equipos/calidad` gana sobre `/admin/equipos`.
 */
export function matchAdminRoute(pathname: string): AdminRoute | undefined {
  let best: AdminRoute | undefined;
  for (const r of ADMIN_ROUTES) {
    const hit = r.exact
      ? pathname === r.url
      : pathname === r.url || pathname.startsWith(r.url + "/");
    if (hit && (!best || r.url.length > best.url.length)) best = r;
  }
  return best;
}
