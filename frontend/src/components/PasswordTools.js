import { useState } from "react";
import { api, errorMessage, setToken } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button, ErrorBox, Field, Notice } from "./ui";

export function TempPasswordBox({ email, password, onClose, newAccount = false }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-line bg-white p-4" data-testid="temp-password-box">
      <Notice tone="orange">
        Password provvisoria per <span className="font-semibold">{email}</span>. Comunicala di persona o al telefono:
        al primo accesso dovrà sceglierne una nuova.{" "}
        {newAccount ? "Al primo accesso attiverà anche la verifica in due passaggi." : "La verifica in due passaggi resta quella già attiva."}
      </Notice>
      <div className="flex flex-wrap items-center gap-2">
        <code className="rounded-lg bg-soft px-3 py-2 font-mono text-base font-semibold tracking-wide" data-testid="temp-password-value">{password}</code>
        <Button variant="secondary" className="min-h-[36px]" data-testid="temp-password-copy"
          onClick={() => navigator.clipboard.writeText(password).then(() => setCopied(true)).catch(() => {})}>
          {copied ? "Copiata" : "Copia"}
        </Button>
        {onClose && <Button variant="ghost" className="min-h-[36px]" onClick={onClose} data-testid="temp-password-close">Chiudi</Button>}
      </div>
      <p className="text-xs text-muted">Non verrà mostrata di nuovo.</p>
    </div>
  );
}

export function ForcePasswordChange() {
  const { user, login, logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (next !== confirm) return setError("Le due password non coincidono.");
    setBusy(true);
    setError("");
    try {
      const r = await api.post("/auth/password", { current_password: current, new_password: next });
      setToken(r.data.access_token);
      await login(r.data.access_token);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-4 py-10">
      <form onSubmit={submit} className="flex w-full max-w-[440px] flex-col gap-4 rounded-2xl border border-line bg-white p-6" data-testid="force-password-change">
        <h1 className="text-lg font-semibold">Scegli la tua nuova password</h1>
        <Notice>Stai usando una password provvisoria ({user.email}). Per continuare scegline una personale.</Notice>
        <ErrorBox>{error}</ErrorBox>
        <Field label="Password provvisoria" htmlFor="fp-current">
          <input id="fp-current" type="password" required autoComplete="current-password" className="input" value={current} onChange={(e) => setCurrent(e.target.value)} data-testid="force-pw-current" />
        </Field>
        <Field label="Nuova password" htmlFor="fp-new" hint="Almeno 10 caratteri, con lettere e numeri.">
          <input id="fp-new" type="password" required autoComplete="new-password" className="input" value={next} onChange={(e) => setNext(e.target.value)} data-testid="force-pw-new" />
        </Field>
        <Field label="Ripeti la nuova password" htmlFor="fp-confirm">
          <input id="fp-confirm" type="password" required autoComplete="new-password" className="input" value={confirm} onChange={(e) => setConfirm(e.target.value)} data-testid="force-pw-confirm" />
        </Field>
        <Button type="submit" loading={busy} data-testid="force-pw-submit">Salva e continua</Button>
        <Button variant="ghost" onClick={logout} data-testid="force-pw-logout">Esci</Button>
      </form>
    </div>
  );
}
