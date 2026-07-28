/**
 * ReservaEstudioSection — franja/tarifa/promo/sueltos de un turno YA
 * EXISTENTE del Estudio (`tipo='estudio'`). Fase 2, #1308: extraída del modo
 * edición de `ReservaDialog` para que la página del pedido pueda administrar
 * el turno inline, sin un diálogo aparte — una sola forma de editar un
 * turno. El modo alta (cliente + estado inicial) sigue solo en
 * `ReservaDialog`, no reusa esta sección.
 *
 * Autocontenida (estado + cotización en vivo + guardado): hidrata desde
 * `pedido`, cotiza vía `GET /admin/estudio/reservas/cotizar` y guarda con
 * `PATCH /admin/estudio/reservas/{id}` — mismos endpoints que el diálogo, sin
 * superficie nueva. El front no calcula plata (MEMORIA 2026-06-29): el
 * desglose se pide en vivo y solo se muestra. El listado "qué incluye"
 * (Espacio/Pack/Pintura/sueltos) vive en `EstudioIncluyeList`, compartido con
 * el modo alta de `ReservaDialog`.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard } from "lucide-react";
import { toast } from "sonner";

import { Section } from "@/design-system/composites/Section";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Spinner } from "@/design-system/ui/spinner";
import { formatARS } from "@/lib/format";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { buildTimeSlots, espacioOverrideInicial } from "@/lib/estudio-slots";
import { estudioAdminApi, type Equipo, type EstudioConfig, type Pedido } from "@/lib/admin/api";
import { Field } from "./shared";
import { EstudioIncluyeList, type SueltoLocal } from "./EstudioIncluyeList";

// Debe coincidir con `NOMBRE_ITEM_PINTURA_RECIENTE`
// (backend/services/estudio/commands/reserva.py) — mismo criterio que
// ReservaDialog para detectar la línea al hidratar.
const NOMBRE_ITEM_PINTURA_RECIENTE = "Recién pintado";

function horasEntre(desde?: string | null, hasta?: string | null, fallback = 2): number {
  if (!desde || !hasta) return fallback;
  const ms = new Date(hasta).getTime() - new Date(desde).getTime();
  return Math.max(1, Math.round(ms / 3_600_000));
}

export function ReservaEstudioSection({
  pedido,
  estudio,
  onSaved,
}: {
  pedido: Pedido;
  estudio: EstudioConfig;
  onSaved?: (pedido: Pedido) => void;
}) {
  const qc = useQueryClient();

  const slots = useMemo(
    () => buildTimeSlots(estudio.open_hour, estudio.close_hour, estudio.min_horas || 1),
    [estudio.open_hour, estudio.close_hour, estudio.min_horas],
  );

  const [fecha, setFecha] = useState(() => pedido.fecha_desde?.slice(0, 10) ?? "");
  const [start, setStart] = useState(() => pedido.fecha_desde?.slice(11, 16) ?? "");
  const [horas, setHoras] = useState(() =>
    horasEntre(pedido.fecha_desde, pedido.fecha_hasta, estudio.min_horas || 2),
  );
  const [conPromo, setConPromo] = useState(false);
  const [pinturaReciente, setPinturaReciente] = useState(false);
  const [sueltos, setSueltos] = useState<SueltoLocal[]>([]);
  const [espacioOverride, setEspacioOverride] = useState("");

  // Hidratación — solo al cambiar de pedido, no en cada tecla (mismo criterio
  // que `ReservaDialog`).
  useEffect(() => {
    const centinela = estudio.equipo_id;
    const promoId = estudio.promo_combo_id;
    const otros = pedido.items.filter((it) => it.equipo_id !== centinela);
    setConPromo(!!promoId && otros.some((it) => it.equipo_id === promoId));
    setPinturaReciente(
      otros.some((it) => it.equipo_id === null && it.nombre_libre === NOMBRE_ITEM_PINTURA_RECIENTE),
    );
    setSueltos(
      otros
        .filter((it) => it.equipo_id !== null && it.equipo_id !== promoId)
        .map((it) => ({
          equipo_id: it.equipo_id!,
          nombre: it.nombre,
          marca: it.marca,
          nombre_publico: it.nombre_publico,
          foto_url: it.foto_url ?? null,
          precio_jornada: it.precio_jornada,
          cantidad: it.cantidad,
        })),
    );
    const horasActuales = horasEntre(
      pedido.fecha_desde,
      pedido.fecha_hasta,
      estudio.min_horas || 2,
    );
    const centinelaItem = pedido.items.find((it) => it.equipo_id === centinela);
    const autoEsperado = (estudio.precio_hora || 0) * horasActuales;
    setEspacioOverride(espacioOverrideInicial(centinelaItem?.precio_jornada, autoEsperado));
    setFecha(pedido.fecha_desde?.slice(0, 10) ?? "");
    setStart(pedido.fecha_desde?.slice(11, 16) ?? "");
    setHoras(horasActuales);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- solo al cambiar de pedido, no en cada campo
  }, [pedido.id]);

  const sueltosInput = useMemo(
    () => sueltos.map((s) => ({ equipo_id: s.equipo_id, cantidad: s.cantidad })),
    [sueltos],
  );

  const cotizarParams = useMemo(
    () => ({
      fecha,
      start,
      horas,
      con_promo: conPromo,
      pintura_reciente: pinturaReciente,
      sueltos: sueltosInput,
      // Excluye el propio turno del chequeo de disponibilidad — si no,
      // siempre se vería "ocupado" por su propia franja.
      pedido_id: pedido.id,
    }),
    [fecha, start, horas, conPromo, pinturaReciente, sueltosInput, pedido.id],
  );
  const cotizarDebounced = useDebouncedValue(cotizarParams, 400);

  const cotizarQ = useQuery({
    queryKey: ["admin", "estudio", "cotizar", cotizarDebounced],
    queryFn: () => estudioAdminApi.cotizarReserva(cotizarDebounced),
    enabled: !!fecha && !!start && horas >= (estudio.min_horas || 1),
  });

  const mutation = useMutation({
    mutationFn: () =>
      estudioAdminApi.updateReserva(pedido.id, {
        fecha,
        start,
        horas,
        con_promo: conPromo,
        pintura_reciente: pinturaReciente,
        sueltos: sueltosInput,
        espacio_monto: espacioOverride.trim() ? Number(espacioOverride) : null,
      }),
    onSuccess: (actualizado) => {
      toast.success("Turno actualizado");
      if (actualizado.promo_advertencia) {
        toast.warning("La promo se reservó incompleta", {
          description: actualizado.promo_advertencia,
          duration: 7000,
        });
      }
      qc.invalidateQueries({ queryKey: ["admin", "pedido", pedido.id] });
      qc.invalidateQueries({ queryKey: ["admin", "estudio", "reservas"] });
      qc.invalidateQueries({ queryKey: ["admin", "estudio", "agenda"] });
      onSaved?.(actualizado);
    },
    onError: (e) => toast.error("No se pudo guardar", { description: (e as Error).message }),
  });

  const handleAddSuelto = (eq: Equipo) => {
    setSueltos((prev) => {
      const existing = prev.find((s) => s.equipo_id === eq.id);
      if (existing) {
        return prev.map((s) => (s.equipo_id === eq.id ? { ...s, cantidad: s.cantidad + 1 } : s));
      }
      return [
        ...prev,
        {
          equipo_id: eq.id,
          nombre: eq.nombre,
          marca: eq.marca,
          nombre_publico: eq.nombre_publico,
          foto_url: eq.foto_url,
          precio_jornada: eq.precio_jornada,
          cantidad: 1,
        },
      ];
    });
  };
  const handleRemoveSuelto = (equipoId: number) =>
    setSueltos((prev) => prev.filter((x) => x.equipo_id !== equipoId));
  const handleChangeSueltoCantidad = (equipoId: number, cantidad: number) =>
    setSueltos((prev) => prev.map((x) => (x.equipo_id === equipoId ? { ...x, cantidad } : x)));

  const cotiz = cotizarQ.data;
  const puedeGuardar = !!fecha && !!start && horas >= (estudio.min_horas || 1);

  return (
    <Section variant="card" tone="elevated" icon={Clapperboard} title="Reserva del Estudio">
      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <Field label="Fecha">
            <Input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
          </Field>
          <Field label="Hora">
            <select
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="h-9 w-full rounded-md border hairline bg-background px-2 text-sm"
            >
              {slots.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label={`Horas · mín ${estudio.min_horas}`}>
            <Input
              type="number"
              min={estudio.min_horas || 1}
              value={horas}
              onChange={(e) => setHoras(Number(e.target.value) || 0)}
            />
          </Field>
        </div>

        <EstudioIncluyeList
          estudio={estudio}
          horas={horas}
          conPromo={conPromo}
          onTogglePromo={setConPromo}
          pinturaReciente={pinturaReciente}
          onTogglePintura={setPinturaReciente}
          sueltos={sueltos}
          onAddSuelto={handleAddSuelto}
          onRemoveSuelto={handleRemoveSuelto}
          onChangeSueltoCantidad={handleChangeSueltoCantidad}
          espacioOverride={espacioOverride}
          onChangeEspacioOverride={setEspacioOverride}
          cotiz={cotiz}
        />

        {/* Total en vivo — el front no calcula, solo muestra (2026-06-29). */}
        <div className="rounded-lg border hairline bg-muted/20 p-3 text-sm">
          {cotizarQ.isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Spinner size="sm" /> Calculando…
            </div>
          ) : cotiz ? (
            <div className="space-y-1">
              <div className="flex justify-between font-semibold text-ink">
                <span>Total</span>
                <span>{formatARS(cotiz.monto_total)}</span>
              </div>
              {!cotiz.espacio_disponible && (
                <p className="mt-1 text-xs text-destructive">
                  El espacio no está disponible: {cotiz.espacio_motivo}
                </p>
              )}
            </div>
          ) : null}
        </div>

        <Button
          onClick={() => mutation.mutate()}
          disabled={!puedeGuardar || mutation.isPending}
          className="w-full"
        >
          {mutation.isPending ? <Spinner size="sm" className="mr-1.5" /> : null}
          Guardar cambios
        </Button>
      </div>
    </Section>
  );
}
