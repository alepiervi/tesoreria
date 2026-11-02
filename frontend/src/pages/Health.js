import { Fragment, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Card, Empty, ErrorBox, Light, Loading, Notice, PageHeader, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { eur } from "../lib/format";

const OVERALL = {
  verde: "Nessun segnale di allerta",
  giallo: "Ci sono punti da tenere d'occhio",
  rosso: "Ci sono segnali di allarme da affrontare subito",
  grigio: "Dati insufficienti",
};

export function fmtRatio(value, format) {
  if (value === null || value === undefined) return "—";
  if (format === "eur") return eur(value);
  if (format === "%") return `${(value * 100).toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
  if (format === "gg") return `${Math.round(value)} giorni`;
  return value.toLocaleString("it-IT", { maximumFractionDigits: 2 });
}

export default function Health() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const { can } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [openRule, setOpenRule] = useState({});

  const load = useCallback(async () => {
    if (!company) return;
    setData(null);
    try {
      const res = await api.get(`/companies/${company.id}/health`);
      setData(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company]);
  useEffect(() => { load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;
  const alerts = data?.alerts;
  const setForm = async (value) => {
    try {
      await api.put(`/companies/${company.id}/legal-form`, { legal_form: value });
      toast("Forma giuridica salvata");
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };

  return (
    <>
      <PageHeader title="Salute dell'azienda" subtitle="Segnali di allerta del Codice della crisi, sostenibilità dei debiti e indici di bilancio"
        actions={<CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <>
          <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-line bg-white p-5">
            <div className="flex items-center gap-4">
              <Light status={alerts.overall} label={OVERALL[alerts.overall]} className="px-3 py-2 text-sm" />
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <label htmlFor="legal" className="text-muted">Forma giuridica</label>
              <select id="legal" className="input w-auto" value={alerts.legal_form} disabled={!can(company.id, "manage_accounting")}
                onChange={(e) => setForm(e.target.value)}>
                <option value="capitali">Società di capitali (Srl, Spa)</option>
                <option value="persone">Società di persone (Snc, Sas)</option>
                <option value="individuale">Impresa individuale</option>
              </select>
            </div>
          </section>

          <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
            <Card title="Segnali di allerta" subtitle="Controllati sui dati del programma ogni volta che apri la pagina">
              <ul className="flex flex-col divide-y divide-soft">
                {alerts.signals.map((s) => (
                  <li key={s.id} className="flex flex-col gap-1.5 py-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="flex min-w-0 items-start gap-3">
                        <Light status={s.status} label="" className="mt-0.5 px-1.5" />
                        <span className="min-w-0"><b>{s.title}</b><span className="block text-sm text-muted">{s.detail}</span></span>
                      </div>
                      <div className="flex items-center gap-3 text-sm">
                        <button type="button" className="font-semibold text-accent hover:underline" aria-expanded={Boolean(openRule[s.id])}
                          onClick={() => setOpenRule((o) => ({ ...o, [s.id]: !o[s.id] }))}>{openRule[s.id] ? "Nascondi regola" : "Cosa dice la legge"}</button>
                        {s.link && s.status !== "verde" && <Link to={s.link} className="font-semibold text-accent hover:underline">Vai →</Link>}
                      </div>
                    </div>
                    {openRule[s.id] && <p className="ml-9 rounded-lg bg-soft px-3 py-2 text-xs leading-relaxed text-[#3D4250]">{s.rule}</p>}
                  </li>
                ))}
              </ul>
            </Card>
            <div className="flex flex-col gap-6">
              <Card title="Sostenibilità dei debiti (DSCR)" subtitle="Risorse disponibili ÷ rate di mutui, finanziamenti e leasing">
                <div className="grid grid-cols-2 gap-3">
                  {alerts.dscr.periods.map((p) => (
                    <div key={p.months} className="rounded-lg border border-line p-3">
                      <span className="text-xs text-muted">Prossimi {p.months} mesi</span>
                      <p className="num text-2xl font-bold">{p.value === null ? "—" : p.value.toLocaleString("it-IT", { maximumFractionDigits: 2 })}</p>
                      <Light status={p.status} label={p.value === null ? "Nessuna rata" : undefined} />
                    </div>
                  ))}
                </div>
                <dl className="num mt-4 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-sm">
                  <dt className="text-muted">Liquidità di oggi</dt><dd className="text-right">{eur(alerts.dscr.cash_cents)}</dd>
                  <dt className="text-muted">Flusso medio mensile della gestione</dt><dd className="text-right">{eur(alerts.dscr.monthly_flow_cents, { signed: true })}</dd>
                  <dt className="text-muted">Debiti già scaduti</dt><dd className="text-right">{eur(-alerts.dscr.overdue_debts_cents)}</dd>
                  {alerts.dscr.periods.map((p) => (
                    <Fragment key={p.months}><dt className="text-muted">Rate nei prossimi {p.months} mesi</dt><dd className="text-right">{eur(p.debt_service_cents)}</dd></Fragment>
                  ))}
                </dl>
                <p className="mt-3 text-xs text-muted">
                  Sopra 1,2 i flussi coprono le rate con margine; sotto 1 non bastano. Il flusso medio è calcolato sugli ultimi 6 mesi
                  ({alerts.dscr.flow_period.from.slice(5, 7)}/{alerts.dscr.flow_period.from.slice(0, 4)} – {alerts.dscr.flow_period.to.slice(5, 7)}/{alerts.dscr.flow_period.to.slice(0, 4)}),
                  senza giroconti, movimenti tra aziende e rate.
                </p>
              </Card>
              <Notice>{alerts.note}</Notice>
            </div>
          </div>

          <Card title={`Indici di bilancio ${data.ratios.year}`}
            subtitle={data.ratios.annualized ? `Ricavi, costi e utile riportati a 12 mesi (${data.ratios.elapsed_days} giorni di dati). Soglie indicative.` : "Soglie indicative."}>
            {!data.ratios.statements_ok && <Notice tone="orange">Il bilancio non quadra: controlla prima la contabilità.</Notice>}
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {data.ratios.items.map((i) => (
                <div key={i.id} className="flex flex-col gap-2 rounded-xl border border-line p-4">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-semibold">{i.label}</span>
                    <Light status={i.status} />
                  </div>
                  <span className="num text-2xl font-bold">{fmtRatio(i.value, i.format)}</span>
                  {i.detail && <span className="text-xs font-semibold text-[#3D4250]">{i.detail}</span>}
                  <span className="text-xs text-muted">{i.meaning}</span>
                  <span className="text-[11px] text-muted">Calcolo: {i.formula}</span>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </>
  );
}
