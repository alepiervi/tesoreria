import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import NotesDrawer from "../components/NotesDrawer";
import { Amount, Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { TX_STATUS, fmtDate } from "../lib/format";

const PAGE = 50;

export default function Transactions() {
  const [company, setCompany] = usePageCompany("view");
  const { can, refreshCounts, user } = useAuth();
  const toast = useToast();
  const [categories, setCategories] = useState([]);
  const [filters, setFilters] = useState({ q: "", status: "", direction: "", category: "", date_from: "", date_to: "" });
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [notesFor, setNotesFor] = useState(null);
  const [rule, setRule] = useState(null);

  useEffect(() => {
    api.get("/categories").then((r) => setCategories(r.data)).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v));
      const res = await api.get(`/companies/${company.id}/transactions`, { params: { ...params, limit } });
      setData(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, filters, limit]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  if (!company) return <Empty title="Nessuna azienda disponibile" />;
  const canCat = can(company.id, "categorize");
  const canRec = can(company.id, "reconcile");
  const set = (k) => (e) => { setLimit(PAGE); setFilters((f) => ({ ...f, [k]: e.target.value })); };

  const changeCategory = async (tx, category) => {
    try {
      const res = await api.patch(`/transactions/${tx.id}`, { category });
      setData((d) => ({ ...d, items: d.items.map((i) => (i.id === tx.id ? { ...i, category } : i)) }));
      if (res.data.suggested_pattern) {
        setRule({ category, pattern: res.data.suggested_pattern, direction: res.data.direction, all: false });
      }
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };

  const createRule = async () => {
    try {
      const res = await api.post("/category-rules", {
        company_id: rule.all ? null : company.id, pattern: rule.pattern, direction: rule.direction,
        category: rule.category, apply_existing: true,
      });
      toast(`Regola creata${res.data.updated ? `: aggiornati ${res.data.updated} movimenti` : ""}`);
      setRule(null);
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };

  const unmatch = async (tx) => {
    if (!window.confirm("Annullare l'abbinamento? Il movimento tornerà da riconciliare.")) return;
    try {
      await api.post(`/transactions/${tx.id}/unmatch`);
      toast("Abbinamento annullato");
      load();
      refreshCounts();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };

  return (
    <>
      <PageHeader title="Movimenti" subtitle="Tutti i movimenti bancari, con categoria e stato di riconciliazione"
        actions={<CompanyPicker value={company.id} onChange={setCompany} />} />

      <Card>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
          <div className="col-span-full sm:col-span-2">
            <label htmlFor="tx-q" className="sr-only">Cerca</label>
            <input id="tx-q" className="input" placeholder="Cerca nella descrizione…" value={filters.q} onChange={set("q")} />
          </div>
          <select aria-label="Stato" className="input" value={filters.status} onChange={set("status")}>
            <option value="">Tutti gli stati</option>
            {Object.entries(TX_STATUS).map(([k, [label]]) => <option key={k} value={k}>{label}</option>)}
          </select>
          <select aria-label="Entrate o uscite" className="input" value={filters.direction} onChange={set("direction")}>
            <option value="">Entrate e uscite</option>
            <option value="in">Solo entrate</option>
            <option value="out">Solo uscite</option>
          </select>
          <select aria-label="Categoria" className="input" value={filters.category} onChange={set("category")}>
            <option value="">Tutte le categorie</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <input aria-label="Dal" type="date" className="input" value={filters.date_from} onChange={set("date_from")} />
          <input aria-label="Al" type="date" className="input" value={filters.date_to} onChange={set("date_to")} />
        </div>
      </Card>

      {rule && (
        <div className="flex flex-col gap-3 rounded-xl border border-accent-mid bg-accent-soft p-4 text-sm text-accent-dark" role="status">
          <span className="font-semibold">Vuoi che d'ora in poi i movimenti simili vadano sempre in "{rule.category}"?</span>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="rule-pattern">Quando la descrizione contiene</label>
            <input id="rule-pattern" className="input min-h-[40px] w-auto min-w-[220px] flex-1 bg-white" value={rule.pattern}
              onChange={(e) => setRule((r) => ({ ...r, pattern: e.target.value }))} />
          </div>
          {user.is_owner && (
            <label className="flex min-h-[40px] items-center gap-2">
              <input type="checkbox" className="h-[18px] w-[18px]" checked={rule.all} onChange={(e) => setRule((r) => ({ ...r, all: e.target.checked }))} />
              Valida per tutte le aziende del gruppo
            </label>
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={createRule} disabled={rule.pattern.trim().length < 3}>Sì, crea la regola</Button>
            <Button variant="secondary" onClick={() => setRule(null)}>No, solo questo movimento</Button>
          </div>
        </div>
      )}
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <Card padded={false}>
          {data.items.length === 0 ? <Empty title="Nessun movimento" text="Prova a cambiare i filtri." /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-sm">
                <thead>
                  <tr className="table-head text-left">
                    <th className="px-5 py-3">Data</th>
                    <th className="py-3 pr-3">Descrizione</th>
                    <th className="py-3 pr-3">Categoria</th>
                    <th className="py-3 pr-3 text-right">Importo</th>
                    <th className="py-3 pr-3">Stato</th>
                    <th className="py-3 pr-5 text-right"><span className="sr-only">Azioni</span></th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((t) => (
                    <tr key={t.id} className="border-b border-soft align-middle">
                      <td className="whitespace-nowrap px-5 py-3 text-muted">{fmtDate(t.date, { year: true })}</td>
                      <td className="py-3 pr-3">
                        <span className="block">{t.description}</span>
                        <span className="block text-xs text-muted">{t.account_label}</span>
                        {t.allocations?.length > 0 && <span className="block text-xs text-accent-dark">↳ {t.allocations.map((a) => a.label).join(", ")}</span>}
                        {t.exclusion_reason && t.status === "escluso" && <span className="block text-xs text-muted">↳ {t.exclusion_reason}</span>}
                      </td>
                      <td className="py-3 pr-3">
                        {canCat ? (
                          <select aria-label="Categoria del movimento" className="input min-h-[40px] w-[190px] text-[13px]" value={t.category} onChange={(e) => changeCategory(t, e.target.value)}>
                            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
                          </select>
                        ) : <span className="text-muted">{t.category}</span>}
                      </td>
                      <td className="whitespace-nowrap py-3 pr-3 text-right"><Amount cents={t.amount_cents} /></td>
                      <td className="py-3 pr-3"><Badge tone={TX_STATUS[t.status][1]}>{TX_STATUS[t.status][0]}</Badge></td>
                      <td className="py-3 pr-5">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" className="min-h-[40px] px-2"
                            onClick={() => setNotesFor({ type: "transaction", id: t.id, companyId: company.id, title: "Note sul movimento", subtitle: `${fmtDate(t.date, { year: true })} · ${t.description}` })}>
                            {t.open_question ? "Domanda aperta · " : ""}Note{t.notes_count ? ` (${t.notes_count})` : ""}
                          </Button>
                          {canRec && t.status !== "da_riconciliare" && (
                            <Button variant="ghost" className="min-h-[40px] px-2" onClick={() => unmatch(t)}>Annulla abbinamento</Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.items.length < data.total && (
            <div className="flex justify-center border-t border-line p-4">
              <Button variant="secondary" onClick={() => setLimit((l) => l + PAGE)}>Mostra altri ({data.total - data.items.length})</Button>
            </div>
          )}
        </Card>
      )}
      <NotesDrawer target={notesFor} onClose={() => setNotesFor(null)} onChanged={load} />
    </>
  );
}
