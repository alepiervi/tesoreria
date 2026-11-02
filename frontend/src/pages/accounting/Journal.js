import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import CompanyPicker, { usePageCompany } from "../../components/CompanyPicker";
import EntryEditor from "../../components/EntryEditor";
import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader, useToast } from "../../components/ui";
import { SOURCE_LABELS, YearSelect, useAccounts, useCostCenters } from "../../lib/accounting";
import { api, errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { eur, fmtDate } from "../../lib/format";

const PAGE = 60;

export default function Journal() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const { can } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [year, setYear] = useState(new Date().getFullYear());
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const account = params.get("conto") || "";
  const [data, setData] = useState(null);
  const [limit, setLimit] = useState(PAGE);
  const [error, setError] = useState("");
  const [open, setOpen] = useState({});
  const [editor, setEditor] = useState({ open: false, entry: null });
  const [accounts] = useAccounts(company?.id, year);
  const [costCenters] = useCostCenters(company?.id);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const res = await api.get(`/companies/${company.id}/entries`, {
        params: { year, q: q || undefined, source: source || undefined, account: account || undefined, limit, newest_first: true },
      });
      setData(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, year, q, source, account, limit]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;
  const canEdit = can(company.id, "manage_accounting");
  const accountName = (accounts || []).find((a) => a.code === account)?.name;
  const ccName = (id) => costCenters.find((c) => c.id === id)?.name;

  const remove = async (e) => {
    if (!window.confirm(`Eliminare la registrazione "${e.description}"?`)) return;
    try {
      await api.delete(`/entries/${e.id}`);
      toast("Registrazione eliminata");
      load();
    } catch (err) {
      toast(errorMessage(err), "orange");
    }
  };

  return (
    <>
      <PageHeader title="Prima nota" subtitle="Libro giornale: le registrazioni di fatture e movimenti riconciliati si creano da sole"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />
          <YearSelect value={year} onChange={setYear} />
          {canEdit && <Button onClick={() => setEditor({ open: true, entry: null })}>Nuova registrazione</Button>}
        </>} />

      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[220px] flex-1">
            <label htmlFor="j-q" className="label">Cerca</label>
            <input id="j-q" className="input mt-1.5" placeholder="Descrizione o numero documento" value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} />
          </div>
          <div>
            <label htmlFor="j-src" className="label">Origine</label>
            <select id="j-src" className="input mt-1.5 w-auto" value={source} onChange={(e) => { setSource(e.target.value); setLimit(PAGE); }}>
              <option value="">Tutte</option>
              {Object.entries(SOURCE_LABELS).map(([k, v]) => <option key={k} value={k}>{v[0]}</option>)}
            </select>
          </div>
          {account && (
            <div className="flex items-center gap-2 pb-2">
              <Badge tone="blue">Conto {account} {accountName ? `· ${accountName}` : ""}</Badge>
              <Button variant="ghost" className="min-h-[36px] px-2" onClick={() => setParams({})}>Togli filtro</Button>
            </div>
          )}
          {data && (
            <div className="num ml-auto pb-2 text-right text-xs text-muted">
              {data.total} registrazioni · dare {eur(data.totals.dare)} · avere {eur(data.totals.avere)}
            </div>
          )}
        </div>
      </Card>

      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : data.items.length === 0 ? (
        <Card><Empty title="Nessuna registrazione" text="Riconcilia i movimenti e importa le fatture: le registrazioni compariranno qui." /></Card>
      ) : (
        <Card padded={false}>
          <ul className="divide-y divide-soft">
            {data.items.map((e) => {
              const tot = e.lines.reduce((s, l) => s + l.dare, 0);
              const isOpen = open[e.id];
              const src = SOURCE_LABELS[e.source] || [e.source, "gray"];
              return (
                <li key={e.id}>
                  <button type="button" className="grid w-full grid-cols-[1fr_auto] items-center gap-3 px-5 py-3 text-left hover:bg-soft sm:grid-cols-[70px_90px_1fr_auto_auto]"
                    aria-expanded={Boolean(isOpen)} onClick={() => setOpen((o) => ({ ...o, [e.id]: !o[e.id] }))}>
                    <span className="num hidden text-xs text-muted sm:block">n. {e.number}</span>
                    <span className="hidden whitespace-nowrap text-muted sm:block">{fmtDate(e.date, { year: true })}</span>
                    <span className="min-w-0">
                      <span className="mr-2 inline-block rounded bg-soft px-1.5 py-0.5 text-[11px] font-bold text-[#3D4250]">{e.causale}</span>
                      <span className="font-semibold">{e.description}</span>
                      <span className="block text-xs text-muted sm:hidden">n. {e.number} · {fmtDate(e.date, { year: true })}</span>
                      {e.doc_number && <span className="ml-2 text-xs text-muted">doc. {e.doc_number}</span>}
                    </span>
                    <Badge tone={src[1]} className="hidden sm:inline-flex">{src[0]}</Badge>
                    <span className="num whitespace-nowrap text-right font-semibold">{eur(tot)}</span>
                  </button>
                  {isOpen && (
                    <div className="bg-[#FAFAF9] px-5 pb-4 pt-1">
                      <div className="overflow-x-auto">
                        <table className="w-full min-w-[640px] text-sm">
                          <thead>
                            <tr className="table-head text-left">
                              <th className="py-2 pr-3">Conto</th>
                              <th className="py-2 pr-3">Dettaglio</th>
                              <th className="py-2 pr-3 text-right">Dare</th>
                              <th className="py-2 text-right">Avere</th>
                            </tr>
                          </thead>
                          <tbody>
                            {e.lines.map((l, i) => (
                              <tr key={i} className="border-b border-soft last:border-0">
                                <td className="py-2 pr-3"><span className="num text-muted">{l.account}</span> {l.account_name}</td>
                                <td className="py-2 pr-3 text-xs text-muted">
                                  {[l.party_name, ccName(l.cost_center_id) && `Centro: ${ccName(l.cost_center_id)}`, l.description].filter(Boolean).join(" · ")}
                                </td>
                                <td className="num py-2 pr-3 text-right">{l.dare ? eur(l.dare) : ""}</td>
                                <td className="num py-2 text-right">{l.avere ? eur(l.avere) : ""}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
                        <span>{e.source === "manuale" ? `Inserita da ${e.created_by_name || "—"}` : e.source === "auto" ? "Creata dal programma: si aggiorna da sola se cambia la fattura o il movimento." : "Creata dalle procedure di fine periodo."}</span>
                        {canEdit && e.source === "manuale" && (
                          <span className="flex gap-1">
                            <Button variant="secondary" className="min-h-[38px]" onClick={() => setEditor({ open: true, entry: e })}>Modifica</Button>
                            <Button variant="danger" className="min-h-[38px]" onClick={() => remove(e)}>Elimina</Button>
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {data.total > data.items.length && (
            <div className="border-t border-soft px-5 py-3 text-center">
              <Button variant="secondary" onClick={() => setLimit((l) => l + PAGE)}>Mostra altre ({data.total - data.items.length})</Button>
            </div>
          )}
        </Card>
      )}

      <EntryEditor open={editor.open} entry={editor.entry} onClose={() => setEditor({ open: false, entry: null })}
        companyId={company.id} accounts={accounts} costCenters={costCenters}
        onSaved={() => { toast(editor.entry ? "Registrazione aggiornata" : "Registrazione salvata"); load(); }} />
    </>
  );
}
