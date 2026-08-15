import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { authedFetch } from "@/lib/authedFetch";
import { BackOfficeAuthCard } from "@/components/admin/BackOfficeAuthCard";
import { GoogleIcon } from "@/design-system/ui/GoogleIcon";
import { loginWithPasskey, passkeyLoginErrorMessage, passkeySupported } from "@/lib/passkey";
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
          ? "No encontramos tu clave de acceso en este dispositivo (o cancelaste). Tu cuenta ya tiene una clave registrada en OTRO dispositivo — entrá desde ese, o pedile a otro admin que te ayude a resetearla."
          : passkeyLoginErrorMessage(e),
      );
      setPasskeyBusy(false);
    }
  }

  if (pasoPasskey) {
    // Bug real (encontrado en revisión): esta pantalla no chequeaba `supported`
    // — en un navegador sin WebAuthn, mostraba el botón igual y el error al
    // clickearlo era el genérico de "no encontramos tu clave" (falso acá: el
    // problema es el navegador, no que falte registrarla). Una vez que la
    // cuenta tiene 2º factor, Google solo ya no alcanza — no hay vuelta atrás
    // desde ESTE dispositivo, así que al menos el mensaje tiene que ser honesto.
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
            registraste (celular, u otra compu con Face ID/Touch ID/Windows Hello).
          </div>
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
