import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, Stat, useToast } from "../../components/ui";
import { centsToInput } from "../../lib/accounting";
import { api, errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { addDays, eur, fmtDate, todayIso } from "../../lib/format";

export default function GroupCash() {
  const { can } = useAuth();
  const toast = useToast();
  const [weeks, setWeeks] = useState(13);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [transfer, setTransfer] = useState(null);
  const [buffer, setBuffer] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/group/liquidity", { params: { weeks } });
      setData(r.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [weeks]);
  useEffect(() => { setData(null); load(); }, [load]);

  return (
    <>
      <PageHeader title="Liquidità di gruppo" subtitle="Dove sono i soldi, chi rischia di restare corto e quanto spostare tra le aziende"
        actions={<>
          <label htmlFor="gw" className="sr-only">Orizzonte</label>
          <select id="gw" className="input w-auto" value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
            <option value={8}>Prossime 8 settimane</option>
            <option value={13}>Prossimi 3 mesi</option>
            <option value={26}>Prossimi 6 mesi</option>
          </select>
          <Button onClick={() => setTransfer({})}>Nuovo trasferimento</Button>
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
            <Stat label="Liquidità del gruppo oggi" value={eur(data.total_cents)} />
            <Stat label="Punto più basso (somma delle aziende)" value={eur(data.total_lowest_cents)} tone={data.total_lowest_cents < 0 ? "warn" : undefined}
              sub="Le aziende possono scendere in settimane diverse" />
            <Stat label="Trasferimenti consigliati" value={String(data.proposals.length)} />
          </div>

          {data.proposals.length > 0 && (
            <Card title="Trasferimenti consigliati" subtitle="Per tenere ogni azienda sopra la sua riserva minima senza farne scendere un'altra">
              <ul className="flex flex-col divide-y divide-soft">
                {data.proposals.map((p, i) => (
                  <li key={i} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <b>{p.from_name} → {p.to_name}</b> <span className="num font-bold">{eur(p.amount_cents)}</span>
                      <span className="block text-sm text-muted">{p.reason}{p.by_date ? ` · entro la settimana del ${fmtDate(p.by_date, { year: true })}` : ""}</span>
                    </div>
                    {data.can_transfer[p.from_id] && data.can_transfer[p.to_id] && (
                      <Button variant="secondary" onClick={() => setTransfer({ from: p.from_id, to: p.to_id, amount: centsToInput(p.amount_cents),
                        date: p.by_date && p.by_date > todayIso() ? addDays(p.by_date, -3) : addDays(todayIso(), 3) })}>Prepara il bonifico</Button>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card padded={false} title="Aziende">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-sm">
                <thead>
                  <tr className="table-head text-left">
                    <th className="px-5 py-3">Azienda</th>
                    <th className="py-3 pr-3 text-right">Oggi</th>
                    <th className="py-3 pr-3 text-right">Punto più basso</th>
                    <th className="py-3 pr-3 text-right">Fine periodo</th>
                    <th className="py-3 pr-3 text-right">Fidi disponibili</th>
                    <th className="py-3 pr-3 text-right">Riserva minima</th>
                    <th className="py-3 pr-5">Situazione</th>
                  </tr>
                </thead>
                <tbody>
                  {data.companies.map((c) => (
                    <tr key={c.id} className="border-b border-soft align-top">
                      <td className="px-5 py-3 font-semibold">{c.name}
                        <span className="block text-xs font-normal text-muted">{c.banks.map((b) => `${b.label}: ${eur(b.balance_cents)}`).join(" · ")}</span></td>
                      <td className="num py-3 pr-3 text-right font-semibold">{eur(c.balance_cents)}</td>
                      <td className={`num py-3 pr-3 text-right ${c.lowest_cents < c.buffer_cents ? "font-bold text-warn-amount" : ""}`}>
                        {eur(c.lowest_cents)}{c.lowest_week_start && <span className="block text-xs font-normal text-muted">sett. del {fmtDate(c.lowest_week_start)}</span>}</td>
                      <td className="num py-3 pr-3 text-right">{eur(c.end_cents)}</td>
                      <td className="num py-3 pr-3 text-right">{eur(c.credit_available_cents)}</td>
                      <td className="num py-3 pr-3 text-right">
                        {can(c.id, "manage_budget") ? (
                          <button type="button" className="text-accent hover:underline" onClick={() => setBuffer({ id: c.id, name: c.name, amount: centsToInput(c.buffer_cents) })}>
                            {eur(c.buffer_cents)}
                          </button>
                        ) : eur(c.buffer_cents)}
                      </td>
                      <td className="py-3 pr-5">
                        {c.need_cents > 0 ? <Badge tone="orange">Mancano {eur(c.need_cents)}</Badge>
                          : c.surplus_cents > 0 ? <Badge tone="blue">Può prestare {eur(c.surplus_cents)}</Badge> : <Badge>In equilibrio</Badge>}
                        {c.uncovered_cents > 0 && <span className="mt-1 block text-xs text-warn-text">{eur(c.uncovered_cents)} non coperti dalle altre aziende: valuta i fidi</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Crediti e debiti tra le aziende" subtitle="Dalla contabilità: finanziamenti tra società e fatture non ancora pagate">
            {data.intercompany.length === 0 ? <p className="text-sm text-muted">Nessuna posizione aperta tra le aziende.</p> : (
              <ul className="flex flex-col gap-2 text-sm">
                {data.intercompany.map((r) => (
                  <li key={`${r.creditor_id}-${r.debtor_id}`}><b>{r.debtor}</b> deve <span className="num font-bold">{eur(r.amount_cents)}</span> a <b>{r.creditor}</b></li>
                ))}
              </ul>
            )}
            <Link to="/intercompany" className="mt-3 inline-block text-sm font-semibold text-accent hover:underline">Movimenti tra le aziende →</Link>
          </Card>
          <Notice>
            Il trasferimento crea un pagamento da autorizzare nell'azienda che presta e un incasso previsto in quella che riceve.
            Per i finanziamenti tra società conviene un accordo scritto (durata, eventuali interessi): chiedi al commercialista.
          </Notice>
        </>
      )}
      <TransferModal value={transfer} companies={data?.companies || []} onClose={() => setTransfer(null)}
        onDone={() => { toast("Bonifico preparato: lo trovi nello Scadenzario da autorizzare"); load(); }} />
      <BufferModal value={buffer} onClose={() => setBuffer(null)} onDone={() => { toast("Riserva minima salvata"); load(); }} />
    </>
  );
}

function TransferModal({ value, companies, onClose, onDone }) {
  const { can } = useAuth();
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const allowed = companies.filter((c) => can(c.id, "manage_deadlines"));
  useEffect(() => {
    if (!value) return;
    setError("");
    setForm({ from: value.from || allowed[0]?.id || "", to: value.to || allowed[1]?.id || "", amount: value.amount || "",
      date: value.date || addDays(todayIso(), 3), description: "Finanziamento infragruppo" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  if (!value || !form) return null;
  const save = async () => {
    setBusy(true);
    try {
      await api.post("/group/transfers", { from_company_id: form.from, to_company_id: form.to, amount: form.amount, date: form.date,
        description: form.description });
      onDone();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  if (allowed.length < 2) {
    return <Modal open onClose={onClose} title="Trasferimento tra aziende"><Empty title="Servono i permessi sulle scadenze di almeno due aziende" /></Modal>;
  }
  return (
    <Modal open onClose={onClose} title="Trasferimento tra aziende"
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save} loading={busy}>Prepara</Button></>}>
      <div className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Da" htmlFor="t-from">
            <select id="t-from" className="input" value={form.from} onChange={(e) => setForm({ ...form, from: e.target.value })}>
              {allowed.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="A" htmlFor="t-to">
            <select id="t-to" className="input" value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })}>
              {allowed.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="Importo €" htmlFor="t-amt"><input id="t-amt" inputMode="decimal" className="input" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></Field>
          <Field label="Data" htmlFor="t-date"><input id="t-date" type="date" className="input" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></Field>
        </div>
        <Field label="Causale" htmlFor="t-desc"><input id="t-desc" className="input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <ErrorBox>{error}</ErrorBox>
      </div>
    </Modal>
  );
}

function BufferModal({ value, onClose, onDone }) {
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { if (value) { setAmount(value.amount); setError(""); } }, [value]);
  if (!value) return null;
  const save = async () => {
    try {
      await api.put(`/companies/${value.id}/cash-buffer`, { amount: amount || "0" });
      onDone();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  return (
    <Modal open onClose={onClose} title={`Riserva minima · ${value.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save}>Salva</Button></>}>
      <Field label="Saldo sotto cui non scendere €" htmlFor="buf" hint="Di solito almeno un mese di stipendi e spese fisse.">
        <input id="buf" inputMode="decimal" className="input" value={amount} onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <ErrorBox>{error}</ErrorBox>
    </Modal>
  );
}
