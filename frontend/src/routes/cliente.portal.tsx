/**
 * cliente.portal.tsx — Portal del cliente.
 *
 * Layout: sidebar 220px en desktop + bottom-nav en mobile, con 3 tabs:
 * Pedidos · Notificaciones · Perfil. El perfil vive como tab (PerfilSection),
 * no como drawer lateral. Notificaciones es un empty-state hasta que exista el
 * endpoint (ver TODO en NotificacionesSection).
 *
 * Toda la lógica de pedidos (fetch, filtros, cancelaciones, documentos,
 * timeline) se preserva en los componentes PedidoCard, DocActions,
 * DocPreviewModal, DocAvailablePopup, PedidoTimeline, buildTimelineSteps.
 */

import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { useEquipos } from "@/hooks/useEquipos";
import { useFavoritos } from "@/hooks/useFavoritos";
import { EquipmentCard } from "@/components/rental/EquipmentCard";
import { authedFetch } from "@/lib/authedFetch";
import { TopBar } from "@/components/rental/shell/TopBar";
import { StatCard } from "@/design-system/composites/StatCard";
import {
  ArrowRight,
  ShieldAlert,
  Search,
  X as XIcon,
  LogOut,
  Bell,
  User,
  Package,
  ClipboardList,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { nombreCliente } from "@/lib/cliente-nombre";
import { esPathInternoSeguro, recheckVerificacionIdentidad } from "@/lib/verificacion";
import {
  fmt,
  fmtDate,
  wasDocSeen,
  markDocSeen,
  docSeenInitialized,
  markDocSeenInitialized,
  ACTIVE_STATES,
  HIST_STATES,
  DOC_NOTIFICABLE,
  TAB_OPTIONS,
} from "@/components/cliente/ClientePortalTypes";
import type {
  Perfil,
  Pedido,
  PortalTab,
  DocTipo,
  Filtro,
} from "@/components/cliente/ClientePortalTypes";
import { SidebarNavItem, BottomNavItem } from "@/components/cliente/nav";
import { NotificacionesSection } from "@/components/cliente/NotificacionesSection";
import { PerfilSection } from "@/components/cliente/PerfilSection";
import {
  PedidoEmpty,
  PedidoCard,
  DocAvailablePopup,
} from "@/components/cliente/ClientePortalPedido";
import { ListasSection } from "@/components/cliente/ClientePortalListas";
import { useListas } from "@/hooks/useListas";

export const Route = createFileRoute("/cliente/portal")({
  head: () => ({ meta: [{ title: "Mis pedidos — Rambla Rental" }] }),
  validateSearch: (
    search: Record<string, unknown>,
  ): {
    nuevo?: number;
    verificacion?: "pendiente";
    return_to?: string;
    tab?: PortalTab;
    keys?: string;
  } => {
    const out: {
      nuevo?: number;
      verificacion?: "pendiente";
      return_to?: string;
      tab?: PortalTab;
      keys?: string;
    } = {};
    const n = Number(search.nuevo);
    if (Number.isFinite(n) && n > 0) out.nuevo = n;
    // Retorno del flujo Didit: el usuario vuelve con ?verificacion=pendiente.
    if (search.verificacion === "pendiente") out.verificacion = "pendiente";
    // Path interno a donde volver tras verificar (carrito/estudio). Validado
    // contra la allowlist anti open-redirect (espejo del backend).
    if (typeof search.return_to === "string" && esPathInternoSeguro(search.return_to))
      out.return_to = search.return_to;
    // Tab inicial (deep-link: menú "Mi perfil", retorno del linking de Google).
    if (
      search.tab === "pedidos" ||
      search.tab === "listas" ||
      search.tab === "notificaciones" ||
      search.tab === "perfil"
    )
      out.tab = search.tab;
    // Resultado del linking de Google (?keys=...): passthrough para que AccessMethods
    // (en el tab Perfil) lo lea y lo limpie — el validateSearch no lo debe descartar.
    if (typeof search.keys === "string") out.keys = search.keys;
    return out;
  },
  component: ClientePortal,
});

export default function ClientePortal() {
  const navigate = useNavigate();
  const { nuevo, verificacion, return_to, tab: initialTab } = Route.useSearch();
  const fav = useFavoritos();
  const { data: allEquipos = [] } = useEquipos();
  const favEquipos = useMemo(
    () => allEquipos.filter((e) => fav.has(String(e.id))),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- depende de fav.items (los datos), no de fav.has (método recreado por render)
    [allEquipos, fav.items],
  );
  // Listas / kits personales (#1092). El hook se iza acá (no dentro de
  // ListasSection) para que el badge del sidebar/bottom-nav y la vista compartan
  // una sola instancia de estado: las mutaciones se reflejan en ambos a la vez.
  const {
    listas,
    loading: listasLoading,
    renombrar: renombrarLista,
    quitarItem: quitarItemLista,
    borrar: borrarLista,
  } = useListas();

  // Estado del portal
  const [activeTab, setActiveTab] = useState<PortalTab>(initialTab ?? "pedidos");
  const [perfil, setPerfil] = useState<Perfil | null>(null);
  const [pedidos, setPedidos] = useState<Pedido[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const nuevoHandledRef = useRef(false);
  // Verificación Didit: true mientras esperamos que llegue el webhook (asíncrono)
  // después de que el usuario vuelve del flujo con ?verificacion=pendiente.
  const [confirmandoVerif, setConfirmandoVerif] = useState(false);
  const verifHandledRef = useRef(false);
  const [tab, setTab] = useState<Filtro>("todos");
  const [query, setQuery] = useState<string>("");
  const [docsNuevos, setDocsNuevos] = useState<
    Array<{ pedidoId: number; numero: string; tipo: DocTipo }>
  >([]);

  useEffect(() => {
    let alive = true;
    Promise.all([authedFetch("/api/cliente/me"), authedFetch("/api/cliente/pedidos")])
      .then(async ([rp, ro]) => {
        if (!alive) return;
        if (!rp.ok || !ro.ok) {
          navigate({ to: "/cliente/login" });
          return;
        }
        setPerfil(await rp.json());
        setPedidos(await ro.json());
      })
      .catch(() => navigate({ to: "/cliente/login" }))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [navigate]);

  // Retorno del flujo Didit (?verificacion=pendiente): el usuario terminó el
  // DNI+selfie y volvió, pero el webhook que confirma la identidad es asíncrono
  // y puede tardar unos segundos. Aterrizamos en el tab Identidad y consultamos
  // /api/cliente/me hasta ver dni_validado_at (o agotar los intentos). Se corre
  // una sola vez por retorno (guard por ref) y limpia el query param al terminar.
  useEffect(() => {
    if (verificacion !== "pendiente" || verifHandledRef.current) return;
    verifHandledRef.current = true;
    setActiveTab("perfil");
    setConfirmandoVerif(true);

    let alive = true;
    let intentos = 0;
    const MAX_INTENTOS = 8; // ~24s (cada 3s)

    // Self-recheck contra Didit en paralelo al polling pasivo: si el webhook se
    // perdió (falla de origen conocida), esto resuelve el estado sin esperar a
    // que un admin lo note. Best-effort — si falla, seguimos poll-eando
    // /api/cliente/me igual (el webhook puede llegar solo).
    void recheckVerificacionIdentidad();

    const limpiar = (verificado: boolean) => {
      if (!alive) return;
      setConfirmandoVerif(false);
      // Si verificó y vino con un return_to (carrito/estudio), lo devolvemos
      // ahí (full-nav). El timeout (limpiar(false)) no lo usa: queda en el portal.
      if (verificado && return_to) {
        window.location.assign(return_to);
        return;
      }
      if (verificado) toast.success("¡Identidad verificada!");
      navigate({ to: "/cliente/portal", search: {}, replace: true });
    };

    const tick = async () => {
      if (!alive) return;
      try {
        const r = await authedFetch("/api/cliente/me");
        if (r.ok) {
          const p: Perfil = await r.json();
          if (alive) setPerfil(p);
          if (p.dni_validado_at) {
            limpiar(true);
            return;
          }
          // "rechazado" es un estado terminal (Didit ya decidió) — no tiene sentido
          // seguir poll-eando los ~24s completos; el tab Identidad ya muestra el
          // motivo y el botón para reintentar (IdentidadSection).
          if (p.dni_verificacion_estado === "rechazado") {
            limpiar(false);
            return;
          }
        }
      } catch {
        /* reintentamos en el próximo tick */
      }
      intentos += 1;
      if (intentos >= MAX_INTENTOS) {
        limpiar(false);
        return;
      }
      timer = window.setTimeout(tick, 3000);
    };

    let timer = window.setTimeout(tick, 1500);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [verificacion, navigate, return_to]);

  useEffect(() => {
    if (pedidos.length === 0) return; // esperar a que carguen los pedidos
    // Primera carga en este device: marcar lo existente como visto (silencioso, sin
    // popup) para no listar decenas de docs históricos en un localStorage limpio.
    if (!docSeenInitialized()) {
      for (const p of pedidos) {
        const docs = p.documentos_disponibles;
        if (!docs) continue;
        for (const tipo of DOC_NOTIFICABLE) if (docs[tipo]) markDocSeen(p.id, tipo);
      }
      markDocSeenInitialized();
      return;
    }
    // Cargas siguientes: solo los docs que aparecieron desde la última visita.
    const nuevos: Array<{ pedidoId: number; numero: string; tipo: DocTipo }> = [];
    for (const p of pedidos) {
      const docs = p.documentos_disponibles;
      if (!docs) continue;
      for (const tipo of DOC_NOTIFICABLE) {
        if (docs[tipo] && !wasDocSeen(p.id, tipo))
          nuevos.push({ pedidoId: p.id, numero: String(p.numero_pedido ?? p.id), tipo });
      }
    }
    nuevos.sort((a, b) => b.pedidoId - a.pedidoId);
    setDocsNuevos(nuevos.slice(0, 5));
  }, [pedidos]);

  function dismissDocsPopup() {
    for (const d of docsNuevos) markDocSeen(d.pedidoId, d.tipo);
    setDocsNuevos([]);
  }

  function verPedido(pedidoId: number) {
    setActiveTab("pedidos");
    setExpanded(pedidoId);
    dismissDocsPopup();
    setTimeout(() => {
      const el = document.getElementById(`pedido-${pedidoId}`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 100);
  }

  useEffect(() => {
    if (loading || nuevo == null || nuevoHandledRef.current) return;
    if (!pedidos.some((p) => p.id === nuevo)) return;
    nuevoHandledRef.current = true;
    verPedido(nuevo);
    setHighlightId(nuevo);
    navigate({ to: "/cliente/portal", search: {}, replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- maneja ?nuevo= una sola vez (guard por ref); verPedido/setHighlightId quedan fuera a propósito
  }, [loading, nuevo, pedidos, navigate]);

  useEffect(() => {
    if (highlightId == null) return;
    const t = setTimeout(() => setHighlightId(null), 3500);
    return () => clearTimeout(t);
  }, [highlightId]);

  // Título del navegador según la solapa activa: el portal es un hub multi-tab, así
  // que entrar directo a ?tab=perfil ya no debe decir "Mis pedidos".
  useEffect(() => {
    const titulos: Record<PortalTab, string> = {
      pedidos: "Mis pedidos",
      listas: "Mis listas",
      notificaciones: "Notificaciones",
      perfil: "Mi perfil",
    };
    document.title = `${titulos[activeTab]} — Rambla Rental`;
  }, [activeTab]);

  async function handleLogout() {
    await authedFetch("/auth/logout", { method: "POST" }).catch(() => {});
    navigate({ to: "/cliente/login" });
  }

  const tabFiltered = useMemo(
    () =>
      tab === "activos"
        ? pedidos.filter((p) => ACTIVE_STATES.has(p.estado))
        : tab === "historial"
          ? pedidos.filter((p) => HIST_STATES.has(p.estado))
          : pedidos,
    [tab, pedidos],
  );

  const q = query.trim().toLowerCase();
  const filteredPedidos = useMemo(() => {
    if (!q) return tabFiltered;
    return tabFiltered.filter((p) => {
      if (
        String(p.numero_pedido ?? "")
          .toLowerCase()
          .includes(q)
      )
        return true;
      if (p.estado.toLowerCase().includes(q)) return true;
      if ((p.notas ?? "").toLowerCase().includes(q)) return true;
      if (
        p.items.some(
          (it) =>
            (it.nombre_publico ?? it.nombre).toLowerCase().includes(q) ||
            (it.marca ?? "").toLowerCase().includes(q) ||
            (it.modelo ?? "").toLowerCase().includes(q),
        )
      )
        return true;
      return false;
    });
  }, [tabFiltered, q]);

  const userName = perfil ? nombreCliente(perfil) : undefined;
  const activosPedidos = pedidos.filter((p) => ACTIVE_STATES.has(p.estado));
  const totalActivos = activosPedidos.reduce((sum, p) => sum + (p.monto_total ?? 0), 0);
  const pendientePago = activosPedidos.reduce(
    (sum, p) => sum + Math.max(0, (p.monto_total ?? 0) - (p.monto_pagado ?? 0)),
    0,
  );
  const historico = pedidos.filter((p) => HIST_STATES.has(p.estado)).length;
  const ahora = Date.now();
  const proximo = activosPedidos
    .flatMap((p) => {
      const ev: { ts: number; iso: string; tipo: string }[] = [];
      const d = p.fecha_desde ? new Date(p.fecha_desde).getTime() : NaN;
      const h = p.fecha_hasta ? new Date(p.fecha_hasta).getTime() : NaN;
      if (!Number.isNaN(d) && d >= ahora) ev.push({ ts: d, iso: p.fecha_desde!, tipo: "retiro" });
      if (!Number.isNaN(h) && h >= ahora)
        ev.push({ ts: h, iso: p.fecha_hasta!, tipo: "devolución" });
      return ev;
    })
    .sort((a, b) => a.ts - b.ts)[0];

  const counts: Record<Filtro, number> = {
    todos: pedidos.length,
    activos: activosPedidos.length,
    historial: historico,
  };

  if (loading) {
    return (
      <div className="min-h-dvh bg-background flex flex-col">
        <TopBar variant="cliente" />
        <div className="flex flex-1">
          <aside className="hidden md:block w-[220px] shrink-0 border-r hairline" />
          <main className="flex-1 px-5 lg:px-12 pt-8">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 mb-9">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-[88px] rounded-md border hairline bg-muted/30 animate-pulse"
                />
              ))}
            </div>
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-14 rounded-xl border hairline bg-muted/20 animate-pulse mb-2.5"
              />
            ))}
          </main>
        </div>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-dvh bg-background flex flex-col">
      {/* TopBar — logo + menú (perfil/salir viven en el menú) */}
      <TopBar variant="cliente" />

      <div className="flex flex-1 overflow-hidden">
        {/* ── Sidebar desktop ─────────────────────────────────────────── */}
        <nav
          className="hidden md:flex flex-col w-[220px] shrink-0 border-r hairline bg-background sticky top-16 h-[calc(100dvh-4rem)] overflow-y-auto py-4"
          aria-label="Navegación del portal"
        >
          {/* Saludo */}
          {perfil && (
            <div className="px-4 mb-5">
              <div className="font-mono text-2xs uppercase tracking-[0.22em] text-muted-foreground">
                Portal · cliente
              </div>
              <div className="font-sans text-sm font-semibold text-ink mt-0.5 truncate">
                {nombreCliente(perfil)}
              </div>
            </div>
          )}

          {/* Nav items */}
          <div className="flex flex-col gap-0.5 px-2">
            <SidebarNavItem
              icon={<Package className="h-4 w-4" />}
              label="Pedidos"
              count={pedidos.length}
              active={activeTab === "pedidos"}
              onClick={() => setActiveTab("pedidos")}
            />
            <SidebarNavItem
              icon={<ClipboardList className="h-4 w-4" />}
              label="Mis listas"
              count={listas.length}
              active={activeTab === "listas"}
              onClick={() => setActiveTab("listas")}
            />
            <SidebarNavItem
              icon={<Bell className="h-4 w-4" />}
              label="Notificaciones"
              active={activeTab === "notificaciones"}
              onClick={() => setActiveTab("notificaciones")}
            />
            <SidebarNavItem
              icon={<User className="h-4 w-4" />}
              label="Perfil"
              active={activeTab === "perfil"}
              onClick={() => setActiveTab("perfil")}
            />
          </div>

          {/* Logout al fondo */}
          <div className="mt-auto px-2 pt-4 border-t hairline mx-2">
            <button
              type="button"
              onClick={handleLogout}
              className="w-full flex items-center gap-2.5 rounded-md px-3 py-2.5 font-sans text-sm text-muted-foreground hover:text-destructive hover:bg-destructive/8 transition"
            >
              <LogOut className="h-4 w-4" />
              Cerrar sesión
            </button>
          </div>
        </nav>

        {/* ── Contenido principal ──────────────────────────────────────── */}
        <main className="flex-1 overflow-y-auto pb-24 md:pb-8">
          {/* TAB: PEDIDOS */}
          {activeTab === "pedidos" && (
            <div className="px-5 lg:px-10 pt-8">
              {/* Banner: identidad no verificada */}
              {perfil && !perfil.dni_validado_at && (
                <button
                  type="button"
                  onClick={() => setActiveTab("perfil")}
                  className="w-full mb-5 flex items-center gap-3 rounded-xl border border-amber bg-amber-soft px-4 py-3 text-left transition hover:bg-amber/20"
                >
                  <ShieldAlert className="h-5 w-5 text-amber shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="font-sans text-sm font-semibold text-ink">
                      Verificá tu identidad para hacer pedidos
                    </div>
                    <div className="font-sans text-xs text-muted-foreground">
                      Necesitás tu DNI + selfie. Tarda menos de 2 minutos.
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 text-muted-foreground shrink-0" />
                </button>
              )}

              {/* Stats */}
              {pedidos.length > 0 && (
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-2.5 mb-9">
                  <StatCard
                    label="Activos"
                    value={String(activosPedidos.length)}
                    meta={`${fmt(totalActivos)} en rentals`}
                  />
                  <StatCard
                    label="Próximo"
                    value={proximo ? fmtDate(proximo.iso) : "—"}
                    meta={proximo ? proximo.tipo : "sin fechas próximas"}
                  />
                  <StatCard
                    label="A pagar"
                    value={pendientePago > 0 ? fmt(pendientePago) : "$ 0"}
                    meta={pendientePago > 0 ? "saldo pendiente" : "todo al día"}
                    valueClassName={pendientePago === 0 ? "text-verde-ink" : undefined}
                  />
                  <StatCard
                    label="Histórico"
                    value={String(historico)}
                    meta="pedidos completados"
                  />
                </div>
              )}

              {/* Favoritos */}
              {favEquipos.length > 0 && (
                <section className="mb-8">
                  <h2 className="font-display text-22 font-black text-ink tracking-[-0.01em] mb-4">
                    Mis favoritos
                  </h2>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 lg:grid-cols-4">
                    {favEquipos.map((item, i) => (
                      <EquipmentCard key={item.id} item={item} index={i} />
                    ))}
                  </div>
                </section>
              )}

              {/* Header pedidos */}
              <div className="flex items-baseline justify-between gap-3 mb-4">
                <h2 className="font-display text-22 font-black text-ink tracking-[-0.01em]">
                  mis pedidos.
                </h2>
                {pedidos.length > 0 && (
                  <span className="font-mono text-2xs uppercase tracking-[0.22em] text-muted-foreground">
                    {pedidos.length} {pedidos.length === 1 ? "pedido" : "pedidos"}
                  </span>
                )}
              </div>

              {/* Search */}
              {pedidos.length > 0 && (
                <div className="mb-3 relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Buscar por número, equipo, marca…"
                    className="w-full rounded-full border hairline bg-surface px-9 py-2.5 font-sans text-sm text-ink outline-none transition placeholder:text-muted-foreground hover:border-ink/30 focus:border-ink focus:bg-card"
                  />
                  {query && (
                    <button
                      type="button"
                      onClick={() => setQuery("")}
                      className="absolute right-2 top-1/2 -translate-y-1/2 grid h-[22px] w-[22px] place-items-center rounded-full text-muted-foreground hover:bg-muted hover:text-ink before:absolute before:left-1/2 before:top-1/2 before:h-11 before:w-11 before:-translate-x-1/2 before:-translate-y-1/2 before:content-['']"
                      aria-label="Limpiar búsqueda"
                    >
                      <XIcon className="h-3 w-3" />
                    </button>
                  )}
                </div>
              )}

              {/* Filter chips */}
              {pedidos.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-4">
                  {TAB_OPTIONS.map(({ value, label }) => {
                    const active = tab === value;
                    return (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setTab(value)}
                        className={cn(
                          "hit-area-inline inline-flex items-center gap-1 rounded-full border px-3.5 py-1.5 font-sans text-xs font-semibold transition",
                          active
                            ? "bg-ink text-amber border-ink"
                            : "border-hairline text-muted-foreground hover:text-ink hover:border-ink",
                        )}
                      >
                        {label}
                        <span
                          className={cn(
                            "font-mono text-3xs tabular-nums",
                            active ? "opacity-85" : "opacity-60",
                          )}
                        >
                          {counts[value]}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Lista */}
              {pedidos.length === 0 ? (
                <PedidoEmpty
                  title="Sin pedidos aún"
                  sub="Todavía no tenés pedidos registrados."
                  cta
                />
              ) : filteredPedidos.length === 0 ? (
                q ? (
                  <PedidoEmpty
                    title="Nada coincide con tu búsqueda"
                    sub={`No encontramos pedidos para "${query}".`}
                    actionLabel="Limpiar búsqueda"
                    onAction={() => setQuery("")}
                    icon="search"
                  />
                ) : (
                  <PedidoEmpty
                    title={tab === "activos" ? "Sin rentals activos" : "Sin pedidos por acá"}
                    sub={
                      tab === "activos"
                        ? "No tenés rentals activos en este momento."
                        : "No tenés pedidos en esta sección."
                    }
                    cta
                  />
                )
              ) : (
                <div className="flex flex-col gap-2.5">
                  {filteredPedidos.map((p) => (
                    <PedidoCard
                      key={p.id}
                      pedido={p}
                      expanded={expanded === p.id}
                      highlight={highlightId === p.id}
                      onToggle={() => setExpanded(expanded === p.id ? null : p.id)}
                      perfilImpuestos={perfil?.perfil_impuestos ?? null}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* TAB: MIS LISTAS */}
          {activeTab === "listas" && (
            <ListasSection
              listas={listas}
              loading={listasLoading}
              allEquipos={allEquipos}
              onRename={renombrarLista}
              onRemoveItem={quitarItemLista}
              onDelete={borrarLista}
            />
          )}

          {/* TAB: NOTIFICACIONES */}
          {activeTab === "notificaciones" && <NotificacionesSection />}

          {/* TAB: PERFIL (incluye sección de identidad) */}
          {activeTab === "perfil" && perfil && (
            <PerfilSection
              perfil={perfil}
              onLogout={handleLogout}
              confirmandoVerif={confirmandoVerif}
              onPerfilChange={setPerfil}
            />
          )}
        </main>
      </div>

      {/* ── Bottom nav mobile ─────────────────────────────────────────── */}
      <nav
        className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t hairline bg-background/95 backdrop-blur-md"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
        aria-label="Navegación del portal"
      >
        <div className="grid grid-cols-4">
          <BottomNavItem
            icon={<Package className="h-5 w-5" />}
            label="Pedidos"
            active={activeTab === "pedidos"}
            onClick={() => setActiveTab("pedidos")}
          />
          <BottomNavItem
            icon={<ClipboardList className="h-5 w-5" />}
            label="Listas"
            active={activeTab === "listas"}
            onClick={() => setActiveTab("listas")}
          />
          <BottomNavItem
            icon={<Bell className="h-5 w-5" />}
            label="Alertas"
            active={activeTab === "notificaciones"}
            onClick={() => setActiveTab("notificaciones")}
          />
          <BottomNavItem
            icon={<User className="h-5 w-5" />}
            label="Perfil"
            active={activeTab === "perfil"}
            onClick={() => setActiveTab("perfil")}
          />
        </div>
      </nav>

      <DocAvailablePopup nuevos={docsNuevos} onDismiss={dismissDocsPopup} onVerPedido={verPedido} />
    </div>
  );
}
