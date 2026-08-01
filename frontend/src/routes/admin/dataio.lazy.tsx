/**
 * Página de datos y backups del back-office.
 *
 * Modelo simple para el dueño: 3 grupos (Configuración, Clientes, Pedidos),
 * cada uno con Backup (descarga un ZIP) y Restaurar (sube ese ZIP, con
 * dry-run que simula antes de aplicar). Más abajo: borrar todo (arrancar de
 * cero) y un bloque "Avanzado" con las exportaciones por entidad / CSV.
 */

import { createLazyFileRoute } from "@tanstack/react-router";
import { useRef, useState } from "react";
import {
  AlertTriangle,
  Database,
  Download,
  FileArchive,
  FileJson,
  FileSpreadsheet,
  Package,
  Settings,
  Trash2,
  Upload,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/design-system/ui/alert-dialog";
import { AdminPage } from "@/components/admin/AdminPage";
import { Button } from "@/design-system/ui/button";
import { Spinner } from "@/design-system/ui/spinner";
import { Input } from "@/design-system/ui/input";
import { dataioAdminApi } from "@/lib/admin/api/dataio";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

const RESET_CONFIRMATION = "BORRAR TODO";

export const Route = createLazyFileRoute("/admin/dataio")({
  component: DataIoPage,
});

type ImportResult = {
  ok: boolean;
  dry_run: boolean;
  stats: Record<string, { inserted?: number; updated?: number; skipped?: number }>;
  total_inserted: number;
  total_updated: number;
};

// Los 3 grupos que ve el dueño. Cada uno mapea a un scope del backend.
const GROUPS = [
  {
    scope: "configuracion",
    label: "Configuración",
    Icon: Settings,
    desc: "Catálogo, specs, ajustes (cotización, WhatsApp, horarios, FAQ), plantillas de mail y descuentos.",
  },
  {
    scope: "clientes",
    label: "Clientes",
    Icon: Users,
    desc: "La base de clientes (datos personales y fiscales).",
  },
  {
    scope: "pedidos",
    label: "Pedidos",
    Icon: Package,
    desc: "Los alquileres con sus items y pagos.",
  },
] as const;

const CATALOG_ENTITIES = [
  { key: "marcas", label: "Marcas" },
  { key: "categorias", label: "Categorías" },
  { key: "spec_definitions", label: "Specs (definiciones)" },
  { key: "categoria_spec_templates", label: "Specs (asignaciones)" },
  { key: "equipos", label: "Equipos" },
  { key: "equipo_specs", label: "Equipo · valores de specs" },
  { key: "equipo_fichas", label: "Equipo · fichas extendidas" },
] as const;

async function downloadFile(entity: string, fallbackName: string) {
  const res = await dataioAdminApi.exportEntity(entity);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const match = cd.match(/filename="?([^";]+)"?/i);
  const filename = match?.[1] ?? fallbackName;

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function DataIoPage() {
  useDocumentTitle("Datos y backups · Back Office");
  const [busy, setBusy] = useState<string | null>(null);
  const [importBusy, setImportBusy] = useState<string | null>(null);
  const [lastImport, setLastImport] = useState<{ scope: string; result: ImportResult } | null>(
    null,
  );
  const [resetOpen, setResetOpen] = useState(false);
  const [resetConfirm, setResetConfirm] = useState("");
  const [resetBusy, setResetBusy] = useState(false);

  const handleDownload = async (entity: string, label: string, fallback: string) => {
    setBusy(entity);
    try {
      await downloadFile(entity, fallback);
      toast.success(`Backup descargado: ${label}`);
    } catch (e) {
      toast.error(`Falló la descarga de ${label}: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  const handleImport = async (scope: string, label: string, file: File, dryRun: boolean) => {
    setImportBusy(scope);
    try {
      const res = await dataioAdminApi.importScope(scope, file, dryRun);
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail ?? `${res.status} ${res.statusText}`);
      setLastImport({ scope, result: json as ImportResult });
      toast.success(
        `${label} — ${dryRun ? "simulación" : "restaurado"}: +${json.total_inserted ?? 0} nuevos, ~${json.total_updated ?? 0} actualizados`,
      );
    } catch (e) {
      toast.error(`Restaurar ${label} falló: ${(e as Error).message}`);
    } finally {
      setImportBusy(null);
    }
  };

  const handleResetOperacional = async () => {
    setResetBusy(true);
    try {
      const res = await dataioAdminApi.resetOperacional(RESET_CONFIRMATION);
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail ?? `${res.status} ${res.statusText}`);
      toast.success(
        `Borrado: ${json.deleted?.clientes ?? 0} clientes, ${json.deleted?.alquileres ?? 0} pedidos`,
      );
      setLastImport(null);
      setResetOpen(false);
      setResetConfirm("");
    } catch (e) {
      toast.error(`Reset falló: ${(e as Error).message}`);
    } finally {
      setResetBusy(false);
    }
  };

  return (
    <AdminPage
      title="Datos y backups"
      maxW="detail"
      description="Guardá una copia de tus datos, restaurala cuando quieras, o borrá todo para arrancar de cero."
    >
      <div className="space-y-8">
        {/* Guía del flujo (lenguaje claro) */}
        <div className="rounded-lg border border-amber/30 bg-amber/5 p-4 text-sm space-y-1.5">
          <div className="font-medium text-ink">Cómo usarlo para probar antes del lanzamiento</div>
          <ol className="list-decimal pl-5 space-y-1 text-muted-foreground">
            <li>
              <strong className="text-foreground">Descargá los backups</strong> que quieras guardar
              (cada uno es un solo archivo <code>backup-…-fecha.zip</code>).
            </li>
            <li>Probá libremente: hacé pedidos como si fueras un cliente.</li>
            <li>
              Cuando quieras <strong className="text-foreground">arrancar de cero</strong>: “Borrar
              clientes y pedidos” → escribí <code>{RESET_CONFIRMATION}</code>. Vuelve la numeración
              a #1.
            </li>
            <li>
              Para <strong className="text-foreground">recuperar</strong> lo guardado: en cada
              grupo, “Restaurar (simular)” te muestra qué va a pasar; después “Restaurar (aplicar)”.
            </li>
          </ol>
        </div>

        {/* ─── BACKUPS por grupo ─── */}
        <section className="space-y-3">
          <h2 className="font-display text-lg">Backup y restaurar</h2>
          <div className="space-y-3">
            {GROUPS.map((g) => (
              <GroupCard
                key={g.scope}
                group={g}
                busy={busy}
                importBusy={importBusy}
                lastImport={lastImport?.scope === g.scope ? lastImport.result : null}
                onDownload={handleDownload}
                onImport={handleImport}
              />
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Restaurar hace <strong>upsert</strong>: agrega lo que falta y actualiza lo que cambió,
            sin borrar lo que no esté en el archivo. Los archivos con datos de clientes/pedidos{" "}
            <strong className="text-foreground">nunca se commitean al repo</strong>.
          </p>
        </section>

        {/* ─── Zona destructiva ─── */}
        <section className="rounded-lg border border-destructive/30 bg-destructive/5 p-5 space-y-2">
          <div className="flex items-start gap-3">
            <AlertTriangle className="size-5 text-destructive shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h2 className="font-display text-lg text-destructive">Arrancar de cero</h2>
              <p className="text-sm text-muted-foreground">
                Borra <strong>todos los clientes y pedidos</strong> (con sus items y pagos) y
                reinicia los contadores, incluida la numeración de pedidos (el próximo vuelve a ser
                #1). El catálogo y la configuración no se tocan.{" "}
                <strong className="text-destructive">No es reversible</strong> — descargá el backup
                de Clientes y Pedidos antes.
              </p>
            </div>
          </div>
          <AlertDialog
            open={resetOpen}
            onOpenChange={(open) => {
              setResetOpen(open);
              if (!open) setResetConfirm("");
            }}
          >
            <AlertDialogTrigger asChild>
              <Button variant="destructive" size="sm">
                <Trash2 className="size-4" />
                Borrar clientes y pedidos
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>¿Borrar TODOS los clientes y pedidos?</AlertDialogTitle>
                <AlertDialogDescription>
                  Elimina permanentemente todos los clientes, pedidos, items y pagos. El catálogo y
                  la configuración no se tocan.
                  <br />
                  <br />
                  Para confirmar, escribí{" "}
                  <code className="font-mono font-bold">{RESET_CONFIRMATION}</code> abajo:
                </AlertDialogDescription>
              </AlertDialogHeader>
              <Input
                autoFocus
                value={resetConfirm}
                onChange={(e) => setResetConfirm(e.target.value)}
                placeholder={RESET_CONFIRMATION}
                className="font-mono"
              />
              <AlertDialogFooter>
                <AlertDialogCancel disabled={resetBusy}>Cancelar</AlertDialogCancel>
                <AlertDialogAction
                  disabled={resetConfirm !== RESET_CONFIRMATION || resetBusy}
                  onClick={(e) => {
                    e.preventDefault();
                    handleResetOperacional();
                  }}
                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                >
                  {resetBusy ? <Spinner size="sm" /> : <Trash2 className="size-4" />}
                  Borrar definitivamente
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </section>

        {/* ─── Avanzado (plegado) ─── */}
        <details className="rounded-lg border bg-card">
          <summary className="cursor-pointer select-none px-5 py-4 font-display text-lg flex items-center gap-2">
            <FileArchive className="size-4" />
            Avanzado · exportar por entidad / CSV
          </summary>
          <div className="border-t px-5 py-5 space-y-6">
            <p className="text-sm text-muted-foreground">
              Para casos puntuales: versionar el catálogo en git, o abrir los datos en Excel. El
              catálogo oficial vive en <code className="text-xs">data/catalog/</code> y se importa
              al arrancar.
            </p>

            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  handleDownload("catalog-all", "Catálogo completo (JSON)", "catalogo.zip")
                }
                disabled={busy !== null}
              >
                {busy === "catalog-all" ? (
                  <Spinner size="sm" />
                ) : (
                  <FileArchive className="size-4" />
                )}
                Catálogo (ZIP de JSONs)
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleDownload("csv-all", "Planillas (CSV)", "planillas-csv.zip")}
                disabled={busy !== null}
              >
                {busy === "csv-all" ? (
                  <Spinner size="sm" />
                ) : (
                  <FileSpreadsheet className="size-4" />
                )}
                Planillas CSV (ZIP)
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleDownload("full", "Backup completo", "backup-full.zip")}
                disabled={busy !== null}
              >
                {busy === "full" ? <Spinner size="sm" /> : <Database className="size-4" />}
                Todo en un ZIP
              </Button>
            </div>

            <div className="rounded-md border divide-y">
              {CATALOG_ENTITIES.map((e) => (
                <div key={e.key} className="flex items-center justify-between gap-4 px-4 py-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <FileJson className="size-4 text-muted-foreground shrink-0" />
                    <span className="text-sm truncate">{e.label}</span>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleDownload(e.key, e.label, `${e.key}.json`)}
                    disabled={busy !== null}
                    className="shrink-0"
                  >
                    {busy === e.key ? <Spinner size="sm" /> : <Download className="size-4" />}
                    JSON
                  </Button>
                </div>
              ))}
            </div>
          </div>
        </details>
      </div>
    </AdminPage>
  );
}

function GroupCard({
  group,
  busy,
  importBusy,
  lastImport,
  onDownload,
  onImport,
}: {
  group: { scope: string; label: string; Icon: typeof Settings; desc: string };
  busy: string | null;
  importBusy: string | null;
  lastImport: ImportResult | null;
  onDownload: (entity: string, label: string, fallback: string) => void;
  onImport: (scope: string, label: string, file: File, dryRun: boolean) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [confirmFile, setConfirmFile] = useState<File | null>(null);
  const { scope, label, Icon, desc } = group;
  const backupEntity = `backup-${scope}`;
  const downloading = busy === backupEntity;
  const importing = importBusy === scope;

  return (
    <div className="rounded-lg border bg-card p-5 space-y-3">
      <div className="flex items-start gap-3">
        <div className="grid size-9 place-items-center rounded-md bg-muted shrink-0">
          <Icon className="size-4" />
        </div>
        <div className="min-w-0">
          <h3 className="font-display text-base text-ink">{label}</h3>
          <p className="text-sm text-muted-foreground">{desc}</p>
        </div>
      </div>

      {/* eslint-disable-next-line no-restricted-syntax -- input file: no hay componente DS */}
      <input
        ref={inputRef}
        type="file"
        accept=".zip"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          const dryRun = e.target.dataset.dryRun === "true";
          e.target.value = "";
          delete e.target.dataset.dryRun;
          if (!f) return;
          // Simular: directo. Aplicar: pide confirmación antes de pisar datos.
          if (dryRun) onImport(scope, label, f, true);
          else setConfirmFile(f);
        }}
      />

      <div className="flex flex-wrap gap-2">
        <Button
          onClick={() => onDownload(backupEntity, label, `backup-${scope}.zip`)}
          disabled={busy !== null || importing}
        >
          {downloading ? <Spinner size="sm" /> : <Download className="size-4" />}
          Descargar backup
        </Button>
        <Button
          variant="outline"
          onClick={() => {
            if (inputRef.current) {
              inputRef.current.dataset.dryRun = "true";
              inputRef.current.click();
            }
          }}
          disabled={importing}
        >
          {importing ? <Spinner size="sm" /> : <Upload className="size-4" />}
          Restaurar (simular)
        </Button>
        <Button
          variant="outline"
          onClick={() => {
            if (inputRef.current) {
              inputRef.current.dataset.dryRun = "false";
              inputRef.current.click();
            }
          }}
          disabled={importing}
        >
          {importing ? <Spinner size="sm" /> : <Upload className="size-4" />}
          Restaurar (aplicar)
        </Button>
      </div>

      {lastImport && (
        <div className="text-xs font-mono bg-background border rounded px-3 py-2 space-y-1">
          <div>
            {lastImport.dry_run ? "[SIMULACIÓN] " : ""}+{lastImport.total_inserted} nuevos, ~
            {lastImport.total_updated} actualizados
          </div>
          {Object.entries(lastImport.stats).map(([entity, s]) => (
            <div key={entity} className="text-muted-foreground">
              {entity}: +{s.inserted ?? 0} / ~{s.updated ?? 0}
            </div>
          ))}
        </div>
      )}

      <AlertDialog open={confirmFile !== null} onOpenChange={(o) => !o && setConfirmFile(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Restaurar {label}?</AlertDialogTitle>
            <AlertDialogDescription>
              Se va a aplicar el archivo <code className="font-mono">{confirmFile?.name}</code>:
              agrega lo que falte y <strong>pisa lo que ya exista</strong> con lo del archivo (no
              borra lo que no esté). Si no estás seguro, cancelá y probá primero con “Restaurar
              (simular)”.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={importing}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              disabled={importing}
              onClick={(e) => {
                e.preventDefault();
                if (confirmFile) onImport(scope, label, confirmFile, false);
                setConfirmFile(null);
              }}
            >
              Restaurar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
