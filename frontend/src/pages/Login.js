import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { RecoveryCodes, TotpSetup } from "../components/TwoFactorSetup";
import { Button, ErrorBox, Field, Notice } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { IDLE_MINUTES, clearIdleLogout, wasIdleLogout } from "../lib/idle";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState(location.state?.email || "");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [step, setStep] = useState("credentials");
  const [setup, setSetup] = useState(null);
  const [pending, setPending] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [idleLoggedOut] = useState(() => wasIdleLogout() || new URLSearchParams(location.search).get("scaduta") === "1");
  useEffect(() => clearIdleLogout(), []);

  if (user) return <Navigate to={location.state?.from || "/"} replace />;

  const enter = async (token) => {
    await login(token);
    navigate(location.state?.from || "/", { replace: true });
  };

  const reset = () => {
    setStep("credentials");
    setCode("");
    setSetup(null);
    setPassword("");
    setUseRecovery(false);
  };

  const run = async (fn) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (err) {
      if (err.response?.data?.detail === "2fa_required") setStep("code");
      else setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submit = (e) => {
    e.preventDefault();
    run(async () => {
      const res = await api.post("/auth/login", { email, password, totp_code: step === "code" ? code : undefined });
      if (res.data.setup_required) {
        const s = await api.post("/auth/2fa/enroll/start", { setup_token: res.data.setup_token });
        setSetup({ ...s.data, token: res.data.setup_token });
        setStep("setup");
        return;
      }
      await enter(res.data.access_token);
    });
  };

  const confirmSetup = (setupCode) => run(async () => {
    const res = await api.post("/auth/2fa/enroll/finish", { setup_token: setup.token, code: setupCode });
    setPending(res.data);
    setStep("codes");
  });

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-4 py-10">
      <div className="flex w-full max-w-[440px] flex-col gap-6">
        <div className="flex flex-col gap-1">
          <span className="flex items-center gap-3 text-2xl font-bold tracking-tight">
            <img src="/logo.png" alt="Logo Nureal" data-testid="app-logo" className="h-11 w-11 rounded-xl" />
            Nureal-Amministrazione
          </span>
          <span className="text-sm text-muted">Accedi per vedere conti, fatture e scadenze delle tue aziende.</span>
        </div>
        <div className="flex flex-col gap-4 rounded-2xl border border-line bg-white p-6">
          <ErrorBox>{error}</ErrorBox>
          {idleLoggedOut && !error && step === "credentials" && (
            <div data-testid="idle-logout-notice"><Notice>Sei stato disconnesso dopo {IDLE_MINUTES} minuti di inattività. Accedi di nuovo per continuare.</Notice></div>
          )}
          {location.state?.invited && step === "credentials" && (
            <div data-testid="invite-accepted-notice"><Notice>{location.state.invited === "existing" ? "Invito accettato: i nuovi accessi sono già attivi. Accedi come sempre con password e codice." : "Account pronto. Accedi con la password appena scelta: poi attiverai la verifica in due passaggi."}</Notice></div>
          )}

          {step === "setup" && (
            <>
              <div data-testid="setup-required-notice">
                <Notice tone="orange">Per sicurezza la verifica in due passaggi è obbligatoria per tutti. Attivala ora: servirà a ogni accesso.</Notice>
              </div>
              <TotpSetup setup={setup} busy={busy} onConfirm={confirmSetup} onCancel={reset} />
            </>
          )}

          {step === "codes" && pending && (
            <RecoveryCodes codes={pending.recovery_codes} doneLabel="Entra nel programma" onDone={() => enter(pending.access_token)} />
          )}

          {(step === "credentials" || step === "code") && (
            <form onSubmit={submit} className="flex flex-col gap-4" data-testid="login-form">
              {step === "credentials" ? (
                <>
                  <Field label="Email" htmlFor="email">
                    <input id="email" type="email" autoComplete="username" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
                  </Field>
                  <Field label="Password" htmlFor="password">
                    <input id="password" type="password" autoComplete="current-password" required className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
                  </Field>
                </>
              ) : useRecovery ? (
                <Field label="Codice di recupero" htmlFor="code" hint="Uno dei codici salvati quando hai attivato la verifica (es. ABCD-EFGH). Ognuno vale una volta.">
                  <input id="code" autoComplete="off" maxLength={9} required className="input font-mono text-lg uppercase tracking-widest" value={code} onChange={(e) => setCode(e.target.value)} data-testid="recovery-code-input" />
                </Field>
              ) : (
                <Field label="Codice di verifica" htmlFor="code" hint="Apri l'app di autenticazione sul telefono e inserisci il codice a 6 cifre.">
                  <input id="code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required className="input text-lg tracking-[0.3em]" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} data-testid="totp-code-input" />
                </Field>
              )}
              <Button type="submit" loading={busy} data-testid="login-submit">{step === "code" ? "Verifica e accedi" : "Accedi"}</Button>
              {step === "code" && (
                <>
                  <Button variant="ghost" data-testid="toggle-recovery" onClick={() => { setUseRecovery(!useRecovery); setCode(""); }}>
                    {useRecovery ? "Usa il codice dell'app" : "Ho perso il telefono: usa un codice di recupero"}
                  </Button>
                  <Button variant="ghost" onClick={reset}>Torna indietro</Button>
                </>
              )}
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
