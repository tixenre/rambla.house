/**
 * Form de alta/edición de equipo. Sin tabs, scroll lineal con secciones
 * colapsables (Ficha, Kit, Avanzado). Mismo flow CREATE / EDIT.
 *
 *  - Identificación: nombre interno + nombre público lado a lado, con toggle
 *    de auto-gen por categoría.
 *  - "Link de fuente" como primera cosa del form, con botones para abrir y
 *    copiar al clipboard.
 *  - "Buscar foto" + "Autocompletar todo" como dos botones del mismo widget.
 *  - HTML upload para extraer specs (determinístico, sin LLM).
 *  - Kit con drag-drop.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload, Trash2, Search } from "lucide-react";
import { Spinner } from "@/design-system/ui/spinner";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/design-system/ui/alert-dialog";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import { Button } from "@/design-system/ui/button";
import { Switch } from "@/design-system/ui/switch";
import { Textarea } from "@/design-system/ui/textarea";
import { Badge } from "@/design-system/ui/badge";
import { AdminPage } from "@/components/admin/AdminPage";

import { adminApi, type Equipo, type EquipoInput } from "@/lib/admin/api";
import { uploadFileToBucket, uploadExternalUrlToBucket, isHostedUrl } from "@/lib/equipment/photos";
import { uploadEquipoFotoFromUrl, uploadEquipoFotosFromUrls } from "@/lib/equipment/equipoFotos";
import { PhotoGallery } from "@/components/common/PhotoGallery";
import { useUsdRate, useRoiPctDefault, calcularPrecioJornada } from "@/hooks/useSettings";
import { renderNombrePublicoTemplate } from "@/lib/equipment/nombre-template";
import { Field, CollapsibleSection, CategoriasPicker } from "./form-helpers";
import { buildSchema, type FormValues, type RecommendedField } from "./equipo-form-schema";
import { useEquipoFotos } from "./useEquipoFotos";
import { useEquipoFormDraft } from "./useEquipoFormDraft";
import { useEquipoFormSubmit } from "./useEquipoFormSubmit";
import { AutocompletarBarSection } from "./AutocompletarBarSection";
import { IdentificacionSection } from "./IdentificacionSection";
import { EquipoPreviewAside } from "./EquipoPreviewAside";
import { PrecioYStockSection } from "./PrecioYStockSection";
import { FichaTecnicaSection } from "./FichaTecnicaSection";
import { KitComboSection } from "./KitComboSection";
import { ContenidoIncluidoSection } from "./ContenidoIncluidoSection";
import { AvanzadoSection } from "./AvanzadoSection";
import { PegarHtmlDialog } from "./PegarHtmlDialog";

// ════════════════════════════════════════════════════════════════════
// Componente principal
// ════════════════════════════════════════════════════════════════════

export function EquipoFormDialog({
  open,
  onOpenChange,
  initial,
  onSubmit,
  saving,
  onCreatedWithMissingRecommended,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  initial?: Equipo | null;
  onSubmit: (data: EquipoInput) => Promise<Equipo>;
  saving?: boolean;
  /** Si el equipo se creó pero le faltan recomendados, el parent decide
   *  qué hacer (ej. reabrir el form en modo edit). #351 */
  onCreatedWithMissingRecommended?: (equipo: Equipo, missing: RecommendedField[]) => void;
}) {
  const isEdit = !!initial;
  const qc = useQueryClient();
  const { rate: usdRate } = useUsdRate({ staleTime: 0 });
  const roiDefault = useRoiPctDefault({ staleTime: 0 });

  // "Aplicar" (guardar sin cerrar) vs "Guardar" (cerrar al terminar). El
  // botón Aplicar setea este ref a false antes de disparar el submit; en el
  // success path consultamos el ref para decidir cerrar o quedarnos.
  const closeOnSuccessRef = useRef(true);

  // ── Estado del form (react-hook-form) ──────────────────────────────
  const schema = useMemo(() => buildSchema(isEdit), [isEdit]);
  const form = useForm<FormValues>({
    resolver: zodResolver(schema) as never,
    defaultValues: {
      nombre: initial?.nombre ?? "",
      marca: initial?.marca ?? "",
      modelo: initial?.modelo ?? "",
      cantidad: initial?.cantidad ?? 1,
      precio_jornada: initial?.precio_jornada ?? undefined,
      precio_usd: initial?.precio_usd ?? undefined,
      roi_pct: initial?.roi_pct ?? (initial ? undefined : roiDefault),
      valor_reposicion: initial?.valor_reposicion ?? undefined,
      fecha_compra: initial?.fecha_compra ?? "",
      // Default "N/A" en CREATE — equipos sin serie real comparten este
      // placeholder y el preflight de duplicados lo ignora.
      serie: initial ? (initial.serie ?? "") : "N/A",
      bh_url: initial?.bh_url ?? "",
      foto_url: initial?.foto_url ?? "",
      dueno: initial?.dueno ?? "Rental",
      estado: (initial?.estado as FormValues["estado"]) ?? "operativo",
      visible_catalogo: initial ? Boolean(initial.visible_catalogo) : true,
      ficha_completa: initial ? Boolean(initial.ficha_completa) : false,
      tipo: (initial?.tipo as FormValues["tipo"]) ?? "simple",
    },
  });

  // ── Pegar HTML (#1051 Stream B) — hermano de "Subir HTML" sin archivo/R2 ──
  const [htmlPasteOpen, setHtmlPasteOpen] = useState(false);
  const [htmlPasteText, setHtmlPasteText] = useState("");
  // Fotos que trajo el último "Pegar HTML" (para el botón "agregar todas" —
  // distinto de `photoCands`, que también junta lo de "Buscar foto").
  const [lastEnrichPhotoCands, setLastEnrichPhotoCands] = useState<string[]>([]);

  // ── Buscar fotos ───────────────────────────────────────────────────
  const [photoCands, setPhotoCands] = useState<string[]>([]);

  // ── Galería multi-foto (edit mode) ────────────────────────────────
  // Concern decoupled del form → useEquipoFotos (query + mutaciones + handlers).
  const gallery = useEquipoFotos(initial, open);

  // CREATE mode: archivo local que se sube después de crear el equipo.
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [pendingFilePreview, setPendingFilePreview] = useState("");
  useEffect(
    () => () => {
      if (pendingFilePreview) URL.revokeObjectURL(pendingFilePreview);
    },
    [pendingFilePreview],
  );

  // ── Sentinel de stock para combos: cantidad = 9999 ─────────────────
  const watchedTipo = form.watch("tipo");
  useEffect(() => {
    if (watchedTipo === "combo") {
      form.setValue("cantidad", 9999, { shouldDirty: true });
    }
  }, [watchedTipo, form]);

  // ── Categorías ─────────────────────────────────────────────────────
  const catsQ = useQuery({
    queryKey: ["admin", "categorias-list"],
    queryFn: () => adminApi.adminListCategorias(),
    enabled: open,
  });
  // Lista de marcas para el dropdown del campo Marca. Source-of-truth:
  // tabla `marcas`. El admin elige una existente o escribe una nueva
  // (autocomplete via <datalist>, free text permitido).
  const marcasQ = useQuery({
    queryKey: ["admin", "marcas-list"],
    queryFn: () => adminApi.adminListMarcas(),
    enabled: open,
  });
  const marcasOptions = useMemo(
    () => [...(marcasQ.data?.items ?? [])].sort((a, b) => a.nombre.localeCompare(b.nombre)),
    [marcasQ.data],
  );

  // ── Categoría de SPECS ─────────────────────────────────────────────
  // Define qué specs aplican (1 de las 5 del registry) Y la generación del
  // nombre público. Es independiente del árbol de catálogo (`selectedCats`),
  // que es solo agrupación para el front-office. El template de specs lo
  // resuelve el backend (`getEquipoSpecs`) desde `categoria_specs`.
  const specCatsQ = useQuery({
    queryKey: ["admin", "spec-categorias"],
    queryFn: () => adminApi.listSpecCategorias(),
    enabled: open,
  });
  const specCatOptions = useMemo(() => specCatsQ.data?.categorias ?? [], [specCatsQ.data]);
  const htmlInputRef = useRef<HTMLInputElement | null>(null);

  // ── Draft: hidratación servidor→borrador centralizada (F1 #1263) ───
  // Ficha, nombre público, html source, precio manual, categorías (catálogo
  // + specs) y specs estructuradas — ver useEquipoFormDraft.ts para el porqué.
  const draft = useEquipoFormDraft(initial, open, {
    categorias: catsQ.data,
    specCategorias: specCatOptions,
  });
  const {
    descripcion,
    setDescripcion,
    notas,
    setNotas,
    contenidoIncluido,
    setContenidoIncluido,
    nombrePublico,
    setNombrePublico,
    nombrePublicoAuto,
    setNombrePublicoAuto,
    autoGenDisponible,
    categoriaRoot,
    categoriaTemplate,
    specs,
    setSpecs,
    specsPropuestos,
    templateItems,
    aplicarSpecsExtraidos,
    selectedCats,
    setSelectedCats,
    htmlSourceUrl,
    setHtmlSourceUrl,
    precioJornadaManual,
    setPrecioJornadaManual,
  } = draft;

  // ── Auto-cálculo del precio/jornada (USD × tasa × ROI) ──────────────
  // La hidratación de `precioJornadaManual` vive en useEquipoFormDraft; acá
  // queda el auto-cálculo, que necesita form.watch/form.setValue.
  const watchedUsd = form.watch("precio_usd");
  const watchedRoi = form.watch("roi_pct");
  useEffect(() => {
    if (precioJornadaManual) return;
    // Chequeo directo a `initial.precio_jornada_manual` (no solo al estado
    // derivado `precioJornadaManual`): cuando `initial` llega async, el
    // efecto que lo siembra (en el hook) y este pueden correr en el MISMO
    // commit — un `setPrecioJornadaManual(true)` recién encolado no se
    // refleja todavía en la clausura de ESTE efecto en el mismo pase (React
    // no re-lee estado recién encolado entre efectos del mismo commit). Sin
    // este chequeo, un equipo con precio manual en la base igual se pisaba
    // apenas abría el form — confirmado en vivo (mismo patrón de carrera
    // que el override de nombre público).
    if (initial?.precio_jornada_manual) return;
    const calc = calcularPrecioJornada(
      watchedUsd ? Number(watchedUsd) : null,
      usdRate,
      watchedRoi ? Number(watchedRoi) : null,
    );
    if (calc !== null) form.setValue("precio_jornada", calc, { shouldDirty: true });
  }, [watchedUsd, watchedRoi, usdRate, precioJornadaManual, form, initial?.precio_jornada_manual]);

  // ── Auto-generación del nombre público ────────────────────────────
  // Preview del molde de la categoría de specs (el mismo que lee el backend
  // en vivo — services.nombre_service._categoria_template_de). Sin molde de
  // categoría no hay auto-gen: ya no hay fallback hardcodeado por categoría
  // (existía en nombre-publico.ts, retirado — era exactamente el patrón que
  // el backend eliminó en #415 por dar nombres que "el back-end nunca iba a
  // producir": la preview tiene que mostrar SOLO lo que se va a guardar).
  const watchedMarca = form.watch("marca");
  const watchedModelo = form.watch("modelo");
  useEffect(() => {
    if (!nombrePublicoAuto) return;
    // Chequeo directo a `initial.nombre_publico_override` (no solo al estado
    // derivado `nombrePublicoAuto`): cuando `initial` llega async, el efecto
    // que carga el override y este pueden correr en el mismo commit — un
    // `setNombrePublicoAuto(false)` recién encolado en el otro efecto no se
    // refleja todavía en la clausura de ESTE efecto en el mismo pase (React
    // no re-lee estado recién encolado entre efectos del mismo commit), así
    // que sin este chequeo este efecto podía pisar el override recién
    // cargado con "" — confirmado en vivo (equipo con override guardado
    // abría con el campo vacío pese al toggle ya en OFF).
    if (initial?.nombre_publico_override?.trim()) return;
    // Sin molde de categoría no hay nada que auto-generar — bail ANTES de
    // tocar el input. `nombrePublicoAuto` arranca en `true` por default y el
    // toggle para apagarlo queda OCULTO cuando `autoGenDisponible` es falso
    // (no hay molde), así que sin este chequeo el efecto seguía disparando en
    // cada cambio de marca/modelo/specs y BORRABA silenciosamente el nombre
    // que el usuario tipeó a mano — confirmado en vivo (modo creación: tipear
    // el nombre público y después la marca lo vaciaba). No alcanza con que
    // el toggle esté oculto: el efecto mismo tiene que respetar la ausencia
    // de molde, no solo la UI.
    if (!categoriaTemplate) return;
    // Buscar el output_config de cada spec en el template (las definiciones
    // viven en templateItems con tipo + output_config; los valores en specs).
    const tmplByLabel = new Map(
      (templateItems ?? []).map((t) => [t.label.trim().toLowerCase(), t] as const),
    );
    const fromTemplate = renderNombrePublicoTemplate(categoriaTemplate, {
      marca: watchedMarca ?? "",
      modelo: watchedModelo ?? "",
      tipo: categoriaRoot ?? "",
      nombre: initial?.nombre ?? "",
      specs: specs.map((s) => {
        const tmpl = tmplByLabel.get(s.label.trim().toLowerCase());
        const isTabla = tmpl?.tipo === "tabla";
        return {
          label: s.label,
          value: s.value,
          ...(isTabla && s.value ? { value_raw: s.value } : {}),
          output_config: tmpl?.output_config ?? null,
        };
      }),
    });
    setNombrePublico(fromTemplate ?? "");
  }, [
    nombrePublicoAuto,
    categoriaRoot,
    categoriaTemplate,
    watchedMarca,
    watchedModelo,
    specs,
    initial?.nombre,
    initial?.nombre_publico_override,
    templateItems,
    setNombrePublico,
  ]);

  // ════════════════════════════════════════════════════════════════════
  // Buscar fotos (solo foto, ~5s) — mismo patrón useMutation que
  // useEquipoFotos.ts (F1 #1263: los 8 handlers async del form).
  // ════════════════════════════════════════════════════════════════════
  const buscarFotosMut = useMutation({
    mutationFn: async () => {
      const u = (form.getValues("bh_url") ?? "").trim();
      const ctrl = new AbortController();
      const timeoutId = setTimeout(() => ctrl.abort(), 30_000);
      try {
        return await adminApi.buscarFotos(
          {
            nombre: form.getValues("nombre"),
            marca: form.getValues("marca") || null,
            modelo: form.getValues("modelo") || null,
            // Si hay URL en el autocompletar bar, usarla como fuente directa.
            ...(u ? { url: u } : {}),
            exclude: photoCands,
          },
          ctrl.signal,
        );
      } finally {
        clearTimeout(timeoutId);
      }
    },
    onSuccess: (r) => {
      const news = (r.foto_candidates ?? []).filter((x) => !photoCands.includes(x));
      setPhotoCands((prev) => [...prev, ...news]);
      if (news.length === 0) toast.info("No se encontraron más fotos");
      else toast.success(`${news.length} fotos encontradas`);
    },
    onError: (e) => {
      if (e instanceof Error && e.name === "AbortError") toast.error("Timeout (30s)");
      else toast.error(e instanceof Error ? e.message : "Error buscando fotos");
    },
  });
  const buscarFotos = () => buscarFotosMut.mutate();

  // CREATE mode elige la foto sin subir nada (queda pendiente hasta crear el
  // equipo); EDIT mode sube ya mismo — solo esa segunda mitad es mutación.
  const elegirFotoMut = useMutation({
    mutationFn: (externalUrl: string) => uploadEquipoFotoFromUrl(initial!.id, externalUrl),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "equipo-fotos", initial?.id] });
      void qc.invalidateQueries({ queryKey: ["admin", "equipos"] });
      toast.success("Foto seleccionada y subida");
    },
    onError: (e) => toast.error(`No se pudo subir: ${e instanceof Error ? e.message : ""}`),
  });
  const elegirFoto = (externalUrl: string) => {
    if (!initial?.id) {
      if (pendingFile) {
        setPendingFile(null);
        if (pendingFilePreview) URL.revokeObjectURL(pendingFilePreview);
        setPendingFilePreview("");
      }
      form.setValue("foto_url", externalUrl, { shouldDirty: true });
      toast.info("Foto elegida (se subirá al crear el equipo)");
      return;
    }
    elegirFotoMut.mutate(externalUrl);
  };

  const subirFotoUrlAR2Mut = useMutation({
    mutationFn: (url: string) => uploadExternalUrlToBucket(initial!.id, url),
    onSuccess: (r2url) => {
      form.setValue("foto_url", r2url, { shouldDirty: true });
      toast.success("Foto subida a R2");
    },
    onError: (e) => toast.error(`No se pudo subir a R2: ${e instanceof Error ? e.message : ""}`),
  });
  const subirFotoUrlAR2 = () => {
    if (!initial?.id) return;
    const url = form.getValues("foto_url");
    if (!url || isHostedUrl(url)) return;
    subirFotoUrlAR2Mut.mutate(url);
  };

  // CREATE mode: archivo local que se sube después de crear el equipo (sync,
  // no es mutación); EDIT mode sube ya mismo.
  const handleUploadMut = useMutation({
    mutationFn: (file: File) => uploadFileToBucket(initial!.id, file),
    onSuccess: (publicUrl) => {
      form.setValue("foto_url", publicUrl, { shouldDirty: true });
      toast.success("Foto subida");
    },
    onError: (e) => toast.error(`Error al subir: ${e instanceof Error ? e.message : ""}`),
  });
  const handleUpload = (file: File) => {
    if (!file) return;
    if (!initial?.id) {
      setPendingFile(file);
      if (pendingFilePreview) URL.revokeObjectURL(pendingFilePreview);
      setPendingFilePreview(URL.createObjectURL(file));
      form.setValue("foto_url", "", { shouldDirty: true });
      toast.info("Foto lista — se va a subir cuando crees el equipo");
      return;
    }
    handleUploadMut.mutate(file);
  };

  // ════════════════════════════════════════════════════════════════════
  // HTML source — sube el archivo, persiste en R2 y extrae specs. También
  // usado por re-extract (#1203): mismo resultado, sin volver a subir el
  // archivo — comparten `aplicarSpecsExtraidos` (del draft; aplica al
  // template o manda a revisión), no hay 2 formas de procesar el resultado.
  // ════════════════════════════════════════════════════════════════════
  const handleHtmlUploadMut = useMutation({
    mutationFn: (file: File) => adminApi.uploadHtmlSource(initial!.id, file),
    onSuccess: (r) => {
      setHtmlSourceUrl(r.html_source_url);
      aplicarSpecsExtraidos(r.specs ?? [], "HTML guardado");
    },
    onError: (e) => toast.error(`Error al subir HTML: ${e instanceof Error ? e.message : ""}`),
  });
  const handleHtmlUpload = (file: File) => {
    if (!initial?.id) return;
    handleHtmlUploadMut.mutate(file);
  };

  const handleReExtractSpecsMut = useMutation({
    mutationFn: () => adminApi.reExtractSpecs(initial!.id),
    onSuccess: (r) => aplicarSpecsExtraidos(r.specs ?? [], "HTML re-procesado"),
    onError: (e) =>
      toast.error(`Error al re-extraer specs: ${e instanceof Error ? e.message : ""}`),
  });
  const handleReExtractSpecs = () => {
    if (!initial?.id) return;
    handleReExtractSpecsMut.mutate();
  };

  // ════════════════════════════════════════════════════════════════════
  // Pegar HTML (#1051 Stream B) — hermano JSON de "Subir HTML": el mismo
  // extractor, pero recibe texto pegado (Chrome MCP, portapapeles) en vez de
  // un archivo, y NO persiste nada en R2/`html_source_url`. Comparte
  // `aplicarSpecsExtraidos` (misma lógica de aplicar specs) — no hay una
  // segunda forma de procesar el resultado.
  // ════════════════════════════════════════════════════════════════════
  const handleEnriquecerFromHtmlMut = useMutation({
    mutationFn: (html: string) => adminApi.enriquecerFromHtml(initial!.id, html),
    onSuccess: (r) => {
      aplicarSpecsExtraidos(r.specs ?? [], "HTML procesado");
      const nuevas = (r.foto_candidates ?? []).filter((u) => !photoCands.includes(u));
      if (nuevas.length > 0) {
        setPhotoCands((prev) => [...prev, ...nuevas]);
        setLastEnrichPhotoCands(nuevas);
      }
      setHtmlPasteOpen(false);
      setHtmlPasteText("");
    },
    onError: (e) => toast.error(`Error al procesar HTML: ${e instanceof Error ? e.message : ""}`),
  });
  const handleEnriquecerFromHtml = () => {
    if (!initial?.id) return;
    const html = htmlPasteText.trim();
    if (!html) {
      toast.error("Pegá el HTML antes de extraer");
      return;
    }
    handleEnriquecerFromHtmlMut.mutate(html);
  };

  const handleAgregarTodasLasFotosMut = useMutation({
    mutationFn: (urls: string[]) => uploadEquipoFotosFromUrls(initial!.id, urls),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["admin", "equipo-fotos", initial?.id] });
      void qc.invalidateQueries({ queryKey: ["admin", "equipos"] });
      if (r.agregadas.length) toast.success(`${r.agregadas.length} fotos agregadas a la galería`);
      if (r.fallidas.length) toast.error(`${r.fallidas.length} fotos no se pudieron agregar`);
      setLastEnrichPhotoCands([]);
    },
    onError: (e) => toast.error(`Error agregando fotos: ${e instanceof Error ? e.message : ""}`),
  });
  const handleAgregarTodasLasFotos = () => {
    if (!initial?.id || lastEnrichPhotoCands.length === 0) return;
    handleAgregarTodasLasFotosMut.mutate(lastEnrichPhotoCands);
  };

  // ════════════════════════════════════════════════════════════════════
  // Submit — mismo flow que el viejo (delegamos en adminApi).
  // ════════════════════════════════════════════════════════════════════
  // Keyboard shortcut: Cmd/Ctrl+S guarda el form (Esc lo maneja el Dialog).
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (saving) return;
        const formEl = document.querySelector<HTMLFormElement>("form[data-equipo-form]");
        formEl?.requestSubmit();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, saving]);

  const submit = useEquipoFormSubmit({
    form,
    isEdit,
    initial,
    draft,
    pendingFile,
    pendingFilePreview,
    setPendingFile,
    setPendingFilePreview,
    closeOnSuccessRef,
    onSubmit,
    onOpenChange,
    onCreatedWithMissingRecommended,
  });

  // ════════════════════════════════════════════════════════════════════
  // Render
  // ════════════════════════════════════════════════════════════════════
  // `form.watch("foto_url")` es el valor SEMBRADO UNA VEZ al montar
  // (react-hook-form `defaultValues`, no reactivo). En EDIT mode, subir una
  // foto nueva o cambiar cuál es la principal en la galería actualiza
  // `gallery.fotos` (React Query, correctamente sincronizado con el backend)
  // pero nunca toca ese valor sembrado — la miniatura de la galería se veía
  // bien, pero el preview grande del costado seguía mostrando la foto vieja
  // hasta cerrar y reabrir el form. La galería es la fuente viva; `foto_url`
  // del form queda de fallback para CREATE mode (ahí `gallery.fotos` está
  // siempre vacío — la query es `enabled: !!initial?.id`, y en create no hay
  // id todavía) y para el raro caso de un equipo en EDIT sin fotos en la
  // galería.
  const fotoGaleriaActual = gallery.fotos.find((f) => f.es_principal)?.url;
  const fotoActual = pendingFilePreview || fotoGaleriaActual || form.watch("foto_url") || undefined;

  // ── Confirmación al cerrar con cambios sin guardar (#232) ──────────
  // Detectamos cambios desde 4 fuentes: form fields (react-hook-form),
  // specs propuestos del autocompletar, ficha externa importada, archivo
  // de foto pendiente de upload. Cubre los casos típicos de pérdida de
  // datos en silencio. Falsos negativos posibles: cambios SOLO en
  // descripcion/notas/specs manuales sin tocar form fields.
  const [confirmCloseOpen, setConfirmCloseOpen] = useState(false);
  const hasUnsavedChanges =
    form.formState.isDirty || specsPropuestos.length > 0 || pendingFile !== null;

  const handleCloseRequest = (next: boolean) => {
    if (!next && hasUnsavedChanges) {
      setConfirmCloseOpen(true);
      return;
    }
    onOpenChange(next);
  };

  // Se lee 3 veces en el JSX de abajo (stock sentinel, título de sección,
  // qué editor montar) — un solo lugar, no 3 form.watch() sueltos.
  const esCombo = form.watch("tipo") === "combo";
  // Kit/Combo y Contenido de la caja son 2 secciones edit-only con el mismo gate.
  const mostrarSeccionesEdit = isEdit && initial;

  const formSections = (
    <>
      {/* ════════════════════════════════════════════════════════════════
              STATUS STRIP — switches de estado (visible + ficha completa)
          ════════════════════════════════════════════════════════════════ */}
      <div className="flex flex-wrap items-center gap-4 text-xs pb-2 border-b hairline">
        <label className="flex items-center gap-1.5 cursor-pointer">
          <Switch
            checked={form.watch("visible_catalogo")}
            onCheckedChange={(v) => form.setValue("visible_catalogo", v, { shouldDirty: true })}
          />
          <span className={form.watch("visible_catalogo") ? "text-ink" : "text-muted-foreground"}>
            {form.watch("visible_catalogo") ? "Visible en catálogo" : "Oculto del catálogo"}
          </span>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <Switch
            checked={form.watch("ficha_completa")}
            onCheckedChange={(v) => form.setValue("ficha_completa", v, { shouldDirty: true })}
          />
          <span className={form.watch("ficha_completa") ? "text-ink" : "text-muted-foreground"}>
            {form.watch("ficha_completa") ? "Ficha completa" : "Ficha pendiente"}
          </span>
        </label>
      </div>

      <AutocompletarBarSection
        isEdit={isEdit}
        bhUrl={form.watch("bh_url") ?? ""}
        onBhUrlChange={(v) => form.setValue("bh_url", v, { shouldDirty: true })}
        htmlInputRef={htmlInputRef}
        htmlSourceUrl={htmlSourceUrl}
        onBuscarFotos={buscarFotos}
        buscarFotosPending={buscarFotosMut.isPending}
        onHtmlFileSelected={handleHtmlUpload}
        uploadingHtmlPending={handleHtmlUploadMut.isPending}
        onPegarHtmlClick={() => setHtmlPasteOpen(true)}
        onReExtractSpecs={handleReExtractSpecs}
        reExtractPending={handleReExtractSpecsMut.isPending}
      />

      <IdentificacionSection
        isEdit={isEdit}
        form={form}
        draft={draft}
        marcasOptions={marcasOptions}
        fotoActual={fotoActual}
        pendingFile={pendingFile}
        onClearPendingFile={() => {
          setPendingFile(null);
          if (pendingFilePreview) URL.revokeObjectURL(pendingFilePreview);
          setPendingFilePreview("");
          form.setValue("foto_url", "", { shouldDirty: true });
        }}
        onUpload={handleUpload}
        onSubirAR2={subirFotoUrlAR2}
        uploadingPending={handleUploadMut.isPending}
        uploadingToR2Pending={subirFotoUrlAR2Mut.isPending}
        photoCands={photoCands}
        lastEnrichPhotoCands={lastEnrichPhotoCands}
        onAgregarTodasLasFotos={handleAgregarTodasLasFotos}
        agregarTodasPending={handleAgregarTodasLasFotosMut.isPending}
        onElegirFoto={elegirFoto}
        elegirFotoPending={elegirFotoMut.isPending}
        elegirFotoVariable={elegirFotoMut.variables}
      />

      {/* ════════════════════════════════════════════════════════════════
              GALERÍA DE FOTOS — solo en edit mode
          ════════════════════════════════════════════════════════════════ */}
      {isEdit && (
        <section className="space-y-2 pt-2 border-t hairline">
          <p className="text-xs font-medium text-ink/80">Galería de fotos</p>
          <p className="text-xs text-muted-foreground">
            La foto marcada como principal aparece en la ficha pública y en el catálogo.
          </p>
          <PhotoGallery
            fotos={gallery.fotos}
            onUpload={gallery.handleGalleryUpload}
            onDelete={gallery.onDelete}
            onReorder={gallery.handleGalleryReorder}
            onSetPrincipal={gallery.handleGallerySetPrincipal}
            uploading={gallery.galleryUploading}
            disabled={gallery.mutating}
          />
        </section>
      )}

      <PrecioYStockSection
        form={form}
        esCombo={esCombo}
        precioJornadaManual={precioJornadaManual}
        setPrecioJornadaManual={setPrecioJornadaManual}
      />

      {/* ════════════════════════════════════════════════════════════════
              DESCRIPCIÓN — campo de marketing/catálogo, separado de la
              ficha técnica. Va en una sección propia para evitar confusión
              con specs.
          ════════════════════════════════════════════════════════════════ */}
      <CollapsibleSection title="Descripción (catálogo público)" defaultOpen={!!descripcion}>
        <Field label="Texto descriptivo">
          <Textarea
            rows={3}
            value={descripcion}
            onChange={(e) => setDescripcion(e.target.value)}
            placeholder="Texto de marketing visible en la ficha del catálogo. Ej: ventajas, casos de uso típicos, diferenciales."
          />
        </Field>
      </CollapsibleSection>

      <FichaTecnicaSection draft={draft} specCatOptions={specCatOptions} />

      {/* ════════════════════════════════════════════════════════════════
              CATEGORÍAS DEL CATÁLOGO — agrupación para el front-office, separada
              de la categoría de specs (que vive en Ficha técnica).
          ════════════════════════════════════════════════════════════════ */}
      <section className="pt-2 border-t hairline space-y-3">
        <div>
          <Label className="text-xs uppercase tracking-wide text-muted-foreground">
            Categorías del catálogo
          </Label>
          <CategoriasPicker
            categorias={catsQ.data ?? []}
            selected={selectedCats}
            onChange={setSelectedCats}
          />
        </div>
      </section>

      {mostrarSeccionesEdit && <KitComboSection esCombo={esCombo} equipoId={initial.id} />}

      {mostrarSeccionesEdit && (
        <ContenidoIncluidoSection
          equipo={initial}
          items={contenidoIncluido}
          onChange={setContenidoIncluido}
        />
      )}

      <AvanzadoSection form={form} notas={notas} setNotas={setNotas} />
    </>
  );

  const titleText = isEdit ? "Editar equipo" : "Nuevo equipo";
  const formId = "equipo-form";

  const publicHint = nombrePublico ? (
    <span className="text-xs text-muted-foreground">
      Se ve en la web como: <span className="text-ink font-medium italic">{nombrePublico}</span>
    </span>
  ) : null;

  // En edit: dos botones — "Aplicar" persiste sin cerrar (para iterar sin
  // perder posición), "Guardar" persiste y vuelve a la lista. En create solo
  // mostramos "Guardar" porque el flujo post-create necesita el handoff a
  // edit (missing-recommended) o la navegación.
  const triggerApply = () => {
    if (saving) return;
    closeOnSuccessRef.current = false;
    document.querySelector<HTMLFormElement>(`form[data-equipo-form]`)?.requestSubmit();
  };
  const footerActions = (
    <>
      <Button type="button" variant="ghost" onClick={() => handleCloseRequest(false)}>
        Cancelar
      </Button>
      {isEdit && (
        <Button type="button" variant="outline" disabled={saving} onClick={triggerApply}>
          {saving ? (
            <>
              <Spinner size="sm" className="mr-1.5" /> Guardando…
            </>
          ) : (
            "Aplicar"
          )}
        </Button>
      )}
      <Button
        type="submit"
        variant="primary"
        form={formId}
        disabled={saving}
        onClick={() => {
          closeOnSuccessRef.current = true;
        }}
      >
        {saving ? (
          <>
            <Spinner size="sm" className="mr-1.5" /> Guardando…
          </>
        ) : (
          "Guardar"
        )}
      </Button>
    </>
  );

  const confirmCloseDialog = (
    <AlertDialog open={confirmCloseOpen} onOpenChange={setConfirmCloseOpen}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Tenés cambios sin guardar</AlertDialogTitle>
          <AlertDialogDescription>
            Si salís ahora, los cambios que hiciste en este equipo se pierden. ¿Querés salir igual?
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Volver al form</AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              setConfirmCloseOpen(false);
              onOpenChange(false);
            }}
          >
            Salir sin guardar
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );

  // Editor de página completa (mock del handoff) — única forma, no hay
  // variante modal (la había, pero ningún caller la usaba — #1263 Fase 0).
  return (
    <>
      <AdminPage title={titleText} maxW="list" description={publicHint} className="pb-28">
        <div className="grid lg:[grid-template-columns:minmax(0,1fr)_320px] gap-6 items-start">
          <form id={formId} onSubmit={submit} className="space-y-5 min-w-0" data-equipo-form>
            {formSections}
          </form>
          <EquipoPreviewAside
            fotoActual={fotoActual}
            nombre={form.watch("nombre")}
            nombrePublico={nombrePublico}
            precioJornada={form.watch("precio_jornada")}
            roiPct={form.watch("roi_pct")}
            valorReposicion={form.watch("valor_reposicion")}
          />
        </div>
      </AdminPage>
      <div className="sticky bottom-0 z-20 border-t hairline bg-background/95 backdrop-blur px-4 md:px-6 py-3 flex justify-end gap-2">
        {footerActions}
      </div>
      {confirmCloseDialog}
      <PegarHtmlDialog
        open={htmlPasteOpen}
        onOpenChange={setHtmlPasteOpen}
        text={htmlPasteText}
        onTextChange={setHtmlPasteText}
        pending={handleEnriquecerFromHtmlMut.isPending}
        onCancel={() => setHtmlPasteOpen(false)}
        onExtract={handleEnriquecerFromHtml}
      />
    </>
  );
}
