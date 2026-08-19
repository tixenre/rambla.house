import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Eye, EyeOff, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { talleresAdminApi } from "@/lib/admin/api/talleres";
import type { EdicionAdmin, TallerConcepto } from "@/lib/admin/api/types";
import { hoyAR } from "@/lib/rental-dates";
import { Pill, type PillTone } from "@/design-system/ui/Pill";
import { Spinner } from "@/design-system/ui/spinner";
import { Switch } from "@/design-system/ui/switch";
import { useConfirm } from "@/components/admin/useConfirm";
import { useScrollFadeMask } from "@/hooks/useScrollFadeMask";
import { CuposPill } from "./CuposPill";
import {
  ClasesSection,
  PagosSection,
  PedidosGeneradosSection,
  PreciosSection,
} from "./EdicionTabs";
import { GaleriaEdicionSection } from "./GaleriaEdicionSection";
import { InscripcionesSection } from "./InscripcionesSection";
import { updateEdicionInCache } from "./cache";

function badgeEstadoEdicion(edicion: EdicionAdmin): { label: string; tone: PillTone } {
  const today = hoyAR();
  // F2: una edición despublicada es un BORRADOR — se arma sin estar en la web
  // (preview vía "ver en web" con sesión admin) y no bloquea el estudio.
  if (!edicion.activo) return { label: "BORRADOR", tone: "warning" };
  if (edicion.frozen_at) return { label: "CONGELADA", tone: "neutral" };
  if (edicion.fecha_inicio > today) return { label: "PRÓXIMAMENTE", tone: "warning" };
  if (edicion.fecha_fin >= today) return { label: "EN CURSO", tone: "success" };
  return { label: "FINALIZADA", tone: "neutral" };
}

function fmtDay(iso: string) {
  return new Date(iso + "T12:00:00").toLocaleDateString("es-AR", {
    day: "numeric",
    month: "short",
  });
}

