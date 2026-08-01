/**
 * Organismos del portal del cliente — lo que ve el cliente logueado en /cliente.
 * El card del pedido (con su plata y estado), la línea de tiempo del pedido, las
 * tarjetas de stat del panel, el bloque de identidad (verificado / sin verificar)
 * y la sección de listas guardadas.
 *
 * Estas piezas viven en `components/cliente/ClientePortal*`. Acá se muestran con los escenarios demo
 * canónicos: el mismo pedido en tres momentos de plata, el cliente en tres
 * estados de identidad. Reciben todo por props (datos demo + callbacks no-op).
 */
import { useState } from "react";

import { type CatalogSection } from "../types";
import { Caption, Sample, Stack } from "../catalog-kit";

import { StatCard } from "@/design-system/composites/StatCard";
import { PedidoCard, PedidoTimeline } from "@/components/cliente/ClientePortalPedido";
import { IdentidadSection } from "@/components/cliente/IdentidadSection";
import { ListasSection } from "@/components/cliente/ClientePortalListas";
import { type Pedido } from "@/components/cliente/ClientePortalTypes";

import {
  pedidoPresupuesto,
  pedidoDebe,
  pedidoPagado,
  perfilVerificado,
  perfilSinVerificar,
  perfilRechazado,
  listasDemo,
  equiposDemo,
  noopAsync,
} from "../fixtures";

// ── Card del pedido (controlado: expandir/colapsar local) ─────────────────────
function PedidoCardDemo({
  pedido,
  defaultExpanded = false,
}: {
  pedido: Pedido;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  return (
    <PedidoCard
      pedido={pedido}
      expanded={expanded}
      onToggle={() => setExpanded((v) => !v)}
      perfilImpuestos={null}
    />
  );
}

export const clienteOrganismosSection: CatalogSection = {
  id: "cliente-organismos",
  title: "Portal del cliente (organismos)",
  hint: "Lo que ve el cliente logueado: el card del pedido (estado + plata visibles), la línea de tiempo, los stats del panel, la identidad y las listas. Mismo pedido en tres momentos de plata; mismo cliente en tres estados de identidad.",
  specimens: [
    {
      name: "StatCard",
      files: ["design-system/composites/StatCard.tsx"],
      blurb:
        "Tarjeta de métrica del panel: rótulo mono + número grande tabular. valueClassName tiñe el valor (ej. facturado en verde-ink). Acá en su uso de dominio (panel del cliente); la ficha genérica vive en Layout & Estructura.",
      render: () => (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Pedidos activos" value="2" meta="1 sin confirmar" />
          <StatCard label="Listas guardadas" value="3" />
          <StatCard label="Facturado 2026" value="$1.240.000" valueClassName="text-verde-ink" />
          <StatCard label="Saldo pendiente" value="$240.000" meta="pedido R-1039" />
        </div>
      ),
    },
    {
      name: "PedidoCard",
      files: ["components/cliente/ClientePortalPedido.tsx"],
      blurb:
        "El card del pedido en el portal: número, estado, fechas, total y saldo. Click expande el detalle (ítems, timeline, documentos, acciones). Las tres etapas de plata.",
      render: () => (
        <div className="mx-auto flex max-w-2xl flex-col gap-3">
          <Sample label="sin iniciar — solicitud, nada pagado">
            <PedidoCardDemo pedido={pedidoPresupuesto} />
          </Sample>
          <Sample label="con seña — confirmado, debe saldo">
            <PedidoCardDemo pedido={pedidoDebe} />
          </Sample>
          <Sample label="pago — finalizado, saldado (expandido)">
            <PedidoCardDemo pedido={pedidoPagado} defaultExpanded />
          </Sample>
        </div>
      ),
    },
    {
      name: "PedidoTimeline",
      files: ["components/cliente/ClientePortalPedido.tsx"],
      blurb:
        "La línea de tiempo del pedido: solicitado → confirmado → retirado → devuelto. Marca el paso actual según el estado.",
      render: () => (
        <div className="mx-auto flex max-w-md flex-col gap-6">
          <Sample label="solicitud — paso 1">
            <PedidoTimeline pedido={pedidoPresupuesto} />
          </Sample>
          <Sample label="finalizado — completo">
            <PedidoTimeline pedido={pedidoPagado} />
          </Sample>
        </div>
      ),
    },
    {
      name: "IdentidadSection",
      files: ["components/cliente/IdentidadSection.tsx"],
      blurb:
        "El bloque de identidad del perfil: badge de estado + CTA para verificar con RENAPER. Verificado, sin verificar y rechazado (con motivo).",
      render: () => (
        <div className="mx-auto flex max-w-md flex-col gap-5">
          <Sample label="verificado — DNI validado">
            <IdentidadSection perfil={perfilVerificado} compact />
          </Sample>
          <Sample label="sin verificar — cuenta liviana">
            <IdentidadSection perfil={perfilSinVerificar} compact />
          </Sample>
          <Sample label="rechazado — muestra el motivo">
            <IdentidadSection perfil={perfilRechazado} compact />
          </Sample>
        </div>
      ),
    },
    {
      name: "ListasSection",
      files: ["components/cliente/ClientePortalListas.tsx"],
      blurb:
        'La tab "mis listas": composiciones guardadas que se reservan de un toque. El contenido se resuelve en vivo del catálogo (acá, de los equipos demo).',
      render: () => (
        <Stack>
          <Caption>
            Las listas guardan solo equipo_id + cantidad; el nombre, la foto y el precio salen del
            catálogo (acá, de los tres equipos demo).
          </Caption>
          <div className="-mx-4 rounded-xl border hairline">
            <ListasSection
              listas={listasDemo}
              loading={false}
              allEquipos={equiposDemo}
              onRename={noopAsync}
              onRemoveItem={noopAsync}
              onDelete={noopAsync}
            />
          </div>
        </Stack>
      ),
    },
  ],
};
