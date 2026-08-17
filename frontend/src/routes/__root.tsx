import { HeadContent, Outlet, createRootRouteWithContext } from "@tanstack/react-router";
import { QueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Toaster } from "@/design-system/ui/sonner";
import { PublicLayout } from "@/components/rental/shell/PublicLayout";
import { FaviconSync } from "@/components/rental/shell/FaviconSync";
import { useCartHeartbeat } from "@/hooks/useCartHeartbeat";
import { SITE_URL } from "@/lib/site";
import { Component, type ReactNode } from "react";

// Los nombres de archivo de los chunks llevan hash de build — tras un deploy,
// una pestaña que quedó abierta desde antes intenta traer un chunk que ya no
// existe. Se arregla solo con un reload (trae el manifest nuevo); no es un bug
// de la app. El guard en sessionStorage evita un loop si el reload no alcanza.
const CHUNK_ERROR_PATTERN =
  /Failed to fetch dynamically imported module|Importing a module script failed/;
const CHUNK_RELOAD_GUARD_KEY = "rambla:chunk-reload-attempted";

class RootErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error) {
    if (
      CHUNK_ERROR_PATTERN.test(error.message) &&
      !sessionStorage.getItem(CHUNK_RELOAD_GUARD_KEY)
    ) {
      sessionStorage.setItem(CHUNK_RELOAD_GUARD_KEY, "1");
      window.location.reload();
    }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-background px-4">
          <div className="max-w-md text-center space-y-4">
            <h1 className="text-2xl font-bold text-foreground">Algo salió mal</h1>
            <pre className="text-xs text-destructive bg-muted p-4 rounded text-left overflow-auto max-h-40">
              {(this.state.error as Error).message}
            </pre>
            <button
              onClick={() => window.location.reload()}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
            >
              Recargar
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function NotFoundComponent() {
  return (
    <PublicLayout>
      <div className="flex items-center justify-center px-4 py-24 min-h-[60vh]">
        <div className="max-w-md text-center">
          <h1 className="font-display text-7xl text-ink">404</h1>
          <h2 className="mt-4 font-display text-xl text-ink">Página no encontrada</h2>
          <div className="mt-6">
            <Link
              to="/rental"
              className="inline-flex items-center justify-center rounded-full bg-foreground px-5 py-2.5 text-sm font-semibold text-background transition hover:bg-amber hover:text-ink"
            >
              Volver al catálogo
            </Link>
          </div>
        </div>
      </div>
    </PublicLayout>
  );
}

function CartSync() {
  useCartHeartbeat();
  return null;
}

const SITE_TITLE = "Rambla — Rental, estudio y workshops audiovisuales";
const SITE_DESC_OG =
  "Alquiler de equipos audiovisuales, estudio de foto y video, y workshops de producción en Mar del Plata.";
const SITE_DESC_TWITTER =
  "Alquiler de equipos, estudio y workshops audiovisuales en Mar del Plata.";

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  // Default de sitio para title/OG/twitter/theme-color — mismo copy que el
  // fallback estático de index.html (main.tsx lo barre antes de montar, ver
  // su comentario). Una ruta/layout que declara su propia clave la pisa acá
  // mismo (TanStack mergea head() por toda la jerarquía y dedupea por key —
  // ya probado con el título de la ficha de un taller pisando al de la
  // lista). `og:image`/`twitter:image`/`og:site_name` NO van acá a propósito:
  // ninguna ruta cliente los declara, así que la imagen dinámica que el
  // backend inyecta server-side (foto del equipo/taller) sigue siendo la
  // única fuente — agregarlos acá los pisaría con la genérica.
  head: () => ({
    meta: [
      { title: SITE_TITLE },
      { property: "og:type", content: "website" },
      { property: "og:url", content: `${SITE_URL}/` },
      { property: "og:title", content: SITE_TITLE },
      { property: "og:description", content: SITE_DESC_OG },
      { property: "og:locale", content: "es_AR" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "twitter:title", content: SITE_TITLE },
      { name: "twitter:description", content: SITE_DESC_TWITTER },
      { name: "theme-color", content: "#fbbf24" },
    ],
  }),
  component: () => (
    <>
      <HeadContent />
      <RootErrorBoundary>
        <FaviconSync />
        <CartSync />
        <Outlet />
        <Toaster richColors position="top-right" />
      </RootErrorBoundary>
    </>
  ),
  notFoundComponent: NotFoundComponent,
});
