import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, useToast } from "../components/ui";
import { centsToInput } from "../lib/accounting";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { eur, fmtDate } from "../lib/format";

const STATUS = { aperta: ["In corso", "blue"], sospesa: ["Sospesa", "orange"], chiusa: ["Chiusa", "gray"] };

function Bar({ value, over }) {
  const pct = Math.max(0, Math.min(100, (value || 0) * 100));
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-soft">
      <div className={`h-full rounded-full ${over ? "bg-warn" : "bg-accent"}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function Projects() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const { can } = useAuth();
  const toast = useToast();
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState(null);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const r = await api.get(`/companies/${company.id}/projects`);
      setItems(r.data.items);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company]);
  useEffect(() => { setItems(null); load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;
  const canEdit = can(company.id, "manage_accounting");

  return (
    <>
      <PageHeader title="Commesse" subtitle="Ricavi, costi e margine di ogni lavoro, confrontati con il preventivo"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />
          {canEdit && <Button onClick={() => setEdit({})}>Nuova commessa</Button>}
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!items ? <Loading /> : items.length === 0 ? (
        <Card><Empty title="Nessuna commessa" text="Crea una commessa e collegala a fatture, cespiti e registrazioni (campo «centro di costo / commessa»)." /></Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {items.map((p) => (
            <Card key={p.id} title={p.name} subtitle={[p.customer, p.start_date && `dal ${fmtDate(p.start_date, { year: true })}`, p.end_date && `al ${fmtDate(p.end_date, { year: true })}`].filter(Boolean).join(" · ")}
              actions={<>
                <Badge tone={STATUS[p.status]?.[1]}>{STATUS[p.status]?.[0]}</Badge>
                {canEdit && <Button variant="ghost" className="min-h-[36px] px-2" onClick={() => setEdit(p)}>Modifica</Button>}
              </>}>
              <div className="flex flex-col gap-3 text-sm">
                <div className="flex flex-col gap-1">
                  <div className="num flex justify-between"><span>Ricavi</span><span><b>{eur(p.ricavi_cents)}</b> su {eur(p.budget_revenue_cents)}</span></div>
                  <Bar value={p.avanzamento_ricavi} />
                </div>
                <div className="flex flex-col gap-1">
                  <div className="num flex justify-between"><span>Costi</span><span><b>{eur(p.costi_cents)}</b> su {eur(p.budget_cost_cents)}</span></div>
                  <Bar value={p.avanzamento_costi} over={p.fuori_budget} />
                </div>
                <div className="num grid grid-cols-2 gap-3 border-t border-soft pt-3">
                  <div><span className="text-xs text-muted">Margine attuale</span><p className={`text-lg font-bold ${p.margine_cents < 0 ? "text-warn-amount" : ""}`}>{eur(p.margine_cents)}</p></div>
                  <div><span className="text-xs text-muted">Margine previsto</span><p className="text-lg font-bold">{eur(p.margine_previsto_cents)}</p></div>
                </div>
                {p.fuori_budget && <Notice tone="orange">I costi hanno superato il preventivo.</Notice>}
                {p.description && <p className="text-xs text-muted">{p.description}</p>}
              </div>
            </Card>
          ))}
        </div>
      )}
      <ProjectModal value={edit} companyId={company.id} onClose={() => setEdit(null)} onSaved={() => { toast("Commessa salvata"); load(); }} />
    </>
  );
}

function ProjectModal({ value, companyId, onClose, onSaved }) {
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!value) return;
    setError("");
    setForm({ name: value.name || "", customer: value.customer || "", description: value.description || "",
      budget_revenue: centsToInput(value.budget_revenue_cents), budget_cost: centsToInput(value.budget_cost_cents),
      start_date: value.start_date || "", end_date: value.end_date || "", status: value.status || "aperta" });
  }, [value]);
  if (!value || !form) return null;
  const save = async () => {
    try {
      const body = { ...form, start_date: form.start_date || null, end_date: form.end_date || null,
        budget_revenue: form.budget_revenue || "0", budget_cost: form.budget_cost || "0" };
      if (value.id) await api.put(`/projects/${value.id}`, body);
      else await api.post(`/companies/${companyId}/projects`, body);
      onSaved();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  return (
    <Modal open onClose={onClose} title={value.id ? "Modifica commessa" : "Nuova commessa"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save}>Salva</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><Field label="Nome" htmlFor="pj-n"><input id="pj-n" className="input" value={form.name} onChange={set("name")} /></Field></div>
        <Field label="Cliente" htmlFor="pj-c"><input id="pj-c" className="input" value={form.customer} onChange={set("customer")} /></Field>
        <Field label="Stato" htmlFor="pj-s">
          <select id="pj-s" className="input" value={form.status} onChange={set("status")}>
            {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v[0]}</option>)}
          </select>
        </Field>
        <Field label="Ricavi previsti €" htmlFor="pj-r"><input id="pj-r" inputMode="decimal" className="input" value={form.budget_revenue} onChange={set("budget_revenue")} /></Field>
        <Field label="Costi previsti €" htmlFor="pj-k"><input id="pj-k" inputMode="decimal" className="input" value={form.budget_cost} onChange={set("budget_cost")} /></Field>
        <Field label="Inizio" htmlFor="pj-a"><input id="pj-a" type="date" className="input" value={form.start_date} onChange={set("start_date")} /></Field>
        <Field label="Fine prevista" htmlFor="pj-b"><input id="pj-b" type="date" className="input" value={form.end_date} onChange={set("end_date")} /></Field>
        <div className="sm:col-span-2"><Field label="Descrizione" htmlFor="pj-d"><input id="pj-d" className="input" value={form.description} onChange={set("description")} /></Field></div>
        <div className="sm:col-span-2"><ErrorBox>{error}</ErrorBox></div>
      </div>
    </Modal>
  );
}
