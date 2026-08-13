import "./styles.css";
import { RouterProvider } from "@tanstack/react-router";
import { QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "framer-motion";
import ReactDOM from "react-dom/client";
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";
import { initGA, trackPageView, initWebVitals } from "./lib/analytics";
import { apiGetAnalyticsConfig, type BackendEquipo } from "./lib/api";
import { backendToEquipment } from "./hooks/useEquipos";
import { queryClient } from "./lib/queryClient";

// Sentry diferido: se carga tras la primera interacción del usuario, no en el
// bundle inicial. Sentry no envuelve el router, por lo que diferirlo es seguro
// (solo pierde errores que ocurren antes del primer click/tecla, un caso raro
// y preferible al costo de parsear ~100KB extra en el critical path).
const SENTRY_DSN = import.meta.env.VITE_SENTRY_DSN as string | undefined;
if (SENTRY_DSN) {
  const initSentry = () => {
    window.removeEventListener("pointerdown", initSentry);
    window.removeEventListener("keydown", initSentry);
    import("@sentry/react").then(({ init, browserTracingIntegration }) => {
      init({
        dsn: SENTRY_DSN,
        environment: import.meta.env.MODE,
        integrations: [browserTracingIntegration()],
        tracesSampleRate: 0.1,
        sendDefaultPii: false,
      });
    });
  };
  window.addEventListener("pointerdown", initSentry, { once: true });
  window.addEventListener("keydown", initSentry, { once: true });
}

// Hydrate React Query desde el catálogo inlineado por el backend en /rental.
// El handler Python inyecta <script id="__INITIAL__" type="application/json">
// con {equipos, categorias} → primer render sin round-trip a Miami.
// Mismo queryKey que useEquipos/useCategorias → RQ usa este dato y lo revalida
// con staleTime normal (30s). Si el elemento no existe o el parse falla, RQ
// fetchea normalmente (sin degradación).
try {
  const el = document.getElementById("__INITIAL__");
  if (el?.textContent) {
    const seed = JSON.parse(el.textContent) as {
      equipos?: { total: number; items: BackendEquipo[] };
      categorias?: unknown[];
      estudio?: unknown;
    };
    if (Array.isArray(seed.equipos?.items)) {
      const items = seed.equipos.items.map(backendToEquipment);
      queryClient.setQueryData(["equipos", undefined, undefined], {
        items,
        usingFallback: false,
      });
    }
    if (Array.isArray(seed.categorias)) {
      queryClient.setQueryData(["categorias"], seed.categorias);
    }
    if (seed.estudio) {
      queryClient.setQueryData(["estudio-fotos"], seed.estudio);
    }
  }
} catch {
  // no-op: React Query fetchea normalmente
}

const router = createRouter({
  routeTree,
  context: { queryClient },
  // Restaurar posición de scroll al hacer back/forward.
  // Crítico para el flujo: catálogo → /equipo/X → back → mismo scroll.
  // Sin esto, back vuelve al top — UX horrible en mobile listando muchos
  // equipos. Default scroll-to-top en navegaciones forward.
  scrollRestoration: true,
  // Precarga los datos + chunks de la ruta en hover/intent → navegaciones
  // percibidas como casi instantáneas (catálogo → ficha, etc.).
  defaultPreload: "intent",
});

// Google Analytics 4.
// El Measurement ID se administra desde el back-office (/admin/settings → Google
// Analytics) y el backend solo lo expone en producción (staging/local devuelven
// null → no contaminan las métricas de prod). VITE_GA4_ID es un override opcional
// de ops: si está seteada gana, y fuerza una propiedad GA en cualquier ambiente.
// Cobertura: solo catálogo público. Salteamos /admin (interno/noindex) y /cliente
// (área privada). El pageview SPA se manda en cada navegación resuelta.
function startAnalytics(measurementId: string) {
  initGA(measurementId);
  initWebVitals(); // RUM: LCP/CLS/INP/FCP/TTFB → GA4 evento "web_vitals"
  const sendPageView = () => {
    const path = router.state.location.pathname;
    if (path.startsWith("/admin") || path.startsWith("/cliente")) return;
    trackPageView(path);
  };
  sendPageView(); // pageview inicial (el fetch async puede resolver post-carga)
  router.subscribe("onResolved", sendPageView);
}

const GA4_OVERRIDE = import.meta.env.VITE_GA4_ID as string | undefined;
if (GA4_OVERRIDE) {
  startAnalytics(GA4_OVERRIDE);
} else {
  apiGetAnalyticsConfig()
    .then((cfg) => {
      if (cfg.ga4_id) startAnalytics(cfg.ga4_id);
    })
    .catch(() => {
      /* sin analítica si el endpoint no responde — no rompe el catálogo */
    });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

// Barre el title/OG/twitter/theme-color estáticos de index.html (o los que
// el backend inyectó server-side para /, /rental, /estudio, /escuelas/{slug})
// ANTES de montar React: TanStack Router los AGREGA vía head() de cada ruta,
// no los REEMPLAZA (React 19 dedupea title/meta solo entre lo que ÉL mismo
// renderiza, no contra HTML que ya estaba en el documento al cargar) — sin
// esto, quedaban DOS de cada uno en vivo (uno viejo/genérico, uno de la
// ruta), y cualquier lector que no haga "el último gana" (la mayoría de los
// parsers) se quedaba con el genérico. `__root.tsx` repone el default
// universal por head() para title/og:type/url/title/description/locale/
// twitter:card/title/description/theme-color — así ninguna ruta queda sin
// nada de eso.
// `og:image`/`twitter:image`/`og:site_name` se BARREN acá (varias rutas
// —rental/estudio/equipo/categoria/preguntas-frecuentes— sí declaran los
// suyos, mismo bug) pero NO llevan default en __root.tsx a propósito: el
// home (`/`) resuelve su og:image en el BACKEND desde `app_settings.
// og_image_url` (configurable en /admin/settings) SIN equivalente client-
// side — ponerle acá un default fijo pisaría ese valor dinámico para
// cualquier lector que ejecute JS. Mismo criterio que canonical/description
// (2026-08-13): una ruta sin su propia declaración se queda sin el tag, no
// con uno potencialmente incorrecto.
//
// `script[data-ssr-jsonld]` — mismo problema, para el JSON-LD que el backend
// inyecta server-side (equipo/escuelas/categoria — ver `_inject_json_ld` en
// backend/main.py): la ruta cliente vuelve a declarar el mismo Product/
// Course/CollectionPage vía head(), así que sin barrer el server-injectado
// quedan dos scripts iguales post-hidratación. El atributo distingue estos
// de los ESTÁTICOS (WebSite/LocalBusiness en index.html, sin equivalente
// client-side) — esos NO se tocan.
document.head
  .querySelectorAll(
    [
      "title",
      'meta[property="og:type"]',
      'meta[property="og:url"]',
      'meta[property="og:title"]',
      'meta[property="og:description"]',
      'meta[property="og:locale"]',
      'meta[property="og:image"]',
      'meta[property="og:site_name"]',
      'meta[name="twitter:card"]',
      'meta[name="twitter:title"]',
      'meta[name="twitter:description"]',
      'meta[name="twitter:image"]',
      'meta[name="theme-color"]',
      "script[data-ssr-jsonld]",
    ].join(", "),
  )
  .forEach((el) => el.remove());

ReactDOM.createRoot(document.getElementById("root")!).render(
  <MotionConfig reducedMotion="user">
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </MotionConfig>,
);
