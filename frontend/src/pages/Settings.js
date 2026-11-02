import { EmailSettings, SdiInfo } from "../components/IntegrationSettings";
import { RecoveryCodes, TotpSetup } from "../components/TwoFactorSetup";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Badge, Button, Card, ErrorBox, Field, Loading, Modal, Notice, PageHeader, useToast } from "../components/ui";
import { api, errorMessage, setToken } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ROLE_LABELS, fmtDateTime } from "../lib/format";

export default function Settings() {
  const { user, companies, can, reload, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = useState(() => (user.is_owner && params.get("nuova") === "1" ? {} : null));
  useEffect(() => {
    if (params.has("nuova")) setParams({}, { replace: true });
  }, [params, setParams]);

  return (
    <>
      <PageHeader title="Impostazioni" subtitle={`${user.name} · ${user.email}`} />
      <div className="grid gap-4 xl:grid-cols-2">
        <TwoFactor user={user} onChanged={reload} />
        <PasswordCard />
      </div>

      {!user.is_developer && <NotificationPrefs />}
      {!user.is_developer && <CategoryRules />}
      {user.is_owner && (
        <div className="grid gap-4 xl:grid-cols-2">
          <EmailSettings onSaved={reload} />
          <SdiInfo />
        </div>
      )}
      {user.is_owner && <Outbox />}

      {!user.is_developer && <Card title="Le tue aziende" actions={user.is_owner && <Button data-testid="new-company-btn" onClick={() => setEditing({})}>+ Nuova azienda</Button>}>
        <ul className="divide-y divide-soft">
          {companies.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-3 py-3">
              <span className="min-w-[200px] flex-1">
                <span className="block font-semibold">{c.name}</span>
                <span className="block text-xs text-muted">P.IVA {c.vat_number || "—"} · codice SDI {c.sdi_code || "—"} · {ROLE_LABELS[c.role]}</span>
              </span>
              {can(c.id, "manage_members") && <Button variant="secondary" className="min-h-[40px]" onClick={() => setEditing(c)}>Modifica dati</Button>}
            </li>
          ))}
        </ul>
      </Card>}

      <Card title="Sicurezza della sessione">
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted">Se pensi che qualcuno abbia usato il tuo account, esci da tutti i dispositivi: dovrai accedere di nuovo ovunque.</p>
          <div>
            <Button variant="danger" onClick={async () => {
              try {
                await api.post("/auth/logout-everywhere");
                logout();
                navigate("/login");
              } catch (e) {
                toast(errorMessage(e), "orange");
              }
            }}>Esci da tutti i dispositivi</Button>
          </div>
        </div>
      </Card>

      {editing && (
        <CompanyModal key={editing.id || "new"} company={editing} onClose={() => setEditing(null)}
          onDone={() => { setEditing(null); toast("Dati salvati"); reload(); }} />
      )}
    </>
  );
}

function TwoFactor({ user, onChanged }) {
  const toast = useToast();
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (fn) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const start = () => run(async () => setSetup((await api.post("/auth/2fa/setup")).data));
  const enable = (c) => run(async () => {
    const res = await api.post("/auth/2fa/enable", { code: c });
    setSetup(null);
    setCodes(res.data.recovery_codes);
  });
  const regenerate = () => run(async () => {
    const res = await api.post("/auth/2fa/recovery-codes", { code });
    setCode("");
    setCodes(res.data.recovery_codes);
  });
  const disable = () => run(async () => {
    await api.post("/auth/2fa/disable", { code });
    toast("Verifica in due passaggi disattivata");
    setCode("");
    onChanged();
  });

  return (
    <Card title="Verifica in due passaggi" subtitle="Oltre alla password serve un codice dall'app sul telefono">
      <div className="flex flex-col gap-4" data-testid="twofactor-card">
        <ErrorBox>{error}</ErrorBox>
        {codes ? (
          <RecoveryCodes codes={codes} doneLabel="Fatto" onDone={() => { setCodes(null); onChanged(); }} />
        ) : user.totp_enabled ? (
          <>
            <Notice>
              Attiva{user.twofa_required ? " e obbligatoria per tutti" : ""}. Codici di recupero rimasti:{" "}
              <span className="font-semibold" data-testid="recovery-codes-left">{user.recovery_codes_left}</span>.
            </Notice>
            <Field label="Codice a 6 cifre dall'app" htmlFor="tfa-code" hint="Serve per generare nuovi codici di recupero (i vecchi smettono di funzionare).">
              <input id="tfa-code" inputMode="numeric" maxLength={6} className="input w-40" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} data-testid="tfa-code" />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" loading={busy} onClick={regenerate} disabled={code.length !== 6} data-testid="regenerate-recovery-btn">Nuovi codici di recupero</Button>
              {!user.twofa_required && <Button variant="danger" loading={busy} onClick={disable} disabled={code.length !== 6}>Disattiva</Button>}
            </div>
          </>
        ) : !setup ? (
          <>
            <Notice tone="orange">Non attiva.</Notice>
            <div><Button onClick={start}>Attiva</Button></div>
          </>
        ) : (
          <TotpSetup setup={setup} busy={busy} onConfirm={enable} onCancel={() => setSetup(null)} />
        )}
      </div>
    </Card>
  );
}

