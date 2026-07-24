/**
 * Builder de combo dedicado (A2 #635).
 *
 * Flujo en 2 pasos dentro de un Dialog:
 *   Paso 1: nombre + foto → crea el equipo (tipo='combo', cantidad=9999 sentinel)
 *           y lo asigna a la categoría "Combos" (creándola si no existe).
 *   Paso 2: ComboEditor para agregar/configurar componentes.
 *
 * Al cerrar en el paso 2 el combo queda guardado. Opcionalmente navega al
 * editor completo para agregar descripción, ficha técnica, etc.
 */

import { useState } from "react";
import { Upload, X, Plus } from "lucide-react";
import { Spinner } from "@/design-system/ui/spinner";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/design-system/ui/dialog";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import { Button } from "@/design-system/ui/button";
import { Switch } from "@/design-system/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";

import { adminApi, type Equipo, type CategoriaAdmin } from "@/lib/admin/api";
import { DUENOS } from "@/lib/admin/duenos";
import { uploadFileToBucket } from "@/lib/equipment/photos";
import { ComboEditor } from "./equipo-form/ComboEditor";

const COMBO_SENTINEL_STOCK = 9999;
const COMBOS_CAT_NOMBRE = "Combos";

async function ensureCombosCat(categorias: CategoriaAdmin[]): Promise<number> {
  const existing = categorias.find(
    (c) => c.nombre.trim().toLowerCase() === COMBOS_CAT_NOMBRE.toLowerCase(),
  );
  if (existing) return existing.id;
  const created = await adminApi.adminCreateCategoria({ nombre: COMBOS_CAT_NOMBRE, prioridad: 10 });
  return created.id;
}

