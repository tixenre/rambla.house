/**
 * AlumnosAdminSection — listado global de inscriptos a talleres ("Alumnos"
 * en el sidebar): quién está anotado y a qué taller, sin tener que entrar
 * taller por taller. Solo lectura — las acciones (confirmar, verificar
 * seña, ofrecer cupo, eliminar) siguen viviendo en `InscripcionesSection`
 * scoped a una edición puntual, para no duplicar esa lógica de mutación en
 * dos lugares (una sola forma de hacer cada cosa).
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clock, GraduationCap, Users } from "lucide-react";

import type { Inscripcion } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { Input } from "@/design-system/ui/input";
import { Pill, type PillTone } from "@/design-system/ui/Pill";
import { ListSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";
import { EmptyState } from "@/design-system/composites/EmptyState";

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("es-AR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

const ESTADO_LABEL: Record<string, string> = {
  en_espera: "Lista de espera",
  pendiente_sena: "Pendiente de seña",
  cupo_ofrecido: "Cupo ofrecido",
  confirmada: "Confirmada",
};

const ESTADO_TONE: Record<string, PillTone> = {
  en_espera: "neutral",
  pendiente_sena: "warning",
  cupo_ofrecido: "info",
  confirmada: "success",
};

export function AlumnosAdminSection() {
  const [search, setSearch] = useState("");

  const listQ = useQuery({
    queryKey: ["admin", "inscripciones"],
    queryFn: () => talleresAdminApi.listInscripcionesGlobal(),
    staleTime: 30_000,
  });

  const alumnos = listQ.data ?? [];
  const needle = search.trim().toLowerCase();
  const filtered = needle
    ? alumnos.filter(
        (a) =>
          a.nombre.toLowerCase().includes(needle) ||
          a.email.toLowerCase().includes(needle) ||
          (a.taller_nombre ?? "").toLowerCase().includes(needle),
      )
    : alumnos;

  const columns: Column<Inscripcion>[] = [
    { header: "Nombre", cell: (a) => a.nombre, className: "font-medium text-ink" },
    {
      header: "Email",
      cell: (a) => (
        <a href={`mailto:${a.email}`} className="hover:text-ink transition">
          {a.email}
        </a>
      ),
      className: "text-muted-foreground",
    },
    {
      header: "Teléfono",
      cell: (a) => a.telefono || "—",
      className: "text-muted-foreground hidden sm:table-cell",
      headClassName: "hidden sm:table-cell",
    },
    {
      header: "Taller",
      cell: (a) => (
        <div className="flex items-center gap-1.5">
          <GraduationCap className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <span className="truncate">
            {a.taller_nombre ?? "—"}
            {a.numero_edicion ? ` · Edición ${a.numero_edicion}` : ""}
          </span>
        </div>
      ),
      className: "max-w-[220px]",
    },
    {
      header: "Estado",
      cell: (a) => {
        const key = a.en_lista_espera ? "en_espera" : (a.estado ?? "");
        return (
          <Pill tone={ESTADO_TONE[key] ?? "neutral"}>{ESTADO_LABEL[key] ?? a.estado ?? "—"}</Pill>
        );
      },
    },
    {
      header: "Fecha",
      cell: (a) => (
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {fmtDate(a.created_at)}
        </span>
      ),
      className: "text-muted-foreground text-xs",
    },
  ];

  return (
    <section className="card p-4 space-y-3">
      <header>
        <h2 className="font-display text-lg text-ink">Alumnos</h2>
        <p className="text-sm text-muted-foreground">
          Todas las personas inscriptas a un taller, con el taller y la edición a la que pertenecen.
          Para confirmar, verificar seña u ofrecer cupo, entrá al taller puntual.
        </p>
      </header>

      <Input
        placeholder="Buscar por nombre, email o taller…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="h-9 max-w-sm"
      />

      {listQ.isLoading && <ListSkeleton rows={4} className="py-2" />}
      {listQ.error && (
        <ErrorState error={listQ.error} onRetry={() => listQ.refetch()} className="py-6" />
      )}

      {!listQ.isLoading && !listQ.error && filtered.length === 0 && (
        <EmptyState
          icon={<Users className="h-6 w-6" />}
          title={search ? "Sin resultados" : "Sin alumnos todavía"}
        />
      )}

      {!listQ.isLoading && filtered.length > 0 && (
        <AdminTable columns={columns} rows={filtered} getRowKey={(a) => a.id} />
      )}
    </section>
  );
}
