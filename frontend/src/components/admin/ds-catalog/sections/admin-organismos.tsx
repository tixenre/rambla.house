/**
 * Organismos del back-office — las piezas ENSAMBLADAS del panel admin (/admin/*).
 * El listado de pedidos (tabla con fila expandible), el modal de registrar pago,
 * la paleta de comandos ⌘F y la barra lateral de navegación.
 *
 * Algunas piezas son fixed/portaled (la paleta) o viven al borde de la página
 * (la sidebar): se muestran con el patrón honesto — un disparador que abre el
 * componente REAL, o una ficha que apunta a la pieza viva — en vez de una
 * maqueta que mienta. La vitrina corre dentro de /admin/diseno (ya logueado),
 * así que estos componentes tienen su contexto real (router, query, sesión).
 */
import { useState } from "react";

import { Button } from "@/design-system/ui/button";
import { type CatalogSection } from "../types";
import { Caption, Stack } from "../catalog-kit";

import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { RegistrarPagoModal } from "@/components/admin/pedido/RegistrarPagoModal";
import { EstadoBadge } from "@/design-system/ui/EstadoBadge";
import { ClienteAvatar } from "@/design-system/ui/ClienteAvatar";
import { ESTADO_LABEL, type Pedido as AdminPedido } from "@/lib/admin/api";
import { formatARS, formatFechaCorta } from "@/lib/format";

import { pedidosAdminDemo, adminPedidoConfirmado } from "../fixtures";

const saldoDe = (p: AdminPedido) => Math.max(0, (p.monto_total ?? 0) - (p.monto_pagado ?? 0));

// ── Tabla de pedidos del back-office (con fila expandible) ────────────────────
function PedidosTableDemo() {
  const [expandedId, setExpandedId] = useState<number | null>(adminPedidoConfirmado.id);
  const columns: Column<AdminPedido>[] = [
    {
      header: "Pedido",
      cell: (p) => (
        <span className="font-mono text-xs text-muted-foreground">#{p.numero_pedido}</span>
      ),
    },
    {
      header: "Cliente",
      cell: (p) => (
        <div className="flex min-w-0 items-center gap-2">
          <ClienteAvatar nombre={p.cliente_nombre} className="h-7 w-7 text-2xs" />
          <span className="truncate">{p.cliente_nombre}</span>
        </div>
      ),
    },
    {
      header: "Fechas",
      cell: (p) => (
        <span className="whitespace-nowrap text-muted-foreground">
          {formatFechaCorta(p.fecha_desde)} → {formatFechaCorta(p.fecha_hasta)}
        </span>
      ),
    },
    {
      header: "Estado",
      cell: (p) => <EstadoBadge estado={p.estado} label={ESTADO_LABEL[p.estado]} />,
    },
    {
      header: "Total",
      align: "right",
      className: "tabular-nums",
      cell: (p) => (
        <div>
          <div className="text-ink">{formatARS(p.monto_total ?? 0)}</div>
          {saldoDe(p) > 0 && (
            <div className="text-2xs text-muted-foreground">saldo {formatARS(saldoDe(p))}</div>
          )}
        </div>
      ),
    },
  ];
  return (
    <Stack>
      <Caption>
        Click en una fila la expande (muestra los ítems). El estado y la plata se ven de un vistazo;
        el saldo aparece solo si debe.
      </Caption>
      <AdminTable
        columns={columns}
        rows={pedidosAdminDemo}
        getRowKey={(p) => p.id}
        isExpanded={(p) => p.id === expandedId}
        onRowClick={(p) => setExpandedId((id) => (id === p.id ? null : p.id))}
        renderExpanded={(p) => (
          <div className="flex flex-col gap-1 px-2 py-1">
            {p.items.map((it) => (
              <div key={it.id} className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">
                  {it.nombre}
                  {it.cantidad > 1 ? ` ×${it.cantidad}` : ""}
                </span>
                <span className="tabular-nums text-ink">{formatARS(it.subtotal)}</span>
              </div>
            ))}
          </div>
        )}
      />
    </Stack>
  );
}

