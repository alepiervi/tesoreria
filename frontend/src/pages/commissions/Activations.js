import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import CompanyPicker, { usePageCompany } from "../../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Modal, Notice, PageHeader, Stat, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { eur, fmtDate, fmtDateTime } from "../../lib/format";
import { KIND, MappingModal, STATUS, monthLabel, monthOptions } from "./shared";

const PAGE = 100;

export default function Activations() {
  const [company, setCompany] = usePageCompany("view_commissions");
  const { can } = useAuth();
  const toast = useToast();
  const months = monthOptions();
  const [month, setMonth] = useState(months[0]);
  const [ov, setOv] = useState(null);
  const [partners, setPartners] = useState([]);
  const [bens, setBens] = useState([]);
  const [filters, setFilters] = useState({ partner_id: "", status: "", assigned: "", q: "" });
  const [list, setList] = useState(null);
  const [limit, setLimit] = useState(PAGE);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [mapping, setMapping] = useState(null);
  const [busy, setBusy] = useState("");
  const [importPartner, setImportPartner] = useState("");
  const [open, setOpen] = useState({});
  const partnerFile = useRef(null);
  const boFile = useRef(null);
  const pending = useRef(null);

  const loadMeta = useCallback(async () => {
    if (!company) return;
    try {
      const [o, p, b] = await Promise.all([
        api.get(`/companies/${company.id}/commissions/overview`, { params: { month } }),
        api.get(`/companies/${company.id}/commission-partners`),
        api.get(`/companies/${company.id}/commission-beneficiaries`),
      ]);
      setOv(o.data);
      setPartners(p.data);
      setBens(b.data.items);
      setImportPartner((cur) => cur || p.data[0]?.id || "");
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, month]);

  const loadList = useCallback(async () => {
    if (!company) return;
    try {
      const params = { ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)), limit };
      const r = await api.get(`/companies/${company.id}/commission-activations`, { params });
      setList(r.data);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, filters, limit]);

  useEffect(() => { setOv(null); loadMeta(); }, [loadMeta]);
  useEffect(() => { const t = setTimeout(loadList, 250); return () => clearTimeout(t); }, [loadList]);

  if (!company) return <Empty title="Nessuna azienda con accesso alle provvigioni" />;
  const canEdit = can(company.id, "manage_commissions");
  const partnerName = (id) => partners.find((p) => p.id === id)?.name || "";

  const upload = async (kind, file, map) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    if (map) fd.append("mapping", JSON.stringify(map));
    setBusy(kind);
    try {
      const url = kind === "partner" ? `/commission-partners/${importPartner}/import` : `/companies/${company.id}/commissions/backoffice`;
      const r = await api.post(url, fd);
      if (r.data.needs_mapping) {
        pending.current = { kind, file };
        setMapping({ ...r.data, title: kind === "partner" ? partnerName(importPartner) : "Backoffice" });
      } else {
        setMapping(null);
        setResult({ kind, partner: kind === "partner" ? partnerName(importPartner) : null, ...r.data });
        loadMeta();
        loadList();
      }
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
      if (partnerFile.current) partnerFile.current.value = "";
      if (boFile.current) boFile.current.value = "";
    }
  };
  const assign = async (a, beneficiaryId) => {
    try {
      await api.post(`/commission-activations/${a.id}/assign`, { beneficiary_id: beneficiaryId || null });
      loadList();
      loadMeta();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };
  const setF = (k) => (e) => { setFilters({ ...filters, [k]: e.target.value }); setLimit(PAGE); };
  const totals = (ov?.partners || []).reduce((s, p) => ({ attivate: s.attivate + (p.attivate || 0), in_lav: s.in_lav + (p.in_lavorazione || 0) }), { attivate: 0, in_lav: 0 });

  return (
    <>
      <PageHeader title="Attivazioni e provvigioni" subtitle="Avanzamenti dei partner abbinati al backoffice, per struttura e dipendente"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_commissions" />
          <label htmlFor="am" className="sr-only">Mese</label>
          <select id="am" className="input w-auto" value={month} onChange={(e) => setMonth(e.target.value)}>
            {months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
          </select>
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!ov ? <Loading /> : ov.setup.partners === 0 ? (
        <Card><Empty title="Configura prima partner, listino e venditori" action={<Link to="/provvigioni/impostazioni"><Button>Vai alle impostazioni</Button></Link>} /></Card>
      ) : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-4">
            <Stat label={`Attivate a ${monthLabel(month).toLowerCase()}`} value={String(totals.attivate)} sub={(ov.partners || []).map((p) => `${p.partner} ${p.attivate || 0}`).join(" · ")} />
            <Stat label="In lavorazione oggi" value={String(totals.in_lav)} />
            <Stat label="Da assegnare" value={String(ov.unmatched)} tone={ov.unmatched ? "warn" : undefined} sub="Senza struttura o dipendente" />
            <Stat label="Margine del mese" value={eur(ov.margin_cents)} sub={`Compensi partner ${eur(ov.revenue_cents)} − provvigioni ${eur(ov.payout_cents)}`} />
          </div>
          {(ov.unpriced > 0 || ov.unknown_status > 0) && (
            <Notice tone="orange">
              {ov.unpriced > 0 && <>{ov.unpriced} attivazioni hanno un'offerta che non è nel listino. </>}
              {ov.unknown_status > 0 && <>{ov.unknown_status} pratiche hanno uno stato da interpretare. </>}
              <Link to="/provvigioni/impostazioni" className="font-semibold underline">Sistema nelle impostazioni</Link>
            </Notice>
          )}

          {canEdit && (
            <Card title="Importa i file del giorno" subtitle="Prima il backoffice, poi gli avanzamenti dei partner: l'abbinamento si rifà da solo">
              <div className="grid gap-4 lg:grid-cols-2">
                <div className="flex flex-col gap-2 rounded-lg border border-line p-4">
                  <b>File del backoffice</b>
                  <span className="text-xs text-muted">Vendite con account, codice fiscale del cliente e codice del venditore.</span>
                  <input ref={boFile} type="file" accept=".csv,.xlsx,.txt" className="hidden" onChange={(e) => upload("backoffice", e.target.files?.[0])} />
                  <Button variant="secondary" className="self-start" loading={busy === "backoffice"} onClick={() => boFile.current?.click()}>Carica backoffice</Button>
                </div>
                <div className="flex flex-col gap-2 rounded-lg border border-line p-4">
                  <b>Avanzamenti del partner</b>
                  <div className="flex flex-wrap items-center gap-2">
                    <label htmlFor="ip" className="sr-only">Partner</label>
                    <select id="ip" className="input w-auto" value={importPartner} onChange={(e) => setImportPartner(e.target.value)}>
                      {partners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                    <input ref={partnerFile} type="file" accept=".csv,.xlsx,.txt" className="hidden" onChange={(e) => upload("partner", e.target.files?.[0])} />
                    <Button loading={busy === "partner"} onClick={() => partnerFile.current?.click()} disabled={!importPartner}>Carica avanzamenti</Button>
                  </div>
                  <span className="text-xs text-muted">Excel o CSV come arriva dal partner. Le pratiche si aggiornano per codice pratica.</span>
                </div>
              </div>
              {ov.imports.length > 0 && (
                <p className="mt-3 text-xs text-muted">Ultimi import: {ov.imports.slice(0, 4).map((i) => `${i.kind === "partner" ? partnerName(i.partner_id) : "backoffice"} ${fmtDateTime(i.at)}`).join(" · ")}</p>
              )}
            </Card>
          )}

          <Card padded={false}>
            <div className="flex flex-wrap items-end gap-3 px-5 pt-5">
              <div className="min-w-[200px] flex-1">
                <label htmlFor="aq" className="label">Cerca</label>
                <input id="aq" className="input mt-1.5" placeholder="Cliente, codice fiscale, pratica, account" value={filters.q} onChange={setF("q")} />
              </div>
              <div>
                <label htmlFor="af-p" className="label">Partner</label>
                <select id="af-p" className="input mt-1.5 w-auto" value={filters.partner_id} onChange={setF("partner_id")}>
                  <option value="">Tutti</option>
                  {partners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="af-s" className="label">Stato</label>
                <select id="af-s" className="input mt-1.5 w-auto" value={filters.status} onChange={setF("status")}>
                  <option value="">Tutti</option>
                  {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v[0]}</option>)}
                  <option value="sconosciuto">Da interpretare</option>
                </select>
              </div>
              <div>
                <label htmlFor="af-a" className="label">Assegnazione</label>
                <select id="af-a" className="input mt-1.5 w-auto" value={filters.assigned} onChange={setF("assigned")}>
                  <option value="">Tutte</option>
                  <option value="no">Da assegnare</option>
                  <option value="si">Assegnate</option>
                </select>
              </div>
              {list && <span className="pb-3 text-xs text-muted">{list.total} pratiche</span>}
            </div>
            {!list ? <Loading /> : list.items.length === 0 ? <Empty title="Nessuna pratica" /> : (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[1020px] text-sm">
                  <thead>
                    <tr className="table-head text-left">
                      <th className="px-5 py-3">Cliente e pratica</th>
                      <th className="py-3 pr-3">Offerta</th>
                      <th className="py-3 pr-3">Stato</th>
                      <th className="py-3 pr-3">Attivazione</th>
                      <th className="py-3 pr-3">Struttura o dipendente</th>
                      <th className="py-3 pr-5 text-right">Provvigione</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.items.map((a) => (
                      <tr key={a.id} className="border-b border-soft align-top">
                        <td className="px-5 py-3">
                          <b>{a.customer_name || a.customer_cf}</b>
                          <span className="block text-xs text-muted">{a.partner_name} · pratica {a.external_id} · {a.customer_cf}{a.account ? ` · account ${a.account}` : ""}</span>
                          <button type="button" className="text-xs font-semibold text-accent hover:underline" onClick={() => setOpen((o) => ({ ...o, [a.id]: !o[a.id] }))}>
                            {open[a.id] ? "Nascondi storia" : `Storia (${(a.history || []).length})`}
                          </button>
                          {open[a.id] && (
                            <ul className="mt-1 text-xs text-muted">
                              {(a.history || []).map((h, i) => <li key={i}>{fmtDate(h.date, { year: true })}: {h.raw || STATUS[h.status]?.[0] || h.status}</li>)}
                            </ul>
                          )}
                        </td>
                        <td className="py-3 pr-3">{a.offer}{a.offer_name ? <span className="block text-xs text-muted">listino: {a.offer_name}</span> : <Badge tone="orange" className="mt-1">Fuori listino</Badge>}</td>
                        <td className="py-3 pr-3">
                          {a.status ? <Badge tone={STATUS[a.status][1]}>{STATUS[a.status][0]}</Badge> : <Badge tone="orange">Da interpretare</Badge>}
                          <span className="block text-xs text-muted">{a.raw_status} · {fmtDate(a.status_date, { year: true })}</span>
                        </td>
                        <td className="whitespace-nowrap py-3 pr-3">{a.activation_date ? fmtDate(a.activation_date, { year: true }) : "—"}
                          {a.storno_date && <span className="block text-xs text-warn-text">cessata il {fmtDate(a.storno_date, { year: true })}</span>}</td>
                        <td className="py-3 pr-3">
                          {canEdit && !a.paid_statement_id ? (
                            <>
                              <label htmlFor={`as-${a.id}`} className="sr-only">Assegna</label>
                              <select id={`as-${a.id}`} className={`input min-w-[200px] ${a.beneficiary_id ? "" : "border-warn"}`} value={a.beneficiary_id || ""}
                                onChange={(e) => assign(a, e.target.value)}>
                                <option value="">— da assegnare —</option>
                                {["struttura", "dipendente"].map((k) => (
                                  <optgroup key={k} label={KIND[k] === "Struttura" ? "Strutture" : "Dipendenti"}>
                                    {bens.filter((b) => b.kind === k && b.active !== false).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                                  </optgroup>
                                ))}
                              </select>
                            </>
                          ) : <b>{a.beneficiary_name || "—"}</b>}
                          <span className="mt-1 block text-xs text-muted">{a.match_note}</span>
                        </td>
                        <td className="num py-3 pr-5 text-right">
                          {a.payout_cents !== null && a.payout_cents !== undefined ? eur(a.payout_cents) : "—"}
                          {a.paid_statement_id && <Badge tone="blue" className="mt-1">In rendiconto</Badge>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {list && list.total > list.items.length && (
              <div className="border-t border-soft px-5 py-3 text-center"><Button variant="secondary" onClick={() => setLimit((l) => l + PAGE)}>Mostra altre</Button></div>
            )}
          </Card>
        </>
      )}
      <MappingModal value={mapping} busy={Boolean(busy)} onClose={() => setMapping(null)}
        onConfirm={(m) => upload(pending.current.kind, pending.current.file, m)} />
      <Modal open={Boolean(result)} onClose={() => setResult(null)} title={result?.kind === "partner" ? `Avanzamenti ${result?.partner}` : "File del backoffice"}
        footer={<Button onClick={() => setResult(null)}>Chiudi</Button>}>
        {result && (
          <div className="flex flex-col gap-3 text-sm">
            <p>{result.rows} righe lette · {result.new} nuove · {result.updated} aggiornate{result.unchanged !== undefined ? ` · ${result.unchanged} senza cambiamenti` : ""}{result.skipped ? ` · ${result.skipped} saltate (dati mancanti)` : ""}.</p>
            <p>Attivazioni abbinate a una struttura o a un dipendente: <b>{result.matched}</b>.</p>
            {result.unknown_statuses?.length > 0 && (
              <Notice tone="orange">Stati da interpretare: {result.unknown_statuses.join(", ")}. Indicali in <Link className="font-semibold underline" to="/provvigioni/impostazioni">Impostazioni → Partner</Link>.</Notice>
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
