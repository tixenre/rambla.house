import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createLazyFileRoute, Link } from "@tanstack/react-router";
import { CheckCircle2, Upload, X } from "lucide-react";
import { toast } from "sonner";

import { PublicLayout } from "@/components/rental/shell/PublicLayout";
import { DatosPago } from "@/components/talleres/DatosPago";
import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { Spinner } from "@/design-system/ui/spinner";
import { EmptyState } from "@/design-system/composites/EmptyState";
import {
  apiClaimOfertaCupo,
  apiGetOfertaCupo,
  apiUploadComprobanteSena,
  type OfertaCupo,
} from "@/lib/api";

export const Route = createLazyFileRoute("/escuelas/sena/$token")({
  component: SenaPage,
});

const MAX_MB = 10;

type UploadState =
  | { status: "idle" }
  | { status: "uploading" }
  | { status: "done"; url: string; key: string; fileName: string }
  | { status: "error"; message: string };

function ComprobanteForm({ token, oferta }: { token: string; oferta: OfertaCupo }) {
  const [upload, setUpload] = useState<UploadState>({ status: "idle" });
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const processFile = async (file: File) => {
    if (file.size > MAX_MB * 1024 * 1024) {
      toast.error(`El archivo no puede superar ${MAX_MB} MB`);
      return;
    }
    setUpload({ status: "uploading" });
    try {
      const { url, key } = await apiUploadComprobanteSena(token, file);
      setUpload({ status: "done", url, key, fileName: file.name });
    } catch (err) {
      setUpload({
        status: "error",
        message: err instanceof Error ? err.message : "No se pudo subir el archivo",
      });
    }
  };

  const handleSubmit = async () => {
    if (upload.status !== "done") {
      toast.error("Adjuntá el comprobante para completar tu seña");
      return;
    }
    setSubmitting(true);
    try {
      await apiClaimOfertaCupo(token, {
        comprobante_url: upload.url,
        comprobante_key: upload.key,
      });
      setDone(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Algo salió mal. Intentá de nuevo.");
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <div className="rounded-2xl border border-border/60 bg-background p-6 sm:p-8 text-center">
        <CheckCircle2 className="mx-auto mb-4 h-10 w-10 text-verde" strokeWidth={1.5} />
        <h3 className="font-display text-xl font-bold text-ink mb-2">¡Tu lugar está reservado!</h3>
        <p className="text-sm text-muted-foreground max-w-xs mx-auto">
          Recibimos tu comprobante. Te enviamos un mail de confirmación.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-border/60 bg-background p-6 flex flex-col gap-4">
      <div>
        <p className="text-xs text-muted-foreground mb-1">Datos para la seña</p>
        <p className="font-display text-2xl font-bold text-ink tabular-nums">
          {oferta.precio_sena_str}
        </p>
        <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
          <DatosPago cuentas={oferta.cuentas_pago} variant="success" />
        </p>
      </div>

      <div
        className={`rounded-xl border border-dashed p-4 transition-colors ${
          dragging ? "border-rosa bg-rosa/5" : "border-border/80 bg-muted/20"
        }`}
      >
        {upload.status === "idle" || upload.status === "error" ? (
          <>
            <label
              htmlFor="sena-comprobante"
              className="flex flex-col items-center gap-2 cursor-pointer"
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                const file = e.dataTransfer.files?.[0];
                if (file) processFile(file);
              }}
            >
              <Upload className="h-6 w-6 text-muted-foreground" strokeWidth={1.5} />
              <span className="text-sm text-muted-foreground text-center">
                Cliqueá para adjuntar o arrastrá acá
                <br />
                <span className="text-xs">JPG, PNG, PDF — máx {MAX_MB} MB</span>
              </span>
              <input
                id="sena-comprobante"
                type="file"
                ref={fileRef}
                accept="image/jpeg,image/png,image/webp,image/heic,application/pdf"
                className="sr-only"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) processFile(file);
                }}
              />
            </label>
            {upload.status === "error" && (
              <p className="mt-2 text-xs text-destructive text-center">{upload.message}</p>
            )}
          </>
        ) : upload.status === "uploading" ? (
          <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground py-2">
            <Spinner size="sm" />
            Subiendo comprobante…
          </div>
        ) : (
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm text-verde-ink">
              <CheckCircle2 className="h-4 w-4 shrink-0" strokeWidth={1.5} />
              <span className="truncate">{upload.fileName}</span>
            </div>
            <IconButton
              type="button"
              aria-label="Quitar archivo"
              size="lg"
              onClick={() => {
                setUpload({ status: "idle" });
                if (fileRef.current) fileRef.current.value = "";
              }}
              className="shrink-0 rounded-full text-muted-foreground hover:text-ink hover:bg-muted"
            >
              <X className="h-4 w-4" />
            </IconButton>
          </div>
        )}
      </div>

      <Button
        onClick={handleSubmit}
        variant="amber"
        shape="pill"
        disabled={submitting || upload.status !== "done"}
        className="w-full py-6 text-base font-bold"
      >
        {submitting ? (
          <span className="flex items-center gap-2">
            <Spinner size="sm" />
            Enviando…
          </span>
        ) : (
          "Completar mi seña"
        )}
      </Button>
    </div>
  );
}

function SenaPage() {
  const { token } = Route.useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["oferta-cupo", token],
    queryFn: () => apiGetOfertaCupo(token),
    staleTime: 0,
    retry: false,
  });

  const status = (error as { status?: number } | null)?.status;

  return (
    <PublicLayout topBar={{ variant: "escuela" }}>
      <div className="min-h-dvh bg-background flex items-center justify-center px-4 py-16">
        <div className="w-full max-w-md">
          {isLoading && (
            <div className="text-center text-muted-foreground text-sm py-16">Cargando…</div>
          )}

          {error && (
            <EmptyState
              icon={<X className="h-6 w-6" />}
              title={
                status === 410 ? "Esta oferta ya no está disponible" : "Este link no es válido"
              }
              sub={
                status === 410
                  ? "El cupo ya fue reclamado, o la oferta venció. Escribinos si creés que es un error."
                  : "El link venció o no es correcto. Revisá el mail o escribinos."
              }
            >
              <Link
                to="/escuelas"
                className="text-sm font-semibold text-ink hover:text-rosa transition"
              >
                Ver talleres
              </Link>
            </EmptyState>
          )}

          {data && (
            <>
              <p className="font-mono text-2xs tracking-[0.25em] uppercase text-rosa mb-2">
                {data.taller_nombre}
              </p>
              <h1 className="font-display text-2xl font-bold text-ink lowercase mb-1">
                ¡Hola {data.nombre_pila}!
              </h1>
              <p className="text-sm text-muted-foreground mb-6">
                Se liberó un cupo para vos — {data.fecha_inicio_str} y {data.fecha_fin_str},{" "}
                {data.horario} en {data.direccion}. Completá tu seña para confirmarlo.
              </p>
              <ComprobanteForm token={token} oferta={data} />
            </>
          )}
        </div>
      </div>
    </PublicLayout>
  );
}
