import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { FileJson, Plus, Upload } from "lucide-react";
import { toast } from "sonner";

import { talleresAdminApi } from "@/lib/admin/api/talleres";
import type { ClaseBody, ModalidadPagoBody, TallerConcepto } from "@/lib/admin/api/types";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Spinner } from "@/design-system/ui/spinner";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/design-system/ui/dialog";
import { useBusinessContact } from "@/hooks/useBusinessContact";
import { TallerCalendario } from "@/components/talleres/TallerCalendario";
import { ClasesAsistente } from "./ClasesAsistente";

// Ficha de importación (ver `backend/scripts/importar_taller.py` — mismo
// esquema, así una ficha que Claude armó para el script sirve tal cual acá).
// `instructor.foto`/`clases[].portada` (paths locales) NO se leen en este
// modo — el navegador no tiene acceso a paths relativos del filesystem de
// quien armó la ficha; las fotos se suben después, desde el taller ya creado.
type FichaTaller = {
  nombre: string;
  subtitulo?: string;
  descripcion?: string;
  // Teaser corto para la tarjeta de /escuelas (mezcla "para quién" + "de qué
  // trata") — no lo pisa la descripción completa truncada.
  resumen?: string;
  publico_objetivo?: string;
  notif_email?: string;
  terminos?: string;
  beneficios?: string;
  pregunta_experiencia?: string;
  mensaje_confirmacion?: string;
  instructor?: {
    nombre: string;
    rol?: string;
    descripcion?: string;
    instagram?: string;
    web?: string;
    proyectos?: string;
  };
  edicion: {
    tipo_taller?: string;
    horario?: string;
    cupos_total?: number;
    precio_total?: number;
    precio_sena?: number;
    direccion?: string | null;
    pago_alias?: string;
    pago_cbu?: string;
    pago_banco?: string;
    usa_estudio?: boolean;
    valor_estudio?: number;
    valor_estudio_modo?: "mensual" | "total";
    usa_equipos?: boolean;
    valor_equipos?: number;
    valor_equipos_modo?: "mensual" | "total";
    clases: ClaseBody[];
    // Opcional — `EdicionCreateBody` no las acepta en la creación, se cargan
    // aparte por PATCH (mismo campo que `PreciosSection` en el admin).
    // El público las ve en `ModalidadSelector` (form de inscripción); con
    // 2+ es un selector real, con 1 sola muestra el monto sin radio (nada
    // que elegir). `PrecioCard`, que mostraba el precio sin depender del
    // form, se retiró — 2026-08-12.
    modalidades?: ModalidadPagoBody[];
  };
};

function parseFicha(raw: string): FichaTaller {
  const data = JSON.parse(raw);
  if (!data?.nombre || !data?.edicion?.clases?.length) {
    throw new Error("La ficha necesita al menos 'nombre' y 'edicion.clases'");
  }
  return data as FichaTaller;
}

