/**
 * EstudioIncluyeList — "qué incluye este turno" como un solo listado: Espacio
 * (siempre, franja horaria + precio editables INLINE en la misma fila) +
 * Pack + Recién pintado (chips para agregar/quitar, se muestran como fila
 * una vez agregados) + Equipos sueltos. Reemplaza los switches sueltos + el
 * campo de override separado + el desglose por-componente duplicado — una
 * sola forma de ver y tocar cada línea, con su precio en vivo al lado (el
 * front no calcula plata, MEMORIA 2026-06-29: los precios de Pack/Pintura/
 * sueltos vienen de `cotiz`, ya resuelto por el backend).
 *
 * El buscador de sueltos arranca colapsado detrás de un chip ("el dueño pidió
 * ver solo Espacio/Pack/Pintura por default"): NO es redundante con "Equipos"
 * del pedido (ese reserva/cobra por el rango de días completo; un suelto
 * reserva/cobra solo la franja horaria puntual del turno, cargo fijo, stock
 * duro) y en una reserva standalone del Estudio es la ÚNICA vía de sumar
 * equipo — por eso se colapsa, no se saca.
 *
 * La fila "Espacio" absorbe fecha/hora/horas (#1308, pedido del dueño: "no
 * quiero el modal... quiero una lista para seleccionar, como con los
 * equipos") — antes vivían en un grid de 3 columnas aparte, arriba de esta
 * lista, en cada caller (duplicado 2 veces); ahora es UNA sola fila de UNA
 * sola lista, igual de simple que la sección "Equipos" del pedido.
 *
 * Presentacional puro — sin query/mutation propias. Compartido por
 * `ReservaEstudioSection` (editar) y `NuevoTurnoEstudioForm` (alta): cada uno
 * maneja su propio estado y le pasa acá los callbacks, así las dos
 * superficies se ven y comportan igual sin duplicar el layout.
 */
import { useMemo, useState } from "react";
import { Plus, X } from "lucide-react";

import { Input } from "@/design-system/ui/input";
import { formatARS } from "@/lib/format";
import { buildTimeSlots } from "@/lib/estudio-slots";
import { type Equipo, type EstudioConfig, type EstudioCotizacion } from "@/lib/admin/api";
import { EquipoComboSearch } from "@/components/admin/pedido/EquipoComboSearch";
import { EquipoThumb } from "@/components/admin/pedido/EquipoThumb";
import type { DraftItem } from "@/components/admin/pedido/usePedidoDraft";
import { Field } from "./shared";

/** Solo lo que la UI necesita mostrar de un suelto agregado — no un `Equipo`
 *  completo (evita fabricar campos que no vienen ni del picker ni del
 *  detalle del pedido, como `dueno`/`visible_catalogo`). Fuente única —
 *  antes duplicado byte a byte en `ReservaDialog` y `ReservaEstudioSection`. */
export type SueltoLocal = {
  equipo_id: number;
  nombre: string;
  marca: string | null;
  nombre_publico?: string | null;
  foto_url: string | null;
  precio_jornada: number | null;
  cantidad: number;
};

function AddChip({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-dashed hairline px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted/30"
    >
      <Plus className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{label}</span>
    </button>
  );
}

