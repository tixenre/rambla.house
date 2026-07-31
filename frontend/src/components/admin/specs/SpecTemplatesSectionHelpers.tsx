/**
 * Sub-components for SpecTemplatesSection — extracted to keep the main file lean.
 * All logic is verbatim from SpecTemplatesSection.tsx.
 */

import React, { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GripVertical, Pencil, Trash2, X } from "lucide-react";
import { ModalBackdrop } from "@/design-system/ui/modal-backdrop";
import { toast } from "sonner";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { Pill } from "@/design-system/ui/Pill";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";

import {
  adminApi,
  type RolCompatibilidad,
  type SpecDefinition,
  type SpecTemplate,
  type SpecTipo,
} from "@/lib/admin/api";

const TIPO_LABEL: Record<SpecTipo, string> = {
  string: "Texto",
  number: "Número",
  rango: "Rango (un valor o dos, separados por '-')",
  wxh: "Dos medidas (ancho × alto, ej. 6144×3240)",
  wxhxd: "Tres medidas (ancho × alto × prof, ej. 130×85×78)",
  multi_enum: "Lista de opciones (varios valores, ej. Wi-Fi, USB-C, SDI)",
  enum: "Opciones (enum)",
  bool: "Sí/No",
  tabla: "Tabla (filas con columnas configurables)",
};

/** Panel con specs huérfanas — valores cargados en equipos cuyo spec_key no
 *  está en el template de la categoría. El dueño decide si formalizarlos.
 *  Evita que el sistema auto-extienda el template silenciosamente. */
export function OrphansPanel({
  orphans,
  onConvert,
}: {
  orphans: { spec_key: string; count_equipos: number; sample_values: string[] }[];
  onConvert: (o: { spec_key: string; sample_values: string[] }) => void;
}) {
  return (
    <div className="rounded-md border hairline border-amber/30 bg-amber-soft/30 overflow-hidden">
      <header className="px-3 py-2 text-xs font-mono uppercase tracking-widest text-muted-foreground border-b hairline">
        Sugerencias del autocompletar — {orphans.length} {orphans.length === 1 ? "spec" : "specs"}{" "}
        cargadas en equipos que no están en el template
      </header>
      <ul className="divide-y hairline">
        {orphans.map((o) => (
          <li key={o.spec_key} className="flex items-center gap-3 px-3 py-2 text-sm">
            <div className="flex-1 min-w-0">
              <div className="font-mono text-xs text-ink">{o.spec_key}</div>
              <div className="text-xs text-muted-foreground">
                {o.count_equipos} {o.count_equipos === 1 ? "equipo" : "equipos"} · ejemplos:{" "}
                {o.sample_values
                  .slice(0, 3)
                  .map((v) => `"${v}"`)
                  .join(", ")}
              </div>
            </div>
            <Button size="sm" variant="outline" onClick={() => onConvert(o)}>
              Agregar al template
            </Button>
          </li>
        ))}
      </ul>
      <p className="px-3 py-2 text-2xs text-muted-foreground bg-amber-soft/50">
        Estos specs vinieron del autocompletar o de cargas anteriores y quedaron como "custom" en
        cada equipo. Si querés que aparezcan formateados en todos los equipos de esta categoría,
        agregalos al template con el tipo y unidad correctos.
      </p>
    </div>
  );
}

/** Pequeño indicador en la cabecera de la tabla mostrando cuántas specs
 *  están marcadas como ficha técnica destacada. La idea es mantener el
 *  conjunto chico (≤4) — son los quick facts del catálogo público y si
 *  son demasiados la card se satura. Soft warning, no enforcement. */
export function DestacadasCounter({ items }: { items: SpecTemplate[] }) {
  const total = items.filter((t) => t.destacado).length;
  const max = 4;
  const over = total > max;
  return (
    <div
      className={`flex items-center gap-2 text-xs ${over ? "text-ink" : "text-muted-foreground"}`}
    >
      <span className="font-mono uppercase tracking-widest">
        Ficha técnica destacada: {total}/{max}
      </span>
      {over && <span>— recomendado {max} máx para no saturar la card del catálogo público.</span>}
    </div>
  );
}

