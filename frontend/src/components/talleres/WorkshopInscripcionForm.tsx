import { useRef, useState } from "react";
import { Upload, CheckCircle2, AlertCircle, X } from "lucide-react";
import { Spinner } from "@/design-system/ui/spinner";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Checkbox } from "@/design-system/ui/checkbox";
import { IconButton } from "@/design-system/ui/icon-button";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import { Textarea } from "@/design-system/ui/textarea";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/design-system/ui/dialog";
import { apiUploadComprobante, apiCrearInscripcion, type Taller } from "@/lib/api";
import { formatARS } from "@/lib/format";
import { ModalidadSelector } from "./ModalidadSelector";

type Props = {
  taller: Taller;
  onSuccess?: (enListaEspera: boolean) => void;
};

type UploadState =
  | { status: "idle" }
  | { status: "uploading" }
  | { status: "done"; url: string; key: string; fileName: string }
  | { status: "error"; message: string };

type SubmitState = "idle" | "submitting" | "success_normal" | "success_espera" | "error";

const MAX_MB = 10;
const ACCEPT_TYPES = "image/jpeg,image/png,image/webp,image/heic,application/pdf";

function TerminosDialog({
  open,
  onOpenChange,
  texto,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  texto: string;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Términos y condiciones del taller</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-line">{texto}</p>
        <DialogFooter>
          <DialogClose asChild>
            <Button>Entendido</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function WorkshopInscripcionForm({ taller, onSuccess }: Props) {
  const [nombre, setNombre] = useState("");
  const [email, setEmail] = useState("");
  const [telefono, setTelefono] = useState("");
  const [telefonoError, setTelefonoError] = useState(false);
  const [experiencia, setExperiencia] = useState("");
  const [modalidadCodigo, setModalidadCodigo] = useState(taller.modalidades[0]?.codigo ?? "");
  const [aceptaTerminos, setAceptaTerminos] = useState(false);
  const [terminosOpen, setTerminosOpen] = useState(false);
  const [upload, setUpload] = useState<UploadState>({ status: "idle" });
  const [dragging, setDragging] = useState(false);
  const [submitState, setSubmitState] = useState<SubmitState>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const cuposDisponibles = Math.max(0, taller.cupos_total - taller.cupos_confirmados);
  const enListaActual = cuposDisponibles === 0;
  const cierrePasado =
    !!taller.fecha_cierre_inscripcion &&
    new Date(taller.fecha_cierre_inscripcion + "T23:59:59") < new Date();

  const processFile = async (file: File) => {
    if (file.size > MAX_MB * 1024 * 1024) {
      toast.error(`El archivo no puede superar ${MAX_MB} MB`);
      return;
    }
    setUpload({ status: "uploading" });
    try {
      const { url, key } = await apiUploadComprobante(taller.slug, file);
      setUpload({ status: "done", url, key, fileName: file.name });
    } catch (err) {
      setUpload({
        status: "error",
        message: err instanceof Error ? err.message : "No se pudo subir el archivo",
      });
    }
  };

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
  };

  const handleDrop = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) processFile(file);
  };

  const removeFile = () => {
    setUpload({ status: "idle" });
    if (fileRef.current) fileRef.current.value = "";
  };

  const telefonoValido = (tel: string) => {
    const digits = tel.replace(/\D/g, "");
    return digits.length >= 6 && digits.length <= 15;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!nombre.trim() || !email.trim() || !telefono.trim()) {
      toast.error("Completá nombre, email y teléfono");
      return;
    }
    if (!telefonoValido(telefono)) {
      setTelefonoError(true);
      toast.error("El teléfono no parece válido — ingresá solo números, sin letras");
      return;
    }
    if (!enListaActual && upload.status !== "done") {
      toast.error("Adjuntá el comprobante de pago para reservar tu cupo");
      return;
    }
    if (!aceptaTerminos) {
      toast.error("Tenés que aceptar los términos y condiciones");
      return;
    }
    setTelefonoError(false);
    setSubmitState("submitting");
    try {
      const result = await apiCrearInscripcion(taller.slug, {
        nombre: nombre.trim(),
        email: email.trim(),
        telefono: telefono.trim(),
        experiencia: experiencia.trim() || undefined,
        comprobante_url: upload.status === "done" ? upload.url : undefined,
        comprobante_key: upload.status === "done" ? upload.key : undefined,
        modalidad_codigo: modalidadCodigo || undefined,
        acepta_terminos: aceptaTerminos,
      });
      setSubmitState(result.en_lista_espera ? "success_espera" : "success_normal");
      onSuccess?.(result.en_lista_espera);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Algo salió mal. Intentá de nuevo.";
      setErrorMsg(msg);
      toast.error(msg);
      setSubmitState("error");
    }
  };

  if (cierrePasado) {
    return (
      <div className="rounded-2xl border border-border/60 bg-muted/20 px-5 py-6 text-center">
        <p className="text-sm font-medium text-ink mb-1">Inscripciones cerradas</p>
        <p className="text-xs text-muted-foreground">
          Esta edición ya no acepta nuevas inscripciones.
        </p>
      </div>
    );
  }

  if (submitState === "success_normal" || submitState === "success_espera") {
    const isEspera = submitState === "success_espera";
    return (
      <div className="rounded-2xl border border-border/60 bg-background p-6 sm:p-8 text-center">
        <CheckCircle2
          className={`mx-auto mb-4 h-10 w-10 ${isEspera ? "text-rosa" : "text-verde"}`}
          strokeWidth={1.5}
        />
        <h3 className="font-display text-xl font-bold text-ink mb-2">
          {isEspera ? "Quedaste en lista de espera" : "¡Tu lugar está reservado!"}
        </h3>
        <p className="text-sm text-muted-foreground max-w-xs mx-auto">
          {isEspera
            ? "Los cupos están completos, pero te anotamos en la lista de espera. Te avisamos si se libera un lugar."
            : "Recibimos tu inscripción. Te enviamos un mail de confirmación con los datos de pago."}
        </p>
        {!isEspera && (
          <div className="mt-6 rounded-xl bg-muted/40 p-4 text-left text-sm">
            <p className="font-medium text-ink mb-2">
              Datos para la seña ({formatARS(taller.precio_sena)})
            </p>
            <p className="text-muted-foreground leading-relaxed">
              Alias: <span className="text-ink font-mono">{taller.pago_alias}</span>
              <br />
              CBU: <span className="text-ink font-mono text-xs">{taller.pago_cbu}</span>
              <br />
              Banco: {taller.pago_banco}
            </p>
          </div>
        )}
        {taller.mensaje_confirmacion && (
          <p className="mt-5 text-xs text-muted-foreground">{taller.mensaje_confirmacion}</p>
        )}
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      {/* Cupos badge */}
      <div
        className={`rounded-xl px-4 py-2.5 text-sm font-medium ${
          enListaActual
            ? "bg-rosa/15 text-rosa"
            : cuposDisponibles <= 3
              ? "bg-rosa/10 text-rosa"
              : "bg-verde/10 text-verde-ink"
        }`}
      >
        {enListaActual
          ? "Los cupos están completos — podés anotarte en la lista de espera"
          : cuposDisponibles === 1
            ? "¡Queda 1 lugar disponible!"
            : `${cuposDisponibles} lugares disponibles`}
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="ins-nombre">Nombre y apellido *</Label>
          <Input
            id="ins-nombre"
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            placeholder="Juana García"
            required
            disabled={submitState === "submitting"}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="ins-telefono">Teléfono celular *</Label>
          <Input
            id="ins-telefono"
            type="tel"
            value={telefono}
            onChange={(e) => {
              setTelefono(e.target.value);
              if (telefonoError) setTelefonoError(false);
            }}
            placeholder="+54 9 223 000-0000"
            required
            disabled={submitState === "submitting"}
            className={telefonoError ? "border-destructive focus-visible:ring-destructive/30" : ""}
          />
          {telefonoError && (
            <p className="text-xs text-destructive">
              Ingresá un número válido (solo dígitos, sin letras)
            </p>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="ins-email">Mail *</Label>
        <Input
          id="ins-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="vos@ejemplo.com"
          required
          disabled={submitState === "submitting"}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="ins-exp">
          {taller.pregunta_experiencia || "¿Tenés algún tipo de experiencia en arte?"}{" "}
          <span className="text-muted-foreground font-normal text-xs">
            (no es necesario para inscribirte, es solo curiosidad :)
          </span>
        </Label>
        <Textarea
          id="ins-exp"
          value={experiencia}
          onChange={(e) => setExperiencia(e.target.value)}
          placeholder="Contanos brevemente, si querés…"
          rows={3}
          disabled={submitState === "submitting"}
        />
      </div>

      <ModalidadSelector
        modalidades={taller.modalidades}
        value={modalidadCodigo}
        onChange={setModalidadCodigo}
      />

      {/* Comprobante upload */}
      <div className="flex flex-col gap-1.5">
        <Label>
          Comprobante de transferencia {!enListaActual && <span className="text-rosa">*</span>}
        </Label>
        <p className="text-xs text-muted-foreground -mt-0.5">
          Para reservar tu cupo, realizá el pago del{" "}
          {taller.precio_total > 0
            ? Math.round((taller.precio_sena / taller.precio_total) * 100)
            : 0}
          % ({formatARS(taller.precio_sena)}) y adjuntá el comprobante.
        </p>
        <div
          className={`mt-1 rounded-xl border border-dashed p-4 transition-colors ${
            dragging ? "border-rosa bg-rosa/5" : "border-border/80 bg-muted/20"
          }`}
        >
          {upload.status === "idle" || upload.status === "error" ? (
            <>
              <label
                htmlFor="ins-comprobante"
                className="flex flex-col items-center gap-2 cursor-pointer"
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
              >
                <Upload className="h-6 w-6 text-muted-foreground" strokeWidth={1.5} />
                <span className="text-sm text-muted-foreground text-center">
                  Cliqueá para adjuntar o arrastrá acá
                  <br />
                  <span className="text-xs">JPG, PNG, PDF — máx {MAX_MB} MB</span>
                </span>
                <input
                  id="ins-comprobante"
                  type="file"
                  ref={fileRef}
                  accept={ACCEPT_TYPES}
                  className="sr-only"
                  onChange={handleFile}
                  disabled={submitState === "submitting"}
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
                onClick={removeFile}
                className="shrink-0 rounded-full text-muted-foreground hover:text-ink hover:bg-muted"
              >
                <X className="h-4 w-4" />
              </IconButton>
            </div>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Alias: <span className="font-mono font-medium text-ink">{taller.pago_alias}</span>
          {" · "}CBU: <span className="font-mono text-ink">{taller.pago_cbu}</span>
          {" · "}
          {taller.pago_banco}
        </p>
      </div>

      <label className="flex items-start gap-2.5 cursor-pointer">
        <Checkbox
          checked={aceptaTerminos}
          onCheckedChange={(v) => setAceptaTerminos(v === true)}
          disabled={submitState === "submitting"}
          className="mt-0.5"
        />
        <span className="text-sm text-muted-foreground">
          Acepto los{" "}
          {taller.terminos ? (
            <button
              type="button"
              onClick={() => setTerminosOpen(true)}
              className="text-ink font-medium underline underline-offset-2 hover:text-rosa transition"
            >
              términos y condiciones
            </button>
          ) : (
            <a
              href="/terminos"
              target="_blank"
              rel="noopener noreferrer"
              className="text-ink font-medium underline underline-offset-2 hover:text-rosa transition"
            >
              términos y condiciones
            </a>
          )}
        </span>
      </label>
      {taller.terminos && (
        <TerminosDialog
          open={terminosOpen}
          onOpenChange={setTerminosOpen}
          texto={taller.terminos}
        />
      )}

      {submitState === "error" && (
        <div className="flex items-center gap-2 rounded-lg bg-destructive/10 border border-destructive/30 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {errorMsg || "Algo salió mal. Revisá los datos e intentá de nuevo."}
        </div>
      )}

      <Button
        type="submit"
        variant="amber"
        shape="pill"
        disabled={submitState === "submitting" || upload.status === "uploading"}
        className="w-full py-6 text-base font-bold"
      >
        {submitState === "submitting" ? (
          <span className="flex items-center gap-2">
            <Spinner size="sm" />
            Enviando…
          </span>
        ) : (
          "Reservar mi cupo"
        )}
      </Button>

      <p className="text-xs text-muted-foreground text-center">* Campos obligatorios</p>
    </form>
  );
}
