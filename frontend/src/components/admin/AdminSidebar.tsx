import { useEffect, useState } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { toast } from "sonner";
import { LogOut, ChevronRight, PanelLeft, Search, UserCog } from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/design-system/ui/sidebar";
import { authedFetch } from "@/lib/authedFetch";
import { ADMIN_NAV } from "./adminNav";

export function AdminSidebar({ email }: { email: string }) {
  const { state, toggleSidebar } = useSidebar();
  const collapsed = state === "collapsed";
  const currentPath = useRouterState({
    select: (router) => router.location.pathname,
  });
  const navigate = useNavigate();
  const [isSigningOut, setIsSigningOut] = useState(false);
  // Grupos abiertos por id. Init: defaultOpen del grupo OR el grupo que contiene
  // la ruta actual. No se persiste — cada carga arranca según esta regla.
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() => {
    const path = typeof window !== "undefined" ? window.location.pathname : "";
    const initial: Record<string, boolean> = {};
    for (const g of ADMIN_NAV) {
      const hasActive = g.items.some(
        (it) => path === it.url || (!it.exact && path.startsWith(it.url + "/")),
      );
      initial[g.id] = g.defaultOpen || hasActive;
    }
    return initial;
  });

  // Al navegar, abrir el grupo que contiene la ruta actual (sin cerrar otros).
  useEffect(() => {
    for (const g of ADMIN_NAV) {
      if (g.items.some((it) => isActive(it.url, it.exact))) {
        setOpenGroups((s) => ({ ...s, [g.id]: true }));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- auto-expandir solo al cambiar de ruta; ADMIN_NAV es config estable y setOpenGroups usa functional update
  }, [currentPath]);

  const handleSignOut = async () => {
    if (isSigningOut) return;
    setIsSigningOut(true);
    try {
      await authedFetch("/auth/logout", { method: "POST" });
      navigate({ to: "/admin/login" });
    } catch (e) {
      toast.error("No se pudo cerrar sesión", {
        description: e instanceof Error ? e.message : String(e),
      });
      setIsSigningOut(false);
    }
  };

  function isActive(url: string, exact?: boolean): boolean {
    if (exact) return currentPath === url;
    return currentPath === url || currentPath.startsWith(url + "/");
  }

  function toggleGroup(id: string) {
    setOpenGroups((s) => ({ ...s, [id]: !s[id] }));
  }

  return (
    <Sidebar collapsible="icon" className="border-r hairline">
      <SidebarHeader className="border-b hairline">
        <div className="flex items-center justify-between gap-1">
          <Link
            to="/admin"
            className="flex min-w-0 items-center gap-2 px-2 py-3 group/header"
            aria-label="Rambla Rental — back-office"
          >
            <svg
              className="topbar-seal shrink-0 block h-9 w-9"
              viewBox="0 0 2000 2000"
              aria-hidden="true"
            >
              <path
                className="seal-badge"
                d="M1930.45,949.73c-.44-.28-.88-.55-1.32-.82l-5.91-3.61c-3.19-2.29-6.58-4.35-10.13-6.19l-121.29-74.1c-49.62-30.31-68.53-93.07-43.93-145.76l63.92-136.86c37.05-79.33-25.29-169.12-112.57-162.14l-150.57,12.05c-57.96,4.64-110.15-35.02-121.21-92.1l-28.73-148.29c-16.65-85.96-119.87-121.96-186.37-65.01l-114.72,98.25c-44.16,37.82-109.7,36.42-152.2-3.26l-110.4-103.08c-64-59.75-168.66-28.21-188.99,56.95l-35.07,146.92c-13.5,56.56-67.34,93.94-125.05,86.82l-149.9-18.5c-86.89-10.72-153.03,76.31-119.42,157.16l57.99,139.48c22.32,53.69.73,115.58-50.14,143.74l-140.79,77.93c-.61.33-1.21.68-1.8,1.02-31.8,18.36-44.19,49.65-41.44,79.73-2.42,22.36,6.21,45.75,29.16,60.2.44.28.88.55,1.32.82l5.91,3.61c3.19,2.29,6.58,4.35,10.13,6.19l121.29,74.1c49.62,30.31,68.54,93.08,43.93,145.76l-63.92,136.86c-37.05,79.33,25.29,169.12,112.57,162.14l150.57-12.05c57.96-4.64,110.15,35.02,121.21,92.1l28.73,148.29c16.65,85.96,119.87,121.96,186.37,65.01l114.72-98.25c44.17-37.82,109.7-36.42,152.2,3.26l110.4,103.08c64,59.75,168.66,28.21,188.99-56.95l35.07-146.92c13.5-56.56,67.34-93.94,125.05-86.82l149.9,18.5c86.89,10.72,153.03-76.31,119.42-157.16l-57.99-139.48c-22.32-53.69-.73-115.58,50.14-143.74l140.79-77.93c.61-.33,1.21-.67,1.8-1.02,31.8-18.36,44.19-49.65,41.44-79.72,2.42-22.36-6.21-45.75-29.16-60.2Z"
              />
              <path
                className="seal-r"
                fillRule="evenodd"
                d="M915.75,1195.19c4.65.25,9.34.57,14.09.7,180.57,4.81,361.28-126.11,403.64-292.43,42.36-166.32-69.69-323.8-250.26-328.61-60.73-1.62-124.87,22.33-177.52,54.92-12.49,7.73-28.44-1.73-27.15-16.37.03-.31.05-.61.08-.92.9-10.19-7.03-18.98-17.27-18.98h-187.42c-3.01,0-5.51,2.32-5.73,5.33-3.46,46.93-27.1,395.19,9.77,700.72,7.24,59.98,58.55,104.88,118.96,104.88h123.28c3.55,0,6.27-3.07,5.69-6.57-1.81-10.9-5.72-34.52-10.67-64.49-.88-5.33,5.3-8.96,9.37-5.4,43.04,37.71,196.54,152,393.92,65.79,2.12-.93,3.54-3.07,3.54-5.39v-254.14c0-9.38-10.05-15.37-18.26-10.83-57.94,32.1-242.52,124.87-389.33,93.98-18.62-3.92-17.49-23.19,1.25-22.2ZM876.68,978.38c26.29-62.04,108.33-118.54,183.26-126.2,74.92-7.66,114.35,36.41,88.07,98.45-26.29,62.04-108.33,118.54-183.26,126.2-74.92,7.66-114.35-36.41-88.07-98.45Z"
              />
            </svg>
            {!collapsed && (
              <div className="min-w-0">
                <div className="font-display text-base leading-tight text-ink truncate">Rambla</div>
                <div className="t-eyebrow">Back-office</div>
              </div>
            )}
          </Link>
          {!collapsed && (
            <button
              type="button"
              onClick={toggleSidebar}
              className="mr-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              aria-label="Colapsar sidebar"
              title="Colapsar"
            >
              <PanelLeft className="h-4 w-4" />
            </button>
          )}
        </div>
      </SidebarHeader>

      <SidebarContent>
        {/* Buscador global ⌘F — despacha el evento que abre el command palette. */}
        <SidebarGroup className="pb-0">
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  onClick={() => window.dispatchEvent(new Event("admin:cmdk"))}
                  tooltip={collapsed ? "Buscar (⌘F)" : undefined}
                >
                  <Search className="h-4 w-4 shrink-0" />
                  {!collapsed && (
                    <>
                      <span className="text-muted-foreground">Buscar…</span>
                      <kbd className="ml-auto rounded border hairline px-1.5 py-0.5 font-mono text-2xs text-muted-foreground">
                        ⌘F
                      </kbd>
                    </>
                  )}
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {collapsed
          ? // Modo icon-rail: todo plano como iconos, sin labels de grupo.
            ADMIN_NAV.map((g) => (
              <SidebarGroup key={g.id} className="py-0">
                <SidebarGroupContent>
                  <SidebarMenu>
                    {g.items.map((it) => (
                      <SidebarMenuItem key={it.url}>
                        <SidebarMenuButton
                          asChild
                          isActive={isActive(it.url, it.exact)}
                          tooltip={it.title}
                        >
                          <Link to={it.url}>
                            <it.icon className="h-4 w-4 shrink-0" />
                          </Link>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    ))}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            ))
          : // Modo expandido: grupos por dominio, label colapsable.
            ADMIN_NAV.map((g) => {
              const isOpen = openGroups[g.id] ?? g.defaultOpen;
              return (
                <SidebarGroup key={g.id}>
                  <SidebarGroupLabel asChild>
                    <button
                      type="button"
                      onClick={() => toggleGroup(g.id)}
                      className="flex w-full items-center font-mono text-2xs uppercase tracking-[0.2em]"
                      aria-expanded={isOpen}
                    >
                      <span>{g.label}</span>
                      <ChevronRight
                        className={`ml-auto h-3 w-3 transition-transform ${isOpen ? "rotate-90" : ""}`}
                      />
                    </button>
                  </SidebarGroupLabel>
                  {isOpen && (
                    <SidebarGroupContent>
                      <SidebarMenu>
                        {g.items.map((it) => (
                          <SidebarMenuItem key={it.url}>
                            <SidebarMenuButton asChild isActive={isActive(it.url, it.exact)}>
                              <Link
                                to={it.url}
                                className="flex items-center gap-2 min-h-11 md:min-h-0"
                              >
                                <it.icon className="h-4 w-4 shrink-0" />
                                <span>{it.title}</span>
                              </Link>
                            </SidebarMenuButton>
                          </SidebarMenuItem>
                        ))}
                      </SidebarMenu>
                    </SidebarGroupContent>
                  )}
                </SidebarGroup>
              );
            })}
      </SidebarContent>

      <SidebarFooter className="border-t hairline">
        {!collapsed && email && (
          <div className="px-2 py-1.5 min-w-0">
            <div className="t-eyebrow">Sesión</div>
            <div className="text-xs text-ink truncate" title={email}>
              {email}
            </div>
          </div>
        )}
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={currentPath === "/admin/cuenta"}
              tooltip={collapsed ? "Mi cuenta" : undefined}
            >
              <Link to="/admin/cuenta" className="flex items-center gap-2 min-h-11 md:min-h-0">
                <UserCog className="h-4 w-4 shrink-0" />
                {!collapsed && <span>Mi cuenta</span>}
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={handleSignOut}
              disabled={isSigningOut}
              tooltip={collapsed ? "Cerrar sesión" : undefined}
            >
              <LogOut className="h-4 w-4 shrink-0" />
              {!collapsed && <span>{isSigningOut ? "Cerrando…" : "Cerrar sesión"}</span>}
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