export function ComboBuilderDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** Callback when combo is created (before component editing). Optional. */
  onCreated?: (equipo: Equipo) => void;
}) {
  const qc = useQueryClient();

  const [step, setStep] = useState<"form" | "componentes">("form");
  const [nombre, setNombre] = useState("");
  const [dueno, setDueno] = useState<string>("Rambla");
  const [visibleCatalogo, setVisibleCatalogo] = useState(true);
  const [saving, setSaving] = useState(false);
  const [equipo, setEquipo] = useState<Equipo | null>(null);

  // Foto
  const [file, setFile] = useState<File | null>(null);
  const [filePreview, setFilePreview] = useState("");
  const [uploading, setUploading] = useState(false);

  const handleFile = (f: File) => {
    setFile(f);
    if (filePreview) URL.revokeObjectURL(filePreview);
    setFilePreview(URL.createObjectURL(f));
  };

  const handleClose = (v: boolean) => {
    if (!v) {
      // Reset para la próxima apertura
      setStep("form");
      setNombre("");
      setDueno("Rambla");
      setVisibleCatalogo(true);
      setSaving(false);
      setEquipo(null);
      setFile(null);
      if (filePreview) URL.revokeObjectURL(filePreview);
      setFilePreview("");
      // Invalidar equipos para que el listado se actualice
      if (equipo) {
        qc.invalidateQueries({ queryKey: ["admin", "equipos"] });
        qc.invalidateQueries({ queryKey: ["admin", "categorias-list"] });
      }
    }
    onOpenChange(v);
  };

  const crearCombo = async () => {
    if (!nombre.trim()) {
      toast.error("El nombre es requerido");
      return;
    }
    setSaving(true);
    try {
      // 1. Obtener/crear categoría Combos
      const cats = await adminApi.adminListCategorias();
      const catId = await ensureCombosCat(cats);

      // 2. Crear el equipo
      const created = await adminApi.createEquipo({
        nombre: nombre.trim(),
        tipo: "combo",
        cantidad: COMBO_SENTINEL_STOCK,
        visible_catalogo: visibleCatalogo ? 1 : 0,
        estado: "operativo",
        precio_jornada: null,
        marca: null,
        modelo: null,
        serie: null,
        dueno,
        bh_url: null,
        foto_url: null,
        fecha_compra: null,
        precio_usd: null,
        roi_pct: null,
        valor_reposicion: null,
        ficha_completa: false,
        categoria_specs: null,
      });

      // 3. Asignar a categoría Combos
      await adminApi.setCategorias(created.id, [catId]);

      // 4. Subir foto si hay
      if (file) {
        setUploading(true);
        try {
          const url = await uploadFileToBucket(created.id, file);
          await adminApi.updateEquipo(created.id, { foto_url: url });
          created.foto_url = url;
        } catch {
          toast.warning("El combo se creó pero no se pudo subir la foto");
        } finally {
          setUploading(false);
        }
      }

      setEquipo(created);
      onCreated?.(created);
      setStep("componentes");
      toast.success("Combo creado — ahora agregá los componentes");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Error al crear el combo");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {step === "form" ? "Nuevo combo" : `Componentes — ${equipo?.nombre ?? ""}`}
          </DialogTitle>
        </DialogHeader>

        {step === "form" ? (
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>Nombre del combo</Label>
              <Input
                value={nombre}
                onChange={(e) => setNombre(e.target.value)}
                placeholder="Ej: Kit iluminación LED + trípode"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") void crearCombo();
                }}
              />
            </div>

            <div className="space-y-1.5">
              <Label>Foto (opcional)</Label>
              {filePreview ? (
                <div className="relative w-24 h-24">
                  <img
                    loading="lazy"
                    decoding="async"
                    src={filePreview}
                    alt=""
                    className="w-full h-full object-contain rounded border hairline bg-muted/30"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      setFile(null);
                      if (filePreview) URL.revokeObjectURL(filePreview);
                      setFilePreview("");
                    }}
                    className="absolute -top-1 -right-1 bg-background border hairline rounded-full p-0.5 text-muted-foreground hover:text-ink"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ) : (
                <label className="flex flex-col items-center justify-center w-24 h-24 rounded border hairline border-dashed cursor-pointer hover:bg-accent transition-colors bg-muted/20">
                  <Upload className="h-5 w-5 text-muted-foreground mb-1" />
                  <span className="text-xs text-muted-foreground">Subir</span>
                  {/* eslint-disable-next-line no-restricted-syntax -- input file: no hay componente DS */}
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) handleFile(f);
                      e.target.value = "";
                    }}
                  />
                </label>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Dueño</Label>
                <Select value={dueno} onValueChange={setDueno}>
                  <SelectTrigger>
                    <SelectValue placeholder="Seleccionar…" />
                  </SelectTrigger>
                  <SelectContent>
                    {DUENOS.map((d) => (
                      <SelectItem key={d} value={d}>
                        {d}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Visibilidad</Label>
                <div className="flex h-9 items-center gap-2">
                  <Switch checked={visibleCatalogo} onCheckedChange={setVisibleCatalogo} />
                  <span className="text-sm text-muted-foreground">
                    {visibleCatalogo ? "Visible en catálogo" : "Oculto del catálogo"}
                  </span>
                </div>
              </div>
            </div>

            <p className="text-xs text-muted-foreground">
              El combo se crea con stock sentinel (9999) — la disponibilidad real se deriva de sus
              componentes.
            </p>
          </div>
        ) : (
          <div className="py-2">{equipo && <ComboEditor equipoId={equipo.id} />}</div>
        )}

        <DialogFooter>
          {step === "form" ? (
            <>
              <Button variant="ghost" onClick={() => handleClose(false)}>
                Cancelar
              </Button>
              <Button onClick={() => void crearCombo()} disabled={saving || uploading}>
                {saving || uploading ? (
                  <>
                    <Spinner size="sm" className="mr-1.5" /> Creando…
                  </>
                ) : (
                  <>
                    <Plus className="h-4 w-4 mr-1.5" /> Crear combo
                  </>
                )}
              </Button>
            </>
          ) : (
            <Button onClick={() => handleClose(false)}>Listo</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