export function EdicionSubRow({
  edicion,
  concepto,
  onDelete,
}: {
  edicion: EdicionAdmin;
  concepto: TallerConcepto;
  onDelete: (edicionId: number) => void;
}) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const badge = badgeEstadoEdicion(edicion);
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState<"clases" | "precios" | "galeria" | "inscripciones">(
    "clases",
  );
  // Mismo caso que el tab-strip del concepto (TallerConceptoRow): en mobile
  // "Inscripciones (N)" puede quedar cortado sin que nada avise que hay que
  // scrollear.
  const tabsScroll = useScrollFadeMask(expanded);

  const { data: inscripciones = [], isLoading: loadingIns } = useQuery({
    queryKey: ["admin", "ediciones", edicion.id, "inscripciones"],
    queryFn: () => talleresAdminApi.listInscripciones(edicion.id),
    enabled: expanded && activeTab === "inscripciones",
    staleTime: 0,
  });

  const { data: borradores } = useQuery({
    queryKey: ["admin", "ediciones", edicion.id, "borradores"],
    queryFn: () => talleresAdminApi.listBorradores(edicion.id),
    enabled: expanded && activeTab === "inscripciones",
    staleTime: 0,
    // No confirmado por el dueño como algo a refrescar en vivo todavía — se
    // ve fresco al abrir la pestaña, sin agregar un poll de fondo nuevo.
  });

  const toggleActivoMut = useMutation({
    mutationFn: (activo: boolean) => talleresAdminApi.updateEdicion(edicion.id, { activo }),
    onSuccess: (updated) => {
      toast.success(updated.activo ? "Edición publicada" : "Edición pasada a borrador");
      updateEdicionInCache(qc, updated);
    },
    // Publicar re-verifica la disponibilidad del estudio: si un borrador quedó
    // pisado por una reserva nueva, el backend responde 409 con el detalle.
    onError: (e) => toast.error((e as Error).message, { duration: 8000 }),
  });

  const deleteMut = useMutation({
    mutationFn: () => talleresAdminApi.deleteEdicion(edicion.id),
    onSuccess: () => {
      toast.success("Edición eliminada");
      onDelete(edicion.id);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  async function handleToggleActivo(v: boolean) {
    if (!v && edicion.cupos_confirmados > 0) {
      const ok = await confirm({
        title: `¿Desactivar la edición #${edicion.numero_edicion}?`,
        description: `Hay ${edicion.cupos_confirmados} inscriptos confirmados.`,
        danger: true,
        confirmLabel: "Desactivar",
      });
      if (!ok) return;
    }
    toggleActivoMut.mutate(v);
  }

  async function handleDelete() {
    if (edicion.cupos_confirmados > 0) {
      toast.error(`No se puede eliminar: hay ${edicion.cupos_confirmados} inscriptos confirmados`);
      return;
    }
    if (
      !(await confirm({
        title: `¿Eliminar la edición #${edicion.numero_edicion}?`,
        description: `Se eliminará la edición de "${concepto.nombre}".`,
        danger: true,
        confirmLabel: "Eliminar",
      }))
    )
      return;
    deleteMut.mutate();
  }

  return (
    <div
      className={`rounded-lg border transition-colors ${
        expanded ? "border-ink/20 bg-surface" : "border-border/50"
      }`}
    >
      {/* Edition header */}
      <div
        className="flex items-center gap-2.5 px-3 py-2.5 cursor-pointer select-none"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="shrink-0 text-xs font-mono font-semibold text-muted-foreground">
          #{edicion.numero_edicion}
        </span>
        <Pill tone={badge.tone} className="font-mono uppercase tracking-wider">
          {badge.label}
        </Pill>

        {/* Date range */}
        {edicion.fecha_inicio && (
          <span className="flex-1 min-w-0 text-xs text-muted-foreground truncate">
            {fmtDay(edicion.fecha_inicio)}
            {edicion.fecha_fin && edicion.fecha_fin !== edicion.fecha_inicio && (
              <> – {fmtDay(edicion.fecha_fin)}</>
            )}
          </span>
        )}

        <CuposPill confirmados={edicion.cupos_confirmados} total={edicion.cupos_total} />

        <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
          {edicion.activo ? (
            <Eye className="h-3 w-3 text-muted-foreground" />
          ) : (
            <EyeOff className="h-3 w-3 text-muted-foreground/40" />
          )}
          <Switch
            checked={edicion.activo}
            onCheckedChange={handleToggleActivo}
            disabled={toggleActivoMut.isPending}
            aria-label={edicion.activo ? "Pasar a borrador" : "Publicar edición"}
          />
          <a
            href={`/escuelas/${edicion.slug}`}
            target="_blank"
            rel="noopener noreferrer"
            className="p-1 rounded text-muted-foreground hover:text-ink transition"
            title="Ver en web"
            aria-label="Ver edición en web"
          >
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>

        <svg
          className={`h-3.5 w-3.5 text-muted-foreground/60 shrink-0 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>

      {/* Edition detail */}
      {expanded && (
        <div className="border-t border-border/40">
          <div
            ref={tabsScroll.ref}
            onScroll={tabsScroll.onScroll}
            className="flex border-b border-border/50 overflow-x-auto"
            style={tabsScroll.style}
          >
            {(
              [
                { id: "clases", label: "Fechas y clases" },
                { id: "precios", label: "Precios y pago" },
                { id: "galeria", label: "Portada y galería" },
                {
                  id: "inscripciones",
                  label: `Inscripciones${edicion.cupos_confirmados > 0 ? ` (${edicion.cupos_confirmados})` : ""}`,
                },
              ] as { id: "clases" | "precios" | "galeria" | "inscripciones"; label: string }[]
            ).map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`shrink-0 px-3 py-2 text-sm border-b-2 -mb-[1px] transition-colors ${
                  activeTab === tab.id
                    ? "border-ink text-ink font-medium"
                    : "border-transparent text-muted-foreground hover:text-ink"
                }`}
              >
                {tab.label}
              </button>
            ))}
            <div className="flex-1" />
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleDelete();
              }}
              disabled={deleteMut.isPending}
              className="px-3 py-2 text-xs text-muted-foreground/60 hover:text-destructive transition shrink-0"
              title="Eliminar edición"
            >
              {deleteMut.isPending ? <Spinner size="xs" /> : <Trash2 className="h-3.5 w-3.5" />}
            </button>
          </div>

          <div className="px-4 pb-5 pt-4">
            {activeTab === "clases" && <ClasesSection edicion={edicion} />}
            {activeTab === "precios" && (
              <div className="flex flex-col gap-0">
                <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground mb-3">
                  Precio y forma de pago
                </p>
                <PreciosSection edicion={edicion} />
                <div className="border-t border-border/40 mt-6 pt-6">
                  <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground mb-3">
                    Datos de pago
                  </p>
                  <PagosSection edicion={edicion} />
                </div>
                <div className="border-t border-border/40 mt-6 pt-6">
                  <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground mb-3">
                    Pedidos generados
                  </p>
                  <PedidosGeneradosSection edicion={edicion} />
                </div>
              </div>
            )}
            {activeTab === "galeria" && (
              <GaleriaEdicionSection
                edicionId={edicion.id}
                fotos={edicion.fotos}
                instituciones={concepto.instituciones}
                onChanged={() => qc.invalidateQueries({ queryKey: ["admin", "talleres"] })}
              />
            )}
            {activeTab === "inscripciones" && (
              <InscripcionesSection
                edicion={edicion}
                concepto={concepto}
                inscripciones={inscripciones}
                loading={loadingIns}
                borradores={borradores}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
