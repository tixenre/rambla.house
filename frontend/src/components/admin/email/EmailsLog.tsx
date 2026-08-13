/**
 * Log de mails enviados (read-only) — qué salió, a quién y qué falló.
 *
 * Es transversal a todos los eventos (por eso vive como su propia sección al pie
 * de /admin/comunicacion, no adentro de un evento).
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Send } from "lucide-react";

import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { ErrorState } from "@/components/admin/ErrorState";
import { TableSkeleton } from "@/components/admin/skeletons";
import { Button } from "@/design-system/ui/button";
import { Pill } from "@/design-system/ui/Pill";
import { SearchInput } from "@/design-system/ui/search-input";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";

import { adminApi, type EmailLogEntry } from "@/lib/admin/api";
import { TEMPLATE_META } from "./templateMeta";

const STATUS_FILTERS = [
  { value: "", label: "Todos" },
  { value: "sent", label: "Enviados" },
  { value: "failed", label: "Fallidos" },
];
const PAGE = 25;

export function EmailsLog() {
  const [status, setStatus] = useState("");
  const [templateKey, setTemplateKey] = useState("");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search.trim(), 250);
  const [offset, setOffset] = useState(0);

  // Cualquier cambio de búsqueda vuelve a la primera página — separado del
  // resto de los filtros (que resetean el offset en su propio onClick/onChange)
  // porque este valor llega debounced, no en el evento del input.
  useEffect(() => setOffset(0), [debouncedSearch]);

  const q = useQuery({
    queryKey: ["admin", "emails-log", status, templateKey, debouncedSearch, offset],
    queryFn: () =>
      adminApi.listEmailsLog({
        status: status || undefined,
        template_key: templateKey || undefined,
        q: debouncedSearch || undefined,
        limit: PAGE,
        offset,
      }),
  });

  const data = q.data;
  const total = data?.total ?? 0;
  const items = data?.items ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => {
                setStatus(f.value);
                setOffset(0);
              }}
              className={`rounded-full px-3 py-1 text-xs transition ${
                status === f.value
                  ? "bg-ink text-background"
                  : "border hairline text-muted-foreground hover:bg-muted/30"
              }`}
            >
              {f.label}
            </button>
          ))}
          <select
            value={templateKey}
            onChange={(e) => {
              setTemplateKey(e.target.value);
              setOffset(0);
            }}
            className="h-8 rounded-full border hairline bg-surface-elevated px-2.5 text-xs text-muted-foreground"
          >
            <option value="">Todas las plantillas</option>
            {Object.entries(TEMPLATE_META).map(([key, meta]) => (
              <option key={key} value={key}>
                {meta.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <SearchInput
            value={search}
            onValueChange={setSearch}
            clearable
            placeholder="Buscar por destinatario…"
            wrapperClassName="w-56"
          />
          <Button
            variant="outline"
            size="sm"
            onClick={() => void q.refetch()}
            disabled={q.isFetching}
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${q.isFetching ? "animate-spin" : ""}`} />
            Refrescar
          </Button>
        </div>
      </div>

      {q.isLoading && <TableSkeleton rows={6} cols={5} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}

      {!q.isLoading && !q.isError && items.length === 0 && (
        <EmptyState
          icon={<Send className="h-6 w-6" />}
          title="No hay envíos registrados todavía"
          sub="Cuando se mande un mail va a aparecer acá."
        />
      )}

      {!q.isError && items.length > 0 && (
        <AdminTable
          columns={EMAIL_LOG_COLUMNS}
          rows={items}
          getRowKey={(e) => e.id}
          rowClassName={() => "align-top"}
        />
      )}

      {total > PAGE && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {offset + 1}–{Math.min(offset + PAGE, total)} de {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setOffset((o) => Math.max(0, o - PAGE))}
              disabled={offset === 0 || q.isFetching}
            >
              Anterior
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setOffset((o) => o + PAGE)}
              disabled={offset + PAGE >= total || q.isFetching}
            >
              Siguiente
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

const EMAIL_LOG_COLUMNS: Column<EmailLogEntry>[] = [
  {
    header: "Fecha",
    className: "whitespace-nowrap font-mono text-xs text-muted-foreground",
    cell: (entry) =>
      entry.sent_at
        ? new Date(entry.sent_at).toLocaleString("es-AR", {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })
        : "—",
  },
  {
    header: "Estado",
    className: "whitespace-nowrap",
    cell: (entry) => {
      const tone =
        entry.status === "sent" ? "success" : entry.status === "failed" ? "danger" : "neutral";
      return <Pill tone={tone}>{entry.status}</Pill>;
    },
  },
  {
    header: "Plantilla",
    cell: (entry) => TEMPLATE_META[entry.template_key]?.label ?? entry.template_key,
  },
  {
    header: "Destinatario",
    className: "font-mono text-xs",
    cell: (entry) => entry.to_addr,
  },
  {
    header: "Detalle",
    className: "text-muted-foreground",
    cell: (entry) =>
      entry.error ? (
        <span className="text-destructive">{entry.error}</span>
      ) : (
        <span className="font-mono text-xs text-muted-foreground/70">
          {entry.provider}
          {entry.provider_id ? ` · ${entry.provider_id}` : ""}
        </span>
      ),
  },
];
