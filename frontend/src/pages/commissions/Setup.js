import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, Tabs, useToast } from "../../components/ui";
import { centsToInput } from "../../lib/accounting";
import { api, errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { eur } from "../../lib/format";
import { KIND, STATUS, monthLabel } from "./shared";

export default function CommissionSetup() {
  const [company, setCompany] = usePageCompany("view_commissions");
  const [tab, setTab] = useState("listino");
  if (!company) return <Empty title="Nessuna azienda con accesso alle provvigioni" />;
  return (
    <>
      <PageHeader title="Impostazioni provvigioni" subtitle="Partner, listino dei compensi, strutture e dipendenti, gare"
        actions={<CompanyPicker value={company.id} onChange={setCompany} permission="view_commissions" />} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "listino", label: "Listino" }, { id: "persone", label: "Strutture e dipendenti" },
        { id: "gare", label: "Gare" }, { id: "partner", label: "Partner e stati" },
      ]} />
      {tab === "listino" && <Offers company={company} />}
      {tab === "persone" && <People company={company} />}
      {tab === "gare" && <Contests company={company} />}
      {tab === "partner" && <Partners company={company} />}
    </>
  );
}

function usePartners(companyId) {
  const [items, setItems] = useState([]);
  const reload = useCallback(() => api.get(`/companies/${companyId}/commission-partners`).then((r) => setItems(r.data)).catch(() => {}), [companyId]);
  useEffect(() => { reload(); }, [reload]);
  return [items, reload];
}

// ---------------- listino

