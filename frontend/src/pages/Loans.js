import { useCallback, useEffect, useState } from "react";
import CompanyPicker from "../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, PageHeader, Stat, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { eur, fmtDate, todayIso } from "../lib/format";

const CREDIT = new Set(["fido", "anticipo_fatture"]);

export default function Loans() {
  const { companiesWith } = useAuth();
  const toast = useToast();
  const [companyId, setCompanyId] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null);
  const [plan, setPlan] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get("/loans", { params: { company_id: companyId || undefined } });
      setData(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [companyId]);

  useEffect(() => {
    load();
  }, [load]);

  const editable = companiesWith("manage_deadlines");
  const remove = async (l) => {
    if (!window.confirm(`Eliminare ${l.kind_label} ${l.lender}?`)) return;
    try {
      await api.delete(`/loans/${l.id}`);
      toast("Eliminato");
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };

  const amort = (data?.items || []).filter((l) => !CREDIT.has(l.kind));
  const lines = (data?.items || []).filter((l) => CREDIT.has(l.kind));

  return (
    <>
      <PageHeader title="Finanziamenti e fidi" subtitle="Le rate entrano da sole nella previsione di cassa; i fidi si sommano alla liquidità disponibile"
        actions={<>
          <CompanyPicker value={companyId} onChange={setCompanyId} allowAll />
          {editable.length > 0 && <Button onClick={() => setEditing({})}>+ Aggiungi</Button>}
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
            <Stat label="Debito residuo" value={eur(data.totals.residual_cents, { short: true })} sub="Mutui, finanziamenti e leasing" />
            <Stat label="Rate al mese" value={eur(data.totals.monthly_installments_cents, { short: true })} />
            <Stat label="Fidi disponibili" value={eur(data.totals.credit_available_cents, { short: true })} sub={`su ${eur(data.totals.credit_limit_cents, { short: true })} accordati`} />
          </div>

          <Card title="Mutui, finanziamenti e leasing" padded={false}>
            {amort.length === 0 ? <Empty title="Nessun finanziamento" /> : (
              <div className="overflow-x-auto px-5 pb-4">
                <table className="w-full min-w-[820px] text-sm">
                  <thead><tr className="table-head text-left">
                    <th className="py-2 pr-3">Finanziamento</th><th className="py-2 pr-3 text-right">Rata</th><th className="py-2 pr-3">Rate</th>
                    <th className="py-2 pr-3">Prossima</th><th className="py-2 pr-3 text-right">Residuo</th><th />
                  </tr></thead>
                  <tbody>
                    {amort.map((l) => (
                      <tr key={l.id} className={`border-b border-soft ${l.active === false ? "opacity-50" : ""}`}>
                        <td className="py-3 pr-3"><span className="font-semibold">{l.kind_label} · {l.lender}</span>
                          <span className="block text-xs text-muted">{l.description}{l.description ? " · " : ""}{l.company_name}{l.rate ? ` · tasso ${String(l.rate).replace(".", ",")}%` : ""}</span></td>
                        <td className="num py-3 pr-3 text-right font-semibold">{eur(l.installment_cents)}</td>
                        <td className="py-3 pr-3 text-xs">{l.paid_installments} pagate · {l.remaining_installments} da pagare
                          <div className="mt-1 h-1.5 w-28 overflow-hidden rounded-full bg-soft" aria-hidden="true">
                            <div className="h-full bg-accent" style={{ width: `${(l.paid_installments / Math.max(1, l.paid_installments + l.remaining_installments)) * 100}%` }} />
                          </div></td>
                        <td className="py-3 pr-3">{l.next_date ? fmtDate(l.next_date, { year: true }) : <Badge tone="blue">Estinto</Badge>}</td>
                        <td className="num py-3 pr-3 text-right font-semibold">{eur(l.residual_cents)}</td>
                        <td className="py-3 text-right">
                          <span className="flex justify-end gap-1">
                            <Button variant="ghost" className="min-h-[40px] px-2" onClick={() => setPlan(l)}>Piano</Button>
                            {l.can_edit && <Button variant="ghost" className="min-h-[40px] px-2" onClick={() => setEditing(l)}>Modifica</Button>}
                            {l.can_edit && <Button variant="ghost" className="min-h-[40px] px-2 text-warn-text" onClick={() => remove(l)}>Elimina</Button>}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Fidi e anticipi">
            {lines.length === 0 ? <p className="text-sm text-muted">Nessun fido inserito.</p> : (
              <ul className="divide-y divide-soft">
                {lines.map((l) => (
                  <li key={l.id} className="flex flex-wrap items-center gap-3 py-3">
                    <span className="min-w-[200px] flex-1"><span className="block font-semibold">{l.kind_label} · {l.lender}</span>
                      <span className="block text-xs text-muted">{l.company_name}</span></span>
                    <span className="w-56">
                      <div className="h-2.5 overflow-hidden rounded-full bg-soft" aria-hidden="true">
                        <div className="h-full bg-warn" style={{ width: `${Math.min(100, (l.used_cents / Math.max(1, l.limit_cents)) * 100)}%` }} />
                      </div>
                      <span className="text-xs text-muted">usati {eur(l.used_cents)} su {eur(l.limit_cents)}</span>
                    </span>
                    <span className="num w-32 text-right font-bold">{eur(l.available_cents)}<span className="block text-xs font-normal text-muted">disponibili</span></span>
                    {l.can_edit && <Button variant="ghost" className="min-h-[40px] px-2" onClick={() => setEditing(l)}>Aggiorna</Button>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
      {editing && <LoanModal loan={editing} companies={editable} kinds={data?.kinds || {}} onClose={() => setEditing(null)}
        onDone={() => { setEditing(null); toast("Salvato"); load(); }} />}
      {plan && <PlanModal loan={plan} onClose={() => setPlan(null)} />}
    </>
  );
}

function LoanModal({ loan, companies, kinds, onClose, onDone }) {
  const money = (c) => (c ? (c / 100).toFixed(2).replace(".", ",") : "");
  const [form, setForm] = useState({
    company_id: loan.company_id || companies[0]?.id, kind: loan.kind || "mutuo", lender: loan.lender || "",
    description: loan.description || "", principal: money(loan.principal_cents), rate: loan.rate ?? "", months: loan.months || "",
    start_date: loan.start_date || todayIso(), installment: loan.id && !loan.principal_cents ? money(loan.installment_cents) : "",
    limit: money(loan.limit_cents), used: money(loan.used_cents), active: loan.active !== false,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const credit = CREDIT.has(form.kind);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const body = { ...form, rate: Number(String(form.rate).replace(",", ".")) || 0, months: Number(form.months) || 0 };
      if (loan.id) await api.put(`/loans/${loan.id}`, body);
      else await api.post(`/companies/${form.company_id}/loans`, body);
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={loan.id ? "Modifica" : "Nuovo finanziamento o fido"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save} loading={busy}>Salva</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        {error && <div className="sm:col-span-2"><ErrorBox>{error}</ErrorBox></div>}
        {!loan.id && companies.length > 1 && (
          <div className="sm:col-span-2"><Field label="Azienda" htmlFor="ln-co">
            <select id="ln-co" className="input" value={form.company_id} onChange={set("company_id")}>
              {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select></Field></div>
        )}
        <Field label="Tipo" htmlFor="ln-kind">
          <select id="ln-kind" className="input" value={form.kind} onChange={set("kind")} disabled={Boolean(loan.id)}>
            {Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Banca o società" htmlFor="ln-lender"><input id="ln-lender" className="input" value={form.lender} onChange={set("lender")} /></Field>
        <div className="sm:col-span-2"><Field label="Descrizione" htmlFor="ln-desc"><input id="ln-desc" className="input" value={form.description} onChange={set("description")} placeholder="Es. mutuo capannone" /></Field></div>
        {credit ? (
          <>
            <Field label="Importo accordato (€)" htmlFor="ln-limit"><input id="ln-limit" inputMode="decimal" className="input" value={form.limit} onChange={set("limit")} /></Field>
            <Field label="Utilizzato oggi (€)" htmlFor="ln-used"><input id="ln-used" inputMode="decimal" className="input" value={form.used} onChange={set("used")} /></Field>
          </>
        ) : (
          <>
            <Field label="Importo finanziato (€)" htmlFor="ln-princ" hint="Con importo e tasso la rata si calcola da sola."><input id="ln-princ" inputMode="decimal" className="input" value={form.principal} onChange={set("principal")} /></Field>
            <Field label="Tasso annuo (%)" htmlFor="ln-rate"><input id="ln-rate" inputMode="decimal" className="input" value={form.rate} onChange={set("rate")} /></Field>
            <Field label="Numero di rate mensili" htmlFor="ln-months"><input id="ln-months" type="number" min={1} className="input" value={form.months} onChange={set("months")} /></Field>
            <Field label="Data della prima rata" htmlFor="ln-start"><input id="ln-start" type="date" className="input" value={form.start_date} onChange={set("start_date")} /></Field>
            <div className="sm:col-span-2"><Field label="Oppure rata fissa (€)" htmlFor="ln-inst" hint="Per i leasing: lascia vuoto l'importo finanziato e scrivi la rata."><input id="ln-inst" inputMode="decimal" className="input" value={form.installment} onChange={set("installment")} /></Field></div>
          </>
        )}
        <label className="flex min-h-[44px] items-center gap-2 text-sm"><input type="checkbox" className="h-[18px] w-[18px]" checked={form.active} onChange={set("active")} /> Attivo</label>
      </div>
    </Modal>
  );
}

function PlanModal({ loan, onClose }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    api.get(`/loans/${loan.id}/schedule`).then((r) => setRows(r.data.rows)).catch(() => setRows([]));
  }, [loan]);
  const today = todayIso();
  return (
    <Modal open wide onClose={onClose} title={`Piano di rimborso · ${loan.kind_label} ${loan.lender}`}>
      {!rows ? <Loading /> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead><tr className="table-head text-left"><th className="py-2 pr-3">N.</th><th className="py-2 pr-3">Data</th>
              <th className="py-2 pr-3 text-right">Rata</th><th className="py-2 pr-3 text-right">Interessi</th><th className="py-2 pr-3 text-right">Capitale</th><th className="py-2 text-right">Residuo</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.n} className={`border-b border-soft ${r.date <= today ? "text-muted" : ""}`}>
                  <td className="py-1.5 pr-3">{r.n}</td><td className="py-1.5 pr-3">{fmtDate(r.date, { year: true })}</td>
                  <td className="num py-1.5 pr-3 text-right">{eur(r.installment_cents)}</td>
                  <td className="num py-1.5 pr-3 text-right">{r.interest_cents ? eur(r.interest_cents) : "—"}</td>
                  <td className="num py-1.5 pr-3 text-right">{eur(r.principal_cents)}</td>
                  <td className="num py-1.5 text-right">{loan.principal_cents ? eur(r.residual_cents) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}
