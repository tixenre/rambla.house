import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Gift, Pencil } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { MoneyInput } from "@/design-system/ui/money-input";
import { Textarea } from "@/design-system/ui/textarea";
import { estudioAdminApi } from "@/lib/admin/api";
import type { EstudioConfig } from "@/lib/admin/api";
import { formatARS } from "@/lib/format";
import { Section, Field } from "./shared";

/** Gestión de la promo de equipos (combo real que reemplaza al pack curado,
 *  #1283 Fase 5). Si ya existe (`config.promo_combo_id`), el PRECIO se edita
 *  acá (`pack_precio`, fijo — no se deriva más de los componentes, ver
 *  docstring de `crear_promo`); los EQUIPOS que la componen se editan desde
 *  Equipos como cualquier otro combo (evita mantener dos formularios para lo
 *  mismo). La descripción también se edita acá (`pack_descripcion`, viva:
 *  `_promo_info` la reusa como descripción de la promo actual). Si no existe,
 *  ofrece crearla desde el pack curado actual. */
export function PromoSection({ config }: { config: EstudioConfig }) {
  const qc = useQueryClient();
  const [nombre, setNombre] = useState(config.pack_nombre || "");
  const [precioObjetivo, setPrecioObjetivo] = useState(config.pack_precio || 0);
  const [descripcion, setDescripcion] = useState(config.pack_descripcion || "");
  // Precio FIJO de la promo YA CREADA — estado propio, separado de
  // `precioObjetivo` (que es el precio con el que se CREA una promo nueva,
  // rama de abajo). Mismo campo (`pack_precio`), dos momentos distintos.
  const [precioFijo, setPrecioFijo] = useState(config.pack_precio || 0);

  const crearMut = useMutation({
    mutationFn: () =>
      estudioAdminApi.crearPromoDesdePack({
        nombre: nombre.trim() || undefined,
        precio_objetivo: precioObjetivo,
      }),
    onSuccess: (res) => {
      qc.setQueryData(["admin", "estudio"], res);
      toast.success("Promo creada");
    },
    onError: (e) => toast.error("No se pudo crear la promo", { description: (e as Error).message }),
  });

  const guardarDescripcionMut = useMutation({
    mutationFn: () => estudioAdminApi.update({ pack_descripcion: descripcion }),
    onSuccess: (res) => {
      qc.setQueryData(["admin", "estudio"], res);
      toast.success("Descripción guardada");
    },
    onError: (e) =>
      toast.error("No se pudo guardar la descripción", { description: (e as Error).message }),
  });

  const guardarPrecioMut = useMutation({
    mutationFn: () => estudioAdminApi.update({ pack_precio: precioFijo }),
    onSuccess: (res) => {
      qc.setQueryData(["admin", "estudio"], res);
      toast.success("Precio guardado");
    },
    onError: (e) =>
      toast.error("No se pudo guardar el precio", { description: (e as Error).message }),
  });

  if (config.promo_combo_id && config.promo) {
    return (
      <Section title="Promo de equipos">
        <div className="flex items-center gap-3 rounded-lg border hairline px-3 py-2.5">
          <div className="relative aspect-square w-12 shrink-0 overflow-hidden rounded bg-muted/40">
            {config.promo.foto_url ? (
              <img
                loading="lazy"
                decoding="async"
                src={config.promo.foto_url}
                alt={config.promo.nombre}
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="grid h-full w-full place-items-center">
                <Gift className="h-5 w-5 text-muted-foreground" />
              </div>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium text-ink">{config.promo.nombre}</div>
            <div className="text-sm text-muted-foreground">
              {formatARS(config.promo.precio)} · oculta del catálogo público
            </div>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/admin/equipos/$id/editar" params={{ id: String(config.promo.equipo_id) }}>
              <Pencil className="h-4 w-4" /> Editar equipos
            </Link>
          </Button>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">
          El precio es fijo — se pone acá y se mantiene, aunque cambien los precios de los equipos
          que la componen. Los equipos que incluye se editan desde Equipos.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <Field label="Precio fijo">
            <MoneyInput value={precioFijo} onChange={setPrecioFijo} />
          </Field>
          <Button
            variant="outline"
            size="sm"
            disabled={guardarPrecioMut.isPending || precioFijo === (config.pack_precio || 0)}
            onClick={() => guardarPrecioMut.mutate()}
          >
            Guardar precio
          </Button>
        </div>
        <div className="mt-3">
          <Field label="Descripción de la promo">
            <Textarea
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              rows={2}
              placeholder="Qué incluye, para qué sirve…"
            />
          </Field>
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            disabled={
              guardarDescripcionMut.isPending || descripcion === (config.pack_descripcion || "")
            }
            onClick={() => guardarDescripcionMut.mutate()}
          >
            Guardar descripción
          </Button>
        </div>
      </Section>
    );
  }

  return (
    <Section title="Promo de equipos">
      <p className="-mt-2 mb-3 text-sm text-muted-foreground">
        Creá el combo real a partir del pack curado de abajo, a un precio fijo — reemplaza al pack
        para la reserva pública.
      </p>
      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <Field label="Nombre">
          <Input
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            placeholder="Pack Todo Incluido"
          />
        </Field>
        <Field label="Precio objetivo">
          <MoneyInput value={precioObjetivo} onChange={setPrecioObjetivo} />
        </Field>
      </div>
      <Button
        onClick={() => crearMut.mutate()}
        disabled={crearMut.isPending || precioObjetivo <= 0}
        className="mt-3"
      >
        Crear promo desde el pack
      </Button>
    </Section>
  );
}
