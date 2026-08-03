/**
 * useEquipoFormSubmit — orquesta el guardado de EquipoFormDialog.tsx: valida
 * (categoría + duplicado de serie), construye el payload, guarda el equipo y
 * encadena los guardados secundarios (foto/ficha/nombre público/specs/
 * categorías) que no viajan en el mismo POST/PATCH.
 *
 * Extraído verbatim del `submit` de EquipoFormDialog.tsx (split de
 * god-module, Frente E del skill `mantenimiento`, #1263 — última pieza tras
 * F0/F1/F2). Cero cambio de comportamiento: mismo orden de guardados, mismos
 * mensajes, mismo criterio de "avisos" vs "falló todo".
 */
import type { RefObject } from "react";
import type { UseFormReturn } from "react-hook-form";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { adminApi, type Equipo, type EquipoInput } from "@/lib/admin/api";
import { uploadFileToBucket, uploadExternalUrlToBucket, isHostedUrl } from "@/lib/equipment/photos";
import { useConfirm } from "@/components/admin/useConfirm";
import { type FormValues, type RecommendedField, RECOMMENDED_LABELS } from "./equipo-form-schema";
import type { EquipoFormDraft } from "./useEquipoFormDraft";

const FIELD_LABELS: Record<string, string> = {
  nombre: "Nombre",
  marca: "Marca",
  modelo: "Modelo",
  cantidad: "Cantidad",
  precio_jornada: "Precio jornada",
  precio_usd: "Precio USD",
  roi_pct: "% día",
  valor_reposicion: "Valor reposición",
  costo_compra: "Costo de compra",
  fecha_compra: "Fecha de compra",
  serie: "Serie",
  bh_url: "Link de fuente",
  foto_url: "Foto",
  dueno: "Dueño",
  estado: "Estado",
};

