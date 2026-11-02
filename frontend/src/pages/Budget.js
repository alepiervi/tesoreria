import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Modal, Notice, PageHeader, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { eur } from "../lib/format";

const MONTHS = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"];

function Bar({ pct, revenue }) {
  const w = Math.min(100, pct ?? 0);
  const bad = pct !== null && (revenue ? pct < 100 : pct > 100);
  const warn = pct !== null && !revenue && pct > 90 && pct <= 100;
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-soft" aria-hidden="true">
      <div className="h-full rounded-full" style={{ width: `${w}%`, background: bad ? "#C25A17" : warn ? "#E8772E" : "#2346D8" }} />
    </div>
  );
}

export default function Budget() {
  const [company, setCompany] = usePageCompany("view");
  const { can } = useAuth();
  const toast = useToast();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const res = await api.get(`/companies/${company.id}/budget`, { params: { year, month } });
      setData(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, year, month]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  if (!company) return <Empty title="Nessuna azienda disponibile" />;
  const canEdit = can(company.id, "manage_budget");

  return (
    <>
      <PageHeader title="Budget" subtitle="Quanto avevi previsto di spendere e incassare, e quanto è successo davvero"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} />
          <select aria-label="Mese" className="input w-auto" value={month} onChange={(e) => setMonth(Number(e.target.value))}>
            {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
          </select>
          <select aria-label="Anno" className="input w-auto" value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {[now.getFullYear() + 1, now.getFullYear(), now.getFullYear() - 1].map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          {canEdit && <Button onClick={() => setEditing(true)}>Imposta budget</Button>}
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <>
          {!data.has_budget && (
            <Notice>Nessun budget per il {year}. {canEdit ? "Clicca \"Imposta budget\": puoi partire dalla media dei mesi passati." : ""}</Notice>
          )}
          <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-4">
            <div className="rounded-xl border border-line bg-white px-5 py-4">
              <span className="text-[13px] text-muted">Costi di {MONTHS[month - 1].toLowerCase()}</span>
              <p className="num text-xl font-bold">{eur(data.totals.cost_actual_cents)}</p>
              <span className="text-xs text-muted">su {eur(data.totals.cost_budget_cents)} previsti</span>
            </div>
            <div className="rounded-xl border border-line bg-white px-5 py-4">
              <span className="text-[13px] text-muted">Incassi di {MONTHS[month - 1].toLowerCase()}</span>
              <p className="num text-xl font-bold">{eur(data.totals.revenue_actual_cents)}</p>
              <span className="text-xs text-muted">obiettivo {eur(data.totals.revenue_budget_cents)}</span>
            </div>
          </div>
          <Card padded={false}>
            {data.rows.length === 0 ? <Empty title="Nessun dato per questo mese" /> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[820px] text-sm">
                  <thead>
                    <tr className="table-head text-left">
                      <th className="px-5 py-3">Categoria</th>
                      <th className="w-[28%] py-3 pr-3">Mese</th>
                      <th className="py-3 pr-3 text-right">Reale</th>
                      <th className="py-3 pr-3 text-right">Budget</th>
                      <th className="py-3 pr-5 text-right">Da inizio anno</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((r) => {
                      const revenue = r.kind === "entrata";
                      return (
                        <tr key={r.category} className="border-b border-soft">
                          <td className="px-5 py-3">
                            <span className="font-semibold">{r.category}</span>
                            {revenue && <Badge className="ml-2" tone="blue">Entrata</Badge>}
                          </td>
                          <td className="py-3 pr-3">
                            {r.budget_cents ? (
                              <div className="flex items-center gap-2">
                                <Bar pct={r.pct} revenue={revenue} />
                                <span className={`w-12 text-right text-xs font-semibold ${r.over ? "text-warn-text" : "text-muted"}`}>{r.pct}%</span>
                              </div>
                            ) : <span className="text-xs text-muted">Nessun budget</span>}
                          </td>
                          <td className="num py-3 pr-3 text-right font-semibold">{eur(r.actual_cents)}</td>
                          <td className="num py-3 pr-3 text-right text-muted">{r.budget_cents ? eur(r.budget_cents) : "—"}</td>
                          <td className="num py-3 pr-5 text-right text-xs">
                            {eur(r.ytd_actual_cents)}{r.ytd_budget_cents ? <span className="text-muted"> / {eur(r.ytd_budget_cents)}</span> : ""}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
      {editing && data && (
        <BudgetEditor company={company} year={year} data={data} onClose={() => setEditing(false)}
          onDone={() => { setEditing(false); toast("Budget salvato"); load(); }} />
      )}
    </>
  );
}

function BudgetEditor({ company, year, data, onClose, onDone }) {
  const initial = Object.fromEntries(data.categories.map((c) => {
    const row = data.rows.find((r) => r.category === c);
    return [c, row ? row.months.map((v) => (v ? String(v / 100).replace(".", ",") : "")) : Array(12).fill("")];
  }));
  const [values, setValues] = useState(initial);
  const [perMonth, setPerMonth] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const setAll = (cat, v) => setValues((s) => ({ ...s, [cat]: Array(12).fill(v) }));
  const setOne = (cat, i, v) => setValues((s) => ({ ...s, [cat]: s[cat].map((x, n) => (n === i ? v : x)) }));
  const toCents = (v) => Math.round(parseFloat(String(v).replace(/\./g, "").replace(",", ".")) * 100) || 0;

  const suggest = async () => {
    try {
      const res = await api.get(`/companies/${company.id}/budget/suggest`);
      setValues((s) => {
        const next = { ...s };
        Object.entries(res.data).forEach(([c, cents]) => { if (next[c]) next[c] = Array(12).fill(String(cents / 100).replace(".", ",")); });
        return next;
      });
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const items = Object.entries(values).map(([category, months]) => ({ category, months: months.map(toCents) }));
      await api.put(`/companies/${company.id}/budget`, { year, items });
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open wide onClose={onClose} title={`Budget ${year} · ${company.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save} loading={busy}>Salva budget</Button></>}>
      <div className="flex flex-col gap-4">
        <ErrorBox>{error}</ErrorBox>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" onClick={suggest}>Proponi dalla media degli ultimi 12 mesi</Button>
          <label className="flex min-h-[44px] items-center gap-2 text-sm">
            <input type="checkbox" className="h-[18px] w-[18px]" checked={perMonth} onChange={(e) => setPerMonth(e.target.checked)} />
            Importi diversi per ogni mese
          </label>
        </div>
        <p className="text-xs text-muted">Importi mensili in euro. Per "Incassi clienti" e "Altre entrate" è l'obiettivo di incasso.</p>
        <div className="flex flex-col divide-y divide-soft">
          {data.categories.map((c) => (
            <div key={c} className="flex flex-col gap-2 py-2">
              <div className="flex flex-wrap items-center gap-3">
                <label htmlFor={`b-${c}`} className="min-w-[200px] flex-1 text-sm font-semibold">{c}</label>
                {!perMonth && (
                  <input id={`b-${c}`} inputMode="decimal" className="input w-40 text-right" placeholder="0"
                    value={values[c][0]} onChange={(e) => setAll(c, e.target.value)} />
                )}
              </div>
              {perMonth && (
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                  {MONTHS.map((m, i) => (
                    <input key={m} aria-label={`${c} ${m}`} inputMode="decimal" className="input min-h-[40px] text-right text-[13px]"
                      placeholder={m.slice(0, 3)} value={values[c][i]} onChange={(e) => setOne(c, i, e.target.value)} />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </Modal>
  );
}
