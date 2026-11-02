import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button, ErrorBox, Field, Loading } from "../components/ui";
import { api, errorMessage } from "../lib/api";

export default function AcceptInvite() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [info, setInfo] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get(`/invites/token/${token}`)
      .then((res) => { setInfo(res.data); setName(res.data.name || ""); })
      .catch((e) => setLoadError(errorMessage(e)));
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (!info.existing_user && password !== confirm) {
      setError("Le due password non coincidono.");
      return;
    }
    setBusy(true);
    try {
      const res = await api.post(`/invites/token/${token}/accept`, { name, password, totp_code: code || undefined });
      navigate("/login", { replace: true, state: { email: res.data.email, invited: res.data.existing_user ? "existing" : "new" } });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-4 py-10">
      <div className="flex w-full max-w-[440px] flex-col gap-6">
        <span className="flex items-center gap-3 text-2xl font-bold tracking-tight">
          <img src="/logo.png" alt="Logo Nureal" data-testid="app-logo" className="h-11 w-11 rounded-xl" />
          Nureal-Amministrazione
        </span>
        {loadError ? (
          <ErrorBox>{loadError}</ErrorBox>
        ) : !info ? (
          <Loading />
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-4 rounded-2xl border border-line bg-white p-6">
            <div className="flex flex-col gap-1">
              <h1 className="text-lg font-semibold">Sei stato invitato come {info.role_label}</h1>
              <p className="text-sm text-muted">
                {info.owner_invite
                  ? "Potrai creare le aziende del gruppo, vedere tutti i dati e invitare i collaboratori."
                  : `Avrai accesso a: ${info.companies.join(", ")}.`}
              </p>
              <p className="text-sm text-muted">Account: <strong className="text-ink">{info.email}</strong></p>
            </div>
            <ErrorBox>{error}</ErrorBox>
            {info.existing_user ? (
              <>
                <Field label="La tua password attuale" htmlFor="pw">
                  <input id="pw" type="password" required autoComplete="current-password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
                </Field>
                {info.existing_totp && (
                  <Field label="Codice di verifica" htmlFor="invite-code" hint="Il codice a 6 cifre dall'app sul telefono, oppure un codice di recupero (es. ABCD-EFGH).">
                    <input id="invite-code" autoComplete="one-time-code" maxLength={9} required className="input w-48 font-mono uppercase" value={code} onChange={(e) => setCode(e.target.value)} data-testid="invite-totp-code" />
                  </Field>
                )}
              </>
            ) : (
              <>
                <Field label="Nome e cognome (o nome dello studio)" htmlFor="name">
                  <input id="name" required className="input" value={name} onChange={(e) => setName(e.target.value)} />
                </Field>
                <Field label="Scegli una password" htmlFor="pw" hint="Almeno 10 caratteri, con lettere e numeri.">
                  <input id="pw" type="password" required autoComplete="new-password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
                </Field>
                <Field label="Ripeti la password" htmlFor="pw2">
                  <input id="pw2" type="password" required autoComplete="new-password" className="input" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                </Field>
              </>
            )}
            <Button type="submit" loading={busy}>Accetta l'invito</Button>
          </form>
        )}
      </div>
    </div>
  );
}