export function EstudioIncluyeList({
  estudio,
  fecha,
  onChangeFecha,
  start,
  onChangeStart,
  horas,
  onChangeHoras,
  conPromo,
  onTogglePromo,
  pinturaReciente,
  onTogglePintura,
  sueltos,
  onAddSuelto,
  onRemoveSuelto,
  onChangeSueltoCantidad,
  espacioOverride,
  onChangeEspacioOverride,
  cotiz,
}: {
  estudio: EstudioConfig;
  fecha: string;
  onChangeFecha: (v: string) => void;
  start: string;
  onChangeStart: (v: string) => void;
  horas: number;
  onChangeHoras: (v: number) => void;
  conPromo: boolean;
  onTogglePromo: (v: boolean) => void;
  pinturaReciente: boolean;
  onTogglePintura: (v: boolean) => void;
  sueltos: SueltoLocal[];
  onAddSuelto: (eq: Equipo) => void;
  onRemoveSuelto: (equipoId: number) => void;
  onChangeSueltoCantidad: (equipoId: number, cantidad: number) => void;
  espacioOverride: string;
  onChangeEspacioOverride: (v: string) => void;
  cotiz?: EstudioCotizacion;
}) {
  const slots = useMemo(
    () => buildTimeSlots(estudio.open_hour, estudio.close_hour, estudio.min_horas || 1),
    [estudio.open_hour, estudio.close_hour, estudio.min_horas],
  );

  // Colapsado por default (el dueño pidió ver solo Espacio/Pack/Pintura) —
  // sueltos ya agregados siguen mostrándose igual, esto solo esconde la vía
  // para agregar uno nuevo hasta que se pida explícitamente.
  const [showBuscador, setShowBuscador] = useState(false);

  const existingAsDraftItems: DraftItem[] = useMemo(
    () =>
      sueltos.map((s) => ({
        uid: String(s.equipo_id),
        equipo_id: s.equipo_id,
        cantidad: s.cantidad,
        precio_jornada: s.precio_jornada ?? 0,
        nombre: s.nombre,
        marca: s.marca,
        nombre_publico: s.nombre_publico,
        foto_url: s.foto_url,
      })),
    [sueltos],
  );

  return (
    <Field label="Qué incluye este turno">
      {showBuscador ? (
        <EquipoComboSearch
          existing={existingAsDraftItems}
          stockMap={{}}
          onAdd={onAddSuelto}
          placeholder="Buscar equipo para sumar…"
        />
      ) : (
        <AddChip label="Agregar equipo puntual" onClick={() => setShowBuscador(true)} />
      )}

      <ul className="mt-2 divide-y hairline rounded-md border hairline">
        {/* Espacio — siempre presente, no se puede quitar (es la base del
            turno); franja horaria + precio se editan ACÁ, inline, en la
            misma fila (#1308 — antes vivían en un grid aparte arriba de
            toda la lista, que es justo lo que se leía como "un form"). */}
        <li className="flex flex-wrap items-center gap-2 px-2.5 py-2">
          <span className="shrink-0 text-sm">Espacio</span>
          <Input
            type="date"
            aria-label="Fecha"
            value={fecha}
            onChange={(e) => onChangeFecha(e.target.value)}
            className="h-8 w-[136px] text-sm"
          />
          <select
            aria-label="Hora"
            value={start}
            onChange={(e) => onChangeStart(e.target.value)}
            className="h-8 rounded-md border hairline bg-background px-1.5 text-sm"
          >
            {slots.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <div className="flex items-center gap-1">
            <Input
              type="number"
              aria-label="Horas"
              min={estudio.min_horas || 1}
              value={horas}
              onChange={(e) => onChangeHoras(Number(e.target.value) || 0)}
              className="h-8 w-14 text-center text-sm"
            />
            <span className="text-xs text-muted-foreground">h</span>
          </div>
          <Input
            type="number"
            min={0}
            value={espacioOverride}
            onChange={(e) => onChangeEspacioOverride(e.target.value)}
            placeholder={String((estudio.precio_hora || 0) * horas)}
            className="ml-auto h-8 w-24 text-right text-sm"
          />
        </li>

        {conPromo && (
          <li className="flex items-center gap-2 px-2.5 py-2">
            <span className="min-w-0 flex-1 truncate text-sm">
              {estudio.promo?.nombre || "Pack"}
            </span>
            <span className="text-sm tabular-nums">{cotiz ? formatARS(cotiz.promo) : "…"}</span>
            <button
              type="button"
              onClick={() => onTogglePromo(false)}
              className="text-muted-foreground hover:text-destructive"
            >
              <X className="h-4 w-4" />
            </button>
          </li>
        )}

        {pinturaReciente && (
          <li className="flex items-center gap-2 px-2.5 py-2">
            <span className="min-w-0 flex-1 truncate text-sm">Recién pintado</span>
            <span className="text-sm tabular-nums">
              {cotiz ? formatARS(cotiz.pintura_reciente) : "…"}
            </span>
            <button
              type="button"
              onClick={() => onTogglePintura(false)}
              className="text-muted-foreground hover:text-destructive"
            >
              <X className="h-4 w-4" />
            </button>
          </li>
        )}

        {sueltos.map((s) => {
          const subtotal = cotiz?.sueltos.find((cs) => cs.equipo_id === s.equipo_id)?.subtotal;
          return (
            <li key={s.equipo_id} className="flex items-center gap-2 px-2.5 py-2">
              <EquipoThumb src={s.foto_url} alt={s.nombre} className="h-8 w-8 shrink-0" />
              <span className="min-w-0 flex-1 truncate text-sm">{s.nombre}</span>
              {subtotal !== undefined && (
                <span className="text-sm tabular-nums text-muted-foreground">
                  {formatARS(subtotal)}
                </span>
              )}
              <Input
                type="number"
                min={1}
                value={s.cantidad}
                onChange={(e) =>
                  onChangeSueltoCantidad(s.equipo_id, Math.max(1, Number(e.target.value) || 1))
                }
                className="h-8 w-16 text-center"
              />
              <button
                type="button"
                onClick={() => onRemoveSuelto(s.equipo_id)}
                className="text-muted-foreground hover:text-destructive"
              >
                <X className="h-4 w-4" />
              </button>
            </li>
          );
        })}
      </ul>

      {(!conPromo && estudio.promo_combo_id) || !pinturaReciente ? (
        <div className="mt-2 flex gap-2">
          {!conPromo && estudio.promo_combo_id && (
            <AddChip label={estudio.promo?.nombre || "Pack"} onClick={() => onTogglePromo(true)} />
          )}
          {!pinturaReciente && (
            <AddChip label="Recién pintado" onClick={() => onTogglePintura(true)} />
          )}
        </div>
      ) : null}
    </Field>
  );
}
