import { useEffect, useState } from "react";
import { Card, Empty, ErrorBox, Light, Loading, PageHeader } from "../../components/ui";
import { YearSelect } from "../../lib/accounting";
import { api, errorMessage } from "../../lib/api";
import { eur } from "../../lib/format";
import { fmtRatio } from "../Health";

const MONEY_ROWS = [
  ["ricavi", "Ricavi"], ["ebitda", "Margine operativo lordo"], ["utile", "Utile"], ["personale", "Costo del personale"],
  ["liquidita", "Liquidità in banca"], ["pfn", "Debito finanziario netto"], ["pn", "Patrimonio netto"], ["crediti_scaduti", "Crediti scaduti"],
];

export default function Compare() {
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setData(null);
    api.get("/group/compare", { params: { year } }).then((r) => { setData(r.data); setError(""); }).catch((e) => setError(errorMessage(e)));
  }, [year]);

  return (
    <>
      <PageHeader title="Confronto tra le aziende" subtitle="Gli stessi numeri e indici, fianco a fianco"
        actions={<YearSelect value={year} onChange={setYear} />} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : data.rows.length === 0 ? <Empty title="Nessuna azienda con accesso alla contabilità" /> : (
        <Card padded={false} subtitle={data.annualized ? "Indici sui valori dell'anno in corso riportati a 12 mesi" : undefined}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="table-head text-left">
                  <th className="px-5 py-3">Voce</th>
                  {data.rows.map((r) => <th key={r.id} className="py-3 pr-5 text-right">{r.name}</th>)}
                </tr>
              </thead>
              <tbody>
                {MONEY_ROWS.map(([key, label]) => {
                  const values = data.rows.map((r) => r[key]);
                  const best = key === "pfn" || key === "crediti_scaduti" || key === "personale" ? Math.min(...values) : Math.max(...values);
                  return (
                    <tr key={key} className="border-b border-soft">
                      <td className="px-5 py-2.5 font-semibold">{label}</td>
                      {data.rows.map((r) => (
                        <td key={r.id} className={`num py-2.5 pr-5 text-right ${r[key] === best && data.rows.length > 1 ? "font-bold text-accent-dark" : ""} ${r[key] < 0 ? "text-warn-amount" : ""}`}>
                          {eur(r[key])}
                        </td>
                      ))}
                    </tr>
                  );
                })}
                <tr className="border-b border-soft">
                  <td className="px-5 py-2.5 font-semibold">Personale sui ricavi</td>
                  {data.rows.map((r) => <td key={r.id} className="num py-2.5 pr-5 text-right">{fmtRatio(r.personale_su_ricavi, "%")}</td>)}
                </tr>
                <tr><td colSpan={data.rows.length + 1} className="bg-[#FAFAF9] px-5 py-2 text-xs font-semibold uppercase tracking-wide text-muted">Indici</td></tr>
                {Object.entries(data.labels).filter(([id]) => id !== "patrimonio").map(([id, label]) => (
                  <tr key={id} className="border-b border-soft">
                    <td className="px-5 py-2.5">{label}</td>
                    {data.rows.map((r) => (
                      <td key={r.id} className="py-2.5 pr-5 text-right">
                        <span className="num mr-2 font-semibold">{fmtRatio(r.indici[id]?.value, r.indici[id]?.format)}</span>
                        <Light status={r.indici[id]?.status} label="" className="px-1.5" />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="px-5 py-3 text-xs text-muted">In blu il valore migliore della riga. Il significato di ogni indice è spiegato nella pagina «Salute dell'azienda».</p>
        </Card>
      )}
    </>
  );
}
