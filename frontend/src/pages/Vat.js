import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { eur, fmtDate } from "../lib/format";

const STATE = { chiuso: ["Chiuso", "gray"], in_corso: ["In corso", "blue"], futuro: ["Futuro", "gray"] };

export default function Vat() {
  const [company, setCompany] = usePageCompany("view");
  const { can } = useAuth();
  const toast = useToast();
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const res = await api.get(`/companies/${company.id}/vat`, { params: { year } });
      setData(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, year]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  if (!company) return <Empty title="Nessuna azienda disponibile" />;
  const canEdit = can(company.id, "manage_deadlines");
  const thisYear = new Date().getFullYear();
  const visible = (data?.periods || []).filter((p) => p.state !== "futuro" || p.invoices_count);

  return (
    <>
      <PageHeader title="IVA stimata" subtitle="Calcolata dalle fatture registrate, con le scadenze F24 inserite nella previsione"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} />
          <select aria-label="Anno" className="input w-auto" value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {[thisYear, thisYear - 1].map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          {canEdit && <Button variant="secondary" onClick={() => setSettingsOpen(true)}>Impostazioni IVA</Button>}
        </>} />
      <Notice tone="orange">
        È una stima per pianificare la cassa: IVA delle fatture emesse meno IVA delle fatture ricevute, con il credito che passa al periodo dopo.
        Non tiene conto di acconto di dicembre, reverse charge, pro-rata e IVA per cassa: l'importo da versare lo conferma il commercialista.
      </Notice>
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
            <div className="rounded-xl border border-line bg-white px-5 py-4">
              <span className="text-[13px] text-muted">Periodicità</span>
              <p className="text-xl font-bold capitalize">{data.mode}</p>
              <span className="text-xs text-muted">{data.vat_auto ? "Scadenze F24 create in automatico" : "Scadenze automatiche disattivate"}</span>
            </div>
            <div className="rounded-xl border border-line bg-white px-5 py-4">
              <span className="text-[13px] text-muted">Totale stimato da versare nel {year}</span>
              <p className="num text-xl font-bold">{eur(data.total_to_pay_cents)}</p>
            </div>
          </div>
          <Card padded={false}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[880px] text-sm">
                <thead>
                  <tr className="table-head text-left">
                    <th className="px-5 py-3">Periodo</th>
                    <th className="py-3 pr-3 text-right">IVA vendite</th>
                    <th className="py-3 pr-3 text-right">IVA acquisti</th>
                    <th className="py-3 pr-3 text-right">Credito/debito precedente</th>
                    <th className="py-3 pr-3 text-right">Da versare</th>
                    <th className="py-3 pr-3">Scadenza F24</th>
                    <th className="py-3 pr-5">Stato</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((p) => (
                    <tr key={p.key} className="border-b border-soft">
                      <td className="px-5 py-3 font-semibold capitalize">{p.label}<span className="block text-xs font-normal text-muted">{p.invoices_count} {p.invoices_count === 1 ? "fattura" : "fatture"}</span></td>
                      <td className="num py-3 pr-3 text-right">{eur(p.sales_vat_cents)}</td>
                      <td className="num py-3 pr-3 text-right">{eur(p.purchases_vat_cents)}</td>
                      <td className="num py-3 pr-3 text-right text-muted">
                        {p.carry_in_cents > 0 ? `credito ${eur(p.carry_in_cents)}` : p.carry_in_cents < 0 ? `+ ${eur(-p.carry_in_cents)} rinviati` : "—"}
                      </td>
                      <td className={`num py-3 pr-3 text-right font-bold ${p.to_pay_cents ? "text-warn-amount" : ""}`}>
                        {p.to_pay_cents ? eur(p.to_pay_cents) : p.credit_out_cents ? <span className="font-semibold text-accent-dark">credito {eur(p.credit_out_cents)}</span> : "—"}
                      </td>
                      <td className="py-3 pr-3">{fmtDate(p.due_date, { year: true })}</td>
                      <td className="py-3 pr-5">
                        <span className="flex flex-wrap gap-1">
                          <Badge tone={STATE[p.state][1]}>{STATE[p.state][0]}</Badge>
                          {p.deadline_status === "pagato" && <Badge tone="blue">Versata</Badge>}
                          {p.deadline_id && p.deadline_status === "da_pagare" && <Badge tone="orange">In scadenzario</Badge>}
                          {!p.deadline_id && p.to_pay_cents > 0 && p.state === "chiuso" && <Badge>Verifica il versamento</Badge>}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
      {settingsOpen && data && (
        <VatSettingsModal company={company} data={data} onClose={() => setSettingsOpen(false)}
          onDone={() => { setSettingsOpen(false); toast("Impostazioni IVA salvate"); load(); }} />
      )}
    </>
  );
}

function VatSettingsModal({ company, data, onClose, onDone }) {
  const [period, setPeriod] = useState(data.mode);
  const [auto, setAuto] = useState(data.vat_auto);
  const [credit, setCredit] = useState(data.opening_credit_cents ? (data.opening_credit_cents / 100).toFixed(2).replace(".", ",") : "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/companies/${company.id}/vat-settings`, { vat_period: period, vat_auto: auto, opening_credit: credit });
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} title={`IVA · ${company.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save} loading={busy}>Salva</Button></>}>
      <div className="flex flex-col gap-4">
        <ErrorBox>{error}</ErrorBox>
        <Field label="Periodicità della liquidazione" htmlFor="vat-p" hint="Chiedila al commercialista se non sei sicuro.">
          <select id="vat-p" className="input" value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="mensile">Mensile (versamento il 16 del mese dopo)</option>
            <option value="trimestrale">Trimestrale (16 maggio, 20 agosto, 16 novembre, 16 marzo)</option>
          </select>
        </Field>
        <Field label="Credito IVA a inizio anno (facoltativo)" htmlFor="vat-c" hint="Dalla dichiarazione dell'anno scorso: riduce i primi versamenti.">
          <input id="vat-c" inputMode="decimal" className="input" value={credit} onChange={(e) => setCredit(e.target.value)} placeholder="0,00" />
        </Field>
        <label className="flex min-h-[44px] items-center gap-2 text-sm">
          <input type="checkbox" className="h-[18px] w-[18px]" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          Crea in automatico le scadenze F24 "IVA stimata" nello scadenzario
        </label>
      </div>
    </Modal>
  );
}
