import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader, Tabs, useToast } from "../../components/ui";
import { api, blobErrorMessage, downloadFile, errorMessage } from "../../lib/api";
import { eur, fmtDate } from "../../lib/format";

const MONTHS = ["Tutto l'anno", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"];

export default function VatRegisters() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const toast = useToast();
  const [direction, setDirection] = useState("attiva");
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const range = month
    ? [`${year}-${String(month).padStart(2, "0")}-01`, new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10)]
    : [undefined, undefined];

  const load = useCallback(async () => {
    if (!company) return;
    setData(null);
    try {
      const res = await api.get(`/companies/${company.id}/vat-registers`, {
        params: { direction, year, date_from: range[0], date_to: range[1] },
      });
      setData(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [company, direction, year, month]);
  useEffect(() => { load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;
  const thisYear = new Date().getFullYear();

  const download = async () => {
    const kind = direction === "attiva" ? "vat_sales" : "vat_purchases";
    try {
      await downloadFile(`/companies/${company.id}/accounting-export`, { kind, year, date_from: range[0], date_to: range[1] }, `${kind}_${year}.xlsx`);
    } catch (e) {
      toast(await blobErrorMessage(e), "orange");
    }
  };

  return (
    <>
      <PageHeader title="Registri IVA" subtitle="Fatture emesse e ricevute con numero di protocollo e riepilogo per aliquota"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />
          <label htmlFor="vr-year" className="sr-only">Anno</label>
          <select id="vr-year" className="input w-auto" value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {[thisYear, thisYear - 1, thisYear - 2].map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          <label htmlFor="vr-month" className="sr-only">Mese</label>
          <select id="vr-month" className="input w-auto" value={month} onChange={(e) => setMonth(Number(e.target.value))}>
            {MONTHS.map((m, i) => <option key={m} value={i}>{m}</option>)}
          </select>
          <Button variant="secondary" onClick={download}>Scarica Excel</Button>
        </>} />
      <Tabs value={direction} onChange={setDirection} tabs={[{ id: "attiva", label: "Registro vendite" }, { id: "passiva", label: "Registro acquisti" }]} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <>
          <div className="grid gap-4 md:grid-cols-[1fr_1fr]">
            <Card title="Riepilogo per aliquota" padded={false}>
              <table className="w-full text-sm">
                <thead>
                  <tr className="table-head text-left">
                    <th className="px-5 py-2.5">Aliquota / natura</th>
                    <th className="py-2.5 pr-3 text-right">Imponibile</th>
                    <th className="py-2.5 pr-5 text-right">Imposta</th>
                  </tr>
                </thead>
                <tbody>
                  {data.summary.map((s) => (
                    <tr key={s.label} className="border-b border-soft">
                      <td className="px-5 py-2.5 font-semibold">{s.label}</td>
                      <td className="num py-2.5 pr-3 text-right">{eur(s.taxable_cents)}</td>
                      <td className="num py-2.5 pr-5 text-right">{eur(s.vat_cents)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="font-bold">
                    <td className="px-5 py-2.5">Totale</td>
                    <td className="num py-2.5 pr-3 text-right">{eur(data.totals.taxable_cents)}</td>
                    <td className="num py-2.5 pr-5 text-right">{eur(data.totals.vat_cents)}</td>
                  </tr>
                </tfoot>
              </table>
            </Card>
            <Card title="Note">
              <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted">
                <li>Il protocollo è progressivo nell'anno in base alla data di registrazione.</li>
                <li>Le fatture in <b>scissione dei pagamenti</b> (split payment) riportano l'IVA che versa il cliente pubblico.</li>
                <li>Le fatture arrivate dopo la chiusura di un periodo vengono registrate alla prima data utile.</li>
                <li>La liquidazione e le dichiarazioni IVA restano a cura del commercialista.</li>
              </ul>
            </Card>
          </div>
          <Card padded={false}>
            {data.rows.length === 0 ? <Empty title="Nessuna fattura nel periodo" /> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[920px] text-sm">
                  <thead>
                    <tr className="table-head text-left">
                      <th className="px-5 py-3">Prot.</th>
                      <th className="py-3 pr-3">Registrazione</th>
                      <th className="py-3 pr-3">Documento</th>
                      <th className="py-3 pr-3">{direction === "attiva" ? "Cliente" : "Fornitore"}</th>
                      <th className="py-3 pr-3 text-right">Imponibile</th>
                      <th className="py-3 pr-3 text-right">IVA</th>
                      <th className="py-3 pr-5 text-right">Totale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((r) => (
                      <tr key={`${r.protocol}-${r.number}`} className="border-b border-soft">
                        <td className="num px-5 py-2.5 text-muted">{r.protocol}</td>
                        <td className="whitespace-nowrap py-2.5 pr-3">{fmtDate(r.registration_date, { year: true })}</td>
                        <td className="py-2.5 pr-3"><b>{r.number}</b> <span className="text-xs text-muted">del {fmtDate(r.date, { year: true })} · {r.doc_type}</span>
                          {r.split_payment && <Badge tone="orange" className="ml-2">Split payment</Badge>}
                          {r.withholding_cents > 0 && <Badge className="ml-2">Ritenuta {eur(r.withholding_cents)}</Badge>}
                        </td>
                        <td className="py-2.5 pr-3">{r.party}<span className="block text-xs text-muted">{r.vat_number}</span></td>
                        <td className="num py-2.5 pr-3 text-right">{eur(r.taxable_cents)}</td>
                        <td className="num py-2.5 pr-3 text-right">{eur(r.vat_cents)}</td>
                        <td className="num py-2.5 pr-5 text-right font-semibold">{eur(r.total_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
