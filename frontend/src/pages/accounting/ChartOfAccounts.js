import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import CompanyPicker, { usePageCompany } from "../../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, Tabs, useToast } from "../../components/ui";
import { AccountSelect, KIND_LABELS, YearSelect, useAccounts, useCostCenters } from "../../lib/accounting";
import { api, errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { eur, fmtDate } from "../../lib/format";

export default function ChartOfAccounts() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState("conti");
  const [year, setYear] = useState(new Date().getFullYear());
  const [accounts, reload] = useAccounts(company?.id, year);
  const ledgerCode = params.get("conto");

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;
  return (
    <>
      <PageHeader title="Piano dei conti" subtitle="Conti a tre livelli con saldi, mastrini e partitari di clienti e fornitori"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />
          <YearSelect value={year} onChange={setYear} />
        </>} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "conti", label: "Conti e saldi" },
        { id: "categorie", label: "Collegamento categorie" },
        { id: "centri", label: "Centri di costo" },
      ]} />
      {tab === "conti" && <AccountsTree company={company} accounts={accounts} reload={reload} onOpen={(code) => setParams({ conto: code })} />}
      {tab === "categorie" && <CategoryMap company={company} accounts={accounts} />}
      {tab === "centri" && <CostCenters company={company} />}
      <LedgerModal company={company} code={ledgerCode} year={year} onClose={() => setParams({})} />
    </>
  );
}

function AccountsTree({ company, accounts, reload, onOpen }) {
  const { can } = useAuth();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [onlyMoved, setOnlyMoved] = useState(true);
  const [collapsed, setCollapsed] = useState({});
  const [adding, setAdding] = useState(null);
  const canEdit = can(company.id, "manage_accounting");

  const visible = useMemo(() => {
    if (!accounts) return [];
    const ql = q.trim().toLowerCase();
    return accounts.filter((a) => {
      if (ql) return a.postable && (a.code.includes(ql) || a.name.toLowerCase().includes(ql));
      if (onlyMoved && !(a.dare || a.avere)) return false;
      const parts = a.code.split(".");
      for (let i = 1; i < parts.length; i += 1) if (collapsed[parts.slice(0, i).join(".")]) return false;
      return true;
    });
  }, [accounts, q, onlyMoved, collapsed]);

  if (!accounts) return <Loading />;
  return (
    <Card padded={false}>
      <div className="flex flex-wrap items-end gap-3 px-5 pt-5">
        <div className="min-w-[220px] flex-1">
          <label htmlFor="acc-q" className="label">Cerca un conto</label>
          <input id="acc-q" className="input mt-1.5" placeholder="Codice o nome, es. 60.02 o energia" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <label className="flex min-h-[44px] items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyMoved} onChange={(e) => setOnlyMoved(e.target.checked)} className="h-4 w-4" />
          Solo conti movimentati
        </label>
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="table-head text-left">
              <th className="px-5 py-3">Conto</th>
              <th className="py-3 pr-3 text-right">Dare</th>
              <th className="py-3 pr-3 text-right">Avere</th>
              <th className="py-3 pr-3 text-right">Saldo</th>
              <th className="py-3 pr-5"><span className="sr-only">Azioni</span></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((a) => {
              const isGroup = !a.postable;
              const pad = q ? 0 : (a.level - 1) * 20;
              return (
                <tr key={a.code} className={`border-b border-soft ${a.level === 1 ? "bg-[#FAFAF9]" : ""} ${a.active === false ? "opacity-50" : ""}`}>
                  <td className="px-5 py-2.5" style={{ paddingLeft: 20 + pad }}>
                    {isGroup ? (
                      <button type="button" className="flex items-center gap-2 text-left" aria-expanded={!collapsed[a.code]}
                        onClick={() => setCollapsed((c) => ({ ...c, [a.code]: !c[a.code] }))}>
                        <span aria-hidden="true" className="w-3 text-muted">{collapsed[a.code] ? "▸" : "▾"}</span>
                        <span className="num text-muted">{a.code}</span>
                        <span className={a.level === 1 ? "font-bold" : "font-semibold"}>{a.name}</span>
                        {a.level === 1 && <Badge className="ml-1">{KIND_LABELS[a.kind]}</Badge>}
                      </button>
                    ) : (
                      <button type="button" className="flex items-center gap-2 text-left hover:underline" onClick={() => onOpen(a.code)}>
                        <span className="num text-muted">{a.code}</span>
                        <span>{a.name}</span>
                        {a.party && <Badge tone="blue">partitario</Badge>}
                        {!a.system && <Badge>aggiunto</Badge>}
                      </button>
                    )}
                  </td>
                  <td className="num py-2.5 pr-3 text-right text-muted">{a.dare ? eur(a.dare) : ""}</td>
                  <td className="num py-2.5 pr-3 text-right text-muted">{a.avere ? eur(a.avere) : ""}</td>
                  <td className={`num py-2.5 pr-3 text-right ${isGroup ? "font-bold" : "font-semibold"}`}>{a.saldo ? eur(a.saldo) : ""}</td>
                  <td className="py-2.5 pr-5 text-right">
                    {canEdit && a.level === 2 && (
                      <Button variant="ghost" className="min-h-[34px] px-2 text-xs" onClick={() => setAdding(a)}>+ Sottoconto</Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {visible.length === 0 && <Empty title="Nessun conto" text="Togli il filtro «Solo conti movimentati» per vedere tutto il piano." />}
      </div>
      <p className="px-5 py-3 text-xs text-muted">Saldo = dare − avere: positivo per attività e costi, negativo per passività e ricavi.</p>
      <AddAccountModal parent={adding} company={company} onClose={() => setAdding(null)}
        onDone={(acc) => { toast(`Creato il conto ${acc.code}`); reload(); }} />
    </Card>
  );
}

function AddAccountModal({ parent, company, onClose, onDone }) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setName(""); setError(""); }, [parent]);
  if (!parent) return null;
  const save = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/companies/${company.id}/accounts`, { parent_code: parent.code, name });
      onDone(r.data);
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} title={`Nuovo sottoconto in ${parent.code} · ${parent.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save} loading={busy} disabled={!name.trim()}>Crea</Button></>}>
      <div className="flex flex-col gap-3">
        <Field label="Nome del conto" htmlFor="new-acc"><input id="new-acc" className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <p className="text-xs text-muted">Il codice viene assegnato in automatico ({parent.code}.50, .51…) e la voce di bilancio è la stessa degli altri conti del gruppo.</p>
        <ErrorBox>{error}</ErrorBox>
      </div>
    </Modal>
  );
}