function Offers({ company }) {
  const { can } = useAuth();
  const toast = useToast();
  const [partners] = usePartners(company.id);
  const [data, setData] = useState(null);
  const [edit, setEdit] = useState(null);
  const canEdit = can(company.id, "manage_commissions");
  const load = useCallback(() => api.get(`/companies/${company.id}/commission-offers`).then((r) => setData(r.data)).catch(() => {}), [company.id]);
  useEffect(() => { load(); }, [load]);
  if (!data) return <Loading />;
  const pname = (id) => partners.find((p) => p.id === id)?.name || "";
  const remove = async (o) => {
    if (!window.confirm(`Togliere «${o.name}» dal listino?`)) return;
    await api.delete(`/commission-offers/${o.id}`).catch((e) => toast(errorMessage(e), "orange"));
    load();
  };
  return (
    <>
      {data.unpriced.length > 0 && (
        <Card title="Offerte nei file dei partner che non sono nel listino" subtitle="Senza listino la provvigione è zero e il rendiconto non si approva">
          <ul className="flex flex-col divide-y divide-soft">
            {data.unpriced.map((u) => (
              <li key={`${u.partner_id}-${u.offer}`} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                <span><b>{u.partner}</b> · {u.offer || "(senza nome)"} <span className="text-muted">· {u.count} pratiche</span></span>
                {canEdit && <Button variant="secondary" className="min-h-[36px]" onClick={() => setEdit({ partner_id: u.partner_id, name: u.offer, match: u.offer })}>Aggiungi al listino</Button>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card padded={false} title="Listino" subtitle="Importo fisso per ogni attivazione. «Riconosce» è il testo che deve comparire nell'offerta del file del partner."
        actions={canEdit && <Button onClick={() => setEdit({ partner_id: partners[0]?.id })}>Nuova offerta</Button>}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="table-head text-left">
                <th className="px-5 py-3">Partner e offerta</th>
                <th className="py-3 pr-3">Riconosce</th>
                <th className="py-3 pr-3 text-right">Ci riconosce il partner</th>
                <th className="py-3 pr-3 text-right">Alla struttura</th>
                <th className="py-3 pr-3 text-right">Al dipendente</th>
                <th className="py-3 pr-5"><span className="sr-only">Azioni</span></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((o) => (
                <tr key={o.id} className={`border-b border-soft ${o.active ? "" : "opacity-50"}`}>
                  <td className="px-5 py-2.5"><b>{o.name}</b><span className="block text-xs text-muted">{pname(o.partner_id)}</span></td>
                  <td className="py-2.5 pr-3 font-mono text-xs">{o.match}</td>
                  <td className="num py-2.5 pr-3 text-right">{eur(o.revenue_cents)}</td>
                  <td className="num py-2.5 pr-3 text-right font-semibold">{eur(o.payout_struttura_cents)}</td>
                  <td className="num py-2.5 pr-3 text-right font-semibold">{eur(o.payout_dipendente_cents)}</td>
                  <td className="py-2.5 pr-5 text-right">
                    {canEdit && <><Button variant="ghost" className="min-h-[36px] px-2" onClick={() => setEdit(o)}>Modifica</Button>
                      <Button variant="ghost" className="min-h-[36px] px-2 text-warn-text" onClick={() => remove(o)}>Elimina</Button></>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.items.length === 0 && <Empty title="Listino vuoto" />}
        </div>
      </Card>
      <OfferModal value={edit} partners={partners} companyId={company.id} onClose={() => setEdit(null)} onSaved={() => { toast("Listino aggiornato"); load(); }} />
    </>
  );
}

function OfferModal({ value, partners, companyId, onClose, onSaved }) {
  const [f, setF] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!value) return;
    setError("");
    setF({ partner_id: value.partner_id || partners[0]?.id || "", name: value.name || "", match: value.match || "",
      revenue: centsToInput(value.revenue_cents), payout_struttura: centsToInput(value.payout_struttura_cents),
      payout_dipendente: centsToInput(value.payout_dipendente_cents), active: value.active ?? true });
  }, [value, partners]);
  if (!value || !f) return null;
  const save = async () => {
    try {
      const body = { ...f, revenue: f.revenue || "0", payout_struttura: f.payout_struttura || "0", payout_dipendente: f.payout_dipendente || "0" };
      if (value.id) await api.put(`/commission-offers/${value.id}`, body);
      else await api.post(`/companies/${companyId}/commission-offers`, body);
      onSaved();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <Modal open onClose={onClose} title={value.id ? "Modifica offerta" : "Nuova offerta nel listino"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save}>Salva</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Partner" htmlFor="of-p">
          <select id="of-p" className="input" value={f.partner_id} onChange={set("partner_id")}>{partners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        </Field>
        <Field label="Nome" htmlFor="of-n"><input id="of-n" className="input" value={f.name} onChange={set("name")} /></Field>
        <div className="sm:col-span-2">
          <Field label="Riconosce" htmlFor="of-m" hint="Testo che deve comparire nell'offerta del file (maiuscole indifferenti). Se più offerte corrispondono vince la più precisa.">
            <input id="of-m" className="input" value={f.match} onChange={set("match")} />
          </Field>
        </div>
        <Field label="Ci riconosce il partner €" htmlFor="of-r"><input id="of-r" inputMode="decimal" className="input" value={f.revenue} onChange={set("revenue")} /></Field>
        <Field label="Provvigione alla struttura €" htmlFor="of-s"><input id="of-s" inputMode="decimal" className="input" value={f.payout_struttura} onChange={set("payout_struttura")} /></Field>
        <Field label="Bonus al dipendente €" htmlFor="of-d"><input id="of-d" inputMode="decimal" className="input" value={f.payout_dipendente} onChange={set("payout_dipendente")} /></Field>
        <label className="flex items-center gap-2 self-end pb-3 text-sm"><input type="checkbox" className="h-4 w-4" checked={f.active} onChange={set("active")} /> Attiva</label>
        <div className="sm:col-span-2"><ErrorBox>{error}</ErrorBox></div>
      </div>
    </Modal>
  );
}

// ---------------- strutture e dipendenti

function People({ company }) {
  const { can, companies } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [edit, setEdit] = useState(null);
  const canEdit = can(company.id, "manage_commissions");
  const load = useCallback(() => api.get(`/companies/${company.id}/commission-beneficiaries`).then((r) => setData(r.data)).catch(() => {}), [company.id]);
  useEffect(() => { load(); }, [load]);
  if (!data) return <Loading />;
  const remove = async (b) => {
    if (!window.confirm(`Eliminare ${b.name}?`)) return;
    try {
      await api.delete(`/commission-beneficiaries/${b.id}`);
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };
  return (
    <>
      {data.unknown_codes.length > 0 && (
        <Notice tone="orange">
          Codici venditore presenti nel backoffice ma non associati a nessuno: {data.unknown_codes.map((u) => `${u.code} (${u.sales} vendite)`).join(", ")}.
          {canEdit && <> Aggiungili a una struttura o a un dipendente esistente, oppure creane uno nuovo.</>}
        </Notice>
      )}
      <Card padded={false} title="Strutture e dipendenti" subtitle="I codici sono quelli del file del backoffice: servono ad abbinare ogni vendita"
        actions={canEdit && <><Button variant="secondary" onClick={() => setEdit({ kind: "dipendente" })}>Nuovo dipendente</Button><Button onClick={() => setEdit({ kind: "struttura" })}>Nuova struttura</Button></>}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="table-head text-left">
                <th className="px-5 py-3">Nome</th><th className="py-3 pr-3">Tipo</th><th className="py-3 pr-3">Codici</th><th className="py-3 pr-3">CF / P.IVA · IBAN</th><th className="py-3 pr-5" />
              </tr>
            </thead>
            <tbody>
              {data.items.map((b) => (
                <tr key={b.id} className={`border-b border-soft ${b.active === false ? "opacity-50" : ""}`}>
                  <td className="px-5 py-2.5 font-semibold">{b.name}{b.group_company_id && <Badge tone="blue" className="ml-2">del gruppo</Badge>}</td>
                  <td className="py-2.5 pr-3">{KIND[b.kind]}</td>
                  <td className="py-2.5 pr-3 font-mono text-xs">{b.codes.join(", ")}</td>
                  <td className="py-2.5 pr-3 text-xs text-muted">{b.tax_code}{b.iban ? ` · ${b.iban}` : ""}</td>
                  <td className="py-2.5 pr-5 text-right">{canEdit && <><Button variant="ghost" className="min-h-[36px] px-2" onClick={() => setEdit(b)}>Modifica</Button>
                    <Button variant="ghost" className="min-h-[36px] px-2 text-warn-text" onClick={() => remove(b)}>Elimina</Button></>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <PersonModal value={edit} companyId={company.id} groupCompanies={companies.filter((c) => c.id !== company.id)} unknown={data.unknown_codes}
        onClose={() => setEdit(null)} onSaved={() => { toast("Salvato: abbinamenti aggiornati"); load(); }} />
    </>
  );
}

function PersonModal({ value, companyId, groupCompanies, unknown, onClose, onSaved }) {
  const [f, setF] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!value) return;
    setError("");
    setF({ kind: value.kind, name: value.name || "", codes: (value.codes || []).join(", "), tax_code: value.tax_code || "", iban: value.iban || "",
      email: value.email || "", group_company_id: value.group_company_id || "", active: value.active ?? true });
  }, [value]);
  if (!value || !f) return null;
  const save = async () => {
    try {
      const body = { ...f, codes: f.codes.split(/[,;\s]+/).filter(Boolean), group_company_id: f.group_company_id || null };
      if (value.id) await api.put(`/commission-beneficiaries/${value.id}`, body);
      else await api.post(`/companies/${companyId}/commission-beneficiaries`, body);
      onSaved();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <Modal open onClose={onClose} title={`${value.id ? "Modifica" : "Nuovo"} ${f.kind === "struttura" ? "struttura" : "dipendente"}`}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save}>Salva</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Tipo" htmlFor="pe-k">
          <select id="pe-k" className="input" value={f.kind} onChange={set("kind")}><option value="struttura">Struttura (azienda collegata)</option><option value="dipendente">Dipendente</option></select>
        </Field>
        <Field label="Nome" htmlFor="pe-n"><input id="pe-n" className="input" value={f.name} onChange={set("name")} /></Field>
        <div className="sm:col-span-2">
          <Field label="Codici venditore (separati da virgola)" htmlFor="pe-c" hint={unknown.length ? `Codici non ancora associati: ${unknown.map((u) => u.code).join(", ")}` : undefined}>
            <input id="pe-c" className="input font-mono" value={f.codes} onChange={set("codes")} />
          </Field>
        </div>
        <Field label={f.kind === "struttura" ? "Partita IVA" : "Codice fiscale"} htmlFor="pe-t"><input id="pe-t" className="input" value={f.tax_code} onChange={set("tax_code")} /></Field>
        {f.kind === "struttura" && <Field label="IBAN per il pagamento" htmlFor="pe-i"><input id="pe-i" className="input" value={f.iban} onChange={set("iban")} /></Field>}
        {f.kind === "struttura" && groupCompanies.length > 0 && (
          <Field label="È un'azienda del gruppo?" htmlFor="pe-g">
            <select id="pe-g" className="input" value={f.group_company_id} onChange={set("group_company_id")}>
              <option value="">No, è esterna</option>
              {groupCompanies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        )}
        <label className="flex items-center gap-2 self-end pb-3 text-sm"><input type="checkbox" className="h-4 w-4" checked={f.active} onChange={set("active")} /> Attivo</label>
        <div className="sm:col-span-2"><ErrorBox>{error}</ErrorBox></div>
      </div>
    </Modal>
  );
}

// ---------------- gare

function Contests({ company }) {
  const { can } = useAuth();
  const toast = useToast();
  const [partners] = usePartners(company.id);
  const [items, setItems] = useState(null);
  const [edit, setEdit] = useState(null);
  const canEdit = can(company.id, "manage_commissions");
  const load = useCallback(() => api.get(`/companies/${company.id}/commission-contests`).then((r) => setItems(r.data)).catch(() => {}), [company.id]);
  useEffect(() => { load(); }, [load]);
  if (!items) return <Loading />;
  return (
    <>
      <Card title="Gare e soglie mensili" subtitle="Premio in base alle attivazioni nette del mese (attivate meno stornate)"
        actions={canEdit && <Button onClick={() => setEdit({})}>Nuova gara</Button>}>
        {items.length === 0 ? <Empty title="Nessuna gara" /> : (
          <ul className="flex flex-col divide-y divide-soft">
            {items.map((g) => (
              <li key={g.id} className={`flex flex-wrap items-start justify-between gap-3 py-3 ${g.active ? "" : "opacity-50"}`}>
                <div className="min-w-0 text-sm">
                  <b>{g.name}</b> <Badge className="ml-1">{g.kind === "tutti" ? "Tutti" : g.kind === "struttura" ? "Strutture" : "Dipendenti"}</Badge>
                  {g.partner_id && <Badge tone="blue" className="ml-1">{partners.find((p) => p.id === g.partner_id)?.name}</Badge>}
                  <span className="block text-muted">Da {monthLabel(g.valid_from)}{g.valid_to ? ` a ${monthLabel(g.valid_to)}` : " (senza scadenza)"}</span>
                  <span className="block">{g.tiers.map((t) => `da ${t.min}: ${eur(t.bonus_cents)}${t.per_activation_cents ? ` + ${eur(t.per_activation_cents)} ad attivazione` : ""}`).join(" · ")}</span>
                </div>
                {canEdit && <div className="flex gap-1"><Button variant="ghost" className="min-h-[36px] px-2" onClick={() => setEdit(g)}>Modifica</Button>
                  <Button variant="ghost" className="min-h-[36px] px-2 text-warn-text" onClick={async () => { await api.delete(`/commission-contests/${g.id}`); load(); }}>Elimina</Button></div>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <ContestModal value={edit} partners={partners} companyId={company.id} onClose={() => setEdit(null)} onSaved={() => { toast("Gara salvata"); load(); }} />
    </>
  );
}

function ContestModal({ value, partners, companyId, onClose, onSaved }) {
  const [f, setF] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!value) return;
    setError("");
    setF({ name: value.name || "", kind: value.kind || "tutti", partner_id: value.partner_id || "", valid_from: value.valid_from || new Date().toISOString().slice(0, 7),
      valid_to: value.valid_to || "", active: value.active ?? true,
      tiers: (value.tiers || [{ min: 5, bonus_cents: 0, per_activation_cents: 0 }]).map((t) => ({ min: t.min, bonus: centsToInput(t.bonus_cents), per_activation: centsToInput(t.per_activation_cents) })) });
  }, [value]);
  if (!value || !f) return null;
  const save = async () => {
    try {
      const body = { ...f, partner_id: f.partner_id || null, valid_to: f.valid_to || null,
        tiers: f.tiers.map((t) => ({ min: Number(t.min) || 0, bonus: t.bonus || "0", per_activation: t.per_activation || "0" })) };
      if (value.id) await api.put(`/commission-contests/${value.id}`, body);
      else await api.post(`/companies/${companyId}/commission-contests`, body);
      onSaved();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const setTier = (i, k, v) => setF({ ...f, tiers: f.tiers.map((t, n) => (n === i ? { ...t, [k]: v } : t)) });
  return (
    <Modal open wide onClose={onClose} title={value.id ? "Modifica gara" : "Nuova gara"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save}>Salva</Button></>}>
      <div className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Nome" htmlFor="g-n"><input id="g-n" className="input" value={f.name} onChange={set("name")} /></Field>
          <Field label="Per chi" htmlFor="g-k"><select id="g-k" className="input" value={f.kind} onChange={set("kind")}>
            <option value="tutti">Strutture e dipendenti</option><option value="struttura">Solo strutture</option><option value="dipendente">Solo dipendenti</option></select></Field>
          <Field label="Partner" htmlFor="g-p"><select id="g-p" className="input" value={f.partner_id} onChange={set("partner_id")}>
            <option value="">Tutti i partner</option>{partners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Field label="Dal mese" htmlFor="g-f"><input id="g-f" type="month" className="input" value={f.valid_from} onChange={set("valid_from")} /></Field>
          <Field label="Al mese (facoltativo)" htmlFor="g-t"><input id="g-t" type="month" className="input" value={f.valid_to} onChange={set("valid_to")} /></Field>
          <label className="flex items-center gap-2 self-end pb-3 text-sm"><input type="checkbox" className="h-4 w-4" checked={f.active} onChange={set("active")} /> Attiva</label>
        </div>
        <span className="label">Soglie (vale la più alta raggiunta)</span>
        {f.tiers.map((t, i) => (
          <div key={i} className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
            <Field label="Da attivazioni" htmlFor={`gt-m-${i}`}><input id={`gt-m-${i}`} inputMode="numeric" className="input" value={t.min} onChange={(e) => setTier(i, "min", e.target.value)} /></Field>
            <Field label="Premio fisso €" htmlFor={`gt-b-${i}`}><input id={`gt-b-${i}`} inputMode="decimal" className="input" value={t.bonus} onChange={(e) => setTier(i, "bonus", e.target.value)} /></Field>
            <Field label="+ € per ogni attivazione" htmlFor={`gt-p-${i}`}><input id={`gt-p-${i}`} inputMode="decimal" className="input" value={t.per_activation} onChange={(e) => setTier(i, "per_activation", e.target.value)} /></Field>
            <Button variant="ghost" className="text-warn-text" aria-label="Togli soglia" disabled={f.tiers.length < 2} onClick={() => setF({ ...f, tiers: f.tiers.filter((_, n) => n !== i) })}>✕</Button>
          </div>
        ))}
        <Button variant="secondary" className="self-start" onClick={() => setF({ ...f, tiers: [...f.tiers, { min: "", bonus: "", per_activation: "" }] })}>Aggiungi soglia</Button>
        <ErrorBox>{error}</ErrorBox>
      </div>
    </Modal>
  );
}

// ---------------- partner e stati

function Partners({ company }) {
  const { can } = useAuth();
  const toast = useToast();
  const [partners, reload] = usePartners(company.id);
  const [edit, setEdit] = useState(null);
  const [statuses, setStatuses] = useState(null);
  const [payDay, setPayDay] = useState(15);
  const canEdit = can(company.id, "manage_commissions");
  useEffect(() => { api.get(`/companies/${company.id}/commission-settings`).then((r) => setPayDay(r.data.pay_day)).catch(() => {}); }, [company.id]);
  const savePay = async () => {
    try {
      await api.put(`/companies/${company.id}/commission-settings`, { pay_day: Number(payDay) });
      toast("Salvato");
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };
  return (
    <>
      <Card padded={false} title="Partner" subtitle="Periodo di storno: se il cliente cessa entro questi mesi dall'attivazione, la provvigione si recupera"
        actions={canEdit && <Button onClick={() => setEdit({})}>Nuovo partner</Button>}>
        <ul className="divide-y divide-soft">
          {partners.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm">
              <span><b>{p.name}</b><span className="block text-muted">Storno entro {p.chargeback_months} mesi · {p.mapping ? "formato del file memorizzato" : "formato del file non ancora visto"}</span></span>
              <span className="flex gap-1">
                <Button variant="secondary" className="min-h-[36px]" onClick={() => setStatuses(p)}>Stati</Button>
                {canEdit && <Button variant="ghost" className="min-h-[36px] px-2" onClick={() => setEdit(p)}>Modifica</Button>}
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Pagamento delle strutture">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Giorno del mese successivo" htmlFor="pd"><input id="pd" inputMode="numeric" className="input w-24" value={payDay} disabled={!canEdit} onChange={(e) => setPayDay(e.target.value)} /></Field>
          {canEdit && <Button variant="secondary" onClick={savePay}>Salva</Button>}
        </div>
        <p className="mt-2 text-xs text-muted">Data di scadenza dei pagamenti creati nello Scadenzario quando approvi i rendiconti.</p>
      </Card>
      <PartnerModal value={edit} companyId={company.id} onClose={() => setEdit(null)} onSaved={() => { toast("Partner salvato"); reload(); }} />
      <StatusModal partner={statuses} canEdit={canEdit} onClose={() => setStatuses(null)} onSaved={(n) => toast(`Stati salvati: ${n} pratiche aggiornate`)} />
    </>
  );
}

function PartnerModal({ value, companyId, onClose, onSaved }) {
  const [f, setF] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { if (value) { setF({ name: value.name || "", chargeback_months: value.chargeback_months ?? 6 }); setError(""); } }, [value]);
  if (!value || !f) return null;
  const save = async () => {
    try {
      const body = { name: f.name, chargeback_months: Number(f.chargeback_months) || 0 };
      if (value.id) await api.put(`/commission-partners/${value.id}`, body);
      else await api.post(`/companies/${companyId}/commission-partners`, body);
      onSaved();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  return (
    <Modal open onClose={onClose} title={value.id ? "Modifica partner" : "Nuovo partner"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save}>Salva</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Nome" htmlFor="pa-n"><input id="pa-n" className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Periodo di storno (mesi)" htmlFor="pa-c"><input id="pa-c" inputMode="numeric" className="input" value={f.chargeback_months} onChange={(e) => setF({ ...f, chargeback_months: e.target.value })} /></Field>
        <div className="sm:col-span-2"><ErrorBox>{error}</ErrorBox></div>
      </div>
    </Modal>
  );
}

function StatusModal({ partner, canEdit, onClose, onSaved }) {
  const [data, setData] = useState(null);
  const [map, setMap] = useState({});
  const [error, setError] = useState("");
  useEffect(() => {
    if (!partner) return;
    setData(null);
    api.get(`/commission-partners/${partner.id}/statuses`).then((r) => {
      setData(r.data);
      setMap(Object.fromEntries(r.data.rows.map((x) => [x.raw, x.status || ""])));
    }).catch((e) => setError(errorMessage(e)));
  }, [partner]);
  if (!partner) return null;
  const save = async () => {
    try {
      const r = await api.put(`/commission-partners/${partner.id}/statuses`, { status_map: Object.fromEntries(Object.entries(map).map(([k, v]) => [k, v || null])) });
      onSaved(r.data.updated);
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  return (
    <Modal open onClose={onClose} title={`Stati di ${partner.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Chiudi</Button>{canEdit && <Button onClick={save}>Salva</Button>}</>}>
      {!data ? <Loading /> : (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted">Come leggere gli stati scritti nei file del partner. Quelli comuni li riconosce da solo.</p>
          {data.rows.map((r) => (
            <div key={r.key} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm">
              <span><b>{r.raw}</b> <span className="text-muted">· {r.count} pratiche</span></span>
              <select aria-label={`Stato per ${r.raw}`} className={`input w-auto ${map[r.raw] ? "" : "border-warn"}`} value={map[r.raw] || ""} disabled={!canEdit}
                onChange={(e) => setMap({ ...map, [r.raw]: e.target.value })}>
                <option value="">— da interpretare —</option>
                {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v[0]}</option>)}
              </select>
            </div>
          ))}
          <ErrorBox>{error}</ErrorBox>
        </div>
      )}
    </Modal>
  );
}
