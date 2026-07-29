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
 * el modo alta de `ReservaDialog` — incluida la franja horaria, que
 * `EstudioIncluyeList` absorbe como parte de la fila "Espacio" (#1308: ya no
 * hay un grid Fecha/Hora/Horas aparte acá, quedaba duplicado con el del alta).
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard } from "lucide-react";
import { toast } from "sonner";

import { Section } from "@/design-system/composites/Section";
import { Spinner } from "@/design-system/ui/spinner";
import { SaveIndicator } from "@/components/admin/pedido/PedidoPageHelpers";
import { formatARS } from "@/lib/format";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { espacioOverrideInicial } from "@/lib/estudio-slots";
import { estudioAdminApi, type Equipo, type EstudioConfig, type Pedido } from "@/lib/admin/api";
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
  accion,
  onSaved,
}: {
  pedido: Pedido;
  estudio: EstudioConfig;
  /** Acción del encabezado de la tarjeta — hoy, el ✕ que saca el turno del
   *  pedido. Va en el header (slot `actions` del `Section`) y no como una fila
   *  colgada abajo, que era donde estaba y no se encontraba. */
  accion?: ReactNode;
  onSaved?: (pedido: Pedido) => void;
}) {
  const qc = useQueryClient();

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
      // La MISMA tarifa que se va a persistir al guardar (línea de abajo) —
      // así lo que muestra la fila "Espacio" y el Total es lo que se cobra, no
      // el precio de lista.
      espacio_monto: espacioOverride.trim() ? Number(espacioOverride) : null,
    }),
    [fecha, start, horas, conPromo, pinturaReciente, sueltosInput, pedido.id, espacioOverride],
  );
  const cotizarDebounced = useDebouncedValue(cotizarParams, 400);

  const cotizarQ = useQuery({
    queryKey: ["admin", "estudio", "cotizar", cotizarDebounced],
    queryFn: () => estudioAdminApi.cotizarReserva(cotizarDebounced),
    enabled: !!fecha && !!start && horas >= (estudio.min_horas || 1),
  });

  // Lo que se persiste, serializado — la unidad de comparación del autosave.
  const payload = useMemo(
    () => ({
      fecha,
      start,
      horas,
      con_promo: conPromo,
      pintura_reciente: pinturaReciente,
      sueltos: sueltosInput,
      espacio_monto: espacioOverride.trim() ? Number(espacioOverride) : null,
    }),
    [fecha, start, horas, conPromo, pinturaReciente, sueltosInput, espacioOverride],
  );
  const payloadKey = useMemo(() => JSON.stringify(payload), [payload]);
  /** Último payload que la base ya tiene. `null` = recién hidratado, todavía no
   *  sabemos cuál es (lo fija el primer pase del efecto de autosave). */
  const guardadoRef = useRef<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => estudioAdminApi.updateReserva(pedido.id, payload),
    onSuccess: (actualizado) => {
      guardadoRef.current = payloadKey;
      if (actualizado.promo_advertencia) {
        toast.warning("La promo se reservó incompleta", {
          description: actualizado.promo_advertencia,
          duration: 7000,
        });
      }
      // El PATCH ya devolvió el turno actualizado: se ESCRIBE en la caché en
      // vez de invalidar. Invalidar disparaba un GET del pedido entero por cada
      // guardado —y como el caller invalidaba la misma key, salían dos— y con
      // él un re-render de toda la pantalla: eso es lo que se sentía como que
      // "se recarga la página".
      qc.setQueryData(["admin", "pedido", pedido.id], actualizado);
      // Estas son de OTRAS pantallas (agenda/lista del Estudio): no están
      // montadas acá, así que invalidarlas no dispara ningún fetch ahora —
      // solo marca que están viejas para cuando se abran.
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

  // Autosave con debounce — TODO lo demás del pedido se guarda solo (decisión
  // del dueño: "todo en el pedido se autosalva, creo que es mejor así"), así
  // que un botón "Guardar cambios" acá era la única cosa de la pantalla que
  // había que acordarse de apretar. Mismo patrón que `usePedidoDraft`: se
  // compara contra lo último que la base confirmó y se dispara pasado el
  // debounce. El primer pase tras hidratar solo REGISTRA el estado actual (no
  // guarda): venía de la base, ya está guardado.
  useEffect(() => {
    if (!puedeGuardar) return;
    if (guardadoRef.current === null) {
      guardadoRef.current = payloadKey;
      return;
    }
    if (guardadoRef.current === payloadKey) return;
    const t = setTimeout(() => mutation.mutate(), 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- autosave con debounce: dispara por el payload; incluir `mutation` reiniciaría el timer en cada render
  }, [payloadKey, puedeGuardar]);

  const saveStatus = mutation.isPending
    ? "saving"
    : mutation.isError
      ? "error"
      : guardadoRef.current !== null && guardadoRef.current !== payloadKey
        ? "dirty"
        : "saved";

  return (
    <Section
      variant="card"
      tone="elevated"
      icon={Clapperboard}
      title="Reserva del Estudio"
      actions={accion}
    >
      <div className="space-y-4">
        <EstudioIncluyeList
          estudio={estudio}
          fecha={fecha}
          onChangeFecha={setFecha}
          start={start}
          onChangeStart={setStart}
          horas={horas}
          onChangeHoras={setHoras}
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

        {/* Total en vivo — el front no calcula, solo muestra (2026-06-29). El
            estado del guardado va acá al lado: se guarda solo, pero tiene que
            poder verse que se guardó. */}
        <div className="rounded-lg border hairline bg-muted/20 p-3 text-sm">
          {cotizarQ.isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Spinner size="sm" /> Calculando…
            </div>
          ) : cotiz ? (
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2 font-semibold text-ink">
                <span>Total</span>
                <span className="flex items-center gap-2">
                  <SaveIndicator status={saveStatus} />
                  {formatARS(cotiz.monto_total)}
                </span>
              </div>
              {!cotiz.espacio_disponible && (
                <p className="mt-1 text-xs text-destructive">
                  El espacio no está disponible: {cotiz.espacio_motivo}
                </p>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </Section>
  );
}