function PasswordCard() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.post("/auth/password", { current_password: current, new_password: next });
      setToken(res.data.access_token);
      setCurrent("");
      setNext("");
      toast("Password aggiornata. Gli altri dispositivi dovranno accedere di nuovo.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Cambia password">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <ErrorBox>{error}</ErrorBox>
        <Field label="Password attuale" htmlFor="pw-cur"><input id="pw-cur" type="password" autoComplete="current-password" className="input" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
        <Field label="Nuova password" htmlFor="pw-new" hint="Almeno 10 caratteri, con lettere e numeri."><input id="pw-new" type="password" autoComplete="new-password" className="input" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
        <div><Button type="submit" loading={busy} disabled={!current || !next}>Aggiorna password</Button></div>
      </form>
    </Card>
  );
}

function CompanyModal({ company, onClose, onDone }) {
  const [form, setForm] = useState(() => ({
    name: company.name || "", vat_number: company.vat_number || "", tax_code: company.tax_code || "",
    sdi_code: company.sdi_code || "", pec: company.pec || "", address: company.address || "",
  }));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      if (company.id) await api.patch(`/companies/${company.id}`, form);
      else await api.post("/companies", form);
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={company.id ? "Dati dell'azienda" : "Nuova azienda"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={submit} loading={busy} disabled={!form.name.trim()}>Salva</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        {error && <div className="sm:col-span-2"><ErrorBox>{error}</ErrorBox></div>}
        <div className="sm:col-span-2"><Field label="Ragione sociale" htmlFor="co-name"><input id="co-name" className="input" value={form.name} onChange={set("name")} /></Field></div>
        <Field label="Partita IVA" htmlFor="co-vat" hint="Serve per riconoscere le fatture XML di questa azienda"><input id="co-vat" className="input" value={form.vat_number} onChange={set("vat_number")} /></Field>
        <Field label="Codice fiscale" htmlFor="co-cf"><input id="co-cf" className="input" value={form.tax_code} onChange={set("tax_code")} /></Field>
        <Field label="Codice destinatario SDI" htmlFor="co-sdi"><input id="co-sdi" className="input" value={form.sdi_code} onChange={set("sdi_code")} /></Field>
        <Field label="PEC" htmlFor="co-pec"><input id="co-pec" className="input" value={form.pec} onChange={set("pec")} /></Field>
        <div className="sm:col-span-2"><Field label="Indirizzo" htmlFor="co-addr"><input id="co-addr" className="input" value={form.address} onChange={set("address")} /></Field></div>
      </div>
    </Modal>
  );
}

