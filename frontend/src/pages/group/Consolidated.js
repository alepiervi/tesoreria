import { useEffect, useState } from "react";
import { Badge, Card, Empty, ErrorBox, Loading, Notice, PageHeader, Stat, Tabs } from "../../components/ui";
import { YearSelect } from "../../lib/accounting";
import { api, errorMessage } from "../../lib/api";
import { eur } from "../../lib/format";
import { Schema } from "../accounting/Statements";

export default function Consolidated() {
  const [year, setYear] = useState(new Date().getFullYear());
  const [tab, setTab] = useState("ce");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setData(null);
    api.get("/group/consolidated", { params: { year } })
      .then((r) => { setData(r.data); setError(""); })
      .catch((e) => setError(errorMessage(e)));
  }, [year]);

  const el = data?.eliminations;
  return (
    <>
      <PageHeader title="Bilancio consolidato" subtitle="Le aziende del gruppo come se fossero una sola, senza le operazioni tra di loro"
        actions={<YearSelect value={year} onChange={setYear} />} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : data.companies.length < 2 ? <Empty title="Serve almeno due aziende con accesso alla contabilità" /> : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-4">
            <Stat label="Ricavi del gruppo" value={eur(data.sintesi.valore_produzione)} sub={`dopo ${eur(el.ricavi_gruppo_cents)} di vendite tra le aziende`} />
            <Stat label="Margine prima delle imposte" value={eur(data.sintesi.risultato_ante_imposte)} tone={data.sintesi.risultato_ante_imposte < 0 ? "warn" : undefined} />
            <Stat label={data.sintesi.utile >= 0 ? "Utile del gruppo" : "Perdita del gruppo"} value={eur(data.sintesi.utile)} tone={data.sintesi.utile < 0 ? "warn" : undefined} />
            <Stat label="Totale attivo" value={eur(data.totale_attivo)} sub={data.quadra ? "Attivo e passivo quadrano" : "Attivo e passivo NON quadrano"} />
          </div>

          <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
            <Card title="Aziende comprese" padded={false}>
              <table className="w-full text-sm">
                <thead>
                  <tr className="table-head text-left">
                    <th className="px-5 py-2.5">Azienda</th>
                    <th className="py-2.5 pr-3 text-right">Valore produzione</th>
                    <th className="py-2.5 pr-5 text-right">Risultato</th>
                  </tr>
                </thead>
                <tbody>
                  {data.companies.map((c) => (
                    <tr key={c.id} className="border-b border-soft">
                      <td className="px-5 py-2.5 font-semibold">{c.name}{!c.quadra && <Badge tone="orange" className="ml-2">non quadra</Badge>}</td>
                      <td className="num py-2.5 pr-3 text-right">{eur(c.valore_produzione)}</td>
                      <td className={`num py-2.5 pr-5 text-right ${c.utile < 0 ? "text-warn-amount" : ""}`}>{eur(c.utile)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card title="Cosa è stato eliminato">
              <dl className="num grid grid-cols-[1fr_auto] gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted">Crediti verso le altre aziende</dt><dd className="text-right">{eur(el.crediti_gruppo_cents)}</dd>
                <dt className="text-muted">Debiti verso le altre aziende</dt><dd className="text-right">{eur(el.debiti_gruppo_cents)}</dd>
                <dt className="text-muted">Vendite tra le aziende</dt><dd className="text-right">{eur(el.ricavi_gruppo_cents)}</dd>
                <dt className="text-muted">Acquisti tra le aziende</dt><dd className="text-right">{eur(el.costi_gruppo_cents)}</dd>
                <dt className="font-semibold">Differenza da sistemare</dt>
                <dd className={`text-right font-bold ${el.differenza_cents ? "text-warn-amount" : ""}`}>{eur(el.differenza_cents)}</dd>
              </dl>
              {data.mismatches.filter((m) => m.difference_cents).length > 0 && (
                <div className="mt-4 flex flex-col gap-2">
                  <span className="label">Posizioni che non coincidono</span>
                  {data.mismatches.filter((m) => m.difference_cents).map((m) => (
                    <p key={`${m.a}-${m.b}`} className="rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn-dark">
                      {m.a} risulta creditrice di {eur(m.a_vs_b_cents)} verso {m.b}, che invece registra {eur(-m.b_vs_a_cents)}:
                      differenza {eur(m.difference_cents)}. Di solito manca una fattura o un movimento da una delle due parti.
                    </p>
                  ))}
                </div>
              )}
            </Card>
          </div>

          <Tabs value={tab} onChange={setTab} tabs={[{ id: "ce", label: "Conto economico" }, { id: "sp", label: "Stato patrimoniale" }]} />
          {tab === "ce" ? (
            <Schema title="Conto economico consolidato" rows={data.conto_economico} year={year} onAccount={() => {}}
              footer={[["Differenza tra valore e costi della produzione (A − B)", data.sintesi.differenza],
                ["Utile (perdita) del gruppo", data.sintesi.utile, data.sintesi.utile_precedente]]} />
          ) : (
            <div className="grid gap-6 xl:grid-cols-2">
              <Schema title="Attivo" rows={data.attivo} total={data.totale_attivo} year={year} onAccount={() => {}} />
              <Schema title="Passivo e patrimonio netto" rows={data.passivo} total={data.totale_passivo} year={year} onAccount={() => {}} />
            </div>
          )}
          <Notice>{data.note} Per il consolidato da depositare servono le scritture del commercialista.</Notice>
        </>
      )}
    </>
  );
}
