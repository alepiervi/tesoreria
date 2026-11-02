import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Modal, Notice, PageHeader, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDate, fmtDateTime } from "../lib/format";

const MONTHS = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"];

function monthOptions() {
  const out = [];
  const d = new Date();
  d.setDate(15);
  for (let i = 0; i < 13; i += 1) {
    out.push(d.toISOString().slice(0, 7));
    d.setMonth(d.getMonth() - 1);
  }
  return out;
}

export default function MonthClose() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const { can } = useAuth();
  const toast = useToast();
  const options = monthOptions();
  const [month, setMonth] = useState(options[1]);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const r = await api.get(`/companies/${company.id}/month-close`, { params: { month } });
      setData(r.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, month]);
  useEffect(() => { setData(null); load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;
  const canTick = can(company.id, "manage_accounting");
  const canClose = can(company.id, "close_fiscal_year");
  const tick = async (item, done) => {
    try {
      await api.put(`/companies/${company.id}/month-close/${month}/items/${item.id}`, { done, note: "" });
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };
  const act = async (action, force = false) => {
    setBusy(true);
    try {
      await api.post(`/companies/${company.id}/month-close/${month}/${action}`, null, { params: force ? { force: true } : {} });
      toast(action === "close" ? "Mese chiuso: movimenti, fatture e registrazioni fino a fine mese sono bloccati" : "Mese riaperto");
      setConfirm(null);
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy(false);
    }
  };
  const mLabel = `${MONTHS[Number(month.slice(5, 7)) - 1]} ${month.slice(0, 4)}`;
  const applicable = (data?.items || []).filter((i) => i.applicable);
  const done = applicable.filter((i) => i.done).length;

  return (
    <>
      <PageHeader title="Chiusura del mese" subtitle="Cosa va fatto a fine mese, da chi, e cosa manca ancora"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />
          <label htmlFor="mc-m" className="sr-only">Mese</label>
          <select id="mc-m" className="input w-auto" value={month} onChange={(e) => setMonth(e.target.value)}>
            {options.map((m) => <option key={m} value={m}>{MONTHS[Number(m.slice(5, 7)) - 1]} {m.slice(0, 4)}</option>)}
          </select>
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
          <Card title={`${mLabel} · ${done} di ${applicable.length} completati`}>
            <div className="mb-4 h-2.5 overflow-hidden rounded-full bg-soft" role="img" aria-label={`${done} di ${applicable.length} completati`}>
              <div className="h-full rounded-full bg-accent" style={{ width: `${applicable.length ? (done / applicable.length) * 100 : 0}%` }} />
            </div>
            <ul className="flex flex-col divide-y divide-soft">
              {data.items.map((i) => (
                <li key={i.id} className={`flex flex-wrap items-start justify-between gap-3 py-3 ${i.applicable ? "" : "opacity-50"}`}>
                  <div className="flex min-w-0 items-start gap-3">
                    {i.auto ? (
                      <span aria-label={i.done ? "Fatto" : "Da fare"} className={`mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-full text-xs font-bold ${i.done ? "bg-accent text-white" : "bg-warn-soft text-warn-text"}`}>
                        {i.done ? "✓" : "!"}
                      </span>
                    ) : (
                      <input type="checkbox" aria-label={i.title} className="mt-1 h-5 w-5 flex-none" checked={i.done} disabled={!canTick || data.closed}
                        onChange={(e) => tick(i, e.target.checked)} />
                    )}
                    <span className="min-w-0">
                      <b>{i.title}</b> <Badge className="ml-1">{i.role_label}</Badge>
                      <span className="block text-sm text-muted">
                        {!i.applicable ? "Non previsto per questo mese." : i.detail}
                        {!i.auto && i.done && i.done_by ? ` Spuntato da ${i.done_by} il ${fmtDateTime(i.done_at)}.` : ""}
                      </span>
                    </span>
                  </div>
                  {i.link && i.applicable && !i.done && <Link to={i.link} className="text-sm font-semibold text-accent hover:underline">Vai →</Link>}
                </li>
              ))}
            </ul>
          </Card>
          <div className="flex flex-col gap-6">
            <Card title="Blocco del mese">
              <div className="flex flex-col gap-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  Stato: {data.closed ? <Badge tone="dark">Chiuso</Badge> : <Badge tone="blue">Aperto</Badge>}
                  {data.lock_date && <Badge>Bloccato fino al {fmtDate(data.lock_date, { year: true })}</Badge>}
                </div>
                {data.closed && data.closed_by && <p className="text-muted">Chiuso da {data.closed_by} il {fmtDateTime(data.closed_at)}.</p>}
                <p>Chiudendo il mese, fatture, movimenti e registrazioni con data fino al {fmtDate(data.to, { year: true })} non si possono più cambiare: il commercialista lavora su dati fermi.</p>
                {!canClose ? <Notice>Il mese lo chiude il titolare o il commercialista.</Notice> : data.closed ? (
                  <Button variant="danger" onClick={() => act("reopen")} loading={busy}>Riapri {mLabel}</Button>
                ) : !data.month_ended ? (
                  <Notice>Il mese non è ancora finito.</Notice>
                ) : data.ready ? (
                  <Button onClick={() => setConfirm("close")} loading={busy}>Chiudi {mLabel}</Button>
                ) : (
                  <>
                    <Button variant="secondary" onClick={() => setConfirm("force")} loading={busy}>Chiudi comunque</Button>
                    <p className="text-xs text-warn-text">Mancano {data.missing} controlli: chiudere comunque è possibile ma resta registrato.</p>
                  </>
                )}
              </div>
            </Card>
            <Notice>Dal giorno 10 il programma ricorda a chi gestisce la contabilità i mesi non ancora chiusi.</Notice>
          </div>
        </div>
      )}
      <Modal open={Boolean(confirm)} onClose={() => setConfirm(null)} title={`Chiudere ${mLabel}?`}
        footer={<><Button variant="secondary" onClick={() => setConfirm(null)}>Annulla</Button>
          <Button onClick={() => act("close", confirm === "force")} loading={busy}>Chiudi e blocca</Button></>}>
        <p className="text-sm">{confirm === "force" ? `Ci sono ancora ${data?.missing} controlli aperti. ` : ""}Dopo la chiusura i dati del mese restano bloccati finché non lo riapri.</p>
      </Modal>
    </>
  );
}