export function useEquipoFormSubmit({
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
}: {
  form: UseFormReturn<FormValues>;
  isEdit: boolean;
  initial: Equipo | null | undefined;
  draft: EquipoFormDraft;
  pendingFile: File | null;
  pendingFilePreview: string;
  setPendingFile: (f: File | null) => void;
  setPendingFilePreview: (s: string) => void;
  closeOnSuccessRef: RefObject<boolean>;
  onSubmit: (data: EquipoInput) => Promise<Equipo>;
  onOpenChange: (v: boolean) => void;
  onCreatedWithMissingRecommended?: (equipo: Equipo, missing: RecommendedField[]) => void;
}) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const {
    descripcion,
    notas,
    tags,
    contenidoIncluido,
    nombrePublicoAuto,
    categoriaTemplate,
    nombrePublico,
    categoriaSpecs,
    equipoSpecsQuery,
    specs,
    selectedCats,
    precioJornadaManual,
  } = draft;

  return form.handleSubmit(
    async (values) => {
      // Validación de creación: al menos una categoría seleccionada (#351).
      // Las categorías viven en estado separado del schema zod, así que las
      // chequeamos acá. En edit dejamos pasar por compat con equipos legacy.
      if (!isEdit && selectedCats.size === 0) {
        toast.error("Categoría requerida", {
          description: "Elegí al menos una categoría antes de guardar.",
        });
        return;
      }

      // Pre-flight: validación de duplicados por serie. La serie es lo más
      // único; si ya hay otro equipo con la misma, le pedimos confirmación al
      // user antes de seguir (puede ser legítimo en kits, pero conviene avisar).
      // EXCEPCIÓN: "N/A" es un placeholder común — los equipos sin serie real
      // comparten ese valor por design, así que no avisamos.
      const serieTrim = values.serie?.trim();
      const isPlaceholderSerie = !!serieTrim && /^(n\/?a|n\/?d|sin\s*serie|-+)$/i.test(serieTrim);
      if (serieTrim && !isPlaceholderSerie) {
        try {
          const r = await adminApi.listEquipos({ q: serieTrim });
          const dups = r.items.filter(
            (e) =>
              e.id !== initial?.id &&
              (e.serie ?? "").trim().toLowerCase() === serieTrim.toLowerCase(),
          );
          if (dups.length > 0) {
            const ok = await confirm({
              title: "¿Guardar con serie duplicada?",
              description: (
                <>
                  Ya hay otro equipo con la serie "{serieTrim}":
                  <br />• {dups[0].nombre}
                  {dups.length > 1 ? ` (+${dups.length - 1} más)` : ""}
                </>
              ),
              confirmLabel: "Guardar igual",
            });
            if (!ok) return;
          }
        } catch {
          // Si la búsqueda falla, no bloqueamos el save.
        }
      }

      const { visible_catalogo, ficha_completa, tipo, ...rest } = values;

      const fotoUrlForm = rest.foto_url || null;
      const fotoExternaPendiente =
        !pendingFile && fotoUrlForm && !isHostedUrl(fotoUrlForm) ? fotoUrlForm : null;
      const fotoUrlInicial = pendingFile ? null : fotoUrlForm;

      const payload: EquipoInput = {
        nombre: rest.nombre,
        cantidad: rest.cantidad,
        estado: rest.estado,
        marca: rest.marca || null,
        modelo: rest.modelo || null,
        serie: rest.serie || null,
        dueno: rest.dueno || null,
        bh_url: rest.bh_url || null,
        foto_url: fotoUrlInicial,
        fecha_compra: rest.fecha_compra || null,
        precio_jornada: rest.precio_jornada ?? null,
        // Explícito para saltear la heurística de inferencia del backend
        // (que asume "manual" si llega precio_jornada SIN roi_pct) — este
        // form manda roi_pct SIEMPRE junto con precio_jornada, así que esa
        // heurística sola nunca detectaría un precio recién tipeado a mano
        // acá; el toggle local YA sabe la verdad, se la pasamos directo.
        precio_jornada_manual: precioJornadaManual,
        precio_usd: rest.precio_usd ?? null,
        roi_pct: rest.roi_pct ?? null,
        valor_reposicion: rest.valor_reposicion ?? null,
        costo_compra: rest.costo_compra ?? null,
        visible_catalogo: visible_catalogo ? 1 : 0,
        ficha_completa: ficha_completa,
        categoria_specs: categoriaSpecs || null,
        tipo,
      };

      const fallidos: string[] = [];
      let equipoId: number | undefined;

      try {
        const saved = await onSubmit(payload);
        equipoId = saved?.id ?? initial?.id;
        if (!equipoId) {
          toast.error("No se pudo guardar el equipo");
          return;
        }

        // Los guardados secundarios (foto/ficha/nombre-público/specs/categorías)
        // van a endpoints y tablas distintas, ninguno lee el resultado de otro
        // — corren en paralelo (Promise.allSettled) en vez de encadenados; cada
        // uno preserva su propio try/catch, así que un fallo no aborta al resto
        // (mismo criterio "avisos" que ya tenía el código secuencial).
        const equipoIdOk = equipoId;
        const tareasSecundarias: Array<() => Promise<void>> = [];

        // Foto pendiente o externa
        if (pendingFile) {
          tareasSecundarias.push(async () => {
            try {
              const r2url = await uploadFileToBucket(equipoIdOk, pendingFile);
              await adminApi.updateEquipo(equipoIdOk, { foto_url: r2url });
              form.setValue("foto_url", r2url, { shouldDirty: false });
              setPendingFile(null);
              if (pendingFilePreview) URL.revokeObjectURL(pendingFilePreview);
              setPendingFilePreview("");
            } catch (e) {
              fallidos.push(`foto (${e instanceof Error ? e.message : "error"})`);
            }
          });
        } else if (fotoExternaPendiente) {
          tareasSecundarias.push(async () => {
            try {
              const r2url = await uploadExternalUrlToBucket(equipoIdOk, fotoExternaPendiente);
              await adminApi.updateEquipo(equipoIdOk, { foto_url: r2url });
              form.setValue("foto_url", r2url, { shouldDirty: false });
            } catch (e) {
              fallidos.push(`foto a R2 (${e instanceof Error ? e.message : "error"})`);
            }
          });
        }

        // Ficha legacy: descripción + notas + keywords + contenido incluido.
        // El nombre público ya NO va acá — vive en equipos.nombre_publico_override
        // (ver más abajo). Las specs estructuradas tampoco — viven en equipo_specs
        // y se persisten vía putEquipoSpecs (más abajo).
        const tieneFicha = isEdit || !!descripcion || !!notas || tags.length > 0;
        if (tieneFicha) {
          tareasSecundarias.push(async () => {
            try {
              const validos = contenidoIncluido.filter((ci) => ci.nombre.trim().length > 0);
              const fichaGuardada = await adminApi.setFicha(equipoIdOk, {
                descripcion: descripcion || null,
                notas: notas || null,
                keywords_json: tags.length ? JSON.stringify(tags) : null,
                // B1 #635: contenido incluido — filtramos los ítems sin nombre
                // (el usuario puede tener una fila vacía sin completar; no la
                // enviamos para no fallar la validación del backend y perder
                // los ítems válidos en la misma operación).
                contenido_incluido_json: validos.length > 0 ? JSON.stringify(validos) : null,
              });
              // Actualizar el cache de ficha inmediatamente con la respuesta del
              // servidor. Sin esto, al usar "Aplicar" (no cierra el form), la
              // invalidación del equipo dispara el effect de hidratación de ficha
              // (useEquipoFormDraft) con la ficha VIEJA (no invalidada) →
              // setContenidoIncluido(viejos) pisa lo recién guardado. Con
              // setQueryData el effect re-corre con la ficha fresca y el
              // contenido queda correcto en pantalla.
              qc.setQueryData(["admin", "equipo-ficha", equipoIdOk], fichaGuardada);
            } catch (e) {
              fallidos.push(`ficha (${e instanceof Error ? e.message : "error"})`);
            }
          });
        }

        // Nombre público: override manual vía el endpoint dedicado — gana
        // SIEMPRE sobre el molde de categoría (ver services/nombre_builder.py).
        // "Auto ON + hay molde de categoría" → el backend ya lo arma en vivo,
        // no hay nada que guardar acá; si tenía un override viejo (volvió a
        // auto), lo soltamos para que el molde tome el control de nuevo.
        const usaMoldeDeCategoria = nombrePublicoAuto && !!categoriaTemplate;
        const texto = usaMoldeDeCategoria ? "" : nombrePublico.trim();
        const teniaOverride = !!initial?.nombre_publico_override?.trim();
        // Solo llamamos al endpoint si hay algo que CAMBIAR — nunca en cada
        // guardado sin condición. Si el campo está vacío y nunca hubo
        // override, no tocamos nada: un equipo que nadie re-guardó desde
        // antes del molde vivo puede tener un `nombre_publico` "fósil" de un
        // mecanismo viejo (auto-build hardcodeado, retirado) — limpiar el
        // override en ese caso dispara actualizar_nombres_de igual y lo
        // pisaría a vacío sin que el usuario haya tocado el nombre.
        if (texto) {
          tareasSecundarias.push(async () => {
            try {
              await adminApi.aprobarNombre(equipoIdOk, { override: texto, revisado: true });
            } catch (e) {
              fallidos.push(`nombre público (${e instanceof Error ? e.message : "error"})`);
            }
          });
        } else if (teniaOverride) {
          tareasSecundarias.push(async () => {
            try {
              await adminApi.aprobarNombre(equipoIdOk, { override: null, revisado: false });
            } catch (e) {
              fallidos.push(`nombre público (${e instanceof Error ? e.message : "error"})`);
            }
          });
        }

        // Specs estructuradas → PUT a equipo_specs (SoT única). El id de cada
        // spec codifica su spec_def_id (`spec-${id}` para guardados, `tmpl-${id}`
        // para los del template materializados), así que mapeamos directo sin
        // round-trip por label —que se rompía cuando el label todavía no estaba
        // resuelto contra el template. Los specs custom (id uuid, sin
        // spec_def_id) no van a equipo_specs: se gestionan en /admin/equipos/specs.
        if (isEdit && equipoSpecsQuery.data) {
          tareasSecundarias.push(async () => {
            try {
              const specsDict: Record<string, string> = {};
              for (const s of specs) {
                const value = s.value.trim();
                if (!value) continue;
                const m = /^(?:spec|tmpl)-(\d+)$/.exec(s.id);
                if (!m) continue;
                specsDict[m[1]] = value;
              }
              await adminApi.putEquipoSpecs(equipoIdOk, specsDict);
            } catch (e) {
              fallidos.push(`specs (${e instanceof Error ? e.message : "error"})`);
            }
          });
        }

        // Categorías (en V2 las habilitamos también en CREATE) — solo si
        // cambiaron: en EDIT se pisaba con el mismo set en cada submit, un
        // round-trip de red innecesario (hallazgo del supervisor, auditoría
        // de performance #1263). En CREATE no hay set previo, así que
        // siempre corre la primera vez.
        const catsIniciales = new Set((initial?.categorias ?? []).map((c) => c.id));
        const categoriasChanged =
          !isEdit ||
          selectedCats.size !== catsIniciales.size ||
          [...selectedCats].some((catId) => !catsIniciales.has(catId));
        if (categoriasChanged) {
          tareasSecundarias.push(async () => {
            try {
              await adminApi.setCategorias(equipoIdOk, [...selectedCats]);
            } catch (e) {
              fallidos.push(`categorías (${e instanceof Error ? e.message : "error"})`);
            }
          });
        }

        await Promise.allSettled(tareasSecundarias.map((t) => t()));
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Error al guardar");
        return;
      }

      // Invalidar las queries PÚBLICAS (catálogo + ficha de equipo) — el save
      // arriba ya invalida lo admin (vía saveMut.onSettled del route padre),
      // pero nombre público/specs/categorías se escriben acá con llamadas
      // directas que ese onSettled no cubre. Sin esto, el catálogo público
      // sigue mostrando el dato viejo hasta que su staleTime (30-60s) vence
      // solo — "tarda en reproducirse" no era timing raro, era que nadie le
      // avisaba. Prefix-match: no hace falta el slug/rango de fechas exacto.
      void qc.invalidateQueries({ queryKey: ["equipos"] });
      void qc.invalidateQueries({ queryKey: ["equipo"] });
      void qc.invalidateQueries({ queryKey: ["categorias"] });

      if (fallidos.length > 0) {
        toast.warning(isEdit ? "Equipo actualizado con avisos" : "Equipo creado con avisos", {
          description: `Falló: ${fallidos.join(" · ")}`,
          duration: 7000,
        });
      } else {
        // En creación, si faltan campos recomendados, ofrecemos completarlos
        // ahora antes de cerrar — el equipo ya está creado, esto es opcional. #351
        if (!isEdit && equipoId) {
          // Para foto consideramos tanto foto_url ya seteada como pendingFile
          // recién subido (que ya se aplicó arriba con setValue).
          const missing: RecommendedField[] = [];
          const fotoTras = form.getValues("foto_url") || pendingFile;
          if (!fotoTras) missing.push("foto");
          if (!descripcion?.trim()) missing.push("descripcion");
          const serieClean = values.serie?.trim();
          if (!serieClean) missing.push("serie");
          if (!values.valor_reposicion || values.valor_reposicion === 0)
            missing.push("valor_reposicion");

          if (missing.length > 0 && onCreatedWithMissingRecommended) {
            const labels = missing.map((m) => RECOMMENDED_LABELS[m]).join(", ");
            toast.success("Equipo creado", {
              description: `Faltan datos recomendados: ${labels}`,
              action: {
                label: "Completar →",
                onClick: () => {
                  // Reabrimos el form en edit mode con el equipo recién creado.
                  // El form vuelve a abrirse con todos los datos cargados y los
                  // campos faltantes resaltados implícitamente vía el dashboard
                  // de calidad (#349).
                  const savedEquipo = { ...(initial ?? {}), ...payload, id: equipoId } as Equipo;
                  onCreatedWithMissingRecommended(savedEquipo, missing);
                },
              },
              duration: 12000,
            });
            onOpenChange(false);
            return;
          }
        }
        toast.success(
          isEdit
            ? closeOnSuccessRef.current
              ? "Equipo actualizado"
              : "Cambios aplicados"
            : "Equipo creado",
        );
      }
      if (closeOnSuccessRef.current) {
        onOpenChange(false);
      } else {
        // Aplicar: reseteamos el baseline de dirty para que las próximas
        // ediciones se detecten como nuevas y el confirm-close vuelva a
        // funcionar después de Aplicar.
        form.reset(form.getValues(), { keepValues: true });
      }
    },
    (errors) => {
      // Fallaba silencioso cuando había errores de validación zod (ej. nombre
      // vacío, número negativo). Acá los surfaceamos como toast con el primer
      // campo problemático para que el usuario sepa qué corregir.
      const entries = Object.entries(errors);
      if (entries.length === 0) {
        toast.error("Hay errores en el formulario, revisalos.");
        return;
      }
      const [field, error] = entries[0];
      const label = FIELD_LABELS[field] ?? field;
      const msg = (error as { message?: string } | undefined)?.message ?? "valor inválido";
      toast.error(`${label}: ${msg}`, {
        description:
          entries.length > 1 ? `Y ${entries.length - 1} campo(s) más con errores.` : undefined,
      });
    },
  );
}
