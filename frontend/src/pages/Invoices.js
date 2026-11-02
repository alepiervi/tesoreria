import { useCallback, useEffect, useRef, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, Tabs, useToast } from "../components/ui";
import { api, downloadFile, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { INVOICE_STATUS, addDays, eur, fmtDate, todayIso } from "../lib/format";

export default function Invoices() {
  const [company, setCompany] = usePageCompany("view");
  const { can, refreshCounts, user } = useAuth();
  const sdiAuto = Boolean(user?.features?.sdi_auto);
  const toast = useToast();
  const [direction, setDirection] = useState("passiva");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [importResult, setImportResult] = useState(null);
  const [busy, setBusy] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [accountingInv, setAccountingInv] = useState(null);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const params = { direction: direction || undefined, status: status || undefined, q: q || undefined };
      const res = await api.get(`/companies/${company.id}/invoices`, { params });
      setItems(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, direction, status, q]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  if (!company) return <Empty title="Nessuna azienda disponibile" />;
  const canManage = can(company.id, "manage_invoices");
  const canAccounting = can(company.id, "view_accounting");

  const upload = async (files) => {
    if (!files?.length) return;
    const form = new FormData();
    [...files].forEach((f) => form.append("files", f));
    setBusy("import");
    try {
      const res = await api.post(`/companies/${company.id}/invoices/import`, form);
      setImportResult(res.data);
      load();
      refreshCounts();
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const syncSdi = async () => {
    setBusy("sdi");
    try {
      const res = await api.post(`/companies/${company.id}/invoices/sync-sdi`);
      toast(res.data.imported ? `${res.data.imported} nuove fatture ricevute` : "Nessuna nuova fattura");
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
    }
  };

  const remove = async (inv) => {
    if (!window.confirm(`Eliminare la fattura ${inv.number}? Verranno eliminate anche le sue scadenze.`)) return;
    try {
      await api.delete(`/invoices/${inv.id}`);
      toast("Fattura eliminata");
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };

  const totalOpen = (items || []).reduce((s, i) => s + ((i.payable_cents ?? i.total_cents) - (i.paid_cents || 0)), 0);

  return (
    <>
      <PageHeader title="Fatture" subtitle="Fatture elettroniche attive e passive, collegate a scadenze e pagamenti"
        actions={
          <>
            <CompanyPicker value={company.id} onChange={setCompany} />
            {canManage && (
              <>
                <input ref={fileRef} type="file" accept=".xml,application/xml,text/xml" multiple className="sr-only" id="xml-upload"
                  onChange={(e) => upload(e.target.files)} />
                <Button variant="secondary" loading={busy === "import"} onClick={() => fileRef.current?.click()}>Importa XML</Button>
                {sdiAuto && <Button variant="secondary" loading={busy === "sdi"} onClick={syncSdi}>Scarica da SDI</Button>}
                <Button onClick={() => setManualOpen(true)}>+ Nuova fattura</Button>
              </>
            )}
          </>
        } />

      <div className="flex flex-wrap items-center gap-3">
        <Tabs value={direction} onChange={setDirection}
          tabs={[{ id: "passiva", label: "Passive (fornitori)" }, { id: "attiva", label: "Attive (clienti)" }, { id: "", label: "Tutte" }]} />
        <select aria-label="Stato" className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Tutti gli stati</option>
          <option value="open">Da pagare / incassare</option>
          <option value="pagata">Pagate</option>
        </select>
        <label htmlFor="inv-q" className="sr-only">Cerca</label>
        <input id="inv-q" className="input w-auto min-w-[220px] flex-1" placeholder="Numero o controparte…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      <ErrorBox>{error}</ErrorBox>
      {!items ? <Loading /> : (
        <Card padded={false}>
          {items.length === 0 ? (
            <Empty title="Nessuna fattura" text={canManage ? (sdiAuto ? "Importa i file XML dal cassetto fiscale o scarica le fatture dallo SDI." : "Importa i file XML scaricati dal cassetto fiscale o dal tuo gestionale.") : "Non ci sono fatture con questi filtri."} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-sm">
                <thead>
                  <tr className="table-head text-left">
                    <th className="px-5 py-3">Data</th>
                    <th className="py-3 pr-3">Numero</th>
                    <th className="py-3 pr-3">Controparte</th>
                    <th className="py-3 pr-3">Scadenza</th>
                    <th className="py-3 pr-3 text-right">Totale</th>
                    <th className="py-3 pr-3 text-right">Residuo</th>
                    <th className="py-3 pr-3">Stato</th>
                    <th className="py-3 pr-5"><span className="sr-only">Azioni</span></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((i) => {
                    const residual = (i.payable_cents ?? i.total_cents) - (i.paid_cents || 0);
                    const overdue = i.status !== "pagata" && i.due_date < todayIso();
                    return (
                      <tr key={i.id} className="border-b border-soft">
                        <td className="whitespace-nowrap px-5 py-3 text-muted">{fmtDate(i.date, { year: true })}</td>
                        <td className="py-3 pr-3 font-semibold">{i.number}<span className="block text-xs font-normal text-muted">{i.direction === "attiva" ? "Attiva" : "Passiva"} · {i.source === "manuale" ? "inserita a mano" : i.source === "sdi" ? "da SDI" : "da XML"}</span></td>
                        <td className="py-3 pr-3">{i.counterparty_name}<span className="block text-xs text-muted">{i.counterparty_vat}</span></td>
                        <td className="whitespace-nowrap py-3 pr-3">{fmtDate(i.due_date, { year: true })}{overdue && <Badge tone="orange" className="ml-2">Scaduta</Badge>}</td>
                        <td className="num whitespace-nowrap py-3 pr-3 text-right font-semibold">{eur(i.total_cents)}
                          {i.withholding_cents > 0 && <span className="block text-xs font-normal text-muted">ritenuta {eur(i.withholding_cents)}</span>}
                          {i.payable_cents !== undefined && i.payable_cents !== i.total_cents && !i.withholding_cents && <span className="block text-xs font-normal text-muted">split payment</span>}</td>
                        <td className="num whitespace-nowrap py-3 pr-3 text-right">{eur(residual)}</td>
                        <td className="py-3 pr-3"><Badge tone={INVOICE_STATUS[i.status]?.[1]}>{INVOICE_STATUS[i.status]?.[0] || i.status}</Badge></td>
                        <td className="py-3 pr-5">
                          <div className="flex justify-end gap-1">
                            {canAccounting && <Button variant="ghost" className="min-h-[40px] px-2" onClick={() => setAccountingInv(i)}>Contabilità</Button>}
                            {i.has_xml && <Button variant="ghost" className="min-h-[40px] px-2" onClick={() => downloadFile(`/invoices/${i.id}/xml`).catch((e) => toast(errorMessage(e), "orange"))}>XML</Button>}
                            {canManage && !i.paid_cents && <Button variant="ghost" className="min-h-[40px] px-2 text-warn-text" onClick={() => remove(i)}>Elimina</Button>}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={5} className="px-5 py-3 text-right text-xs font-semibold text-muted">Residuo totale delle fatture in elenco</td>
                    <td className="num py-3 pr-3 text-right font-bold">{eur(totalOpen)}</td>
                    <td colSpan={2} />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </Card>
      )}

      <InvoiceAccountingModal invoice={accountingInv} canEdit={can(company.id, "manage_accounting")} companyId={company.id}
        onClose={() => setAccountingInv(null)} onSaved={(msg) => { toast(msg); load(); }} />
      <Modal open={Boolean(importResult)} onClose={() => setImportResult(null)} title="Risultato dell'importazione"
        footer={<Button onClick={() => setImportResult(null)}>Chiudi</Button>}>
        {importResult && (
          <div className="flex flex-col gap-3">
            <Notice>{importResult.imported} fatture nuove importate. Le scadenze sono state create in automatico.</Notice>
            <ul className="flex flex-col divide-y divide-soft text-sm">
              {importResult.results.map((r, n) => (
                <li key={n} className="flex flex-col gap-0.5 py-2">
                  <span className="font-semibold">{r.file}</span>
                  {r.ok ? (
                    <span className="text-muted">
                      {r.created ? "Importata" : "Già presente"}: {r.direction} {r.number} · {r.counterparty} · {eur(r.total_cents)}
                    </span>
                  ) : <span className="text-warn-text">{r.error}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Modal>

      <ManualInvoiceModal open={manualOpen} onClose={() => setManualOpen(false)} companyId={company.id}
        onDone={() => { setManualOpen(false); toast("Fattura inserita"); load(); }} />
    </>
  );
}

function ManualInvoiceModal({ open, onClose, companyId, onDone }) {
  const empty = { direction: "passiva", number: "", date: todayIso(), due_date: addDays(todayIso(), 30), counterparty_name: "", counterparty_vat: "", total: "", iban: "", description: "" };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post(`/companies/${companyId}/invoices`, form);
      setForm(empty);
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Nuova fattura"
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={submit} loading={busy}>Salva</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2"><ErrorBox>{error}</ErrorBox></div>
        <Field label="Tipo" htmlFor="mi-dir">
          <select id="mi-dir" className="input" value={form.direction} onChange={set("direction")}>
            <option value="passiva">Passiva (da un fornitore)</option>
            <option value="attiva">Attiva (a un cliente)</option>
          </select>
        </Field>
        <Field label="Numero" htmlFor="mi-num"><input id="mi-num" className="input" value={form.number} onChange={set("number")} /></Field>
        <Field label="Data" htmlFor="mi-date"><input id="mi-date" type="date" className="input" value={form.date} onChange={set("date")} /></Field>
        <Field label="Scadenza" htmlFor="mi-due"><input id="mi-due" type="date" className="input" value={form.due_date} onChange={set("due_date")} /></Field>
        <Field label={form.direction === "attiva" ? "Cliente" : "Fornitore"} htmlFor="mi-cp"><input id="mi-cp" className="input" value={form.counterparty_name} onChange={set("counterparty_name")} /></Field>
        <Field label="Partita IVA" htmlFor="mi-vat"><input id="mi-vat" className="input" value={form.counterparty_vat} onChange={set("counterparty_vat")} /></Field>
        <Field label="Totale (€, IVA inclusa)" htmlFor="mi-tot"><input id="mi-tot" inputMode="decimal" className="input" placeholder="1.220,00" value={form.total} onChange={set("total")} /></Field>
        {form.direction === "passiva" && (
          <Field label="IBAN del fornitore" htmlFor="mi-iban"><input id="mi-iban" className="input" value={form.iban} onChange={set("iban")} /></Field>
        )}
        <div className="sm:col-span-2">
          <Field label="Descrizione" htmlFor="mi-desc"><input id="mi-desc" className="input" value={form.description} onChange={set("description")} /></Field>
        </div>
      </div>
    </Modal>
  );
}


function InvoiceAccountingModal({ invoice, canEdit, companyId, onClose, onSaved }) {
  const [data, setData] = useState(null);
  const [costCenters, setCostCenters] = useState([]);
  const [account, setAccount] = useState("");
  const [cc, setCc] = useState("");
  const [remember, setRemember] = useState(true);
  const [asset, setAsset] = useState({ open: false, category: "elettroniche", name: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!invoice) return;
    setData(null); setError(""); setAsset({ open: false, category: "elettroniche", name: "" });
    api.get(`/invoices/${invoice.id}/accounting`).then((r) => {
      setData(r.data);
      setAccount(r.data.account_code || "");
      setCc(r.data.cost_center_id || "");
    }).catch((e) => setError(errorMessage(e)));
    api.get(`/companies/${companyId}/cost-centers`).then((r) => setCostCenters(r.data)).catch(() => {});
  }, [invoice, companyId]);

  if (!invoice) return null;
  const passive = invoice.direction === "passiva";
  const save = async () => {
    setBusy(true);
    try {
      if (asset.open) {
        await api.post(`/invoices/${invoice.id}/as-asset`, { category: asset.category, name: asset.name });
        onSaved("Fattura registrata come cespite");
      } else {
        await api.put(`/invoices/${invoice.id}/accounting`, { account_code: account || null, cost_center_id: cc || null, remember_for_supplier: remember });
        onSaved("Registrazione della fattura aggiornata");
      }
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const editable = canEdit && data && !data.locked;

  return (
    <Modal open onClose={onClose} wide title={`Contabilità · fattura ${invoice.number} · ${invoice.counterparty_name}`}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Chiudi</Button>
        {editable && <Button onClick={save} loading={busy}>{asset.open ? "Crea cespite" : "Salva"}</Button>}
      </>}>
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <div className="flex flex-col gap-4">
          {data.locked && <Notice tone="orange">La fattura è in un periodo contabile chiuso: la registrazione non si può più cambiare.</Notice>}
          {editable && !asset.open && (
            <div className="grid gap-3 md:grid-cols-2">
              <Field label={passive ? "Conto di costo" : "Conto di ricavo"} htmlFor="ia-acc" hint="Vuoto = conto predefinito">
                <select id="ia-acc" className="input" value={account} onChange={(e) => setAccount(e.target.value)}>
                  <option value="">Predefinito</option>
                  {data.options.map((o) => <option key={o.code} value={o.code}>{o.code} · {o.name}</option>)}
                </select>
              </Field>
              <Field label="Centro di costo o commessa" htmlFor="ia-cc">
                <select id="ia-cc" className="input" value={cc} onChange={(e) => setCc(e.target.value)}>
                  <option value="">Nessuno</option>
                  {costCenters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </Field>
              {passive && (
                <label className="flex items-center gap-2 text-sm md:col-span-2">
                  <input type="checkbox" className="h-4 w-4" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                  Usa questo conto anche per le prossime fatture di {invoice.counterparty_name}
                </label>
              )}
            </div>
          )}
          {editable && passive && (
            <div className="rounded-lg border border-line p-3">
              <label className="flex items-center gap-2 text-sm font-semibold">
                <input type="checkbox" className="h-4 w-4" checked={asset.open} onChange={(e) => setAsset({ ...asset, open: e.target.checked })} />
                È un bene strumentale da ammortizzare (cespite)
              </label>
              {asset.open && (
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <Field label="Categoria" htmlFor="ia-cat">
                    <select id="ia-cat" className="input" value={asset.category} onChange={(e) => setAsset({ ...asset, category: e.target.value })}>
                      {Object.entries(data.asset_categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                  </Field>
                  <Field label="Descrizione del bene" htmlFor="ia-name"><input id="ia-name" className="input" value={asset.name} onChange={(e) => setAsset({ ...asset, name: e.target.value })} /></Field>
                </div>
              )}
            </div>
          )}
          <div>
            <span className="label">Registrazione in prima nota</span>
            {!data.entry ? <p className="mt-1 text-sm text-muted">Nessuna registrazione.</p> : (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full min-w-[520px] text-sm">
                  <thead>
                    <tr className="table-head text-left">
                      <th className="py-2 pr-3">Conto</th>
                      <th className="py-2 pr-3 text-right">Dare</th>
                      <th className="py-2 text-right">Avere</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.entry.lines.map((l, n) => (
                      <tr key={n} className="border-b border-soft">
                        <td className="py-2 pr-3"><span className="num text-muted">{l.account}</span> {l.account_name}{l.party_name ? <span className="text-xs text-muted"> · {l.party_name}</span> : null}</td>
                        <td className="num py-2 pr-3 text-right">{l.dare ? eur(l.dare) : ""}</td>
                        <td className="num py-2 text-right">{l.avere ? eur(l.avere) : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-xs text-muted">Registrata il {fmtDate(data.entry.date, { year: true })} con causale {data.entry.causale}.</p>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
