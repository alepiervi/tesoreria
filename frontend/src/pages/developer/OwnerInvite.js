import { useCallback, useEffect, useState } from "react";
import { Button, Card, ErrorBox, Field, Notice, PageHeader, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";

const when = (iso) => new Date(iso).toLocaleDateString("it-IT");

export default function DevOwnerInvite() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [link, setLink] = useState(null);
  const [pending, setPending] = useState([]);
  const toast = useToast();

  const load = useCallback(() => {
    api.get("/developer/owner-invites").then((r) => setPending(r.data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api.post("/developer/owner-invites", { email, name });
      setLink({ id: r.data.id, url: r.data.invite_url });
      setEmail("");
      setName("");
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    await navigator.clipboard.writeText(link.url).catch(() => {});
    toast("Link copiato");
  };

  const cancel = async (id) => {
    await api.delete(`/developer/owner-invites/${id}`);
    if (link?.id === id) setLink(null);
    load();
  };

  return (
    <>
      <PageHeader title="Invito titolare" subtitle="Il titolare crea le aziende e vede tutti i dati. Tu resti senza accesso ai dati." />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Nuovo link di invito" subtitle="Valido 7 giorni. Il titolare sceglie da solo la sua password.">
          <form onSubmit={submit} className="flex flex-col gap-4" data-testid="owner-invite-form">
            <ErrorBox>{error}</ErrorBox>
            <Field label="Email del titolare" htmlFor="owner-email">
              <input id="owner-email" type="email" className="input" required value={email} onChange={(e) => setEmail(e.target.value)} data-testid="owner-invite-email" />
            </Field>
            <Field label="Nome (facoltativo)" htmlFor="owner-name">
              <input id="owner-name" className="input" value={name} onChange={(e) => setName(e.target.value)} data-testid="owner-invite-name" />
            </Field>
            <div><Button type="submit" loading={busy} data-testid="owner-invite-submit">Crea link di invito</Button></div>
          </form>
          {link && (
            <div className="mt-4 flex flex-col gap-2" data-testid="owner-invite-link-box">
              <Notice>Link creato. Invialo al titolare: aprendolo crea il suo account e prende in carico tutte le aziende.</Notice>
              <div className="flex gap-2">
                <input readOnly value={link.url} className="input flex-1 font-mono text-xs" data-testid="owner-invite-link" onFocus={(e) => e.target.select()} />
                <Button variant="secondary" onClick={copy} data-testid="owner-invite-copy">Copia</Button>
              </div>
            </div>
          )}
        </Card>
        <Card title="Inviti in attesa">
          {pending.length === 0 ? <p className="text-sm text-muted">Nessun invito in attesa.</p> : (
            <ul className="divide-y divide-soft" data-testid="owner-invites-pending">
              {pending.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                  <span className="flex-1"><span className="font-semibold">{i.email}</span> <span className="text-muted">· scade il {when(i.expires_at)}</span></span>
                  <Button variant="secondary" className="min-h-[36px]" onClick={() => cancel(i.id)} data-testid={`owner-invite-cancel-${i.id}`}>Annulla</Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
