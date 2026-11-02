import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ROLE_LABELS, fmtDateTime } from "../lib/format";

export default function Members() {
  const { companiesWith, user } = useAuth();
  const toast = useToast();
  const managed = companiesWith("manage_members");
  const [members, setMembers] = useState(null);
  const [invites, setInvites] = useState([]);
  const [error, setError] = useState("");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [newLink, setNewLink] = useState(null);

  const load = useCallback(async () => {
    try {
      const [m, i] = await Promise.all([api.get("/members"), api.get("/invites")]);
      setMembers(m.data);
      setInvites(i.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  const canManage = managed.length > 0;
  useEffect(() => {
    if (canManage) load();
  }, [load, canManage]);

  if (!managed.length) return <Empty title="Accesso non consentito" text="Solo il titolare può gestire gli utenti." />;

  const act = async (fn, text) => {
    try {
      await fn();
      toast(text);
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };

  const companyName = (id) => managed.find((c) => c.id === id)?.name || "";

  return (
    <>
      <PageHeader title="Utenti e accessi" subtitle="Chi può vedere cosa, azienda per azienda"
        actions={<Button onClick={() => setInviteOpen(true)}>+ Invita un utente</Button>} />
      <ErrorBox>{error}</ErrorBox>

      {newLink && (
        <Notice>
          <div className="flex flex-col gap-2">
            <span>Invito creato per <strong>{newLink.email}</strong>. Manda questo link alla persona (vale 7 giorni):</span>
            <div className="flex flex-wrap gap-2">
              <input readOnly aria-label="Link di invito" className="input flex-1 font-mono text-xs" value={newLink.url} onFocus={(e) => e.target.select()} />
              <Button variant="secondary" onClick={() => navigator.clipboard?.writeText(newLink.url).then(() => toast("Link copiato"))}>Copia link</Button>
            </div>
          </div>
        </Notice>
      )}

      {!members ? <Loading /> : (
        <Card padded={false} title="Chi ha accesso">
          <ul className="divide-y divide-line">
            {members.map((m) => (
              <li key={m.id} className={`flex flex-col gap-3 px-5 py-4 ${m.active ? "" : "opacity-60"}`}>
                <div className="flex flex-wrap items-center gap-3">
                  <span className="min-w-[200px] flex-1">
                    <span className="block font-semibold">{m.name || m.email}{m.is_me && <span className="font-normal text-muted"> (tu)</span>}</span>
                    <span className="block text-xs text-muted">{m.email} · ultimo accesso {m.last_login_at ? fmtDateTime(m.last_login_at) : "mai"}</span>
                  </span>
                  <Badge tone={m.totp_enabled ? "blue" : "orange"}>{m.totp_enabled ? "Verifica in due passaggi attiva" : "Verifica da attivare al prossimo accesso"}</Badge>
                  {!m.active && <Badge>Disattivato</Badge>}
                  {user.is_owner && !m.is_me && !m.is_owner && m.totp_enabled && (
                    <Button variant="secondary" className="min-h-[40px]" data-testid={`reset-2fa-${m.id}`}
                      onClick={() => window.confirm(`Azzerare la verifica in due passaggi di ${m.email}? Al prossimo accesso dovrà riattivarla con il nuovo telefono.`) && act(() => api.post(`/members/${m.id}/reset-2fa`), "Verifica azzerata")}>
                      Azzera verifica
                    </Button>
                  )}
                  {user.is_owner && !m.is_me && !m.is_owner && (
                    m.active
                      ? <Button variant="danger" className="min-h-[40px]" onClick={() => window.confirm(`Bloccare ${m.email} su tutte le aziende?`) && act(() => api.post(`/members/${m.id}/deactivate`), "Utente disattivato")}>Disattiva</Button>
                      : <Button variant="secondary" className="min-h-[40px]" onClick={() => act(() => api.post(`/members/${m.id}/activate`), "Utente riattivato")}>Riattiva</Button>
                  )}
                </div>
                <div className="flex flex-col gap-2">
                  {m.access.map((a) => (
                    <div key={a.company_id} className="flex flex-wrap items-center gap-3 rounded-lg bg-page px-3 py-2">
                      <span className="min-w-[160px] flex-1 text-sm font-semibold">{a.company_name}</span>
                      <label htmlFor={`role-${m.id}-${a.company_id}`} className="sr-only">Ruolo su {a.company_name}</label>
                      <select id={`role-${m.id}-${a.company_id}`} className="input min-h-[40px] w-auto text-[13px]" value={a.role} disabled={m.is_me || m.is_owner}
                        onChange={(e) => act(() => api.put(`/members/${m.id}/companies/${a.company_id}`, { role: e.target.value }), "Ruolo aggiornato")}>
                        {Object.entries(ROLE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                      </select>
                      {!m.is_me && !m.is_owner && (
                        <Button variant="ghost" className="min-h-[40px] px-2 text-warn-text"
                          onClick={() => window.confirm(`Revocare l'accesso di ${m.email} a ${a.company_name}?`) && act(() => api.delete(`/members/${m.id}/companies/${a.company_id}`), "Accesso revocato")}>
                          Revoca
                        </Button>
                      )}
                    </div>
                  ))}
                  {!m.is_me && !m.is_owner && <AddAccess member={m} managed={managed} onAdd={(cid, role) => act(() => api.put(`/members/${m.id}/companies/${cid}`, { role }), "Accesso aggiunto")} />}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {invites.length > 0 && (
        <Card title="Inviti in attesa">
          <ul className="divide-y divide-soft">
            {invites.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center gap-3 py-3">
                <span className="min-w-[200px] flex-1">
                  <span className="block font-semibold">{i.email}</span>
                  <span className="block text-xs text-muted">{ROLE_LABELS[i.role]} · {i.company_ids.map(companyName).filter(Boolean).join(", ")} · scade {fmtDateTime(i.expires_at)}</span>
                </span>
                <Button variant="ghost" className="min-h-[40px] px-2 text-warn-text" onClick={() => act(() => api.delete(`/invites/${i.id}`), "Invito annullato")}>Annulla</Button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <InviteModal open={inviteOpen} managed={managed} onClose={() => setInviteOpen(false)}
        onDone={(inv) => { setInviteOpen(false); setNewLink({ email: inv.email, url: `${window.location.origin}${inv.invite_path}` }); load(); }} />
    </>
  );
}

function AddAccess({ member, managed, onAdd }) {
  const missing = managed.filter((c) => !member.access.some((a) => a.company_id === c.id));
  const [cid, setCid] = useState("");
  const [role, setRole] = useState("lettura");
  if (!missing.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor={`add-${member.id}`} className="sr-only">Aggiungi azienda</label>
      <select id={`add-${member.id}`} className="input min-h-[40px] w-auto text-[13px]" value={cid} onChange={(e) => setCid(e.target.value)}>
        <option value="">+ Dai accesso a un'altra azienda…</option>
        {missing.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      {cid && (
        <>
          <select aria-label="Ruolo" className="input min-h-[40px] w-auto text-[13px]" value={role} onChange={(e) => setRole(e.target.value)}>
            {Object.entries(ROLE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <Button className="min-h-[40px]" onClick={() => { onAdd(cid, role); setCid(""); }}>Aggiungi</Button>
        </>
      )}
    </div>
  );
}

function InviteModal({ open, managed, onClose, onDone }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("commercialista");
  const [picked, setPicked] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const company_ids = managed.filter((c) => picked[c.id]).map((c) => c.id);
      const res = await api.post("/invites", { email, name, role, company_ids });
      setEmail("");
      setName("");
      setPicked({});
      onDone(res.data);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Invita un utente"
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={submit} loading={busy}>Crea invito</Button></>}>
      <div className="flex flex-col gap-4">
        <ErrorBox>{error}</ErrorBox>
        <Field label="Email" htmlFor="inv-email"><input id="inv-email" type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="nome@studio.it" /></Field>
        <Field label="Nome (facoltativo)" htmlFor="inv-name"><input id="inv-name" className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Ruolo" htmlFor="inv-role" hint={ROLE_HINTS[role]}>
          <select id="inv-role" className="input" value={role} onChange={(e) => setRole(e.target.value)}>
            {Object.entries(ROLE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <fieldset className="flex flex-col gap-1">
          <legend className="label mb-2">Aziende a cui dare accesso</legend>
          {managed.map((c) => (
            <label key={c.id} className="flex min-h-[44px] items-center gap-2 text-sm">
              <input type="checkbox" className="h-[18px] w-[18px]" checked={Boolean(picked[c.id])} onChange={(e) => setPicked((p) => ({ ...p, [c.id]: e.target.checked }))} />
              {c.name}
            </label>
          ))}
        </fieldset>
        <Notice>Dopo aver creato l'invito riceverai un link da mandare alla persona. Al primo accesso sceglierà la sua password.</Notice>
      </div>
    </Modal>
  );
}

const ROLE_HINTS = {
  titolare: "Vede e fa tutto, autorizza i pagamenti, gestisce gli utenti.",
  amministrazione: "Gestisce fatture, scadenze e riconciliazioni; prepara i pagamenti ma non li autorizza.",
  commercialista: "Consulta, scrive note, chiede chiarimenti, carica documenti ed esporta. Non paga e non modifica.",
  lettura: "Può solo consultare.",
};
