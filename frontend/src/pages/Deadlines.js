import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, Tabs, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { DEADLINE_STATUS, KIND_LABELS, eur, fmtDate, todayIso } from "../lib/format";

export default function Deadlines() {
  const [tab, setTab] = useState("scadenze");
  return (
    <>
      <PageHeader title="Scadenzario" subtitle="Incassi, pagamenti, F24 e spese ricorrenti che alimentano la previsione" />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "scadenze", label: "Scadenze" }, { id: "ricorrenti", label: "Spese e entrate ricorrenti" }]} />
      {tab === "scadenze" ? <DeadlineList /> : <RecurringList />}
    </>
  );
}

function DeadlineList() {
  const { anyCan, companiesWith } = useAuth();
  const toast = useToast();
  const [companyId, setCompanyId] = useState("");
  const [scope, setScope] = useState("open");
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [payFor, setPayFor] = useState(null);
  const [newOpen, setNewOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get("/deadlines", { params: { company_id: companyId || undefined, scope } });
      setItems(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [companyId, scope]);

  useEffect(() => {
    load();
  }, [load]);

  const action = async (fn, text) => {
    try {
      await fn();
      toast(text);
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };

  const totals = (items || []).reduce((acc, d) => {
    if (["pagato", "incassato"].includes(d.status)) return acc;
    if (d.kind === "incasso") acc.in += d.amount_cents;
    else acc.out += d.amount_cents;
    return acc;
  }, { in: 0, out: 0 });

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <CompanyPicker value={companyId} onChange={setCompanyId} allowAll />
        <select aria-label="Quali scadenze" className="input w-auto" value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="open">Da saldare</option>
          <option value="all">Tutte, anche saldate</option>
        </select>
        <span className="flex-1" />
        {anyCan("manage_deadlines") && <Button onClick={() => setNewOpen(true)}>+ Nuova scadenza</Button>}
      </div>
      {items && (
        <div className="flex flex-wrap gap-4 text-sm">
          <span>Da incassare: <strong className="num">{eur(totals.in)}</strong></span>
          <span>Da pagare: <strong className="num text-warn-amount">{eur(totals.out)}</strong></span>
        </div>
      )}
      <ErrorBox>{error}</ErrorBox>
      {!items ? <Loading /> : (
        <Card padded={false}>
          {items.length === 0 ? <Empty title="Nessuna scadenza" /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-sm">
                <thead>
                  <tr className="table-head text-left">
                    <th className="px-5 py-3">Data</th>
                    <th className="py-3 pr-3">Tipo</th>
                    <th className="py-3 pr-3">Descrizione</th>
                    <th className="py-3 pr-3 text-right">Importo</th>
                    <th className="py-3 pr-3">Stato</th>
                    <th className="py-3 pr-5 text-right"><span className="sr-only">Azioni</span></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((d) => {
                    const p = d.permissions;
                    const isOut = d.kind !== "incasso";
                    const st = DEADLINE_STATUS[d.status] || [d.status, "gray"];
                    return (
                      <tr key={d.id} className="border-b border-soft">
                        <td className="whitespace-nowrap px-5 py-3 font-semibold">
                          {fmtDate(d.due_date, { year: true })}
                          {d.overdue && <Badge tone="orange" className="ml-2">Scaduta</Badge>}
                        </td>
                        <td className="py-3 pr-3"><Badge tone={d.kind === "incasso" ? "blue" : d.kind === "f24" ? "orange" : "gray"}>{KIND_LABELS[d.kind]}</Badge></td>
                        <td className="py-3 pr-3">
                          {d.description}
                          <span className="block text-xs text-muted">{d.company_name}{d.beneficiary ? ` · ${d.beneficiary}` : ""}</span>
                          {d.requested_by_name && d.status === "in_attesa_autorizzazione" && <span className="block text-xs text-warn-text">Preparato da {d.requested_by_name}</span>}
                          {d.payment_ref && <span className="block text-xs text-muted">Rif. {d.payment_ref}</span>}
                          {d.estimate && <span className="block text-xs text-warn-text">Stima calcolata dalle fatture: l'importo esatto lo conferma il commercialista</span>}
                        </td>
                        <td className={`num whitespace-nowrap py-3 pr-3 text-right font-semibold ${isOut ? "text-warn-amount" : ""}`}>{isOut ? "− " : "+ "}{eur(d.amount_cents)}</td>
                        <td className="py-3 pr-3"><Badge tone={st[1]}>{st[0]}</Badge></td>
                        <td className="py-3 pr-5">
                          <div className="flex flex-wrap justify-end gap-1">
                            {isOut && ["da_pagare", "in_attesa_autorizzazione"].includes(d.status) && p.includes("authorize_payment") && (
                              <Button className="min-h-[40px]" onClick={() => setPayFor({ d, mode: "authorize" })}>Autorizza pagamento</Button>
                            )}
                            {isOut && d.status === "da_pagare" && p.includes("request_payment") && !p.includes("authorize_payment") && (
                              <Button variant="secondary" className="min-h-[40px]" onClick={() => setPayFor({ d, mode: "request" })}>Prepara pagamento</Button>
                            )}
                            {isOut && d.status === "in_attesa_autorizzazione" && !p.includes("authorize_payment") && (
                              <span className="self-center text-xs text-muted">Lo autorizza il titolare</span>
                            )}
                            {["aperta", "da_pagare", "inviato"].includes(d.status) && p.includes("manage_deadlines") && (
                              <Button variant="ghost" className="min-h-[40px] px-2"
                                onClick={() => action(() => api.post(`/deadlines/${d.id}/mark-done`), "Scadenza chiusa")}>
                                {isOut ? "Segna pagata" : "Segna incassata"}
                              </Button>
                            )}
                            {!d.invoice_id && p.includes("manage_deadlines") && (
                              <Button variant="ghost" className="min-h-[40px] px-2 text-warn-text"
                                onClick={() => window.confirm("Eliminare questa scadenza?") && action(() => api.delete(`/deadlines/${d.id}`), "Scadenza eliminata")}>
                                Elimina
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
      <PayModal state={payFor} onClose={() => setPayFor(null)} onDone={(text) => { setPayFor(null); toast(text); load(); }} />
      <NewDeadlineModal open={newOpen} companies={companiesWith("manage_deadlines")} onClose={() => setNewOpen(false)}
        onDone={() => { setNewOpen(false); toast("Scadenza creata"); load(); }} />
    </>
  );
}

function PayModal({ state, onClose, onDone }) {
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!state) return;
    setError("");
    api.get(`/companies/${state.d.company_id}/bank-accounts`).then((r) => {
      const active = r.data.filter((a) => a.status === "attivo");
      setAccounts(active);
      setAccountId(state.d.account_id || active[0]?.id || "");
    }).catch((e) => setError(errorMessage(e)));
  }, [state]);

  if (!state) return null;
  const { d, mode } = state;
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const url = mode === "authorize" ? `/deadlines/${d.id}/authorize` : `/deadlines/${d.id}/request-payment`;
      const res = await api.post(url, { account_id: accountId });
      onDone(mode === "authorize" ? `Bonifico inviato (rif. ${res.data.payment_ref})` : "Pagamento preparato: ora deve autorizzarlo il titolare");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={mode === "authorize" ? "Autorizza il pagamento" : "Prepara il pagamento"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={submit} loading={busy} disabled={!accountId}>{mode === "authorize" ? `Paga ${eur(d.amount_cents)}` : "Invia al titolare"}</Button></>}>
      <div className="flex flex-col gap-4">
        <ErrorBox>{error}</ErrorBox>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-muted">Descrizione</dt><dd className="font-semibold">{d.description}</dd>
          <dt className="text-muted">Beneficiario</dt><dd>{d.beneficiary || "—"}</dd>
          {d.iban && <><dt className="text-muted">IBAN</dt><dd className="font-mono text-[13px]">{d.iban}</dd></>}
          <dt className="text-muted">Importo</dt><dd className="num font-semibold">{eur(d.amount_cents)}</dd>
          <dt className="text-muted">Scadenza</dt><dd>{fmtDate(d.due_date, { year: true })}</dd>
        </dl>
        <Field label="Conto da cui pagare" htmlFor="pay-acc">
          <select id="pay-acc" className="input" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.bank_name} · {a.label} {a.iban_masked} — {eur(a.balance_cents)}</option>)}
          </select>
        </Field>
        {mode === "authorize" && <Notice>Modalità demo: il bonifico è simulato. Con un provider reale confermerai con le credenziali della banca.</Notice>}
      </div>
    </Modal>
  );
}

function NewDeadlineModal({ open, companies, onClose, onDone }) {
  const empty = { company_id: "", kind: "pagamento", description: "", due_date: todayIso(), amount: "", beneficiary: "", iban: "" };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const companyId = form.company_id || companies[0]?.id;

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const { company_id, ...body } = form;
      await api.post(`/companies/${companyId}/deadlines`, body);
      setForm(empty);
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Nuova scadenza"
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={submit} loading={busy}>Salva</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2"><ErrorBox>{error}</ErrorBox></div>
        {companies.length > 1 && (
          <div className="sm:col-span-2">
            <Field label="Azienda" htmlFor="nd-co">
              <select id="nd-co" className="input" value={companyId} onChange={set("company_id")}>
                {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
          </div>
        )}
        <Field label="Tipo" htmlFor="nd-kind">
          <select id="nd-kind" className="input" value={form.kind} onChange={set("kind")}>
            {Object.entries(KIND_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Data di scadenza" htmlFor="nd-date"><input id="nd-date" type="date" className="input" value={form.due_date} onChange={set("due_date")} /></Field>
        <div className="sm:col-span-2">
          <Field label="Descrizione" htmlFor="nd-desc"><input id="nd-desc" className="input" value={form.description} onChange={set("description")} placeholder="Es. F24 IVA novembre" /></Field>
        </div>
        <Field label="Importo (€)" htmlFor="nd-amt"><input id="nd-amt" inputMode="decimal" className="input" value={form.amount} onChange={set("amount")} placeholder="1.500,00" /></Field>
        <Field label={form.kind === "incasso" ? "Da chi" : "Beneficiario"} htmlFor="nd-ben"><input id="nd-ben" className="input" value={form.beneficiary} onChange={set("beneficiary")} /></Field>
        {form.kind !== "incasso" && form.kind !== "f24" && (
          <div className="sm:col-span-2">
            <Field label="IBAN del beneficiario" htmlFor="nd-iban"><input id="nd-iban" className="input font-mono" value={form.iban} onChange={set("iban")} /></Field>
          </div>
        )}
      </div>
    </Modal>
  );
}

function RecurringList() {
  const [company, setCompany] = usePageCompany("view");
  const { can } = useAuth();
  const toast = useToast();
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const res = await api.get(`/companies/${company.id}/recurring`);
      setItems(res.data);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company]);

  useEffect(() => {
    load();
  }, [load]);

  if (!company) return <Empty title="Nessuna azienda disponibile" />;
  const canEdit = can(company.id, "manage_deadlines");
  const monthly = (items || []).filter((r) => r.active).reduce((s, r) => s + (r.kind === "entrata" ? r.amount_cents : -r.amount_cents), 0);

  const remove = async (r) => {
    if (!window.confirm(`Eliminare "${r.description}"?`)) return;
    try {
      await api.delete(`/recurring/${r.id}`);
      toast("Eliminata");
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <CompanyPicker value={company.id} onChange={setCompany} />
        <span className="flex-1" />
        {canEdit && <Button onClick={() => setEditing({})}>+ Aggiungi</Button>}
      </div>
      <Notice>Le voci ricorrenti (stipendi, affitto, rate) entrano nella previsione di cassa ogni mese nel giorno indicato.</Notice>
      <ErrorBox>{error}</ErrorBox>
      {!items ? <Loading /> : (
        <Card padded={false}>
          {items.length === 0 ? <Empty title="Nessuna voce ricorrente" text="Aggiungi stipendi, affitto e rate per avere una previsione più precisa." /> : (
            <ul className="divide-y divide-soft">
              {items.map((r) => (
                <li key={r.id} className={`flex flex-wrap items-center gap-3 px-5 py-3 ${r.active ? "" : "opacity-60"}`}>
                  <span className="w-24 text-sm text-muted">Ogni {r.day_of_month}</span>
                  <span className="min-w-[160px] flex-1 font-semibold">{r.description}{!r.active && <Badge className="ml-2">In pausa</Badge>}</span>
                  <span className={`num w-32 text-right font-semibold ${r.kind === "uscita" ? "text-warn-amount" : ""}`}>{r.kind === "uscita" ? "− " : "+ "}{eur(r.amount_cents)}</span>
                  {canEdit && (
                    <span className="flex gap-1">
                      <Button variant="ghost" className="min-h-[40px] px-2" onClick={() => setEditing(r)}>Modifica</Button>
                      <Button variant="ghost" className="min-h-[40px] px-2 text-warn-text" onClick={() => remove(r)}>Elimina</Button>
                    </span>
                  )}
                </li>
              ))}
              <li className="flex justify-end gap-3 px-5 py-3 text-sm">
                <span className="text-muted">Saldo mensile delle voci attive</span>
                <strong className={`num ${monthly < 0 ? "text-warn-amount" : ""}`}>{eur(monthly, { signed: true })}</strong>
              </li>
            </ul>
          )}
        </Card>
      )}
      <RecurringModal item={editing} companyId={company.id} onClose={() => setEditing(null)} onDone={() => { setEditing(null); toast("Salvato"); load(); }} />
    </>
  );
}

function RecurringModal({ item, companyId, onClose, onDone }) {
  const [form, setForm] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!item) return;
    setError("");
    setForm(item.id
      ? { kind: item.kind, description: item.description, amount: (item.amount_cents / 100).toFixed(2).replace(".", ","), day_of_month: item.day_of_month, active: item.active }
      : { kind: "uscita", description: "", amount: "", day_of_month: 27, active: true });
  }, [item]);

  if (!item) return null;
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const body = { ...form, day_of_month: Number(form.day_of_month) };
      if (item.id) await api.put(`/recurring/${item.id}`, body);
      else await api.post(`/companies/${companyId}/recurring`, body);
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={item.id ? "Modifica voce ricorrente" : "Nuova voce ricorrente"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={submit} loading={busy}>Salva</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2"><ErrorBox>{error}</ErrorBox></div>
        <Field label="Tipo" htmlFor="rc-kind">
          <select id="rc-kind" className="input" value={form.kind} onChange={set("kind")}>
            <option value="uscita">Uscita</option>
            <option value="entrata">Entrata</option>
          </select>
        </Field>
        <Field label="Giorno del mese" htmlFor="rc-day"><input id="rc-day" type="number" min={1} max={31} className="input" value={form.day_of_month} onChange={set("day_of_month")} /></Field>
        <div className="sm:col-span-2"><Field label="Descrizione" htmlFor="rc-desc"><input id="rc-desc" className="input" value={form.description} onChange={set("description")} placeholder="Es. Stipendi" /></Field></div>
        <Field label="Importo (€)" htmlFor="rc-amt"><input id="rc-amt" inputMode="decimal" className="input" value={form.amount} onChange={set("amount")} /></Field>
        <label className="flex min-h-[44px] items-center gap-2 self-end text-sm">
          <input type="checkbox" className="h-[18px] w-[18px]" checked={Boolean(form.active)} onChange={set("active")} /> Attiva
        </label>
      </div>
    </Modal>
  );
}
