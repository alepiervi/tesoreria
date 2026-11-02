import { useCallback, useEffect, useRef, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, useToast } from "../components/ui";
import { centsToInput } from "../lib/accounting";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { eur } from "../lib/format";

const MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const monthLabel = (m) => (m ? `${MONTHS[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}` : "");

export default function CentralRisk() {
  const [company, setCompany] = usePageCompany("view");
  const { can } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState(null);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const r = await api.get(`/companies/${company.id}/central-risk`);
      setData(r.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company]);
  useEffect(() => { setData(null); load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda disponibile" />;
  const canEdit = can(company.id, "manage_banks");
  const openMonth = async (month) => {
    const rows = month ? (await api.get(`/companies/${company.id}/central-risk/${month}`)).data : [];
    setEdit({ month: month || new Date(new Date().getFullYear(), new Date().getMonth() - 1, 15).toISOString().slice(0, 7),
      rows: rows.length ? rows.map((r) => ({ bank: r.bank, category: r.category, granted: centsToInput(r.granted_cents), used: centsToInput(r.used_cents),
        overdraft: centsToInput(r.overdraft_cents), past_due: centsToInput(r.past_due_cents) }))
        : (data?.rows || []).map((r) => ({ bank: r.bank, category: r.category, granted: centsToInput(r.granted_cents), used: "", overdraft: "", past_due: "" })) });
  };
  const maxUsed = Math.max(1, ...(data?.trend || []).map((t) => t.granted_cents));

  return (
    <>
      <PageHeader title="Centrale Rischi e affidamenti" subtitle="Come ti vedono le banche: accordato, utilizzato e sconfinamenti mese per mese"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} />
          {canEdit && <Button onClick={() => openMonth(null)}>Aggiungi un mese</Button>}
        </>} />
      <Notice>
        Il prospetto mensile si chiede gratis alla Banca d'Italia (servizio online «Centrale Rischi») oppure alla tua banca. Inseriscilo qui
        ogni mese: il programma controlla gli sconfinamenti, che sono tra i segnali di allerta del Codice della crisi.
      </Notice>
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : !data.latest_month ? (
        <Card><Empty title="Nessun dato inserito" text="Aggiungi l'ultimo prospetto della Centrale Rischi." /></Card>
      ) : (
        <>
          <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
            <Card title={`Situazione di ${monthLabel(data.latest_month)}`} padded={false}
              actions={canEdit && <Button variant="secondary" onClick={() => openMonth(data.latest_month)}>Modifica</Button>}>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[620px] text-sm">
                  <thead>
                    <tr className="table-head text-left">
                      <th className="px-5 py-3">Banca e tipo</th>
                      <th className="py-3 pr-3 text-right">Accordato</th>
                      <th className="py-3 pr-3 text-right">Utilizzato</th>
                      <th className="py-3 pr-5 text-right">Sconfinato / scaduto</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((r) => (
                      <tr key={r.id} className="border-b border-soft">
                        <td className="px-5 py-2.5"><b>{r.bank}</b><span className="block text-xs text-muted">{data.categories[r.category]}</span></td>
                        <td className="num py-2.5 pr-3 text-right">{eur(r.granted_cents)}</td>
                        <td className="num py-2.5 pr-3 text-right">{eur(r.used_cents)}</td>
                        <td className={`num py-2.5 pr-5 text-right ${r.overdraft_cents + r.past_due_cents ? "font-bold text-warn-amount" : "text-muted"}`}>
                          {eur(r.overdraft_cents + r.past_due_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="Per banca">
              <ul className="flex flex-col gap-4">
                {data.banks.map((b) => (
                  <li key={b.bank} className="flex flex-col gap-1.5">
                    <div className="flex items-center justify-between gap-2 text-sm">
                      <b>{b.bank}</b>
                      <span className="num text-muted">{eur(b.used_cents)} su {eur(b.granted_cents)}</span>
                    </div>
                    <div className="h-2.5 overflow-hidden rounded-full bg-soft" role="img" aria-label={`Utilizzo ${Math.round((b.usage || 0) * 100)}%`}>
                      <div className={`h-full rounded-full ${b.usage > 0.9 ? "bg-warn" : "bg-accent"}`} style={{ width: `${Math.min(100, (b.usage || 0) * 100)}%` }} />
                    </div>
                    {b.overdraft_cents + b.past_due_cents > 0 && <Badge tone="orange">Sconfinamento {eur(b.overdraft_cents + b.past_due_cents)}</Badge>}
                  </li>
                ))}
              </ul>
              {data.differences.length > 0 && (
                <div className="mt-4 flex flex-col gap-2">
                  {data.differences.map((d) => (
                    <p key={d.bank} className="rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn-dark">
                      {d.bank}: in Finanziamenti hai fidi per {eur(d.program_cents)}, la Centrale Rischi riporta {eur(d.central_risk_cents)}. Aggiorna uno dei due.
                    </p>
                  ))}
                </div>
              )}
            </Card>
          </div>
          <Card title="Andamento" subtitle="Accordato (chiaro) e utilizzato (scuro) per mese">
            <div className="flex items-end gap-3 overflow-x-auto pb-1" style={{ minHeight: 170 }}>
              {data.trend.map((t) => (
                <button key={t.month} type="button" disabled={!canEdit} onClick={() => openMonth(t.month)}
                  className="flex min-w-[54px] flex-col items-center gap-1 text-xs disabled:cursor-default">
                  <div className="relative flex h-[130px] w-9 items-end rounded bg-accent-soft" style={{ height: 130 * (t.granted_cents / maxUsed) || 4 }}>
                    <div className="w-full rounded bg-accent" style={{ height: `${t.granted_cents ? Math.min(100, (t.used_cents / t.granted_cents) * 100) : 0}%` }} />
                  </div>
                  <span className="text-muted">{monthLabel(t.month)}</span>
                  {t.overdraft_cents > 0 && <span className="font-bold text-warn-amount">!</span>}
                </button>
              ))}
            </div>
          </Card>
        </>
      )}
      <MonthModal value={edit} categories={data?.categories || {}} companyId={company.id} onClose={() => setEdit(null)}
        onSaved={() => { toast("Centrale Rischi aggiornata"); load(); }} />
    </>
  );
}

function MonthModal({ value, categories, companyId, onClose, onSaved }) {
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const fileRef = useRef(null);
  useEffect(() => {
    if (!value) return;
    setError("");
    setForm({ month: value.month, rows: value.rows.length ? value.rows : [{ bank: "", category: "revoca", granted: "", used: "", overdraft: "", past_due: "" }] });
  }, [value]);
  if (!value || !form) return null;
  const setRow = (i, patch) => setForm((f) => ({ ...f, rows: f.rows.map((r, n) => (n === i ? { ...r, ...patch } : r)) }));
  const save = async () => {
    setBusy("save");
    try {
      await api.put(`/companies/${companyId}/central-risk`, form);
      onSaved();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };
  const read = async (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    setBusy("read");
    try {
      const r = await api.post(`/companies/${companyId}/central-risk/read`, fd);
      if (r.data.read) setForm({ month: r.data.month || form.month, rows: r.data.rows });
      else setError(r.data.message);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  return (
    <Modal open wide onClose={onClose} title="Prospetto della Centrale Rischi"
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save} loading={busy === "save"}>Salva</Button></>}>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Mese" htmlFor="cr-m"><input id="cr-m" type="month" className="input w-auto" value={form.month} onChange={(e) => setForm({ ...form, month: e.target.value })} /></Field>
          <input ref={fileRef} type="file" accept="application/pdf,image/*" className="hidden" onChange={(e) => read(e.target.files?.[0])} />
          <Button variant="secondary" loading={busy === "read"} onClick={() => fileRef.current?.click()}>Leggi dal PDF</Button>
          <span className="text-xs text-muted">Con l'assistente collegato a Claude i dati si compilano dal PDF; controllali sempre.</span>
        </div>
        {form.rows.map((r, i) => (
          <div key={i} className="grid gap-2 rounded-lg border border-line p-3 md:grid-cols-[1.2fr_1.4fr_1fr_1fr_1fr_1fr_auto]">
            <input aria-label="Banca" placeholder="Banca" className="input" value={r.bank} onChange={(e) => setRow(i, { bank: e.target.value })} />
            <select aria-label="Tipo" className="input" value={r.category} onChange={(e) => setRow(i, { category: e.target.value })}>
              {Object.entries(categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            {[["granted", "Accordato"], ["used", "Utilizzato"], ["overdraft", "Sconfinato"], ["past_due", "Scaduto"]].map(([k, l]) => (
              <input key={k} aria-label={l} placeholder={l} inputMode="decimal" className="input num text-right" value={r[k]} onChange={(e) => setRow(i, { [k]: e.target.value })} />
            ))}
            <Button variant="ghost" className="text-warn-text" aria-label="Togli riga" onClick={() => setForm((f) => ({ ...f, rows: f.rows.filter((_, n) => n !== i) }))}>✕</Button>
          </div>
        ))}
        <Button variant="secondary" className="self-start" onClick={() => setForm((f) => ({ ...f, rows: [...f.rows, { bank: "", category: "revoca", granted: "", used: "", overdraft: "", past_due: "" }] }))}>
          Aggiungi riga
        </Button>
        <ErrorBox>{error}</ErrorBox>
      </div>
    </Modal>
  );
}
