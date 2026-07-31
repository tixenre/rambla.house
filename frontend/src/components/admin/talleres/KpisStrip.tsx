import { useQuery } from "@tanstack/react-query";
import { Banknote, CheckCircle2, Clock, Wallet } from "lucide-react";

import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { StatCard } from "@/design-system/composites/StatCard";

// F4c: strip de mini-KPIs arriba de las inscripciones — números que antes se
// contaban a mano. La plata (esperada/recibida) la resuelve el backend
// (GET .../kpis); el front solo la muestra.
export function KpisStrip({ edicionId }: { edicionId: number }) {
  const { data } = useQuery({
    queryKey: ["admin", "ediciones", edicionId, "kpis"],
    queryFn: () => talleresAdminApi.getEdicionKpis(edicionId),
    staleTime: 0,
  });

  if (!data) return null;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      <StatCard
        size="md"
        label="Señas verificadas"
        value={data.senas_verificadas}
        icon={CheckCircle2}
      />
      <StatCard size="md" label="Señas pendientes" value={data.senas_pendientes} icon={Clock} />
      <StatCard size="md" label="Recibido" value={data.plata_recibida_str} icon={Wallet} />
      <StatCard size="md" label="Esperado" value={data.plata_esperada_str} icon={Banknote} />
    </div>
  );
}
