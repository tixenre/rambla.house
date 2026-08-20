/**
 * SinEnviarAdminSection — listado global de borradores de inscripción sin
 * enviar ("Sin enviar" en el sidebar): quién empezó el formulario de un
 * taller y no llegó a mandarlo, sin tener que entrar edición por edición.
 * Solo lectura — el seguimiento es un link de WhatsApp pre-armado, mismo
 * patrón que `InscripcionesSection` (scoped a una edición puntual), que
 * sigue siendo la fuente para esa vista — acá no se duplica esa lógica,
 * solo se cruza cross-taller.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import { Clock, GraduationCap, Inbox, MessageCircle } from "lucide-react";

import type { Borrador } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { whatsappLink } from "@/lib/whatsapp";
import { buildBorradorWhatsappMessage } from "@/lib/talleres/borrador";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { Input } from "@/design-system/ui/input";
import { Pill } from "@/design-system/ui/Pill";
import { ListSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";
import { EmptyState } from "@/design-system/composites/EmptyState";

export function SinEnviarAdminSection() {
  const [search, setSearch] = useState("");

  const listQ = useQuery({
    queryKey: ["admin", "borradores"],
    queryFn: () => talleresAdminApi.listBorradoresGlobal(),
    staleTime: 30_000,
  });

  const borradores = listQ.data?.borradores ?? [];
  const needle = search.trim().toLowerCase();
  const filtered = needle
    ? borradores.filter(
        (b) =>
          (b.nombre ?? "").toLowerCase().includes(needle) ||
          (b.email ?? "").toLowerCase().includes(needle) ||
          (b.taller_nombre ?? "").toLowerCase().includes(needle),
      )
    : borradores;

  const columns: Column<Borrador>[] = [
    { header: "Nombre", cell: (b) => b.nombre || "Sin nombre", className: "font-medium text-ink" },
    {
      header: "Email",
      cell: (b) =>
        b.email ? (
          <a href={`mailto:${b.email}`} className="hover:text-ink transition">
            {b.email}
          </a>
        ) : (
          "—"
        ),
      className: "text-muted-foreground",
    },
    {
      header: "Teléfono",
      cell: (b) => b.telefono || "—",
      className: "text-muted-foreground hidden sm:table-cell",
      headClassName: "hidden sm:table-cell",
    },
    {
      header: "Taller",
      cell: (b) => (
        <div className="flex items-center gap-1.5">
          <GraduationCap className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <span className="truncate">
            {b.taller_nombre ?? "—"}
            {b.numero_edicion ? ` · Edición ${b.numero_edicion}` : ""}
          </span>
        </div>
      ),
      className: "max-w-[220px]",
    },
    {
      header: "Estado",
      cell: (b) => (
        <Pill tone={b.abandonado ? "warning" : "info"}>
          {b.abandonado ? "Abandonado" : "Activo"}
        </Pill>
      ),
    },
    {
      header: "Última actividad",
      cell: (b) => (
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {formatDistanceToNow(new Date(b.updated_at), { addSuffix: true, locale: es })}
        </span>
      ),
      className: "text-muted-foreground text-xs",
    },
    {
      header: "",
      cell: (b) => {
        const wasaLink = whatsappLink({
          phone: b.telefono,
          message: buildBorradorWhatsappMessage(b),
        });
        if (!wasaLink) return null;
        return (
          <a
            href={wasaLink}
            target="_blank"
            rel="noopener noreferrer"
            className="flex h-8 w-8 items-center justify-center rounded-full text-verde-ink hover:bg-verde/10 transition"
            title="Escribir por WhatsApp"
          >
            <MessageCircle className="h-4 w-4" />
          </a>
        );
      },
    },
  ];

  return (
    <section className="card p-4 space-y-3">
      <header>
        <h2 className="font-display text-lg text-ink">Sin enviar</h2>
        <p className="text-sm text-muted-foreground">
          Personas que empezaron el formulario de inscripción a un taller y no llegaron a mandarlo,
          con el taller y la edición a la que estaban por anotarse.
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
          icon={<Inbox className="h-6 w-6" />}
          title={search ? "Sin resultados" : "Nadie quedó a mitad de camino"}
        />
      )}

      {!listQ.isLoading && filtered.length > 0 && (
        <AdminTable columns={columns} rows={filtered} getRowKey={(b) => b.id} />
      )}
    </section>
  );
}
