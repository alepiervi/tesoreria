import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ImportStatementModal, ManualAccountModal } from "../components/BankImport";
import { ForecastChart, MonthlyChart, forecastNote } from "../components/Charts";
import ScenarioModal from "../components/ScenarioModal";
import { Amount, Badge, Button, Card, ErrorBox, Field, Loading, Modal, Notice, PageHeader, Stat, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { KIND_LABELS, ROLE_LABELS, TX_STATUS, eur, fmtDate } from "../lib/format";

export default function CompanyPage() {
  const { companyId } = useParams();
  const { byId, can, setSelectedId, companies, refreshCounts } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const company = byId[companyId];
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [weeks, setWeeks] = useState(8);
  const [busy, setBusy] = useState("");
  const [connectOpen, setConnectOpen] = useState(false);
  const [convert, setConvert] = useState(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [importFor, setImportFor] = useState(null);
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const [openWeek, setOpenWeek] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/companies/${companyId}/dashboard`, { params: { weeks } });
      setData(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [companyId, weeks]);

  useEffect(() => {
    if (company) setSelectedId(companyId);
  }, [company, companyId, setSelectedId]);

  useEffect(() => {
    load();
  }, [load]);

  if (!company) return <ErrorBox>Azienda non trovata o non accessibile.</ErrorBox>;
  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!data) return <Loading />;

  const canBanks = can(companyId, "manage_banks");
  const note = forecastNote(data.forecast);

  const run = async (key, fn, okText) => {
    setBusy(key);
    try {
      const res = await fn();
      if (okText) toast(typeof okText === "function" ? okText(res.data) : okText);
      await load();
      refreshCounts();
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <PageHeader
        title={company.name}
        subtitle={`P.IVA ${company.vat_number || "—"} · il tuo ruolo: ${ROLE_LABELS[company.role]}`}
        actions={
          <>
            {companies.length > 1 && (
              <select aria-label="Cambia azienda" className="input w-auto font-semibold" value={companyId}
                onChange={(e) => navigate(`/aziende/${e.target.value}`)}>
                {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            )}
            {canBanks && (
              <Button variant="secondary" loading={busy === "sync"}
                onClick={() => run("sync", () => api.post(`/companies/${companyId}/bank-accounts/sync-all`),
                  (d) => d.new_transactions ? `${d.new_transactions} nuovi movimenti scaricati` : "Nessun nuovo movimento")}>
                Aggiorna movimenti
              </Button>
            )}
          </>
        }
      />

      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
        <Stat label="Saldo conti" value={eur(data.card.balance_cents)}
          sub={data.forecast.credit_available_cents ? `+ ${eur(data.forecast.credit_available_cents, { short: true })} di fidi disponibili` : `${data.card.accounts_count} conti`} />
        <Stat label="Entrate del mese" value={eur(data.card.month_inflow_cents, { short: true })} />
        <Stat label="Uscite del mese" value={eur(data.card.month_outflow_cents, { short: true })} />
        <Stat label="Da riconciliare" value={data.card.to_reconcile} tone={data.card.to_reconcile ? "warn" : undefined}
          sub={<Link to="/riconciliazione" className="font-semibold text-accent">Vai alla riconciliazione →</Link>} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <Card title="Conti" actions={canBanks && (
          <>
            <Button variant="secondary" onClick={() => setManualOpen(true)}>+ Conto o carta</Button>
            <Button variant="secondary" onClick={() => { setConvert(null); setConnectOpen(true); }}>+ Collega in automatico</Button>
          </>
        )}>
          {data.accounts.length === 0 ? (
            <p className="text-sm text-muted">Nessun conto collegato.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-line">
              {data.accounts.map((a) => {
                const manual = a.provider === "manuale";
                const warn = a.consent_days_left !== undefined && a.consent_days_left <= 30;
                const off = a.status === "scollegato";
                const staleDays = manual && a.last_import_to ? Math.floor((Date.now() - new Date(a.last_import_to + "T12:00:00")) / 86400000) : null;
                if (manual) {
                  return (
                    <li key={a.id} className={`flex flex-col gap-1.5 py-3 ${off ? "opacity-60" : ""}`}>
                      <div className="flex justify-between gap-3">
                        <span className="font-semibold">{a.bank_name} · {a.label} <Badge className="ml-1" tone={a.account_type === "carta" ? "blue" : "gray"}>{a.account_type === "carta" ? "Carta" : "Manuale"}</Badge></span>
                        <span className={`num font-semibold ${a.balance_cents < 0 ? "text-warn-amount" : ""}`}>{eur(a.balance_cents)}</span>
                      </div>
                      <span className="text-xs text-muted">
                        {a.iban_masked} · {a.account_type === "carta" ? "da addebitare" : "saldo"} al {fmtDate(a.balance_date, { year: true })}
                        {a.account_type === "carta" && a.linked_account_id && (() => {
                          const l = data.accounts.find((x) => x.id === a.linked_account_id);
                          return l ? ` · addebito su ${l.bank_name} ${l.iban_masked}${a.card_debit_day ? ` il giorno ${a.card_debit_day}` : ""}` : "";
                        })()}
                      </span>
                      <span className={`text-xs font-semibold ${!a.last_import_to || staleDays > 7 ? "text-warn-text" : "text-muted"}`}>
                        {a.last_import_to ? `Movimenti importati fino al ${fmtDate(a.last_import_to, { year: true })}` : "Nessun estratto conto importato"}
                      </span>
                      {canBanks && !off && (
                        <div className="flex flex-wrap gap-2">
                          <Button variant="secondary" className="min-h-[40px]" onClick={() => setImportFor(a)}>{a.account_type === "carta" ? "Importa estratto carta" : "Importa estratto conto"}</Button>
                          {a.account_type !== "carta" && <Button variant="ghost" className="min-h-[40px] px-2" onClick={() => { setConvert(a); setConnectOpen(true); }}>Rendi automatico</Button>}
                        </div>
                      )}
                    </li>
                  );
                }
                return (
                  <li key={a.id} className={`flex flex-col gap-1.5 py-3 ${off ? "opacity-60" : ""}`}>
                    <div className="flex justify-between gap-3">
                      <span className="font-semibold">{a.bank_name} · {a.label}</span>
                      <span className="num font-semibold">{eur(a.balance_cents)}</span>
                    </div>
                    <span className="text-xs text-muted">{a.iban_masked} · aggiornato {fmtDate(a.balance_date)}</span>
                    <div className="flex flex-wrap items-center gap-2">
                      {off ? <Badge>Scollegato</Badge> : (
                        <span className={`text-xs font-semibold ${warn ? "text-warn-text" : "text-muted"}`}>
                          {warn ? `Consenso bancario da rinnovare tra ${a.consent_days_left} giorni` : `Consenso valido ancora ${a.consent_days_left} giorni`}
                        </span>
                      )}
                      {canBanks && !off && (
                        <>
                          {warn && <Button variant="ghost" className="min-h-[36px] px-2" loading={busy === `renew-${a.id}`}
                            onClick={() => run(`renew-${a.id}`, () => api.post(`/bank-accounts/${a.id}/renew-consent`), "Consenso rinnovato")}>Rinnova consenso</Button>}
                          <Button variant="ghost" className="min-h-[36px] px-2" loading={busy === `sync-${a.id}`}
                            onClick={() => run(`sync-${a.id}`, () => api.post(`/bank-accounts/${a.id}/sync`), (d) => `${d.new_transactions} nuovi movimenti`)}>Aggiorna</Button>
                        </>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card title="Previsione di cassa" subtitle="Da fatture aperte, F24 e IVA stimata, rate e spese ricorrenti"
          actions={<>
            <Button variant="secondary" onClick={() => setScenarioOpen(true)}>Prova uno scenario</Button>
            <select aria-label="Orizzonte" className="input w-auto" value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
              <option value={8}>8 settimane</option>
              <option value={12}>12 settimane</option>
              <option value={26}>6 mesi</option>
            </select>
          </>}>
          <ForecastChart forecast={data.forecast} />
          {note && <div className="mt-3"><Notice tone={note.tone}>{note.text}</Notice></div>}
          <details className="mt-3">
            <summary className="cursor-pointer text-sm font-semibold text-accent">Dettaglio settimana per settimana</summary>
            <ul className="mt-2 divide-y divide-soft">
              {data.forecast.weeks.map((w) => (
                <li key={w.week} className="py-2">
                  <button type="button" className="flex min-h-[40px] w-full flex-wrap items-center justify-between gap-2 text-left text-sm"
                    onClick={() => setOpenWeek(openWeek === w.week ? null : w.week)} aria-expanded={openWeek === w.week}>
                    <span className="font-semibold">Settimana {w.week} · dal {fmtDate(w.start)}</span>
                    <span className="num text-xs text-muted">+{eur(w.inflow_cents, { short: true })} / −{eur(w.outflow_cents, { short: true })}</span>
                    <span className={`num font-semibold ${w.balance_end_cents < 0 ? "text-warn-amount" : ""}`}>{eur(w.balance_end_cents)}</span>
                  </button>
                  {openWeek === w.week && (
                    <ul className="mt-1 flex flex-col gap-1 pl-2 text-xs">
                      {w.items.length === 0 && <li className="text-muted">Nessun movimento previsto.</li>}
                      {w.items.map((i, n) => (
                        <li key={n} className="flex justify-between gap-3">
                          <span>{fmtDate(i.due_date)} · {i.description}{i.overdue ? " (scaduta)" : ""}{i.estimate ? " · stima" : ""}</span>
                          <span className={`num whitespace-nowrap font-semibold ${i.kind === "incasso" || i.kind === "entrata" ? "" : "text-warn-amount"}`}>
                            {i.kind === "incasso" || i.kind === "entrata" ? "+" : "−"}{eur(i.amount_cents)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          </details>
        </Card>
      </div>

      <Card title="Entrate e uscite, ultimi 6 mesi"><MonthlyChart data={data.monthly} /></Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Ultimi movimenti" actions={<Link to="/movimenti" className="text-sm font-semibold text-accent">Tutti i movimenti →</Link>}>
          <ul className="divide-y divide-soft">
            {data.recent.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center gap-3 py-2.5">
                <span className="w-14 text-xs text-muted">{fmtDate(t.date)}</span>
                <span className="min-w-[140px] flex-1 text-sm">{t.description}<span className="block text-xs text-muted">{t.category}</span></span>
                <Badge tone={TX_STATUS[t.status][1]}>{TX_STATUS[t.status][0]}</Badge>
                <Amount cents={t.amount_cents} className="w-28 text-right" />
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Scadenze dei prossimi 30 giorni" actions={<Link to="/scadenze" className="text-sm font-semibold text-accent">Scadenzario →</Link>}>
          {data.upcoming.length === 0 ? <p className="text-sm text-muted">Nessuna scadenza.</p> : (
            <ul className="divide-y divide-soft">
              {data.upcoming.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-3 py-2.5">
                  <span className="w-14 font-semibold">{fmtDate(d.due_date)}</span>
                  <Badge tone={d.kind === "incasso" ? "blue" : d.kind === "f24" ? "orange" : "gray"}>{KIND_LABELS[d.kind]}</Badge>
                  <span className="min-w-[140px] flex-1 text-sm">{d.description}</span>
                  {d.overdue && <Badge tone="orange">Scaduta</Badge>}
                  <span className={`num w-28 text-right font-semibold ${d.kind === "incasso" ? "" : "text-warn-amount"}`}>{d.kind === "incasso" ? "+ " : "− "}{eur(d.amount_cents)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <ConnectModal open={connectOpen} convert={convert} onClose={() => setConnectOpen(false)} companyId={companyId}
        onDone={() => { setConnectOpen(false); setConvert(null); load(); refreshCounts(); }} />
      <ScenarioModal open={scenarioOpen} companyId={companyId} title={company.name} onClose={() => setScenarioOpen(false)} />
      <ManualAccountModal open={manualOpen} companyId={companyId} accounts={data?.accounts || []} onClose={() => setManualOpen(false)}
        onDone={(acc) => { setManualOpen(false); toast("Conto aggiunto: ora importa l'estratto conto"); load(); setImportFor(acc); }} />
      <ImportStatementModal account={importFor} onClose={() => setImportFor(null)}
        onDone={(r) => {
          setImportFor(null);
          toast(r.imported ? `${r.imported} movimenti importati${r.duplicates ? `, ${r.duplicates} già presenti` : ""}` : "Nessun movimento nuovo");
          load();
          refreshCounts();
        }} />
    </>
  );
}

function ConnectModal({ open, convert, onClose, companyId, onDone }) {
  const [bank, setBank] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  useEffect(() => {
    if (open) setBank(convert ? convert.bank_name : "");
  }, [open, convert]);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api.post(`/companies/${companyId}/bank-accounts/connect`,
        { bank_name: bank, manual_account_id: convert?.id || undefined });
      if (res.data.redirect_url) {
        window.location.assign(res.data.redirect_url);
        return;
      }
      toast(convert ? "Il conto ora si aggiorna in automatico: i movimenti importati sono stati mantenuti" : "Conto collegato e movimenti degli ultimi 90 giorni scaricati");
      setBank("");
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={convert ? "Rendi automatico il conto" : "Collega un conto in automatico"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={submit} loading={busy} disabled={!bank.trim()}>Collega</Button></>}>
      <div className="flex flex-col gap-4">
        <ErrorBox>{error}</ErrorBox>
        <Field label="Banca" htmlFor="bank" hint="Con il collegamento reale verrai portato sul sito della banca per autorizzare l'accesso in sola lettura (consenso PSD2, valido 180 giorni).">
          <input id="bank" className="input" value={bank} onChange={(e) => setBank(e.target.value)} placeholder="Es. Banca A" />
        </Field>
        {convert && (
          <Notice>Il conto {convert.iban_masked} manterrà tutti i movimenti importati finora; da ora in poi i nuovi arriveranno da soli.</Notice>
        )}
        <Notice tone="orange">Modalità demo: il collegamento e i movimenti scaricati sono simulati finché non attivi un provider open banking.</Notice>
      </div>
    </Modal>
  );
}
