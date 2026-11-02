import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, Stat, useToast } from "../../components/ui";
import { YearSelect, centsToInput, useCostCenters } from "../../lib/accounting";
import { api, errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { eur, fmtDate } from "../../lib/format";

export default function Assets() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const { can } = useAuth();
  const toast = useToast();
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState(null);
  const [schedule, setSchedule] = useState(null);
  const [busy, setBusy] = useState(false);
  const [costCenters] = useCostCenters(company?.id);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const res = await api.get(`/companies/${company.id}/assets`, { params: { year } });
      setData(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, year]);
  useEffect(() => { setData(null); load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;
  const canEdit = can(company.id, "manage_accounting");

  const post = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/companies/${company.id}/depreciation`, null, { params: { year } });
      toast(`Ammortamenti ${year} registrati: ${eur(r.data.total_cents)}`);
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy(false);
    }
  };
  const remove = async (a) => {
    if (!window.confirm(`Eliminare il cespite "${a.name}"? Le registrazioni già fatte restano.`)) return;
    try {
      await api.delete(`/assets/${a.id}`);
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };

  return (
    <>
      <PageHeader title="Cespiti e ammortamenti" subtitle="Registro dei beni strumentali con piano di ammortamento"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />
          <YearSelect value={year} onChange={setYear} />
          {canEdit && <Button variant="secondary" onClick={() => setEdit({})}>Nuovo cespite</Button>}
          {canEdit && <Button onClick={post} loading={busy}>{data?.posted ? "Aggiorna ammortamenti" : "Registra ammortamenti"} {year}</Button>}
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-4">
            <Stat label="Costo storico" value={eur(data.totals.cost)} />
            <Stat label="Fondo ammortamento" value={eur(data.totals.fund)} sub={`al 31/12/${year}`} />
            <Stat label="Valore residuo" value={eur(data.totals.cost - data.totals.fund)} />
            <Stat label={`Quota ${year}`} value={eur(data.totals.quota)}
              sub={data.posted ? `Registrata il ${fmtDate(data.posted.date, { year: true })}` : "Non ancora registrata"} />
          </div>
          <Card padded={false}>
            {data.items.length === 0 ? (
              <Empty title="Nessun cespite" text="Aggiungi i beni a mano oppure trasforma una fattura di acquisto in cespite dalla pagina Fatture." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] text-sm">
                  <thead>
                    <tr className="table-head text-left">
                      <th className="px-5 py-3">Bene</th>
                      <th className="py-3 pr-3">Acquisto</th>
                      <th className="py-3 pr-3 text-right">Aliquota</th>
                      <th className="py-3 pr-3 text-right">Costo</th>
                      <th className="py-3 pr-3 text-right">Quota {year}</th>
                      <th className="py-3 pr-3 text-right">Fondo</th>
                      <th className="py-3 pr-3 text-right">Residuo</th>
                      <th className="py-3 pr-5"><span className="sr-only">Azioni</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((a) => (
                      <tr key={a.id} className="border-b border-soft">
                        <td className="px-5 py-2.5"><b>{a.name}</b><span className="block text-xs text-muted">{a.category_label}{a.supplier ? ` · ${a.supplier}` : ""}
                          {costCenters.find((c) => c.id === a.cost_center_id) ? ` · ${costCenters.find((c) => c.id === a.cost_center_id).name}` : ""}</span>
                          {a.residual_cents === 0 && <Badge className="mt-1">Completamente ammortizzato</Badge>}
                          {a.disposed_date && <Badge tone="orange" className="mt-1">Dismesso il {fmtDate(a.disposed_date, { year: true })}</Badge>}
                        </td>
                        <td className="whitespace-nowrap py-2.5 pr-3">{fmtDate(a.purchase_date, { year: true })}</td>
                        <td className="num py-2.5 pr-3 text-right">{String(a.rate).replace(".", ",")}%</td>
                        <td className="num py-2.5 pr-3 text-right">{eur(a.cost_cents)}</td>
                        <td className="num py-2.5 pr-3 text-right font-semibold">{eur(a.quota_cents)}</td>
                        <td className="num py-2.5 pr-3 text-right">{eur(a.fund_cents)}</td>
                        <td className="num py-2.5 pr-3 text-right">{eur(a.residual_cents)}</td>
                        <td className="py-2.5 pr-5">
                          <div className="flex justify-end gap-1">
                            <Button variant="ghost" className="min-h-[36px] px-2" onClick={() => setSchedule(a)}>Piano</Button>
                            {canEdit && <Button variant="ghost" className="min-h-[36px] px-2" onClick={() => setEdit(a)}>Modifica</Button>}
                            {canEdit && <Button variant="ghost" className="min-h-[36px] px-2 text-warn-text" onClick={() => remove(a)}>Elimina</Button>}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          <Notice>
            Aliquote dei coefficienti ministeriali più comuni, con la quota dimezzata nel primo anno. L'aliquota si può cambiare per ogni bene.
            «Registra ammortamenti» crea (o aggiorna) un'unica registrazione al 31/12 con le quote di tutti i beni.
          </Notice>
        </>
      )}
      <AssetModal asset={edit} categories={data?.categories || {}} costCenters={costCenters} companyId={company.id}
        onClose={() => setEdit(null)} onSaved={() => { toast("Cespite salvato"); load(); }} />
      <ScheduleModal asset={schedule} onClose={() => setSchedule(null)} />
    </>
  );
}

function AssetModal({ asset, categories, costCenters, companyId, onClose, onSaved }) {
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!asset) return;
    setError("");
    setForm({
      name: asset.name || "", category: asset.category || "elettroniche", cost: centsToInput(asset.cost_cents),
      purchase_date: asset.purchase_date || new Date().toISOString().slice(0, 10), rate: asset.rate ?? "",
      first_year_half: asset.first_year_half ?? true, accumulated_before: centsToInput(asset.accumulated_before_cents),
      accumulated_before_year: asset.accumulated_before_year || "", disposed_date: asset.disposed_date || "", cost_center_id: asset.cost_center_id || "",
    });
  }, [asset]);
  if (!asset || !form) return null;
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const save = async () => {
    setBusy(true);
    try {
      const body = { ...form, rate: form.rate === "" ? null : Number(String(form.rate).replace(",", ".")),
        accumulated_before_year: form.accumulated_before_year ? Number(form.accumulated_before_year) : null,
        disposed_date: form.disposed_date || null, cost_center_id: form.cost_center_id || null };
      if (asset.id) await api.put(`/assets/${asset.id}`, body);
      else await api.post(`/companies/${companyId}/assets`, body);
      onSaved();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} title={asset.id ? "Modifica cespite" : "Nuovo cespite"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save} loading={busy}>Salva</Button></>}>
      <div className="flex flex-col gap-3">
        <Field label="Descrizione" htmlFor="as-name"><input id="as-name" className="input" value={form.name} onChange={(e) => set({ name: e.target.value })} /></Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Categoria" htmlFor="as-cat">
            <select id="as-cat" className="input" value={form.category} onChange={(e) => set({ category: e.target.value, rate: "" })}>
              {Object.entries(categories).map(([k, v]) => <option key={k} value={k}>{v.label} ({String(v.rate).replace(".", ",")}%)</option>)}
            </select>
          </Field>
          <Field label="Aliquota %" htmlFor="as-rate" hint="Vuoto = quella della categoria">
            <input id="as-rate" inputMode="decimal" className="input" value={form.rate} onChange={(e) => set({ rate: e.target.value })} />
          </Field>
          <Field label="Costo (imponibile) €" htmlFor="as-cost"><input id="as-cost" inputMode="decimal" className="input" value={form.cost} onChange={(e) => set({ cost: e.target.value })} /></Field>
          <Field label="Data di acquisto" htmlFor="as-date"><input id="as-date" type="date" className="input" value={form.purchase_date} onChange={(e) => set({ purchase_date: e.target.value })} /></Field>
          <Field label="Già ammortizzato €" htmlFor="as-before" hint="Per beni acquistati prima di usare il programma">
            <input id="as-before" inputMode="decimal" className="input" value={form.accumulated_before} onChange={(e) => set({ accumulated_before: e.target.value })} />
          </Field>
          <Field label="…fino all'anno" htmlFor="as-before-y"><input id="as-before-y" inputMode="numeric" className="input" value={form.accumulated_before_year} onChange={(e) => set({ accumulated_before_year: e.target.value })} /></Field>
          <Field label="Data di dismissione" htmlFor="as-disp"><input id="as-disp" type="date" className="input" value={form.disposed_date} onChange={(e) => set({ disposed_date: e.target.value })} /></Field>
          <Field label="Centro di costo" htmlFor="as-cc">
            <select id="as-cc" className="input" value={form.cost_center_id} onChange={(e) => set({ cost_center_id: e.target.value })}>
              <option value="">Nessuno</option>
              {costCenters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4" checked={form.first_year_half} onChange={(e) => set({ first_year_half: e.target.checked })} />
          Quota dimezzata nel primo anno
        </label>
        <ErrorBox>{error}</ErrorBox>
      </div>
    </Modal>
  );
}

function ScheduleModal({ asset, onClose }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    if (!asset) return;
    setRows(null);
    api.get(`/assets/${asset.id}/schedule`).then((r) => setRows(r.data.rows || r.data)).catch(() => setRows([]));
  }, [asset]);
  if (!asset) return null;
  return (
    <Modal open onClose={onClose} title={`Piano di ammortamento · ${asset.name}`}>
      {!rows ? <Loading /> : (
        <table className="w-full text-sm">
          <thead>
            <tr className="table-head text-left">
              <th className="py-2 pr-3">Anno</th>
              <th className="py-2 pr-3 text-right">Quota</th>
              <th className="py-2 pr-3 text-right">Fondo</th>
              <th className="py-2 text-right">Residuo</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.year} className="border-b border-soft">
                <td className="py-2 pr-3 font-semibold">{r.year}</td>
                <td className="num py-2 pr-3 text-right">{eur(r.quota_cents)}</td>
                <td className="num py-2 pr-3 text-right">{eur(r.fund_cents)}</td>
                <td className="num py-2 text-right">{eur(r.residual_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  );
}
