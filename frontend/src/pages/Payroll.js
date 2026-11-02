import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, Stat, useToast } from "../components/ui";
import { centsToInput, parseEuro, useCostCenters } from "../lib/accounting";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { eur } from "../lib/format";

const MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const label = (m) => `${MONTHS[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}`;
const FIELDS = [
  ["lordo", "Retribuzione lorda"], ["contributi_ditta", "Contributi INPS a carico azienda"],
  ["contributi_dipendente", "Contributi a carico dei dipendenti"], ["irpef", "Ritenute IRPEF e addizionali"],
  ["altre_trattenute", "Altre trattenute (sindacati, cessioni…)"], ["netto", "Netto da pagare"], ["tfr", "TFR maturato nel mese"],
];

export default function Payroll() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const { can } = useAuth();
  const toast = useToast();
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState(null);
  const [costCenters] = useCostCenters(company?.id);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const r = await api.get(`/companies/${company.id}/payrolls`, { params: { year } });
      setData(r.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, year]);
  useEffect(() => { setData(null); load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;
  const canEdit = can(company.id, "manage_payroll");
  const remove = async (p) => {
    if (!window.confirm(`Eliminare le paghe di ${label(p.month)}? Si cancellano anche la registrazione e le scadenze non pagate.`)) return;
    try {
      await api.delete(`/payrolls/${p.id}`);
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };
  const t = data?.totals;

  return (
    <>
      <PageHeader title="Paghe" subtitle="Dal riepilogo del consulente del lavoro: registrazione degli stipendi, netto da pagare e F24"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />
          <label htmlFor="py" className="sr-only">Anno</label>
          <select id="py" className="input w-auto" value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {[0, 1, 2].map((n) => <option key={n} value={new Date().getFullYear() - n}>{new Date().getFullYear() - n}</option>)}
          </select>
          {canEdit && <Button onClick={() => setEdit({})}>Inserisci un mese</Button>}
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-4">
            <Stat label={`Costo del personale ${year}`} value={eur(t.lordo + t.contributi_ditta + t.tfr)} sub="Lordo + contributi azienda + TFR" />
            <Stat label="Netto pagato ai dipendenti" value={eur(t.netto)} />
            <Stat label="Versato con F24" value={eur(t.irpef + t.contributi_ditta + t.contributi_dipendente)} sub="IRPEF e contributi INPS" />
          </div>
          <Card padded={false}>
            {data.items.length === 0 ? (
              <Empty title="Nessun mese inserito" text="Inserisci i totali del riepilogo paghe (o carica il PDF): il programma registra gli stipendi e crea le scadenze." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] text-sm">
                  <thead>
                    <tr className="table-head text-left">
                      <th className="px-5 py-3">Mese</th>
                      <th className="py-3 pr-3 text-right">Lordo</th>
                      <th className="py-3 pr-3 text-right">Contributi azienda</th>
                      <th className="py-3 pr-3 text-right">IRPEF</th>
                      <th className="py-3 pr-3 text-right">Netto</th>
                      <th className="py-3 pr-3 text-right">TFR</th>
                      <th className="py-3 pr-3 text-right">Costo totale</th>
                      <th className="py-3 pr-5"><span className="sr-only">Azioni</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((p) => (
                      <tr key={p.id} className="border-b border-soft">
                        <td className="px-5 py-2.5 font-semibold capitalize">{label(p.month)}<span className="block text-xs font-normal normal-case text-muted">{p.employees ? `${p.employees} dipendenti` : ""}</span></td>
                        <td className="num py-2.5 pr-3 text-right">{eur(p.lordo_cents)}</td>
                        <td className="num py-2.5 pr-3 text-right">{eur(p.contributi_ditta_cents)}</td>
                        <td className="num py-2.5 pr-3 text-right">{eur(p.irpef_cents)}</td>
                        <td className="num py-2.5 pr-3 text-right font-semibold">{eur(p.netto_cents)}</td>
                        <td className="num py-2.5 pr-3 text-right">{eur(p.tfr_cents)}</td>
                        <td className="num py-2.5 pr-3 text-right font-bold">{eur(p.lordo_cents + p.contributi_ditta_cents + p.tfr_cents)}</td>
                        <td className="py-2.5 pr-5">
                          {canEdit && (
                            <div className="flex justify-end gap-1">
                              <Button variant="ghost" className="min-h-[36px] px-2" onClick={() => setEdit(p)}>Modifica</Button>
                              <Button variant="ghost" className="min-h-[36px] px-2 text-warn-text" onClick={() => remove(p)}>Elimina</Button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          <Notice>
            Per ogni mese il programma crea: la registrazione degli stipendi in prima nota, la scadenza del netto da pagare e
            l'F24 del 16 del mese dopo (IRPEF e contributi). Quando riconcili i bonifici, chiudono i debiti verso dipendenti, INPS ed Erario.
            I cedolini restano del consulente del lavoro.
          </Notice>
        </>
      )}
      <PayrollModal value={edit} companyId={company.id} costCenters={costCenters} onClose={() => setEdit(null)}
        onSaved={() => { toast("Paghe registrate"); load(); }} />
    </>
  );
}

function PayrollModal({ value, companyId, costCenters, onClose, onSaved }) {
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const fileRef = useRef(null);

  useEffect(() => {
    if (!value) return;
    setError("");
    const prev = new Date(new Date().getFullYear(), new Date().getMonth() - 1, 15).toISOString().slice(0, 7);
    setForm({
      month: value.month || prev, employees: value.employees || "", pay_date: value.pay_date || "", cost_center_id: value.cost_center_id || "",
      ...Object.fromEntries(FIELDS.map(([k]) => [k, centsToInput(value[`${k}_cents`])])),
    });
  }, [value]);

  const check = useMemo(() => {
    if (!form) return null;
    const v = Object.fromEntries(FIELDS.map(([k]) => [k, parseEuro(form[k]) || 0]));
    return { diff: v.netto + v.irpef + v.contributi_dipendente + v.altre_trattenute - v.lordo, cost: v.lordo + v.contributi_ditta + v.tfr,
      f24: v.irpef + v.contributi_ditta + v.contributi_dipendente };
  }, [form]);

  if (!value || !form) return null;
  const save = async () => {
    setBusy("save");
    try {
      const body = { ...form, employees: form.employees ? Number(form.employees) : null, pay_date: form.pay_date || null, cost_center_id: form.cost_center_id || null };
      if (value.id) await api.put(`/payrolls/${value.id}`, body);
      else await api.post(`/companies/${companyId}/payrolls`, body);
      onSaved();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };
  const read = async (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    setBusy("read");
    try {
      const r = await api.post(`/companies/${companyId}/payrolls/read`, fd);
      if (r.data.read) setForm((f) => ({ ...f, ...Object.fromEntries(Object.entries(r.data.values).filter(([, v]) => v !== null && v !== undefined)) }));
      else setError(r.data.message);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <Modal open wide onClose={onClose} title={value.id ? `Paghe di ${label(value.month)}` : "Paghe del mese"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save} loading={busy === "save"} disabled={Math.abs(check.diff) > 100}>Registra</Button></>}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-soft p-3 text-sm">
          <input ref={fileRef} type="file" accept="application/pdf,image/*" className="hidden" onChange={(e) => read(e.target.files?.[0])} />
          <Button variant="secondary" loading={busy === "read"} onClick={() => fileRef.current?.click()}>Leggi dal PDF del consulente</Button>
          <span className="text-muted">Usa il «riepilogo contabile» o il prospetto paghe del mese. Controlla sempre i numeri letti.</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Mese" htmlFor="pm"><input id="pm" type="month" className="input" value={form.month} onChange={(e) => setForm({ ...form, month: e.target.value })} /></Field>
          <Field label="Dipendenti" htmlFor="pe"><input id="pe" inputMode="numeric" className="input" value={form.employees} onChange={(e) => setForm({ ...form, employees: e.target.value })} /></Field>
          <Field label="Data pagamento stipendi" htmlFor="pd"><input id="pd" type="date" className="input" value={form.pay_date} onChange={(e) => setForm({ ...form, pay_date: e.target.value })} /></Field>
          <Field label="Centro di costo" htmlFor="pc">
            <select id="pc" className="input" value={form.cost_center_id} onChange={(e) => setForm({ ...form, cost_center_id: e.target.value })}>
              <option value="">Nessuno</option>
              {costCenters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {FIELDS.map(([k, l]) => (
            <Field key={k} label={`${l} €`} htmlFor={`pf-${k}`}>
              <input id={`pf-${k}`} inputMode="decimal" className="input num text-right" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
            </Field>
          ))}
        </div>
        <div className="num flex flex-wrap gap-4 rounded-lg border border-line p-3 text-sm">
          <span>Costo per l'azienda <b>{eur(check.cost)}</b></span>
          <span>F24 del 16 <b>{eur(check.f24)}</b></span>
          <span className={Math.abs(check.diff) > 100 ? "font-bold text-warn-amount" : "font-semibold text-accent-dark"}>
            {Math.abs(check.diff) > 100 ? `Netto + trattenute non corrisponde al lordo (differenza ${eur(Math.abs(check.diff))})` : "Lordo e netto coerenti"}
          </span>
        </div>
        <ErrorBox>{error}</ErrorBox>
      </div>
    </Modal>
  );
}
