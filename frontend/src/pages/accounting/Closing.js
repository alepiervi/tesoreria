import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import CompanyPicker, { usePageCompany } from "../../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, useToast } from "../../components/ui";
import { AccountSelect, YearSelect, useAccounts, useCostCenters } from "../../lib/accounting";
import { api, errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { eur, fmtDate } from "../../lib/format";

const KIND_HELP = {
  risconto_attivo: "Costo pagato ora ma di competenza in parte dell'anno dopo (es. assicurazione annuale pagata a ottobre).",
  rateo_passivo: "Costo di competenza di quest'anno che si pagherà l'anno dopo (es. interessi o canoni posticipati).",
  risconto_passivo: "Ricavo incassato ora ma di competenza in parte dell'anno dopo (es. canone annuale anticipato).",
  rateo_attivo: "Ricavo di competenza di quest'anno che si incasserà l'anno dopo.",
};

export default function Closing() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const { can } = useAuth();
  const toast = useToast();
  const [year, setYear] = useState(new Date().getFullYear());
  const [years, setYears] = useState(null);
  const [accruals, setAccruals] = useState(null);
  const [checks, setChecks] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [accrualOpen, setAccrualOpen] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [accounts] = useAccounts(company?.id, year);
  const [inventoryDone, setInventoryDone] = useState(false);
  const [costCenters] = useCostCenters(company?.id);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const [y, a, c] = await Promise.all([
        api.get(`/companies/${company.id}/fiscal-years`),
        api.get(`/companies/${company.id}/accruals`, { params: { year } }),
        api.get(`/companies/${company.id}/accounting-checks`),
      ]);
      setYears(y.data); setAccruals(a.data); setChecks(c.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, year]);
  useEffect(() => { load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;
  const canEdit = can(company.id, "manage_accounting");
  const canClose = can(company.id, "close_fiscal_year");
  const info = years?.years.find((y) => y.year === year) || { year, closed: false, locked: false, depreciation_posted: false };
  const lock = years?.lock_date;
  const openIssues = checks.filter((c) => !c.ok && ["quadratura", "transitorio"].includes(c.id));

  const run = async (key, fn, okText) => {
    setBusy(key);
    try {
      const r = await fn();
      toast(okText(r.data));
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
    }
  };

  const steps = [
    {
      id: "iva", title: "Liquidazioni IVA", text: "Giroconto di IVA vendite e acquisti su Erario c/IVA per ogni periodo già chiuso.",
      action: canEdit && <Button variant="secondary" loading={busy === "iva"} disabled={info.locked}
        onClick={() => run("iva", () => api.post(`/companies/${company.id}/vat-settlements`, null, { params: { year } }), (d) => `${d.posted} liquidazioni registrate o aggiornate`)}>Registra</Button>,
    },
    {
      id: "amm", title: "Ammortamenti", done: info.depreciation_posted, text: "Quote dell'anno di tutti i cespiti, in un'unica registrazione al 31/12.",
      action: <Link to="/contabilita/cespiti" className="text-sm font-semibold text-accent hover:underline">Vai ai cespiti →</Link>,
    },
    {
      id: "rat", title: "Ratei e risconti", done: (accruals?.items || []).length > 0,
      text: "Rettifiche di competenza: si stornano da sole il 1° gennaio dell'anno dopo.",
      action: canEdit && <Button variant="secondary" disabled={info.locked} onClick={() => setAccrualOpen(true)}>Aggiungi</Button>,
    },
    {
      id: "rim", title: "Rimanenze di magazzino", done: inventoryDone,
      text: "Valore delle merci in magazzino al 31/12: riduce i costi dell'anno e diventa rimanenza iniziale dell'anno dopo.",
      action: <a href="#rimanenze" className="text-sm font-semibold text-accent hover:underline">Inserisci ↓</a>,
    },
    {
      id: "altre", title: "Stipendi, TFR, fatture da ricevere, imposte",
      text: "Si inseriscono dalla prima nota con i modelli già pronti, sui dati del consulente del lavoro e del commercialista.",
      action: <Link to="/contabilita/prima-nota" className="text-sm font-semibold text-accent hover:underline">Apri la prima nota →</Link>,
    },
    {
      id: "check", title: "Controlli di quadratura", done: openIssues.length === 0,
      text: openIssues.length ? openIssues.map((c) => c.title).join(" · ") : "Dare e avere in pareggio, nessun importo da attribuire.",
      action: <Link to="/contabilita/bilancio" className="text-sm font-semibold text-accent hover:underline">Vedi i controlli →</Link>,
    },
  ];

  return (
    <>
      <PageHeader title="Chiusure e rettifiche" subtitle="Scritture di fine anno, chiusura e riapertura dei conti, blocco del periodo"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />
          <YearSelect value={year} onChange={setYear} />
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!years ? <Loading /> : (
        <>
          <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
            <Card title={`Fine esercizio ${year}`} subtitle={info.closed ? "Esercizio chiuso: i conti sono stati riaperti al 1° gennaio successivo" : "Passaggi consigliati prima della chiusura"}>
              <ol className="flex flex-col divide-y divide-soft">
                {steps.map((s, i) => (
                  <li key={s.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                    <div className="flex min-w-0 items-start gap-3">
                      <span className={`flex h-7 w-7 flex-none items-center justify-center rounded-full text-xs font-bold ${s.done ? "bg-accent text-white" : "bg-soft text-[#3D4250]"}`}>{s.done ? "✓" : i + 1}</span>
                      <span className="min-w-0"><b>{s.title}</b><span className="block text-sm text-muted">{s.text}</span></span>
                    </div>
                    {s.action}
                  </li>
                ))}
              </ol>
            </Card>
            <Card title="Chiusura dell'esercizio">
              <div className="flex flex-col gap-3 text-sm">
                <p>
                  La chiusura gira costi e ricavi sul conto economico, rileva l'utile o la perdita, chiude lo stato patrimoniale e
                  riapre i conti al 1° gennaio. Poi <b>blocca</b> tutte le date fino al 31/12: fatture, movimenti e registrazioni
                  di quell'anno non si possono più cambiare.
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  Stato: {info.closed ? <Badge tone="dark">Chiuso</Badge> : <Badge tone="blue">Aperto</Badge>}
                  {lock && <Badge>Bloccato fino al {fmtDate(lock, { year: true })}</Badge>}
                </div>
                {canClose ? (
                  info.closed ? (
                    <Button variant="danger" onClick={() => setConfirm("reopen")} loading={busy === "reopen"}>Riapri l'esercizio {year}</Button>
                  ) : (
                    <Button onClick={() => setConfirm("close")} loading={busy === "close"} disabled={openIssues.length > 0}>Chiudi l'esercizio {year}</Button>
                  )
                ) : <Notice>Chiusura e riapertura le fa il titolare o il commercialista.</Notice>}
                {!info.closed && openIssues.length > 0 && <p className="text-xs text-warn-text">Prima sistema i controlli segnalati.</p>}
              </div>
            </Card>
          </div>

          <Card title={`Ratei e risconti ${year}`} padded={false}
            actions={canEdit && !info.locked && <Button variant="secondary" onClick={() => setAccrualOpen(true)}>Nuovo rateo o risconto</Button>}>
            {(accruals?.items || []).length === 0 ? <Empty title="Nessuna rettifica di competenza" /> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-sm">
                  <thead>
                    <tr className="table-head text-left">
                      <th className="px-5 py-3">Descrizione</th>
                      <th className="py-3 pr-3">Tipo</th>
                      <th className="py-3 pr-3">Periodo</th>
                      <th className="py-3 pr-3 text-right">Importo</th>
                      <th className="py-3 pr-3 text-right">Rettifica al 31/12</th>
                      <th className="py-3 pr-5"><span className="sr-only">Azioni</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {accruals.items.map((a) => (
                      <tr key={a.id} className="border-b border-soft">
                        <td className="px-5 py-2.5 font-semibold">{a.description}<span className="block text-xs font-normal text-muted">conto {a.account_code}</span></td>
                        <td className="py-2.5 pr-3">{accruals.kinds[a.kind]}</td>
                        <td className="whitespace-nowrap py-2.5 pr-3">{fmtDate(a.start, { year: true })} → {fmtDate(a.end, { year: true })}</td>
                        <td className="num py-2.5 pr-3 text-right">{eur(a.amount_cents)}</td>
                        <td className="num py-2.5 pr-3 text-right font-semibold">{eur(a.portion_cents)}</td>
                        <td className="py-2.5 pr-5 text-right">
                          {canEdit && !info.locked && <Button variant="ghost" className="min-h-[36px] px-2 text-warn-text"
                            onClick={() => run("del", () => api.delete(`/accruals/${a.id}`), () => "Rettifica eliminata")}>Elimina</Button>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}

      {years && <Inventory company={company} year={year} locked={info.locked} canEdit={canEdit} onLoaded={setInventoryDone} />}

      <AccrualModal open={accrualOpen} onClose={() => setAccrualOpen(false)} companyId={company.id} year={year}
        kinds={accruals?.kinds || {}} accounts={accounts} costCenters={costCenters} onSaved={() => { toast("Rettifica registrata"); load(); }} />

      <Modal open={Boolean(confirm)} onClose={() => setConfirm(null)}
        title={confirm === "close" ? `Chiudere l'esercizio ${year}?` : `Riaprire l'esercizio ${year}?`}
        footer={<>
          <Button variant="secondary" onClick={() => setConfirm(null)}>Annulla</Button>
          <Button variant={confirm === "close" ? "primary" : "danger"} onClick={() => {
            const action = confirm;
            setConfirm(null);
            run(action, () => api.post(`/companies/${company.id}/fiscal-years/${year}/${action}`),
              (d) => (action === "close" ? `Esercizio chiuso: ${d.result_cents >= 0 ? "utile" : "perdita"} ${eur(Math.abs(d.result_cents))}` : "Esercizio riaperto"));
          }}>{confirm === "close" ? "Chiudi e blocca" : "Riapri"}</Button>
        </>}>
        {confirm === "close" ? (
          <p className="text-sm">Verranno create le registrazioni di chiusura al 31/12/{year} e di riapertura al 01/01/{year + 1}. Il periodo sarà bloccato: per correggere qualcosa bisognerà riaprire l'esercizio.</p>
        ) : (
          <p className="text-sm">Le registrazioni di chiusura e riapertura vengono eliminate e il blocco torna alla fine dell'anno precedente. Si può riaprire solo l'ultimo esercizio chiuso.</p>
        )}
      </Modal>
    </>
  );
}

function AccrualModal({ open, onClose, companyId, year, kinds, accounts, costCenters, onSaved }) {
  const empty = { kind: "risconto_attivo", description: "", amount: "", start: `${year}-10-01`, end: `${year + 1}-09-30`, account_code: "", cost_center_id: "" };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (open) { setForm(empty); setError(""); } }, [open, year]);
  if (!open) return null;
  const isCost = ["risconto_attivo", "rateo_passivo"].includes(form.kind);
  const save = async () => {
    setBusy(true);
    try {
      await api.post(`/companies/${companyId}/accruals`, { ...form, year, cost_center_id: form.cost_center_id || null });
      onSaved();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} title="Nuovo rateo o risconto"
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save} loading={busy}>Registra</Button></>}>
      <div className="flex flex-col gap-3">
        <Field label="Tipo" htmlFor="ac-kind" hint={KIND_HELP[form.kind]}>
          <select id="ac-kind" className="input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value, account_code: "" })}>
            {Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Descrizione" htmlFor="ac-desc"><input id="ac-desc" className="input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Importo totale €" htmlFor="ac-amt"><input id="ac-amt" inputMode="decimal" className="input" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></Field>
          <Field label="Dal" htmlFor="ac-start"><input id="ac-start" type="date" className="input" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} /></Field>
          <Field label="Al" htmlFor="ac-end"><input id="ac-end" type="date" className="input" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} /></Field>
        </div>
        <Field label={isCost ? "Conto di costo" : "Conto di ricavo"} htmlFor="ac-acc">
          <AccountSelect id="ac-acc" accounts={accounts} kinds={[isCost ? "costo" : "ricavo"]} value={form.account_code} onChange={(v) => setForm({ ...form, account_code: v })} />
        </Field>
        {costCenters.length > 0 && (
          <Field label="Centro di costo" htmlFor="ac-cc">
            <select id="ac-cc" className="input" value={form.cost_center_id} onChange={(e) => setForm({ ...form, cost_center_id: e.target.value })}>
              <option value="">Nessuno</option>
              {costCenters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        )}
        <p className="text-xs text-muted">La quota è calcolata a giorni sul periodo indicato.</p>
        <ErrorBox>{error}</ErrorBox>
      </div>
    </Modal>
  );
}

function Inventory({ company, year, locked, canEdit, onLoaded }) {
  const toast = useToast();
  const [rows, setRows] = useState([]);
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const r = await api.get(`/companies/${company.id}/inventories`);
    const doc = r.data.items.find((i) => i.year === year);
    setSaved(doc || null);
    onLoaded(Boolean(doc && doc.total_cents));
    setRows(doc?.items?.length ? doc.items.map((i) => ({ description: i.description, qty: String(i.qty).replace(".", ","), unit_cost: (i.unit_cost_cents / 100).toLocaleString("it-IT") })) : []);
    setValue(doc && !doc.items?.length && doc.value_cents ? (doc.value_cents / 100).toLocaleString("it-IT") : "");
  }, [company.id, year, onLoaded]);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const total = rows.length
    ? rows.reduce((s, r) => s + (Number(String(r.qty).replace(",", ".")) || 0) * (Number(String(r.unit_cost).replace(/\./g, "").replace(",", ".")) || 0), 0)
    : Number(String(value).replace(/\./g, "").replace(",", ".")) || 0;
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await api.put(`/companies/${company.id}/inventories/${year}`, {
        year, value: rows.length ? "" : value, items: rows.map((r) => ({ description: r.description, qty: Number(String(r.qty).replace(",", ".")) || 0, unit_cost: r.unit_cost || "0" })),
      });
      toast("Rimanenze registrate");
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const setRow = (i, patch) => setRows((rs) => rs.map((r, n) => (n === i ? { ...r, ...patch } : r)));
  const editable = canEdit && !locked;

  return (
    <section id="rimanenze">
      <Card title={`Rimanenze di magazzino al 31/12/${year}`} subtitle={saved ? `Registrate: ${eur(saved.total_cents)} · ultimo aggiornamento di ${saved.updated_by_name || "—"}` : "Non ancora inserite"}
        actions={editable && <Button onClick={save} loading={busy}>Registra {eur(Math.round(total * 100))}</Button>}>
        <div className="flex flex-col gap-3">
          {rows.length === 0 && (
            <Field label="Valore totale del magazzino €" htmlFor="inv-v" hint="Oppure inserisci gli articoli uno per uno.">
              <input id="inv-v" inputMode="decimal" className="input max-w-xs" value={value} disabled={!editable} onChange={(e) => setValue(e.target.value)} />
            </Field>
          )}
          {rows.map((r, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr_auto]">
              <input aria-label="Articolo" placeholder="Articolo" className="input" value={r.description} disabled={!editable} onChange={(e) => setRow(i, { description: e.target.value })} />
              <input aria-label="Quantità" placeholder="Quantità" inputMode="decimal" className="input num text-right" value={r.qty} disabled={!editable} onChange={(e) => setRow(i, { qty: e.target.value })} />
              <input aria-label="Costo unitario" placeholder="Costo unitario €" inputMode="decimal" className="input num text-right" value={r.unit_cost} disabled={!editable} onChange={(e) => setRow(i, { unit_cost: e.target.value })} />
              {editable && <Button variant="ghost" className="text-warn-text" aria-label="Togli articolo" onClick={() => setRows((rs) => rs.filter((_, n) => n !== i))}>✕</Button>}
            </div>
          ))}
          {editable && <Button variant="secondary" className="self-start" onClick={() => setRows((rs) => [...rs, { description: "", qty: "", unit_cost: "" }])}>Aggiungi articolo</Button>}
          <p className="text-xs text-muted">Valuta le merci al costo d'acquisto (o al valore di realizzo se più basso). La registrazione si storna da sola il 1° gennaio.</p>
          <ErrorBox>{error}</ErrorBox>
        </div>
      </Card>
    </section>
  );
}