function NotificationPrefs() {
  const toast = useToast();
  const [prefs, setPrefs] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api.get("/me/notification-settings").then((r) => setPrefs(r.data)).catch((e) => setError(errorMessage(e)));
  }, []);

  if (!prefs) return <Card title="Notifiche"><Loading /></Card>;
  const set = (k) => (e) => setPrefs((p) => ({ ...p, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const save = async () => {
    setBusy("save");
    setError("");
    try {
      await api.put("/me/notification-settings", prefs);
      toast("Preferenze salvate");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };
  const test = async () => {
    setBusy("test");
    try {
      const r = await api.post("/me/notification-settings/test");
      toast(r.data.mode === "smtp" ? `Riepilogo inviato a ${prefs.email}` : "Email non inviata: il titolare deve configurare la casella email in Impostazioni", r.data.mode === "smtp" ? undefined : "orange");
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
    }
  };

  return (
    <section id="notifiche">
      <Card title="Notifiche" subtitle="Nel programma le vedi sempre (campanella). Qui scegli cosa ricevere anche fuori.">
        <div className="flex flex-col gap-3">
          <ErrorBox>{error}</ErrorBox>
          {prefs.channels.email !== "smtp" && (
            <Notice tone="orange">Le email non partono ancora: il titolare deve configurare la casella email (Impostazioni → Casella email per gli invii).</Notice>
          )}
          <label className="flex min-h-[44px] items-center gap-2 text-sm">
            <input type="checkbox" className="h-[18px] w-[18px]" checked={prefs.email_alerts} onChange={set("email_alerts")} />
            Avvisi importanti via email a {prefs.email} (pagamenti in scadenza, crediti scaduti, liquidità in calo, domande del commercialista)
          </label>
          <label className="flex min-h-[44px] items-center gap-2 text-sm">
            <input type="checkbox" className="h-[18px] w-[18px]" checked={prefs.weekly_digest} onChange={set("weekly_digest")} />
            Riepilogo settimanale via email il lunedì mattina
          </label>
          <label className="flex min-h-[44px] items-center gap-2 text-sm">
            <input type="checkbox" className="h-[18px] w-[18px]" checked={prefs.monthly_report} onChange={set("monthly_report")} />
            Report mensile in PDF il primo del mese
          </label>
          {prefs.channels.whatsapp !== "none" && (
            <label className="flex min-h-[44px] items-center gap-2 text-sm">
              <input type="checkbox" className="h-[18px] w-[18px]" checked={prefs.whatsapp_alerts} onChange={set("whatsapp_alerts")} />
              Avvisi importanti anche su WhatsApp
            </label>
          )}
          {prefs.channels.whatsapp !== "none" && prefs.whatsapp_alerts && (
            <Field label="Numero WhatsApp" htmlFor="wa-num" hint="Con il prefisso internazionale, es. +39 333 1234567">
              <input id="wa-num" type="tel" className="input max-w-xs" value={prefs.whatsapp_number} onChange={set("whatsapp_number")} />
            </Field>
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={save} loading={busy === "save"}>Salva</Button>
            <Button variant="secondary" onClick={test} loading={busy === "test"}>Mandami ora il riepilogo</Button>
          </div>
        </div>
      </Card>
    </section>
  );
}

function CategoryRules() {
  const toast = useToast();
  const [rules, setRules] = useState(null);
  const load = useCallback(() => {
    api.get("/category-rules").then((r) => setRules(r.data)).catch(() => setRules([]));
  }, []);
  useEffect(() => { load(); }, [load]);
  const remove = async (r) => {
    try {
      await api.delete(`/category-rules/${r.id}`);
      toast("Regola eliminata");
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };
  return (
    <Card title="Regole di categoria" subtitle="Create quando correggi la categoria di un movimento: valgono per i movimenti nuovi">
      {!rules ? <Loading /> : rules.length === 0 ? (
        <p className="text-sm text-muted">Nessuna regola. Quando cambi la categoria di un movimento il programma ti propone di crearne una.</p>
      ) : (
        <ul className="divide-y divide-soft">
          {rules.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
              <span className="min-w-[220px] flex-1">
                Se contiene <strong>"{r.pattern}"</strong>{r.direction === "in" ? " (entrate)" : r.direction === "out" ? " (uscite)" : ""} → <strong>{r.category}</strong>
                <span className="block text-xs text-muted">{r.company_name}{r.created_by_name ? ` · ${r.created_by_name}` : ""}</span>
              </span>
              <Button variant="ghost" className="min-h-[40px] px-2 text-warn-text" onClick={() => remove(r)}>Elimina</Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Outbox() {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);
  useEffect(() => {
    api.get("/outbox", { params: { limit: 30 } }).then((r) => setData(r.data)).catch(() => setData({ items: [] }));
  }, []);
  return (
    <Card title="Messaggi del programma"
      subtitle="Ultime email inviate (o non partite perché la casella non era configurata)">
      {!data ? <Loading /> : data.items.length === 0 ? <p className="text-sm text-muted">Nessun messaggio.</p> : (
        <ul className="divide-y divide-soft">
          {data.items.map((m) => (
            <li key={m.id} className="py-2.5">
              <button type="button" className="flex min-h-[40px] w-full flex-wrap items-center gap-3 text-left text-sm" onClick={() => setOpen(open === m.id ? null : m.id)} aria-expanded={open === m.id}>
                <Badge tone={m.status === "errore" ? "orange" : m.status === "inviato" ? "blue" : "gray"}>{m.channel === "email" ? "Email" : "WhatsApp"} · {m.status}</Badge>
                <span className="min-w-[200px] flex-1 truncate font-semibold">{m.subject || m.body.slice(0, 80)}</span>
                <span className="text-xs text-muted">{m.to} · {fmtDateTime(m.created_at)}</span>
              </button>
              {open === m.id && (
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-page p-3 font-sans text-xs leading-relaxed">
                  {m.body}{m.attachments?.length ? `\n\nAllegati: ${m.attachments.join(", ")}` : ""}{m.error ? `\n\nErrore: ${m.error}` : ""}
                </pre>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
