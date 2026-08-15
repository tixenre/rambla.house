import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { authedFetch, AuthedHttpError } from "@/lib/authedFetch";
import { BackOfficeAuthCard } from "@/components/admin/BackOfficeAuthCard";
import { GoogleIcon } from "@/design-system/ui/GoogleIcon";
import { Input } from "@/design-system/ui/input";
import {
  loginWithPasskey,
  passkeyErrorMessage,
  passkeyLoginErrorMessage,
  passkeySupported,
  registerPasskey,
} from "@/lib/passkey";
import { loginConCodigoRespaldo } from "@/lib/backupCodes";
import { KeyRound } from "lucide-react";

export const Route = createFileRoute("/admin/login")({
  head: () => ({
    meta: [{ title: "Login · Back Office" }, { name: "robots", content: "noindex, nofollow" }],
  }),
  // Sin esto, TanStack Router descarta cualquier search param no declarado al
  // normalizar la URL — incluido `paso`, que llega desde el redirect de
  // /auth/callback (2º factor) y necesita sobrevivir al primer render.
  validateSearch: (
    search: Record<string, unknown>,
  ): { error?: string; denied?: string; paso?: string } => {
    const out: { error?: string; denied?: string; paso?: string } = {};
    if (typeof search.error === "string") out.error = search.error;
    if (typeof search.denied === "string") out.denied = search.denied;
    if (typeof search.paso === "string") out.paso = search.paso;
    return out;
  },
  component: AdminLoginPage,
});

const ERROR_MESSAGES: Record<string, string> = {
  not_allowed: "Tu cuenta de Google no está autorizada para acceder al admin.",
  state_mismatch: "Error de seguridad en el flujo de login. Intentá de nuevo.",
  token_error: "No se pudo completar la autenticación con Google. Intentá de nuevo.",
  userinfo_error: "No se pudo obtener tu información de Google. Intentá de nuevo.",
  no_email: "Google no devolvió un email. Verificá los permisos de tu cuenta.",
  no_code: "Google no devolvió el código de autorización. Intentá de nuevo.",
};

function AdminLoginPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [devMode, setDevMode] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(true);
  const [supported] = useState(() => passkeySupported());
  const [passkeyBusy, setPasskeyBusy] = useState(false);
  // 2º factor obligatorio: Google ya verificó, pero esta cuenta tiene una passkey
  // enrolada → no hay sesión todavía, hace falta confirmar con ella (backend no
  // minteó nada en /auth/callback, ver auth/google.py).
  const [pasoPasskey, setPasoPasskey] = useState(false);
  // Recovery: perdió el dispositivo con la passkey → código de respaldo en vez
  // de la ceremonia WebAuthn (auth/backup_codes.py).
  const [showBackupForm, setShowBackupForm] = useState(false);
  const [backupCode, setBackupCode] = useState("");
  const [backupBusy, setBackupBusy] = useState(false);
  // Tras un login exitoso con código de respaldo hay sesión pero SIGUE sin
  // passkey funcional en este dispositivo — sin este paso, el próximo login
  // volvería a pegar contra el mismo muro (y a consumir otro código de a uno).
  const [recovered, setRecovered] = useState(false);
  const [enrollBusy, setEnrollBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const errCode = params.get("error");
    if (errCode) {
      setError(ERROR_MESSAGES[errCode] ?? `Error: ${errCode}`);
    }
    // Flag `denied=1` lo setea AdminLayout cuando el usuario está logueado
    // en Google pero su email no está en ADMIN_EMAILS.
    if (params.get("denied") === "1") {
      setError(ERROR_MESSAGES.not_allowed);
    }
    if (params.get("paso") === "passkey") {
      setPasoPasskey(true);
      return; // no hay sesión todavía — no chequear /auth/me
    }

    authedFetch("/auth/me").then(async (r) => {
      if (!r.ok) return;
      // Solo redirect al admin si el usuario es admin. Sino se queda
      // viendo la pantalla de login (con el mensaje si vino con denied).
      const data = (await r.json()) as { is_admin?: boolean };
      if (data.is_admin) navigate({ to: "/admin" });
    });

    authedFetch("/auth/config").then(async (r) => {
      if (r.ok) {
        const data = await r.json();
        setDevMode(data.dev_mode ?? false);
        setGoogleEnabled(data.google_enabled ?? true);
      }
    });
  }, [navigate]);

  function handleGoogleLogin() {
    window.location.href = "/auth/google";
  }

  function handleDevLogin() {
    window.location.href = "/auth/dev-login";
  }

  async function handlePasskeyLogin() {
    if (passkeyBusy) return;
    setError(null);
    setPasskeyBusy(true);
    try {
      await loginWithPasskey();
      window.location.href = "/admin";
    } catch (e) {
      // `passkeyLoginErrorMessage` sugiere "entrá con Google y agregá una clave desde
      // tu perfil" — correcto en la pantalla principal (Google sola alcanza para
      // loguearse ahí), pero circular/imposible acá: en `pasoPasskey` ya entraste con
      // Google y el backend a propósito NO minteó sesión (2º factor obligatorio, ver
      // auth/google.py) — no hay "tu perfil" al que ir sin resolver primero este paso.
      // Bug real: Pablo (otro admin) quedó sin salida en este dispositivo con el
      // mensaje genérico, que lo mandaba a hacer algo que no podía hacer.
      setError(
        pasoPasskey
          ? "No encontramos tu clave de acceso en este dispositivo (o cancelaste). Tu cuenta ya tiene una clave registrada en OTRO dispositivo — entrá desde ese, o usá un código de respaldo abajo."
          : passkeyLoginErrorMessage(e),
      );
      setPasskeyBusy(false);
    }
  }

  async function handleBackupCodeLogin() {
    if (backupBusy || !backupCode.trim()) return;
    setError(null);
    setBackupBusy(true);
    try {
      await loginConCodigoRespaldo(backupCode.trim());
      setRecovered(true); // sesión ya minteada — falta registrar una passkey nueva ACÁ
    } catch (e) {
      // `.detail` (no `.message`): un admin no técnico como Pablo no debería ver
      // "POST /auth/backup-code/login → 401: ..." — solo el texto que mandó el
      // backend (AuthedHttpError.detail, ver authedFetch.ts).
      setError(
        e instanceof AuthedHttpError && e.detail
          ? e.detail
          : e instanceof Error
            ? e.message
            : "No se pudo verificar el código.",
      );
    } finally {
      setBackupBusy(false);
    }
  }

  async function handleEnrollAfterRecovery() {
    setEnrollBusy(true);
    try {
      await registerPasskey("admin");
      window.location.href = "/admin";
    } catch (e) {
      setError(passkeyErrorMessage(e));
      setEnrollBusy(false);
    }
  }

  if (recovered) {
    return (
      <BackOfficeAuthCard
        title="Recuperaste el acceso"
        description="Registrá una clave de acceso nueva en este dispositivo — sin esto, la próxima vez vas a volver a quedar sin poder entrar."
        error={error}
      >
        <button
          onClick={handleEnrollAfterRecovery}
          disabled={enrollBusy}
          className="w-full flex items-center justify-center gap-3 rounded-md border hairline bg-background py-2.5 text-sm font-medium text-ink transition hover:bg-surface active:scale-[0.98] disabled:opacity-60"
        >
          <KeyRound className="h-4 w-4" />
          {enrollBusy ? "Registrando…" : "Registrar clave de acceso"}
        </button>
        <button
          onClick={() => (window.location.href = "/admin")}
          className="w-full text-center text-xs text-muted-foreground hover:text-ink transition mt-2"
        >
          Ahora no, llevame al admin
        </button>
      </BackOfficeAuthCard>
    );
  }

  if (pasoPasskey) {
    // Bug real (encontrado en revisión): esta pantalla no chequeaba `supported`
    // — en un navegador sin WebAuthn, mostraba el botón igual y el error al
    // clickearlo era el genérico de "no encontramos tu clave" (falso acá: el
    // problema es el navegador, no que falte registrarla). Una vez que la
    // cuenta tiene 2º factor, Google solo ya no alcanza — pero ahora SÍ hay
    // vuelta atrás desde este dispositivo: un código de respaldo (abajo).
    return (
      <BackOfficeAuthCard
        title="Confirmá tu identidad"
        description="Tu cuenta de Google es correcta. Como segundo factor, confirmá con tu clave de acceso para entrar."
        error={error}
      >
        {supported ? (
          <button
            onClick={handlePasskeyLogin}
            disabled={passkeyBusy}
            className="w-full flex items-center justify-center gap-3 rounded-md border hairline bg-background py-2.5 text-sm font-medium text-ink transition hover:bg-surface active:scale-[0.98] disabled:opacity-60"
          >
            <KeyRound className="h-4 w-4" />
            {passkeyBusy ? "Verificando…" : "Confirmar con mi clave de acceso"}
          </button>
        ) : (
          <div className="rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-xs text-ink">
            Este navegador no soporta claves de acceso. Entrá desde el dispositivo donde la
            registraste (celular, u otra compu con Face ID/Touch ID/Windows Hello) — o usá un código
            de respaldo abajo.
          </div>
        )}

        {/* Recovery: perdió el dispositivo con la passkey. Independiente de `supported` —
            es un código de texto, no una ceremonia WebAuthn, así que sirve incluso en un
            navegador sin soporte. */}
        {showBackupForm ? (
          <div className="space-y-2 border-t hairline pt-3 mt-1">
            <Input
              autoFocus
              value={backupCode}
              onChange={(e) => setBackupCode(e.target.value)}
              placeholder="XXXXX-XXXXX"
              className="text-center font-mono uppercase"
              onKeyDown={(e) => e.key === "Enter" && handleBackupCodeLogin()}
            />
            <button
              onClick={handleBackupCodeLogin}
              disabled={backupBusy || !backupCode.trim()}
              className="w-full flex items-center justify-center gap-3 rounded-md border hairline bg-background py-2.5 text-sm font-medium text-ink transition hover:bg-surface active:scale-[0.98] disabled:opacity-60"
            >
              {backupBusy ? "Verificando…" : "Confirmar código"}
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowBackupForm(true)}
            className="w-full text-center text-xs text-muted-foreground hover:text-ink transition"
          >
            ¿Perdiste el dispositivo? Usar un código de respaldo
          </button>
        )}
      </BackOfficeAuthCard>
    );
  }

  return (
    <BackOfficeAuthCard
      title="Acceso admin"
      description={
        devMode
          ? "Modo desarrollo — sin OAuth requerido."
          : "Ingresá con tu cuenta de Google autorizada."
      }
      error={error}
    >
      {devMode && (
        <button
          onClick={handleDevLogin}
          className="w-full flex items-center justify-center gap-3 rounded-md border hairline bg-amber/10 border-amber/30 py-2.5 text-sm font-medium text-ink transition hover:bg-amber/15 active:scale-[0.98]"
        >
          Entrar en modo desarrollo
        </button>
      )}

      {googleEnabled && (
        <button
          onClick={handleGoogleLogin}
          className="w-full flex items-center justify-center gap-3 rounded-md border hairline bg-background py-2.5 text-sm font-medium text-ink transition hover:bg-surface active:scale-[0.98]"
        >
          <GoogleIcon />
          Entrar con Google
        </button>
      )}

      {supported && (
        <button
          onClick={handlePasskeyLogin}
          disabled={passkeyBusy}
          className="w-full flex items-center justify-center gap-3 rounded-md border hairline bg-background py-2.5 text-sm font-medium text-ink transition hover:bg-surface active:scale-[0.98] disabled:opacity-60"
        >
          <KeyRound className="h-4 w-4" />
          {passkeyBusy ? "Verificando…" : "Entrar con clave de acceso"}
        </button>
      )}
    </BackOfficeAuthCard>
  );
}
