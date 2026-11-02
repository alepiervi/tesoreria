import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Button, ErrorBox, Field, Notice } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { IDLE_MINUTES } from "../lib/idle";

const DEMO = [
  ["titolare@demo.it", "Titolare"],
  ["amministrazione@demo.it", "Amministrazione"],
  ["commercialista@demo.it", "Commercialista"],
];
const SHOW_DEMO = process.env.REACT_APP_SHOW_DEMO_LOGIN !== "false";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={location.state?.from || "/"} replace />;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.post("/auth/login", { email, password, totp_code: needCode ? code : undefined });
      await login(res.data.access_token);
      navigate(location.state?.from || "/", { replace: true });
    } catch (err) {
      if (err.response?.data?.detail === "2fa_required") {
        setNeedCode(true);
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-4 py-10">
      <div className="flex w-full max-w-[420px] flex-col gap-6">
        <div className="flex flex-col gap-1">
          <span className="flex items-center gap-3 text-2xl font-bold tracking-tight">
            <img src="/logo.png" alt="Logo Nureal" data-testid="app-logo" className="h-11 w-11 rounded-xl" />
            Nureal-Amministrazione
          </span>
          <span className="text-sm text-muted">Accedi per vedere conti, fatture e scadenze delle tue aziende.</span>
        </div>
        <form onSubmit={submit} className="flex flex-col gap-4 rounded-2xl border border-line bg-white p-6">
          <ErrorBox>{error}</ErrorBox>
          {new URLSearchParams(location.search).get("scaduta") === "1" && !error && (
            <div data-testid="idle-logout-notice"><Notice>Sei stato disconnesso dopo {IDLE_MINUTES} minuti di inattività. Accedi di nuovo per continuare.</Notice></div>
          )}
          {!needCode ? (
            <>
              <Field label="Email" htmlFor="email">
                <input id="email" type="email" autoComplete="username" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
              </Field>
              <Field label="Password" htmlFor="password">
                <input id="password" type="password" autoComplete="current-password" required className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
              </Field>
            </>
          ) : (
            <Field label="Codice di verifica" htmlFor="code" hint="Apri l'app di autenticazione sul telefono e inserisci il codice a 6 cifre.">
              <input id="code" inputMode="numeric" autoComplete="one-time-code" maxLength={8} required className="input text-lg tracking-[0.3em]" value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
          )}
          <Button type="submit" loading={busy}>{needCode ? "Verifica e accedi" : "Accedi"}</Button>
          {needCode && (
            <Button variant="ghost" onClick={() => { setNeedCode(false); setCode(""); }}>Torna indietro</Button>
          )}
        </form>
        {SHOW_DEMO && !needCode && (
          <div className="flex flex-col gap-2 rounded-2xl border border-dashed border-[#C9CDD4] p-4">
            <span className="text-xs font-semibold text-muted">Utenti di prova · password Demo2026demo</span>
            <div className="flex flex-wrap gap-2">
              {DEMO.map(([mail, label]) => (
                <Button key={mail} variant="secondary" className="min-h-[40px] text-[13px]" onClick={() => { setEmail(mail); setPassword("Demo2026demo"); }}>
                  {label}
                </Button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
