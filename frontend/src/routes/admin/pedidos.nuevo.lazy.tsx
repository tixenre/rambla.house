import { createLazyFileRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { Spinner } from "@/design-system/ui/spinner";
import { adminApi } from "@/lib/admin/api";
import { ymd } from "@/lib/rental-dates";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

export const Route = createLazyFileRoute("/admin/pedidos/nuevo")({
  component: NuevoPedidoPage,
});

// Crea un borrador y abre el editor. Mismo endpoint `createPedido`, sin tocar backend.
function NuevoPedidoPage() {
  useDocumentTitle("Nuevo pedido · Back-office");
  const navigate = useNavigate();
  const started = useRef(false);
  // ?cliente_id=123 (ej. "Nuevo pedido" desde la ficha de un cliente) precarga
  // el borrador ya vinculado — el editor lo muestra solo (contacto en vivo,
  // enriquecido por el backend).
  const search = useSearch({ strict: false }) as { cliente_id?: string | number };

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    // El backend exige fecha_desde/fecha_hasta NOT NULL → arrancamos con
    // hoy → mañana como placeholder editable desde el editor.
    const hoy = new Date();
    const manana = new Date(hoy);
    manana.setDate(manana.getDate() + 1);
    const clienteId = Number(search.cliente_id);
    adminApi
      .createPedido({
        estado: "borrador",
        cliente_nombre: "",
        cliente_id: Number.isFinite(clienteId) && clienteId > 0 ? clienteId : undefined,
        fecha_desde: ymd(hoy),
        fecha_hasta: ymd(manana),
        items: [],
      })
      .then((p) => {
        navigate({ to: "/admin/pedidos/$id", params: { id: String(p.id) }, replace: true });
      })
      .catch((e: Error) => {
        toast.error(`No se pudo crear el borrador: ${e.message}`);
        navigate({ to: "/admin/pedidos", replace: true });
      });
  }, [navigate, search.cliente_id]);

  return (
    <div className="flex items-center justify-center h-[60vh] text-muted-foreground gap-2">
      <Spinner size="sm" /> Creando borrador…
    </div>
  );
}