export function NuevoConceptoDialog({
  open,
  onClose,
  onSuccess,
}: {
  open: boolean;
  onClose: () => void;
  onSuccess: (created: TallerConcepto) => void;
}) {
  const [nombre, setNombre] = useState("");
  const [instructorNombre, setInstructorNombre] = useState("");
  const [clases, setClases] = useState<ClaseBody[]>([]);
  const [cupos, setCupos] = useState("12");
  const [precioTotal, setPrecioTotal] = useState("0");
  const [precioSena, setPrecioSena] = useState("0");

  // Modo import: una ficha JSON (la misma que arma el script de importación)
  // reemplaza el form de más abajo — no se recotejan los mismos campos dos
  // veces, la ficha ya trae todo (incluidos los que el form manual no pide:
  // subtítulo, descripción, pago, economía del Estudio/equipos).
  const [importMode, setImportMode] = useState(false);
  const [ficha, setFicha] = useState<FichaTaller | null>(null);
  const [fichaError, setFichaError] = useState("");
  const businessAddress = useBusinessContact().address;

  useEffect(() => {
    if (open) {
      setNombre("");
      setInstructorNombre("");
      setClases([]);
      setCupos("12");
      setPrecioTotal("0");
      setPrecioSena("0");
      setImportMode(false);
      setFicha(null);
      setFichaError("");
    }
  }, [open]);

  async function handleFichaFile(file: File) {
    setFichaError("");
    try {
      setFicha(parseFicha(await file.text()));
    } catch (e) {
      setFicha(null);
      setFichaError(e instanceof Error ? e.message : "JSON inválido");
    }
  }

  const mut = useMutation({
    mutationFn: (body: object) => talleresAdminApi.createConcepto(body),
    onSuccess: async (created) => {
      toast.success(`Taller creado: ${created.nombre}`);
      // Perfil rico del instructor (rol/bio/instagram/web/proyectos) — el
      // POST de arriba solo hace find-or-create por nombre, el resto se
      // completa acá (mismo orden que el script de importación).
      const rich = ficha?.instructor;
      const camposRicos =
        rich && Object.fromEntries(Object.entries(rich).filter(([k, v]) => k !== "nombre" && v));
      const instructorId = created.instructores[0]?.id;
      if (camposRicos && Object.keys(camposRicos).length > 0 && instructorId) {
        try {
          await talleresAdminApi.updateInstructor(instructorId, camposRicos);
        } catch (e) {
          toast.error(`No se pudo completar el perfil del instructor: ${(e as Error).message}`);
        }
      }
      const modalidades = ficha?.edicion.modalidades;
      const edicionId = created.ediciones[0]?.id;
      if (modalidades?.length && edicionId) {
        try {
          await talleresAdminApi.updateEdicion(edicionId, { modalidades });
        } catch (e) {
          toast.error(`No se pudieron cargar las modalidades de pago: ${(e as Error).message}`);
        }
      }
      onSuccess(created);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  function handleSubmitFicha(f: FichaTaller) {
    const ed = f.edicion;
    mut.mutate({
      nombre: f.nombre,
      instructor_nombre: f.instructor?.nombre ?? "",
      subtitulo: f.subtitulo ?? "",
      descripcion: f.descripcion ?? "",
      resumen: f.resumen ?? "",
      publico_objetivo: f.publico_objetivo ?? "",
      notif_email: f.notif_email ?? "",
      terminos: f.terminos ?? "",
      beneficios: f.beneficios ?? "",
      pregunta_experiencia: f.pregunta_experiencia ?? "",
      mensaje_confirmacion: f.mensaje_confirmacion ?? "",
      edicion: {
        tipo_taller: ed.tipo_taller || "intensivo",
        clases: ed.clases,
        cupos_total: ed.cupos_total ?? 12,
        precio_total: ed.precio_total ?? 0,
        precio_sena: ed.precio_sena ?? 0,
        horario: ed.horario ?? "",
        pago_alias: ed.pago_alias ?? "",
        pago_cbu: ed.pago_cbu ?? "",
        pago_banco: ed.pago_banco ?? "",
        direccion: ed.direccion || businessAddress,
        activo: false,
        usa_estudio: ed.usa_estudio ?? false,
        valor_estudio: ed.valor_estudio ?? 0,
        valor_estudio_modo: ed.valor_estudio_modo ?? "mensual",
        usa_equipos: ed.usa_equipos ?? false,
        valor_equipos: ed.valor_equipos ?? 0,
        valor_equipos_modo: ed.valor_equipos_modo ?? "mensual",
        numero_edicion: 1,
      },
    });
  }

  function handleSubmit() {
    if (importMode) {
      if (!ficha) {
        toast.error("Subí una ficha JSON válida primero");
        return;
      }
      handleSubmitFicha(ficha);
      return;
    }
    if (!nombre.trim()) {
      toast.error("Ingresá el nombre del taller");
      return;
    }
    if (!instructorNombre.trim()) {
      toast.error("Ingresá el nombre del/la instructor/a");
      return;
    }
    if (clases.length === 0) {
      toast.error("Agregá al menos una clase");
      return;
    }
    const c = parseInt(cupos, 10);
    const pt = parseInt(precioTotal, 10);
    const ps = parseInt(precioSena, 10);
    if (isNaN(c) || c < 1) {
      toast.error("Cupos inválidos");
      return;
    }
    if (isNaN(pt) || isNaN(ps) || ps > pt) {
      toast.error("Precios inválidos (la seña no puede superar el total)");
      return;
    }
    mut.mutate({
      nombre: nombre.trim(),
      instructor_nombre: instructorNombre.trim(),
      edicion: {
        // `tipo_taller` no tiene UI propia (Escuela v2) — el backend igual lo
        // exige (NOT NULL), así que viaja fijo.
        tipo_taller: "intensivo",
        clases,
        cupos_total: c,
        precio_total: pt,
        precio_sena: ps,
        numero_edicion: 1,
      },
    });
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Nuevo taller</DialogTitle>
        </DialogHeader>

        <div className="flex items-center justify-between -mt-1 mb-1">
          <p className="text-xs text-muted-foreground">
            {importMode
              ? "Subí la ficha JSON — el resto se completa solo."
              : "Cargá los datos a mano, o importá una ficha ya armada."}
          </p>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 text-xs text-muted-foreground hover:text-ink"
            onClick={() => {
              setImportMode((v) => !v);
              setFicha(null);
              setFichaError("");
            }}
          >
            {importMode ? (
              "Cargar a mano"
            ) : (
              <>
                <FileJson className="h-3.5 w-3.5" />
                Importar JSON
              </>
            )}
          </Button>
        </div>

        {importMode ? (
          <div className="flex flex-col gap-4 py-2">
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-border/60 px-6 py-10 text-center">
              <Upload className="h-6 w-6 text-muted-foreground/60" />
              <div className="flex flex-col gap-1">
                <p className="text-sm">Elegí el archivo .json de la ficha</p>
                <p className="text-2xs text-muted-foreground">
                  Mismo formato que usa el importador — pedíselo a quien te lo arme.
                </p>
              </div>
              {/* eslint-disable-next-line no-restricted-syntax -- input file: no hay componente DS */}
              <input
                type="file"
                accept="application/json,.json"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void handleFichaFile(f);
                }}
                className="text-sm"
              />
            </div>

            {fichaError && (
              <p className="text-sm text-destructive" role="alert">
                {fichaError}
              </p>
            )}

            {ficha && (
              <div className="flex flex-col gap-3 rounded-xl border border-border/50 bg-muted/10 p-4">
                <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Listo para crear
                </p>
                <div className="flex flex-col gap-1 text-sm">
                  <p className="font-semibold text-ink">{ficha.nombre}</p>
                  {ficha.instructor?.nombre && (
                    <p className="text-muted-foreground">{ficha.instructor.nombre}</p>
                  )}
                  <p className="text-muted-foreground">
                    {ficha.edicion.clases.length} clase
                    {ficha.edicion.clases.length !== 1 ? "s" : ""}
                    {" · "}
                    {ficha.edicion.cupos_total ?? 12} cupos
                    {" · "}
                    {!ficha.edicion.direccion &&
                      "dirección: la de Rambla (sin especificar en la ficha)"}
                  </p>
                  {ficha.edicion.modalidades && ficha.edicion.modalidades.length > 0 && (
                    <p className="text-muted-foreground">
                      Modalidades: {ficha.edicion.modalidades.map((m) => m.label).join(" · ")}
                    </p>
                  )}
                </div>
                <p className="text-2xs text-muted-foreground border-t border-border/40 pt-2">
                  La edición queda en borrador. Fotos de portada/instructor se suben después, desde
                  el taller ya creado.
                </p>
              </div>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-5 py-2">
            <div className="grid sm:grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Nombre del taller *
                </label>
                <Input
                  value={nombre}
                  onChange={(e) => setNombre(e.target.value)}
                  placeholder="Ej: Dirección de arte"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Instructor/a *
                </label>
                <Input
                  value={instructorNombre}
                  onChange={(e) => setInstructorNombre(e.target.value)}
                  placeholder="Ej: Jime Troncoso"
                />
              </div>
            </div>

            <div className="border-t border-border/50 pt-4">
              <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground mb-3">
                Clases — 1.ª edición *
              </p>
              <ClasesAsistente clases={clases} onChange={setClases} />
              {clases.length > 0 && (
                <div className="mt-4 pointer-events-none select-none">
                  <TallerCalendario sesiones={clases} />
                </div>
              )}
            </div>

            <div className="grid sm:grid-cols-3 gap-4 border-t border-border/50 pt-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Cupos totales
                </label>
                <Input
                  type="number"
                  min={1}
                  value={cupos}
                  onChange={(e) => setCupos(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Precio total (ARS)
                </label>
                <Input
                  type="number"
                  min={0}
                  value={precioTotal}
                  onChange={(e) => setPrecioTotal(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Seña (ARS)
                </label>
                <Input
                  type="number"
                  min={0}
                  value={precioSena}
                  onChange={(e) => setPrecioSena(e.target.value)}
                />
              </div>
            </div>
          </div>
        )}

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="ghost">Cancelar</Button>
          </DialogClose>
          <Button
            onClick={handleSubmit}
            disabled={mut.isPending || (importMode && !ficha)}
            className="gap-2"
          >
            {mut.isPending ? <Spinner size="sm" /> : <Plus className="h-4 w-4" />}
            Crear taller
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
