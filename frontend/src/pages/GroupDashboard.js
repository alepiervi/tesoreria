import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ForecastChart, MonthlyChart, forecastNote } from "../components/Charts";
import ScenarioModal from "../components/ScenarioModal";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Notice, PageHeader, Stat } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { DEADLINE_STATUS, KIND_LABELS, eur, fmtDate } from "../lib/format";

export default function GroupDashboard() {
  const { setSelectedId, companies, user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [scenarioOpen, setScenarioOpen] = useState(false);

  useEffect(() => {
    api.get("/dashboard/group").then((r) => setData(r.data)).catch((e) => setError(errorMessage(e)));
  }, []);

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!data) return <Loading />;
  if (!companies.length) {
    if (user?.is_owner) {
      return <Empty title="Benvenuto in Nureal-Amministrazione" text="Per iniziare crea la tua prima azienda con la partita IVA corretta."
        action={<Button data-testid="create-first-company-btn" onClick={() => navigate("/impostazioni")}>+ Crea la prima azienda</Button>} />;
    }
    return <Empty title="Nessuna azienda" text="Non hai ancora accesso a nessuna azienda. Chiedi al titolare di invitarti." />;
  }

  const t = data.totals;
  const note = forecastNote(data.forecast);
  const consent = data.companies.flatMap((c) => c.consent_warnings.map((w) => ({ ...w, company: c.name, companyId: c.id })));
  const stale = data.companies.flatMap((c) => (c.stale_imports || []).map((s) => ({ ...s, company: c.name, companyId: c.id })));
  const open = (id) => { setSelectedId(id); navigate(`/aziende/${id}`); };

  return (
    <>
      <PageHeader title="Vista di gruppo" subtitle={`${data.companies.length} aziende · ${t.accounts_count} conti collegati`} />

      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
        <Stat label="Liquidità totale" value={eur(t.balance_cents, { short: true })}
          sub={t.credit_available_cents ? `+ ${eur(t.credit_available_cents, { short: true })} di fidi disponibili` : "Somma dei saldi bancari"} />
        <Stat label="Entrate del mese" value={eur(t.month_inflow_cents, { short: true })}
          sub={t.internal_transfers_cents ? `Esclusi ${eur(t.internal_transfers_cents, { short: true })} tra aziende del gruppo` : "Mese in corso"} />
        <Stat label="Uscite del mese" value={eur(t.month_outflow_cents, { short: true })} sub={`Saldo del mese ${eur(t.month_inflow_cents - t.month_outflow_cents, { signed: true, short: true })}`} />
        <Stat label="Da riconciliare" value={t.to_reconcile} sub={t.open_questions ? `${t.open_questions} chiarimenti aperti` : "Movimenti senza fattura abbinata"} tone={t.to_reconcile ? "warn" : undefined} />
      </div>

      {consent.length > 0 && (
        <Notice tone="orange">
          {consent.map((w) => (
            <div key={w.account_id}>
              Il consenso bancario di <strong>{w.company}</strong> ({w.bank_name} {w.iban_masked}) scade tra {w.days_left} giorni.{" "}
              <Link className="font-semibold underline" to={`/aziende/${w.companyId}`}>Rinnova</Link>
            </div>
          ))}
        </Notice>
      )}

      {stale.length > 0 && (
        <Notice tone="orange">
          {stale.map((s) => (
            <div key={s.account_id}>
              Conto manuale di <strong>{s.company}</strong> ({s.bank_name} {s.iban_masked}):{" "}
              {s.last_import_to ? `movimenti fermi al ${fmtDate(s.last_import_to, { year: true })}` : "nessun estratto conto importato"}.{" "}
              <Link className="font-semibold underline" to={`/aziende/${s.companyId}`}>Importa</Link>
            </div>
          ))}
        </Notice>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Entrate e uscite, ultimi 6 mesi" subtitle="Tutte le aziende visibili, giroconti esclusi">
          <MonthlyChart data={data.monthly} />
        </Card>
        <Card title="Previsione di cassa del gruppo" subtitle="Saldo a fine settimana, prossime 8 settimane"
          actions={<Button variant="secondary" onClick={() => setScenarioOpen(true)}>Prova uno scenario</Button>}>
          <ForecastChart forecast={data.forecast} />
          {note && <div className="mt-3"><Notice tone={note.tone}>{note.text}</Notice></div>}
        </Card>
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold">Le aziende</h2>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-4">
          {data.companies.map((c) => (
            <button key={c.id} type="button" onClick={() => open(c.id)}
              className="flex flex-col gap-2.5 rounded-xl border border-line bg-white px-5 py-4 text-left hover:border-accent-mid">
              <span className="flex w-full justify-between gap-2">
                <span className="text-[15px] font-semibold">{c.name}</span>
                <span className="text-xs font-semibold text-accent">Apri →</span>
              </span>
              <span className="num text-2xl font-bold tracking-tight">{eur(c.balance_cents)}</span>
              <span className="flex flex-wrap gap-3 text-xs text-muted">
                <span>Entrate mese {eur(c.month_inflow_cents, { short: true })}</span>
                <span>Uscite mese {eur(c.month_outflow_cents, { short: true })}</span>
              </span>
              <span className="flex flex-wrap gap-2">
                <Badge tone={c.to_reconcile ? "orange" : "blue"}>{c.to_reconcile ? `${c.to_reconcile} da riconciliare` : "Tutto riconciliato"}</Badge>
                {c.open_questions > 0 && <Badge tone="orange">{c.open_questions} chiarimenti</Badge>}
              </span>
            </button>
          ))}
        </div>
      </section>

      <ScenarioModal open={scenarioOpen} companyId="" title="Gruppo" onClose={() => setScenarioOpen(false)} />

      <Card title="Scadenze dei prossimi 14 giorni" actions={<Link to="/scadenze" className="text-sm font-semibold text-accent">Tutto lo scadenzario →</Link>}>
        {data.upcoming.length === 0 ? (
          <p className="text-sm text-muted">Nessuna scadenza nei prossimi 14 giorni.</p>
        ) : (
          <ul className="divide-y divide-soft">
            {data.upcoming.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-3 py-3">
                <span className="w-16 font-semibold">{fmtDate(d.due_date)}</span>
                <Badge tone={d.kind === "incasso" ? "blue" : d.kind === "f24" ? "orange" : "gray"}>{KIND_LABELS[d.kind]}</Badge>
                <span className="min-w-[160px] flex-1">{d.description}<span className="block text-xs text-muted">{d.company_name}</span></span>
                {d.overdue && <Badge tone="orange">Scaduta</Badge>}
                {d.status === "in_attesa_autorizzazione" && <Badge tone="orange">{DEADLINE_STATUS[d.status][0]}</Badge>}
                <span className={`num w-32 text-right font-semibold ${d.kind === "incasso" ? "" : "text-warn-amount"}`}>
                  {d.kind === "incasso" ? "+ " : "− "}{eur(d.amount_cents)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
