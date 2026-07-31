import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Users } from "lucide-react";
import { toast } from "sonner";

import type { TallerConcepto, Interesado } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { Button } from "@/design-system/ui/button";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { ListSkeleton } from "@/components/admin/skeletons";
import { EmptyState } from "@/design-system/composites/EmptyState";

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("es-AR", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * F4b: `interesados_taller` era write-only (se guardaban leads cuando no
 * había cupos, pero nadie los veía desde el admin). Esta pestaña los lista +
 * un botón para avisarles cuando se abre una nueva edición.
 */
export function InteresadosSection({ concepto }: { concepto: TallerConcepto }) {
  const qc = useQueryClient();

  const { data: interesados = [], isLoading } = useQuery({
    queryKey: ["admin", "talleres", concepto.id, "interesados"],
    queryFn: () => talleresAdminApi.listInteresados(concepto.id),
    staleTime: 30_000,
  });

  const notificarMut = useMutation({
    mutationFn: (interesadoId: number) =>
      talleresAdminApi.notificarInteresado(concepto.id, interesadoId),
    onSuccess: () => {
      toast.success("Aviso enviado");
      qc.invalidateQueries({ queryKey: ["admin", "talleres", concepto.id, "interesados"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  if (isLoading) return <ListSkeleton rows={3} />;

  if (interesados.length === 0) {
    return (
      <EmptyState
        icon={<Users className="h-6 w-6" />}
        title="Sin interesados todavía"
        sub="Se anotan acá cuando alguien deja sus datos porque no había cupos disponibles."
      />
    );
  }

  const columns: Column<Interesado>[] = [
    { header: "Nombre", cell: (i) => i.nombre, className: "font-medium text-ink" },
    {
      header: "Email",
      cell: (i) => (
        <a href={`mailto:${i.email}`} className="hover:text-ink transition">
          {i.email}
        </a>
      ),
      className: "text-muted-foreground",
    },
    {
      header: "Teléfono",
      cell: (i) => i.telefono || "—",
      className: "text-muted-foreground hidden sm:table-cell",
      headClassName: "hidden sm:table-cell",
    },
    {
      header: "Se anotó",
      cell: (i) => fmtDate(i.created_at),
      className: "text-muted-foreground text-xs",
    },
    {
      header: "",
      cell: (i) => (
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1.5 px-2 text-xs"
          disabled={notificarMut.isPending}
          onClick={() => notificarMut.mutate(i.id)}
        >
          <Bell className="h-3 w-3" />
          {i.notificado_at
            ? `Avisado ${fmtDate(i.notificado_at)} — re-avisar`
            : "Avisar nueva edición"}
        </Button>
      ),
    },
  ];

  return <AdminTable columns={columns} rows={interesados} getRowKey={(i) => i.id} />;
}
