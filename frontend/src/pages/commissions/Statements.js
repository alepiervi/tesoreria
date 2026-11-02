import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Modal, Notice, PageHeader, Stat, useToast } from "../../components/ui";
import { api, blobErrorMessage, downloadFile, errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { eur, fmtDate, fmtDateTime } from "../../lib/format";
import { KIND, monthLabel, monthOptions } from "./shared";

const STATE = { bozza: ["Da approvare", "orange"], approvato: ["Approvato · da pagare", "blue"], pagato: ["Pagato", "gray"], chiuso: ["Chiuso (saldo da recuperare)", "dark"] };
const LINE = { attivazione: "Attivazione", storno: "Storno", gara: "Gara", riporto: "Riporto" };

export default function CommissionStatements() {
  const [company, setCompany] = usePageCompany("view_commissions");
  const { can } = useAuth();
  const toast = useToast();
  const months = monthOptions();
  const [month, setMonth] = useState(months[1]);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState({});
  const [selected, setSelected] = useState({});
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const r = await api.get(`/companies/${company.id}/commission-statements`, { params: { month } });
      setData(r.data);
      setSelected(Object.fromEntries(r.data.rows.filter((x) => x.status === "bozza").map((x) => [x.beneficiary.id, true])));
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, month]);
  useEffect(() => { setData(null); load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alle provvigioni" />;
  const canEdit = can(company.id, "manage_commissions");
  const current = month === months[0];
  const ids = Object.entries(selected).filter(([, v]) => v).map(([k]) => k);
  const selectedRows = (data?.rows || []).filter((r) => ids.includes(r.beneficiary.id));

  const approve = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/companies/${company.id}/commission-statements/approve`, { month, beneficiary_ids: ids });
      toast(`${r.data.approved} rendiconti approvati: ${eur(r.data.total_cents)} da pagare o mettere in busta`);
      setConfirm(false);
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy(false);
    }
  };
  const act = async (row, action) => {
    try {
      await api.post(`/commission-statements/${row.statement_id}/${action}`);
      toast(action === "paid" ? "Segnato come pagato" : "Rendiconto riaperto");
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };
  const download = async (kind) => {
    try {
      await downloadFile(`/companies/${company.id}/commission-statements/export`, { month, kind }, `provvigioni_${month}.xlsx`);
    } catch (e) {
      toast(await blobErrorMessage(e), "orange");
    }
  };

  return (
    <>
      <PageHeader title="Rendiconti provvigioni" subtitle="Per ogni struttura e dipendente: attivazioni, storni recuperati, gare e saldo del mese"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_commissions" />
          <label htmlFor="sm" className="sr-only">Mese</label>
          <select id="sm" className="input w-auto" value={month} onChange={(e) => setMonth(e.target.value)}>
            {months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
          </select>
          <Button variant="secondary" onClick={() => download("tutti")}>Excel del mese</Button>
          <Button variant="secondary" onClick={() => download("dipendente")}>Bonus per il consulente</Button>
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-4">
            <Stat label="Provvigioni alle strutture" value={eur(data.summary.strutture_cents)} />
            <Stat label="Bonus ai dipendenti" value={eur(data.summary.dipendenti_cents)} />
            <Stat label="Storni recuperati" value={eur(data.summary.storni_cents)} tone={data.summary.storni_cents ? "warn" : undefined} />
            <Stat label="Premi delle gare" value={eur(data.summary.gare_cents)} />
          </div>
          {current ? (
            <Notice>Mese in corso: i numeri sono provvisori. Il rendiconto si approva dopo la fine del mese.</Notice>
          ) : (
            <Notice>
              Le bozze comprendono anche le attivazioni dei mesi prima non ancora pagate (per esempio arrivate in ritardo dal partner).
              Gli storni si recuperano solo per i clienti cessati entro il periodo di storno del partner.
            </Notice>
          )}
          {data.summary.senza_prezzo > 0 && <Notice tone="orange">{data.summary.senza_prezzo} attivazioni hanno un'offerta senza compenso nel listino: completalo prima di approvare.</Notice>}
          {data.rows.length === 0 ? <Card><Empty title="Niente da rendicontare in questo mese" /></Card> : (
            <Card padded={false}
              actions={canEdit && !current && data.summary.da_approvare > 0 && (
                <Button onClick={() => setConfirm(true)} disabled={!ids.length}>Approva selezionati ({ids.length})</Button>
              )}
              title={`${monthLabel(month)} · ${data.rows.length} rendiconti`}>
              <ul className="divide-y divide-soft">
                {data.rows.map((r) => {
                  const b = r.beneficiary;
                  const by = (t) => r.lines.filter((l) => l.type === t).reduce((s, l) => s + l.amount_cents, 0);
                  const st = STATE[r.status];
                  return (
                    <li key={b.id} className="px-5 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-3">
                          {canEdit && r.status === "bozza" && !current && (
                            <input type="checkbox" className="h-5 w-5" aria-label={`Seleziona ${b.name}`} checked={Boolean(selected[b.id])}
                              onChange={(e) => setSelected({ ...selected, [b.id]: e.target.checked })} />
                          )}
                          <button type="button" className="min-w-0 text-left" aria-expanded={Boolean(open[b.id])} onClick={() => setOpen((o) => ({ ...o, [b.id]: !o[b.id] }))}>
                            <b>{b.name}</b> <Badge className="ml-1">{KIND[b.kind]}</Badge>
                            <span className="num block text-xs text-muted">
                              Attivazioni {eur(by("attivazione"))}{by("storno") ? ` · storni ${eur(by("storno"))}` : ""}{by("gara") ? ` · gare ${eur(by("gara"))}` : ""}{by("riporto") ? ` · riporto ${eur(by("riporto"))}` : ""}
                            </span>
                          </button>
                        </div>
                        <div className="flex flex-wrap items-center gap-3">
                          <Badge tone={st[1]}>{st[0]}</Badge>
                          <span className={`num text-lg font-bold ${r.total_cents < 0 ? "text-warn-amount" : ""}`}>{eur(r.total_cents)}</span>
                          {canEdit && r.status === "approvato" && <Button variant="secondary" className="min-h-[38px]" onClick={() => act(r, "paid")}>Segna pagato</Button>}
                          {canEdit && ["approvato", "chiuso"].includes(r.status) && <Button variant="ghost" className="min-h-[38px] px-2" onClick={() => act(r, "reopen")}>Riapri</Button>}
                        </div>
                      </div>
                      {open[b.id] && (
                        <div className="mt-3 overflow-x-auto rounded-lg border border-line">
                          <table className="w-full min-w-[640px] text-sm">
                            <tbody>
                              {r.lines.map((l, i) => (
                                <tr key={i} className="border-b border-soft last:border-0">
                                  <td className="w-[110px] px-3 py-2"><Badge tone={l.type === "storno" || l.type === "riporto" ? "orange" : l.type === "gara" ? "blue" : "gray"}>{LINE[l.type]}</Badge></td>
                                  <td className="whitespace-nowrap py-2 pr-3 text-muted">{l.date ? fmtDate(l.date, { year: true }) : ""}</td>
                                  <td className="py-2 pr-3">{l.description}{l.warning && <span className="block text-xs text-warn-text">{l.warning}</span>}</td>
                                  <td className={`num whitespace-nowrap px-3 py-2 text-right font-semibold ${l.amount_cents < 0 ? "text-warn-amount" : ""}`}>{eur(l.amount_cents)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {r.approved_at && <p className="px-3 py-2 text-xs text-muted">Approvato da {r.approved_by} il {fmtDateTime(r.approved_at)}.</p>}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}
        </>
      )}
      <Modal open={confirm} onClose={() => setConfirm(false)} title={`Approvare ${ids.length} rendiconti di ${monthLabel(month).toLowerCase()}?`}
        footer={<><Button variant="secondary" onClick={() => setConfirm(false)}>Annulla</Button><Button onClick={approve} loading={busy}>Approva</Button></>}>
        <div className="flex flex-col gap-2 text-sm">
          <p>Strutture: <b>{eur(selectedRows.filter((r) => r.beneficiary.kind === "struttura" && r.total_cents > 0).reduce((s, r) => s + r.total_cents, 0))}</b> — per ognuna si crea il pagamento nello Scadenzario (da autorizzare). Aspetta la loro fattura prima di pagare.</p>
          <p>Dipendenti: <b>{eur(selectedRows.filter((r) => r.beneficiary.kind === "dipendente" && r.total_cents > 0).reduce((s, r) => s + r.total_cents, 0))}</b> — vanno in busta paga: scarica «Bonus per il consulente».</p>
          <p className="text-muted">I saldi negativi (più storni che attivazioni) passano al mese dopo e si recuperano lì.</p>
        </div>
      </Modal>
    </>
  );
}
