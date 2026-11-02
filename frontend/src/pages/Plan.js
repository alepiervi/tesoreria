import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Button, Card, Empty, ErrorBox, Light, Loading, Notice, PageHeader, useToast } from "../components/ui";
import { centsToInput } from "../lib/accounting";
import { api, blobErrorMessage, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { eur, fmtDateTime } from "../lib/format";

const FIELDS = [
  ["revenue_growth", "Crescita dei ricavi", "%"],
  ["variable_cost_pct", "Costi variabili sui ricavi", "%"],
  ["fixed_cost_growth", "Aumento dei costi fissi", "%"],
  ["staff_growth", "Aumento del costo del personale", "%"],
  ["capex", "Investimenti", "€"],
  ["capex_rate", "Aliquota di ammortamento degli investimenti", "%"],
  ["new_loan", "Nuovo finanziamento", "€"],
  ["new_loan_rate", "Tasso del nuovo finanziamento", "%"],
  ["new_loan_months", "Durata del nuovo finanziamento", "mesi"],
  ["dso_days", "Giorni medi di incasso", "gg"],
  ["dpo_days", "Giorni medi di pagamento", "gg"],
  ["tax_rate", "Imposte sull'utile (IRES + IRAP)", "%"],
];

const ROWS = [
  ["ricavi", "Ricavi", true], ["costi_variabili", "Costi variabili"], ["costi_fissi", "Costi fissi"], ["personale", "Personale"],
  ["ebitda", "Margine operativo lordo (MOL)", true], ["ammortamenti", "Ammortamenti"], ["ebit", "Risultato operativo", true],
  ["interessi", "Interessi"], ["imposte", "Imposte"], ["utile", "Utile netto", true],
  ["sep", "Flussi di cassa"],
  ["flusso_operativo", "Flusso di cassa della gestione", true], ["variazione_circolante", "di cui variazione crediti/debiti commerciali"],
  ["investimenti", "Investimenti"], ["nuovi_finanziamenti", "Nuovi finanziamenti"], ["servizio_debito", "Rate dei finanziamenti"],
  ["cassa_fine", "Cassa a fine anno", true], ["debito_fine", "Debiti finanziari a fine anno"], ["pfn", "Debito finanziario netto"],
];

function toForm(a) {
  return {
    ...a, capex: centsToInput(a.capex_cents) || "0", new_loan: centsToInput(a.new_loan_cents) || "0",
    variable_cost_pct: a.variable_cost_pct ?? "", dso_days: a.dso_days ?? "", dpo_days: a.dpo_days ?? "",
  };
}

function toBody(years) {
  const num = (v) => (v === "" || v === null || v === undefined ? null : Number(String(v).replace(",", ".")));
  return years.map((y) => ({
    revenue_growth: num(y.revenue_growth) ?? 0, variable_cost_pct: num(y.variable_cost_pct), fixed_cost_growth: num(y.fixed_cost_growth) ?? 0,
    staff_growth: num(y.staff_growth) ?? 0, capex: String(y.capex || "0"), capex_rate: num(y.capex_rate) ?? 20,
    new_loan: String(y.new_loan || "0"), new_loan_rate: num(y.new_loan_rate) ?? 0, new_loan_months: Math.round(num(y.new_loan_months) || 60),
    dso_days: num(y.dso_days) === null ? null : Math.round(num(y.dso_days)), dpo_days: num(y.dpo_days) === null ? null : Math.round(num(y.dpo_days)),
    tax_rate: num(y.tax_rate) ?? 27.9,
  }));
}

export default function Plan() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const { can } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [years, setYears] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    if (!company) return;
    setData(null);
    try {
      const r = await api.get(`/companies/${company.id}/plan`);
      setData(r.data);
      setYears(r.data.assumptions.map(toForm));
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company]);
  useEffect(() => { load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;

  const run = async (save) => {
    setBusy(save ? "save" : "run");
    try {
      const r = await api.post(`/companies/${company.id}/plan`, { years: toBody(years), save });
      setData((d) => ({ ...r.data, saved_at: save ? new Date().toISOString() : d?.saved_at }));
      setError("");
      if (save) toast("Ipotesi salvate");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };
  const download = async () => {
    try {
      const res = await api.post(`/companies/${company.id}/plan/export`, { years: toBody(years) }, { responseType: "blob" });
      const href = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = href;
      a.download = "piano_3_anni.xlsx";
      a.click();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    } catch (e) {
      toast(await blobErrorMessage(e), "orange");
    }
  };
  const setYear = (i, key, value) => setYears((ys) => ys.map((y, n) => (n === i ? { ...y, [key]: value } : y)));
  const copyFirst = () => setYears((ys) => ys.map((y, n) => (n === 0 ? y : { ...ys[0], capex: "0", new_loan: "0" })));

  return (
    <>
      <PageHeader title="Piano a 3 anni" subtitle="Conto economico, cassa e debiti dei prossimi tre anni, partendo dai numeri di oggi"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />
          <Button variant="secondary" onClick={download} disabled={!years}>Scarica Excel</Button>
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!data || !years ? <Loading /> : (
        <>
          <Notice>
            Base di partenza: {data.base.source}. Ricavi {eur(data.base.ricavi)}, costi variabili {data.base.variable_pct.toLocaleString("it-IT")}% dei ricavi,
            incasso medio in {data.base.dso_days} giorni, pagamento medio in {data.base.dpo_days} giorni, liquidità {eur(data.base.cash)}.
          </Notice>
          <Card title="Le tue ipotesi" subtitle="Lascia vuoti costi variabili e giorni per usare i valori di oggi"
            actions={<>
              <Button variant="ghost" onClick={copyFirst}>Copia il primo anno sugli altri</Button>
              <Button variant="secondary" onClick={() => run(false)} loading={busy === "run"}>Ricalcola</Button>
              {can(company.id, "manage_budget") && <Button onClick={() => run(true)} loading={busy === "save"}>Salva ipotesi</Button>}
            </>}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="table-head text-left">
                    <th className="py-2 pr-3">Ipotesi</th>
                    {data.years.map((y) => <th key={y} className="py-2 pr-3 text-right">{y}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {FIELDS.map(([key, label, unit]) => (
                    <tr key={key} className="border-b border-soft">
                      <td className="py-1.5 pr-3">{label} <span className="text-xs text-muted">({unit})</span></td>
                      {years.map((y, i) => (
                        <td key={i} className="py-1.5 pr-3">
                          <input aria-label={`${label} ${data.years[i]}`} inputMode="decimal" className="input num min-h-[38px] text-right"
                            value={y[key] ?? ""} onChange={(e) => setYear(i, key, e.target.value)} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.saved_at && <p className="mt-2 text-xs text-muted">Ultimo salvataggio {fmtDateTime(data.saved_at)}</p>}
          </Card>
          <Card title="Risultati" padded={false}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="table-head text-left">
                    <th className="px-5 py-3">Voce</th>
                    {data.rows.map((r) => <th key={r.year} className="py-3 pr-5 text-right">{r.year}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {ROWS.map(([key, label, bold]) => key === "sep" ? (
                    <tr key={key}><td colSpan={4} className="bg-[#FAFAF9] px-5 py-2 text-xs font-semibold uppercase tracking-wide text-muted">{label}</td></tr>
                  ) : (
                    <tr key={key} className="border-b border-soft">
                      <td className={`px-5 py-2.5 ${bold ? "font-semibold" : "text-[#3D4250]"}`}>{label}</td>
                      {data.rows.map((r) => (
                        <td key={r.year} className={`num py-2.5 pr-5 text-right ${bold ? "font-bold" : ""} ${r[key] < 0 && key !== "pfn" ? "text-warn-amount" : ""}`}>{eur(r[key])}</td>
                      ))}
                    </tr>
                  ))}
                  <tr className="border-b border-soft">
                    <td className="px-5 py-2.5 font-semibold">MOL sui ricavi</td>
                    {data.rows.map((r) => <td key={r.year} className="num py-2.5 pr-5 text-right">{r.ebitda_margin === null ? "—" : `${r.ebitda_margin.toLocaleString("it-IT")}%`}</td>)}
                  </tr>
                  <tr>
                    <td className="px-5 py-2.5 font-semibold">DSCR (flusso della gestione ÷ rate)</td>
                    {data.rows.map((r) => (
                      <td key={r.year} className="py-2.5 pr-5 text-right">
                        <span className="num mr-2 font-bold">{r.dscr === null ? "—" : r.dscr.toLocaleString("it-IT")}</span>
                        <Light status={r.dscr === null ? "verde" : r.dscr >= 1.2 ? "verde" : r.dscr >= 1 ? "giallo" : "rosso"} label="" className="px-1.5" />
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="px-5 py-3 text-xs text-muted">{data.note} Il DSCR del piano non conta la liquidità già in cassa: misura se la gestione dell'anno basta da sola a pagare le rate.</p>
          </Card>
        </>
      )}
    </>
  );
}