function Badge({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "amber";
}) {
  return <Pill tone={tone === "amber" ? "warning" : "neutral"}>{children}</Pill>;
}

export function SortableSpecRow({
  template,
  onEdit,
  onDelete,
  disabled,
}: {
  template: SpecTemplate;
  onEdit: () => void;
  onDelete: () => void;
  disabled: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: template.id,
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      // Columnas 1 y 5 anchas en mobile (48px/96px): a 44×44 el gate táctil,
      // el drag-handle solo (columna 1) y los DOS icon-buttons de acción
      // (columna 5, `size="xs"` = 44px c/u + gap) ya no entraban en los
      // 24px/64px fijos de antes — se recortaban contra el borde o se
      // solapaban con la columna vecina. `md:` vuelve al layout denso
      // original (los icon-buttons bajan a 28px en desktop).
      className="grid grid-cols-[48px_1fr_90px_minmax(0,1fr)_96px] items-center gap-2 px-3 py-2 text-sm hover:bg-muted/20 md:grid-cols-[24px_1fr_140px_minmax(0,1fr)_64px]"
    >
      <IconButton
        aria-label={`Reordenar ${template.label}`}
        size="xs"
        disabled={disabled}
        className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="h-4 w-4" />
      </IconButton>

      <div className="min-w-0">
        <div className="truncate text-ink">{template.label}</div>
        <div className="font-mono text-2xs text-muted-foreground truncate">{template.spec_key}</div>
      </div>

      <div className="text-xs min-w-0">
        {TIPO_LABEL[template.tipo]}
        {(template.tipo === "number" ||
          template.tipo === "rango" ||
          template.tipo === "wxh" ||
          template.tipo === "wxhxd") &&
        template.unidad
          ? ` · ${template.unidad}`
          : ""}
        {template.tipo === "enum" && template.enum_options ? (
          <div className="text-2xs text-muted-foreground truncate">
            {template.enum_options.join(", ")}
          </div>
        ) : null}
      </div>

      <div className="hidden md:flex flex-wrap gap-1 text-2xs min-w-0">
        {template.destacado && <Badge tone="amber">★ ficha destacada</Badge>}
      </div>
      <div className="md:hidden" aria-hidden />

      <div className="flex justify-end gap-1">
        <IconButton
          aria-label="Editar"
          size="xs"
          onClick={onEdit}
          className="text-muted-foreground hover:bg-muted/50 hover:text-ink"
        >
          <Pencil className="h-3.5 w-3.5" />
        </IconButton>
        <IconButton
          aria-label="Eliminar"
          size="xs"
          onClick={onDelete}
          className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </IconButton>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Modal crear/editar
// ─────────────────────────────────────────────────────────────────────

export function SpecTemplateFormModal({
  categoriaId,
  template,
  prefillKey,
  prefillSampleValues,
  categoriaPath,
  onClose,
  onSaved,
}: {
  categoriaId: number;
  template: SpecTemplate | null;
  /** Si se abre desde una sugerencia orphan, pre-llena la búsqueda con
   *  ese key para que sea fácil encontrar la spec correspondiente. */
  prefillKey?: string;
  /** Valores de ejemplo del orphan — útiles para que el dueño los vea
   *  mientras decide qué spec asignar. */
  prefillSampleValues?: string[];
  categoriaPath: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = template == null;
  const qcInner = useQueryClient();

  // Modo ASIGNAR (isNew): el user elige una spec del catálogo global y
  // setea los flags por categoría. NO crea specs nuevas — ese flujo vive en
  // Gear Compatibility → Definiciones (fuente de verdad).
  // Modo EDITAR (!isNew): solo flags de la asignación; los campos globales
  // (label/tipo/unidad/enum_options/compat) se editan en Gear Compat.

  // Catálogo global de specs (para el picker en modo asignar).
  const defsQ = useQuery({
    queryKey: ["admin", "spec-definitions"],
    queryFn: () => adminApi.listSpecDefinitions(),
    enabled: isNew,
    staleTime: 0,
  });

  // En modo asignar: spec seleccionada del catálogo. Si vino prefillKey,
  // intentamos pre-seleccionarla automáticamente cuando carga la lista.
  const [selectedDefId, setSelectedDefId] = useState<number | null>(null);
  const [search, setSearch] = useState(prefillKey ?? "");

  // Si vino prefillKey y el catálogo cargó, pre-seleccionar la spec exacta.
  // (No deps en setSelectedDefId para evitar loops.)
  if (isNew && prefillKey && defsQ.data && selectedDefId == null) {
    const match = defsQ.data.items.find(
      (d) => d.spec_key === prefillKey || d.label.toLowerCase() === prefillKey.toLowerCase(),
    );
    if (match) setSelectedDefId(match.id);
  }

  // Flags de la asignación (per-categoría).
  const [flags, setFlags] = useState({
    prioridad: template?.prioridad ?? 100,
    destacado: template?.destacado ?? false,
    obligatorio: template?.obligatorio ?? false,
    visible_en_card: template?.visible_en_card ?? false,
    visible_en_nombre: template?.visible_en_nombre ?? false,
    rol_compatibilidad: (template?.rol_compatibilidad ?? null) as RolCompatibilidad,
  });
  const [busy, setBusy] = useState(false);

  // Specs disponibles para asignar = catálogo global - las que ya están
  // asignadas a esta categoría (vienen como hermanas de `template` en el
  // GET listSpecTemplates, pero acá filtramos client-side).
  const yaAsignadasIds = useQuery({
    queryKey: ["admin", "spec-templates", categoriaId, "ids-only"],
    queryFn: async () => {
      const r = await adminApi.listSpecTemplates(categoriaId);
      return new Set(r.items.map((t) => t.spec_def_id));
    },
    enabled: isNew,
    staleTime: 0,
  });

  const candidatas = useMemo(() => {
    const all = defsQ.data?.items ?? [];
    const ya = yaAsignadasIds.data ?? new Set<number>();
    const q = search.trim().toLowerCase();
    return all
      .filter((d) => !ya.has(d.id))
      .filter((d) => {
        if (!q) return true;
        return d.label.toLowerCase().includes(q) || d.spec_key.toLowerCase().includes(q);
      })
      .sort((a, b) =>
        a.validado === b.validado ? a.label.localeCompare(b.label) : a.validado ? -1 : 1,
      );
  }, [defsQ.data, yaAsignadasIds.data, search]);

  // Spec del catálogo seleccionada (modo asignar) o derivada del template (edit).
  const specInfo: SpecDefinition | undefined = isNew
    ? defsQ.data?.items.find((d) => d.id === selectedDefId)
    : (defsQ.data?.items.find((d) => d.id === template?.spec_def_id) ??
      (template
        ? ({
            id: template.spec_def_id,
            spec_key: template.spec_key,
            label: template.label,
            tipo: template.tipo,
            unidad: template.unidad,
            enum_options: template.enum_options,
            ayuda: template.ayuda,
            es_compatibilidad: template.es_compatibilidad,
            compatibilidad_modo: template.compatibilidad_modo,
            validado: false,
          } as SpecDefinition)
        : undefined));

  const showRolField =
    specInfo?.es_compatibilidad &&
    specInfo?.compatibilidad_modo === "jerarquia" &&
    specInfo?.tipo === "enum";

  async function handleSave() {
    if (isNew && !selectedDefId) {
      toast.error("Seleccioná una spec del catálogo para asignar.");
      return;
    }
    setBusy(true);
    try {
      if (isNew && selectedDefId) {
        await adminApi.assignSpecToCategoria(categoriaId, {
          spec_def_id: selectedDefId,
          prioridad: flags.prioridad,
          destacado: flags.destacado,
          obligatorio: flags.obligatorio,
          visible_en_card: flags.visible_en_card,
          visible_en_filtros: true,
          visible_en_nombre: flags.visible_en_nombre,
          ayuda: null,
          rol_compatibilidad: showRolField ? flags.rol_compatibilidad : null,
        });
        toast.success("Spec asignada a la categoría");
      } else if (template) {
        await adminApi.updateSpecTemplate(template.id, {
          prioridad: flags.prioridad,
          destacado: flags.destacado,
          obligatorio: flags.obligatorio,
          visible_en_card: flags.visible_en_card,
          visible_en_nombre: flags.visible_en_nombre,
          rol_compatibilidad: showRolField ? flags.rol_compatibilidad : null,
        });
        toast.success("Asignación actualizada");
      }
      qcInner.invalidateQueries({ queryKey: ["admin", "spec-templates"] });
      qcInner.invalidateQueries({ queryKey: ["admin", "spec-definitions"] });
      onSaved();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalBackdrop
      onClose={onClose}
      className="z-50 bg-black/60 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="bg-background rounded-lg border hairline w-full max-w-lg max-h-[90vh] overflow-y-auto shadow-xl">
        <header className="flex items-center justify-between border-b hairline px-4 py-3">
          <div className="min-w-0">
            <div className="font-display text-base text-ink">
              {isNew ? "Asignar spec a categoría" : "Editar asignación"}
            </div>
            <div className="text-xs text-muted-foreground truncate">{categoriaPath}</div>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1.5 text-muted-foreground hover:bg-muted/50 hover:text-ink"
            aria-label="Cerrar"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="p-4 space-y-3">
          {prefillKey && prefillSampleValues && prefillSampleValues.length > 0 && (
            <div className="rounded-md border hairline border-amber/30 bg-amber-soft/30 px-3 py-2 text-xs">
              <div className="font-mono uppercase tracking-widest text-muted-foreground mb-0.5">
                Sugerencia desde "{prefillKey}"
              </div>
              <div className="text-ink">
                Valores en equipos: {prefillSampleValues.map((v) => `"${v}"`).join(", ")}
              </div>
              <p className="text-muted-foreground mt-1 text-2xs">
                Buscá una spec del catálogo que matchee, o creala en Gear Compatibility si no
                existe.
              </p>
            </div>
          )}

          {/* ── Modo ASIGNAR: picker del catálogo ───────────────────────── */}
          {isNew && (
            <>
              <div>
                <Label className="text-xs">Buscar spec en el catálogo</Label>
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Buscar por label o spec_key…"
                  className="font-mono"
                  autoFocus
                />
                <p className="text-2xs text-muted-foreground mt-1">
                  Las specs validadas aparecen arriba. Si no encontrás la que buscás,{" "}
                  <a href="/admin/gear-compatibility" className="text-ink underline">
                    creala en Gear Compatibility →
                  </a>
                </p>
              </div>
              <div className="border hairline rounded-md max-h-64 overflow-y-auto divide-y hairline">
                {defsQ.isLoading && (
                  <div className="px-3 py-2 text-xs text-muted-foreground">Cargando…</div>
                )}
                {!defsQ.isLoading && candidatas.length === 0 && (
                  <div className="px-3 py-2 text-xs text-muted-foreground italic">
                    {search
                      ? "Ninguna spec disponible matchea la búsqueda."
                      : "Todas las specs del catálogo ya están asignadas a esta categoría."}
                  </div>
                )}
                {candidatas.map((d) => (
                  <button
                    type="button"
                    key={d.id}
                    onClick={() => setSelectedDefId(d.id)}
                    className={
                      "w-full text-left px-3 py-1.5 text-xs hover:bg-muted/30 " +
                      (selectedDefId === d.id ? "bg-amber-soft/40" : "")
                    }
                  >
                    <div className="flex items-center gap-1.5">
                      {d.validado && <span className="text-verde-ink">✓</span>}
                      <span className="text-ink font-medium">{d.label}</span>
                      <span className="font-mono text-3xs text-muted-foreground">{d.spec_key}</span>
                      <span className="text-3xs text-muted-foreground ml-auto">
                        {TIPO_LABEL[d.tipo]}
                        {d.unidad ? ` · ${d.unidad}` : ""}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </>
          )}

          {/* ── Spec seleccionada (info read-only) ──────────────────────── */}
          {specInfo && (
            <div className="rounded-md border hairline bg-muted/20 px-3 py-2 space-y-0.5">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-xs font-medium text-ink">{specInfo.label}</span>
                <span className="font-mono text-3xs text-muted-foreground">
                  {specInfo.spec_key}
                </span>
                <span className="text-3xs text-muted-foreground">
                  · {TIPO_LABEL[specInfo.tipo]}
                  {specInfo.unidad ? ` · ${specInfo.unidad}` : ""}
                </span>
                {specInfo.es_compatibilidad && (
                  <span className="text-3xs bg-amber-soft/60 text-ink px-1 rounded">
                    compat {specInfo.compatibilidad_modo}
                  </span>
                )}
              </div>
              {specInfo.tipo === "enum" || specInfo.tipo === "multi_enum" ? (
                <div className="text-2xs text-muted-foreground">
                  Opciones: {(specInfo.enum_options ?? []).join(", ") || "—"}
                </div>
              ) : null}
              {specInfo.ayuda && (
                <div className="text-2xs text-muted-foreground italic">{specInfo.ayuda}</div>
              )}
              <a
                href="/admin/gear-compatibility"
                className="text-2xs text-ink underline inline-block"
              >
                Editar la definición global →
              </a>
            </div>
          )}

          {/* ── Flags de la asignación (per-categoría) ─────────────────── */}
          {(specInfo || !isNew) && (
            <fieldset className="border hairline rounded-md p-3 space-y-2">
              <legend className="px-1 text-xs text-muted-foreground">
                Flags para esta categoría
              </legend>
              <Toggle
                label="Ficha técnica destacada — aparece como quick fact en la card del catálogo público (recomendado máx 4 por categoría)"
                checked={flags.destacado}
                onChange={(v) => setFlags({ ...flags, destacado: v })}
              />
              <Toggle
                label="Visible en card del catálogo"
                checked={flags.visible_en_card}
                onChange={(v) => setFlags({ ...flags, visible_en_card: v })}
              />
              <Toggle
                label="Obligatorio al cargar el equipo"
                checked={flags.obligatorio}
                onChange={(v) => setFlags({ ...flags, obligatorio: v })}
              />
              {showRolField && (
                <div>
                  <Label className="text-xs">Rol en compatibilidad jerárquica</Label>
                  <Select
                    value={flags.rol_compatibilidad ?? "ninguno"}
                    onValueChange={(v) =>
                      setFlags({
                        ...flags,
                        rol_compatibilidad:
                          v === "ninguno" ? null : (v as "contenedor" | "contenido"),
                      })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ninguno">No participa</SelectItem>
                      <SelectItem value="contenedor">Contenedor (proyecta — ej. lente)</SelectItem>
                      <SelectItem value="contenido">Contenido (recibe — ej. sensor)</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-2xs text-muted-foreground mt-1">
                    El modo jerárquico de la spec global decide; acá solo definís cómo participa
                    esta categoría.
                  </p>
                </div>
              )}
            </fieldset>
          )}
        </div>

        <footer className="border-t hairline px-4 py-3 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancelar
          </Button>
          <Button onClick={handleSave} disabled={busy || (isNew && !selectedDefId)}>
            {busy ? "Guardando…" : isNew ? "Asignar" : "Guardar"}
          </Button>
        </footer>
      </div>
    </ModalBackdrop>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
      {/* eslint-disable-next-line no-restricted-syntax -- checkbox nativo: el DS Checkbox es Radix (otra API) */}
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4"
      />
      <span>{label}</span>
    </label>
  );
}
