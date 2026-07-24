/**
 * Agenda — selector Semana/Mes de la ocupación del Estudio. Semana
 * (`AgendaSemanal`) es la grilla día×hora para operar el día a día; Mes
 * (`AgendaMensual`) es la vista panorámica para planificar con antelación.
 * Ambas leen `GET /admin/estudio/agenda`, cada una con su propio rango.
 */
import { useState } from "react";

import { SegmentedControl } from "@/design-system/ui/segmented-control";
import { AgendaSemanal } from "./AgendaSemanal";
import { AgendaMensual } from "./AgendaMensual";

export function Agenda({
  openHour,
  closeHour,
  onNavigatePedido,
}: {
  openHour: number;
  closeHour: number;
  onNavigatePedido: (id: number) => void;
}) {
  const [vista, setVista] = useState<"semana" | "mes">("semana");

  const vistaSwitch = (
    <SegmentedControl
      variant="pill"
      value={vista}
      onChange={(v) => setVista(v as "semana" | "mes")}
      options={[
        { value: "semana", label: "Semana" },
        { value: "mes", label: "Mes" },
      ]}
    />
  );

  return vista === "semana" ? (
    <AgendaSemanal
      openHour={openHour}
      closeHour={closeHour}
      onNavigatePedido={onNavigatePedido}
      vistaSwitch={vistaSwitch}
    />
  ) : (
    <AgendaMensual onNavigatePedido={onNavigatePedido} vistaSwitch={vistaSwitch} />
  );
}
