import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Notice, PageHeader, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { eur, fmtDate } from "../../lib/format";

export default function Classify() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const { can } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [choice, setChoice] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const r = await api.get(`/companies/${company.id}/invoices-to-classify`);
      setData(r.data);
      setChoice(Object.fromEntries(r.data.items.map((i) => [i.id, i.suggestion?.account_code || ""])));
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company]);
  useEffect(() => { setData(null); load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;
  const canEdit = can(company.id, "manage_accounting");
  const save = async (ids) => {
    const items = ids.filter((id) => choice[id]).map((id) => ({ invoice_id: id, account_code: choice[id] }));
    if (!items.length) return;
    setBusy(true);
    try {
      const r = await api.post(`/companies/${company.id}/invoices-to-classify`, { items, remember_for_supplier: true });
      toast(`${r.data.classified} fatture registrate sul conto scelto`);
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy(false);
    }
  };
  const withChoice = (data?.items || []).filter((i) => choice[i.id]).map((i) => i.id);

  return (
    <>
      <PageHeader title="Fatture da classificare" subtitle="Fatture di acquisto ancora sul conto generico, con il conto suggerito"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />
          {canEdit && <Button onClick={() => save(withChoice)} loading={busy} disabled={!withChoice.length}>Conferma tutte ({withChoice.length})</Button>}
        </>} />
      <Notice>
        Il conto scelto viene ricordato per il fornitore: le sue prossime fatture andranno lì da sole. I suggerimenti arrivano
        dalle scelte già fatte nel gruppo e dalle parole della fattura; controllali prima di confermare.
      </Notice>
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : data.items.length === 0 ? (
        <Card><Empty title="Tutto classificato" text="Nessuna fattura di acquisto sul conto generico." /></Card>
      ) : (
        <Card padded={false}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="table-head text-left">
                  <th className="px-5 py-3">Fattura</th>
                  <th className="py-3 pr-3">Descrizione</th>
                  <th className="py-3 pr-3 text-right">Imponibile</th>
                  <th className="py-3 pr-3">Conto</th>
                  <th className="py-3 pr-5"><span className="sr-only">Azioni</span></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((i) => (
                  <tr key={i.id} className="border-b border-soft align-top">
                    <td className="px-5 py-3"><b>{i.counterparty_name}</b><span className="block text-xs text-muted">n. {i.number} del {fmtDate(i.date, { year: true })}</span></td>
                    <td className="max-w-[260px] py-3 pr-3 text-muted">{i.description || "—"}</td>
                    <td className="num py-3 pr-3 text-right">{eur(i.taxable_cents)}</td>
                    <td className="py-3 pr-3">
                      <label htmlFor={`c-${i.id}`} className="sr-only">Conto per {i.number}</label>
                      <select id={`c-${i.id}`} className="input min-w-[260px]" value={choice[i.id] || ""} disabled={!canEdit}
                        onChange={(e) => setChoice({ ...choice, [i.id]: e.target.value })}>
                        <option value="">— scegli il conto —</option>
                        {data.options.map((o) => <option key={o.code} value={o.code}>{o.code} · {o.name}</option>)}
                      </select>
                      {i.suggestion && (
                        <span className="mt-1 flex items-center gap-2 text-xs text-muted">
                          <Badge tone={i.suggestion.confidence === "alta" ? "blue" : "gray"}>Suggerito</Badge>{i.suggestion.reason}
                        </span>
                      )}
                    </td>
                    <td className="py-3 pr-5 text-right">
                      {canEdit && <Button variant="secondary" className="min-h-[38px]" disabled={!choice[i.id] || busy} onClick={() => save([i.id])}>Conferma</Button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