export function LedgerModal({ company, code, year, onClose }) {
  const [data, setData] = useState(null);
  const [parties, setParties] = useState(null);
  const [party, setParty] = useState("");
  const [error, setError] = useState("");

  useEffect(() => { setParty(""); setParties(null); }, [code]);
  useEffect(() => {
    if (!code) return;
    setData(null);
    api.get(`/companies/${company.id}/ledger`, { params: { account: code, year, party_key: party || undefined } })
      .then((r) => { setData(r.data); setError(""); })
      .catch((e) => setError(errorMessage(e)));
  }, [company.id, code, year, party]);
  useEffect(() => {
    if (!code || !data?.account?.party || parties) return;
    api.get(`/companies/${company.id}/parties`, { params: { account: code } }).then((r) => setParties(r.data)).catch(() => setParties([]));
  }, [company.id, code, data, parties]);

  if (!code) return null;
  return (
    <Modal open onClose={onClose} wide title={data ? `Mastrino ${data.account.code} · ${data.account.name}` : "Mastrino"}>
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <div className="flex flex-col gap-4">
          {parties && parties.length > 0 && (
            <div className="flex flex-col gap-2">
              <span className="label">Partitario</span>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => setParty("")}
                  className={`min-h-[36px] rounded-full border px-3 text-xs font-semibold ${!party ? "border-accent bg-accent-soft text-accent-dark" : "border-line"}`}>Tutti</button>
                {parties.map((p) => (
                  <button key={p.party_key} type="button" onClick={() => setParty(p.party_key)}
                    className={`min-h-[36px] rounded-full border px-3 text-xs font-semibold ${party === p.party_key ? "border-accent bg-accent-soft text-accent-dark" : "border-line"}`}>
                    {p.party_name} · <span className="num">{eur(p.saldo)}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="num flex flex-wrap gap-4 text-sm">
            <span>Saldo iniziale <b>{eur(data.opening)}</b></span>
            <span>Dare <b>{eur(data.totals.dare)}</b></span>
            <span>Avere <b>{eur(data.totals.avere)}</b></span>
            <span>Saldo finale <b>{eur(data.closing)}</b></span>
          </div>
          {data.rows.length === 0 ? <Empty title="Nessun movimento nell'anno" /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="table-head text-left">
                    <th className="py-2 pr-3">Data</th>
                    <th className="py-2 pr-3">Descrizione</th>
                    <th className="py-2 pr-3 text-right">Dare</th>
                    <th className="py-2 pr-3 text-right">Avere</th>
                    <th className="py-2 text-right">Saldo</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r, i) => (
                    <tr key={`${r.entry_id}-${i}`} className="border-b border-soft">
                      <td className="whitespace-nowrap py-2 pr-3 text-muted">{fmtDate(r.date, { year: true })}</td>
                      <td className="py-2 pr-3"><span className="mr-1.5 rounded bg-soft px-1.5 py-0.5 text-[11px] font-bold">{r.causale}</span>{r.description}
                        {r.party_name && !party && <span className="block text-xs text-muted">{r.party_name}</span>}</td>
                      <td className="num py-2 pr-3 text-right">{r.dare ? eur(r.dare) : ""}</td>
                      <td className="num py-2 pr-3 text-right">{r.avere ? eur(r.avere) : ""}</td>
                      <td className="num py-2 text-right font-semibold">{eur(r.balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Link to={`/contabilita/prima-nota?conto=${data.account.code}`} className="text-sm font-semibold text-accent hover:underline">
            Vedi le registrazioni complete in prima nota →
          </Link>
        </div>
      )}
    </Modal>
  );
}

function CategoryMap({ company, accounts }) {
  const { can } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const canEdit = can(company.id, "manage_accounting");

  useEffect(() => {
    api.get(`/companies/${company.id}/accounting-settings`).then((r) => setData(r.data)).catch((e) => setError(errorMessage(e)));
  }, [company.id]);

  const save = async () => {
    setBusy(true);
    try {
      const r = await api.put(`/companies/${company.id}/accounting-settings`, { category_map: data.category_map, enabled: data.enabled });
      toast(`Collegamenti salvati: ${r.data.sync?.aggiornata || 0} registrazioni aggiornate`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!data || !accounts) return <><ErrorBox>{error}</ErrorBox><Loading /></>;
  return (
    <Card title="Da categoria del movimento a conto" subtitle="Per i movimenti in banca senza fattura (stipendi, affitti, F24, commissioni…)"
      actions={canEdit && <Button onClick={save} loading={busy}>Salva e aggiorna le registrazioni</Button>}>
      <Notice>
        I movimenti abbinati a una fattura vanno sempre su clienti o fornitori. Quelli sul conto «Movimenti da attribuire» (20.04.99) restano
        da sistemare: il commercialista li sposta con una registrazione in prima nota o cambiando qui il collegamento.
      </Notice>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {Object.entries(data.category_map).map(([cat, code]) => (
          <Field key={cat} label={cat} htmlFor={`cat-${cat}`}>
            {canEdit ? (
              <AccountSelect id={`cat-${cat}`} accounts={accounts} value={code}
                onChange={(v) => setData({ ...data, category_map: { ...data.category_map, [cat]: v } })} />
            ) : <span className="text-sm">{code} · {accounts.find((a) => a.code === code)?.name}</span>}
          </Field>
        ))}
      </div>
      <ErrorBox>{error}</ErrorBox>
    </Card>
  );
}

function CostCenters({ company }) {
  const { can } = useAuth();
  const toast = useToast();
  const [items, reload] = useCostCenters(company.id);
  const [year] = useState(new Date().getFullYear());
  const [report, setReport] = useState(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const canEdit = can(company.id, "manage_accounting");

  const loadReport = useCallback(() => {
    api.get(`/companies/${company.id}/cost-center-report`, { params: { year } }).then((r) => setReport(r.data)).catch(() => {});
  }, [company.id, year]);
  useEffect(loadReport, [loadReport]);

  const add = async () => {
    try {
      await api.post(`/companies/${company.id}/cost-centers`, { name });
      setName("");
      reload();
      loadReport();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const remove = async (c) => {
    try {
      await api.delete(`/cost-centers/${c.id}`);
      reload();
      loadReport();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };
  const rows = report?.rows || [];

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1.3fr]">
      <Card title="Centri di costo" subtitle="Reparti, sedi, commesse o linee di prodotto">
        <ul className="flex flex-col divide-y divide-soft">
          {items.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-3 py-2.5">
              <span><b>{c.name}</b>{c.description && <span className="block text-xs text-muted">{c.description}</span>}</span>
              {canEdit && <Button variant="ghost" className="min-h-[36px] px-2 text-warn-text" onClick={() => remove(c)}>Elimina</Button>}
            </li>
          ))}
          {items.length === 0 && <li className="py-4 text-sm text-muted">Nessun centro di costo.</li>}
        </ul>
        {canEdit && (
          <div className="mt-4 flex gap-2">
            <label htmlFor="cc-new" className="sr-only">Nuovo centro di costo</label>
            <input id="cc-new" className="input" placeholder="Nuovo centro di costo" value={name} onChange={(e) => setName(e.target.value)} />
            <Button onClick={add} disabled={!name.trim()}>Aggiungi</Button>
          </div>
        )}
        <ErrorBox>{error}</ErrorBox>
        <p className="mt-3 text-xs text-muted">Il centro di costo si assegna alle fatture (pulsante «Contabilità» nella pagina Fatture), ai cespiti e alle righe di prima nota.</p>
      </Card>
      <Card title={`Margine per centro di costo · ${year}`} padded={false}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[440px] text-sm">
            <thead>
              <tr className="table-head text-left">
                <th className="px-5 py-3">Centro</th>
                <th className="py-3 pr-3 text-right">Ricavi</th>
                <th className="py-3 pr-3 text-right">Costi</th>
                <th className="py-3 pr-5 text-right">Margine</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id || "none"} className="border-b border-soft">
                  <td className="px-5 py-2.5 font-semibold">{r.name}</td>
                  <td className="num py-2.5 pr-3 text-right">{eur(r.ricavi)}</td>
                  <td className="num py-2.5 pr-3 text-right">{eur(r.costi)}</td>
                  <td className={`num py-2.5 pr-5 text-right font-bold ${r.margine < 0 ? "text-warn-amount" : ""}`}>{eur(r.margine)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