// ── Modal de registrar pago (disparador + estado local) ───────────────────────
function RegistrarPagoModalDemo() {
  const [open, setOpen] = useState(false);
  return (
    <Stack>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Registrar un pago
      </Button>
      <Caption>
        El modal real de registrar un pago (destinatario, método, monto). Demo sobre un pedido
        ficticio (#1039, debe $240.000) — registrar acá no toca datos reales.
      </Caption>
      <RegistrarPagoModal
        pedidoId={9102}
        total={390000}
        pagado={150000}
        open={open}
        onOpenChange={setOpen}
      />
    </Stack>
  );
}

// ── Paleta de comandos ⌘F (dispara el evento que abre la REAL, ya montada) ─────
function CommandPaletteDemo() {
  return (
    <Stack>
      <Button variant="secondary" onClick={() => window.dispatchEvent(new Event("admin:cmdk"))}>
        Abrir la paleta de comandos
      </Button>
      <Caption>
        La paleta ⌘F del back-office. Se abre con ⌘F (o Ctrl+K) desde cualquier pantalla del admin —
        el botón dispara el mismo evento. Saltá a una sección o buscá pedidos, clientes y equipos
        sin soltar el teclado.
      </Caption>
    </Stack>
  );
}

// ── Ficha de la sidebar (vive fija al borde — no se embebe) ────────────────────
function AdminSidebarFicha() {
  return (
    <Stack>
      <Caption>
        La barra de navegación del back-office — la que ves a la izquierda de esta misma página.
        Vive fija al borde de la pantalla, así que no se embebe acá: esta es su ficha.
      </Caption>
      <div className="rounded-xl border hairline p-4">
        <div className="t-eyebrow mb-2">AdminSidebar — organismo</div>
        <ul className="flex flex-col gap-1.5 text-sm text-muted-foreground">
          <li>· Grupos por dominio, colapsables.</li>
          <li>· Buscador global ⌘F arriba de todo (abre la paleta de comandos).</li>
          <li>· Resalta la sección activa y auto-expande su grupo al navegar.</li>
          <li>· Colapsa a un riel de iconos para ganar espacio.</li>
        </ul>
      </div>
    </Stack>
  );
}

export const adminOrganismosSection: CatalogSection = {
  id: "admin-organismos",
  title: "Back-office (organismos)",
  hint: "Las piezas del panel admin: el listado de pedidos (tabla con fila expandible), el modal de registrar pago, la paleta de comandos ⌘F y la barra lateral. Datos demo: cuatro pedidos en distintos estados (solicitud · confirmado con saldo · finalizado).",
  specimens: [
    {
      name: "AdminTable",
      files: ["components/admin/AdminTable.tsx"],
      blurb:
        "El shell de tabla del back-office: encabezados + filas desde una def de columnas, sobre el primitivo Table. Una sola forma de la tabla del admin. Acá, el listado de pedidos con estado, plata y fila expandible.",
      render: () => <PedidosTableDemo />,
    },
    {
      name: "RegistrarPagoModal",
      files: ["components/admin/pedido/RegistrarPagoModal.tsx"],
      blurb:
        "El modal para registrar un pago sobre un pedido: destinatario, método y monto. Controlado (open / onOpenChange); cierra la mutación contra el pedido.",
      render: () => <RegistrarPagoModalDemo />,
    },
    {
      name: "AdminCommandPalette",
      files: ["components/admin/AdminCommandPalette.tsx"],
      blurb:
        "La paleta de comandos ⌘F del back-office: saltar a una sección o buscar pedidos, clientes y equipos sin sacar las manos del teclado. Vive montada en el layout del admin; el botón dispara el mismo evento que abre la real.",
      render: () => <CommandPaletteDemo />,
    },
    {
      name: "AdminSidebar",
      files: ["components/admin/AdminSidebar.tsx"],
      blurb:
        "La barra de navegación del back-office: grupos por dominio colapsables, buscador ⌘F, resaltado de sección activa y colapso a riel de iconos. Vive fija al borde de la pantalla — acá va su ficha.",
      render: () => <AdminSidebarFicha />,
    },
  ],
};
