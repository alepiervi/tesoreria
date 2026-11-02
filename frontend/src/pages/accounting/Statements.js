import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import CompanyPicker, { usePageCompany } from "../../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Notice, PageHeader, Stat, Tabs, useToast } from "../../components/ui";
import { YearSelect } from "../../lib/accounting";
import { api, blobErrorMessage, downloadFile, errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { eur } from "../../lib/format";
import { LedgerModal } from "./ChartOfAccounts";

export default function Statements() {
  const [company, setCompany] = usePageCompany("view_accounting");
  const { can } = useAuth();
  const toast = useToast();
  const [year, setYear] = useState(new Date().getFullYear());
  const [tab, setTab] = useState("sp");
  const [st, setSt] = useState(null);
  const [tb, setTb] = useState(null);
  const [checks, setChecks] = useState(null);
  const [error, setError] = useState("");
  const [ledger, setLedger] = useState(null);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    if (!company) return;
    setSt(null); setTb(null); setChecks(null);
    try {
      const [a, b, c] = await Promise.all([
        api.get(`/companies/${company.id}/statements`, { params: { year } }),
        api.get(`/companies/${company.id}/trial-balance`, { params: { year } }),
        api.get(`/companies/${company.id}/accounting-checks`),
      ]);
      setSt(a.data); setTb(b.data); setChecks(c.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company, year]);
  useEffect(() => { load(); }, [load]);

  if (!company) return <Empty title="Nessuna azienda con accesso alla contabilità" />;
  const issues = (checks || []).filter((c) => !c.ok).length;

  const download = async (kind, format = "xlsx") => {
    try {
      await downloadFile(`/companies/${company.id}/accounting-export`, { kind, year, format }, `${kind}_${year}.${format}`);
    } catch (e) {
      toast(await blobErrorMessage(e), "orange");
    }
  };
  const sync = async () => {
    setSyncing(true);
    try {
      await api.post(`/companies/${company.id}/accounting/sync`);
      toast("Registrazioni automatiche ricalcolate");
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <>
      <PageHeader title="Bilancio" subtitle="Stato patrimoniale e conto economico secondo lo schema CEE, bilancio di verifica e controlli"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} permission="view_accounting" />
          <YearSelect value={year} onChange={setYear} />
          <Button variant="secondary" onClick={() => download("statements", "pdf")}>PDF</Button>
          <Button variant="secondary" onClick={() => download("statements")}>Excel</Button>
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!st ? <Loading /> : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-4">
            <Stat label="Valore della produzione" value={eur(st.sintesi.valore_produzione)} />
            <Stat label="Costi della produzione" value={eur(st.sintesi.costi_produzione)} />
            <Stat label={st.sintesi.utile >= 0 ? "Utile dell'esercizio" : "Perdita dell'esercizio"} value={eur(st.sintesi.utile)}
              tone={st.sintesi.utile < 0 ? "warn" : undefined} sub={st.sintesi.imposte ? `dopo ${eur(st.sintesi.imposte)} di imposte` : "imposte non ancora registrate"} />
            <Stat label="Totale attivo" value={eur(st.totale_attivo)} sub={st.quadra ? "Attivo e passivo quadrano" : "Attivo e passivo NON quadrano"} />
          </div>
          <Tabs value={tab} onChange={setTab} tabs={[
            { id: "sp", label: "Stato patrimoniale" },
            { id: "ce", label: "Conto economico" },
            { id: "verifica", label: "Bilancio di verifica" },
            { id: "centri", label: "Centri di costo" },
            { id: "controlli", label: "Controlli", count: issues },
          ]} />
          {tab === "sp" && (
            <div className="grid gap-6 xl:grid-cols-2">
              <Schema title="Attivo" rows={st.attivo} total={st.totale_attivo} year={year} onAccount={setLedger} />
              <Schema title="Passivo e patrimonio netto" rows={st.passivo} total={st.totale_passivo} year={year} onAccount={setLedger} />
            </div>
          )}
          {tab === "ce" && (
            <Schema title="Conto economico" rows={st.conto_economico} year={year} onAccount={setLedger}
              footer={[["Differenza tra valore e costi della produzione (A − B)", st.sintesi.differenza],
                ["Risultato prima delle imposte", st.sintesi.risultato_ante_imposte],
                ["Utile (perdita) dell'esercizio", st.sintesi.utile, st.sintesi.utile_precedente]]} />
          )}
          {tab === "verifica" && <Trial tb={tb} onAccount={setLedger} onExport={() => download("trial")} />}
          {tab === "centri" && <CostCenterTable rows={st.centri_di_costo?.rows || []} />}
          {tab === "controlli" && (
            <Card title="Controlli di quadratura" subtitle="Da guardare prima di chiudere un periodo o mandare i dati al commercialista"
              actions={can(company.id, "manage_accounting") && <Button variant="secondary" onClick={sync} loading={syncing}>Ricalcola registrazioni automatiche</Button>}>
              <ul className="flex flex-col divide-y divide-soft">
                {(checks || []).map((c) => (
                  <li key={c.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                    <div className="flex min-w-0 items-start gap-3">
                      <Badge tone={c.ok ? "blue" : "orange"}>{c.ok ? "OK" : "Da vedere"}</Badge>
                      <span className="min-w-0"><b>{c.title}</b><span className="block text-sm text-muted">{c.detail}</span></span>
                    </div>
                    {c.link && !c.ok && <Link to={c.link} className="text-sm font-semibold text-accent hover:underline">Sistema →</Link>}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <Notice>
            Il bilancio è costruito dalle registrazioni del programma: per essere definitivo servono le scritture di fine anno
            (ammortamenti, ratei e risconti, rimanenze, imposte) e la verifica del commercialista. Il deposito in formato XBRL si fa con il suo software.
          </Notice>
        </>
      )}
      <LedgerModal company={company} code={ledger} year={year} onClose={() => setLedger(null)} />
    </>
  );
}

export function Schema({ title, rows, total, footer, year, onAccount }) {
  const [open, setOpen] = useState({});
  return (
    <Card title={title} padded={false}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-sm">
          <thead>
            <tr className="table-head text-left">
              <th className="px-5 py-3">Voce</th>
              <th className="py-3 pr-3 text-right">{year}</th>
              <th className="py-3 pr-5 text-right">{year - 1}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <FragmentRow key={r.code} r={r} open={open[r.code]} toggle={() => setOpen((o) => ({ ...o, [r.code]: !o[r.code] }))} onAccount={onAccount} />
            ))}
          </tbody>
          <tfoot>
            {total !== undefined && (
              <tr className="border-t-2 border-ink">
                <td className="px-5 py-3 font-bold">Totale</td>
                <td className="num py-3 pr-3 text-right font-bold">{eur(total)}</td>
                <td />
              </tr>
            )}
            {(footer || []).map(([label, value, prev]) => (
              <tr key={label} className="border-t border-line">
                <td className="px-5 py-3 font-bold">{label}</td>
                <td className={`num py-3 pr-3 text-right font-bold ${value < 0 ? "text-warn-amount" : ""}`}>{eur(value)}</td>
                <td className="num py-3 pr-5 text-right text-muted">{prev !== undefined ? eur(prev) : ""}</td>
              </tr>
            ))}
          </tfoot>
        </table>
      </div>
    </Card>
  );
}

function FragmentRow({ r, open, toggle, onAccount }) {
  const hasAccounts = r.accounts?.length > 0;
  const weight = r.level === 0 ? "font-bold" : r.level === 1 ? "font-semibold" : "";
  return (
    <>
      <tr className={`border-b border-soft ${r.level === 0 ? "bg-[#FAFAF9]" : ""}`}>
        <td className="px-5 py-2.5" style={{ paddingLeft: 20 + r.level * 18 }}>
          {hasAccounts ? (
            <button type="button" onClick={toggle} aria-expanded={Boolean(open)} className={`flex items-center gap-2 text-left ${weight}`}>
              <span aria-hidden="true" className="w-3 text-muted">{open ? "▾" : "▸"}</span>{r.label}
            </button>
          ) : <span className={weight}>{r.label}</span>}
        </td>
        <td className={`num py-2.5 pr-3 text-right ${weight}`}>{r.amount ? eur(r.amount) : "—"}</td>
        <td className="num py-2.5 pr-5 text-right text-muted">{r.previous ? eur(r.previous) : "—"}</td>
      </tr>
      {open && r.accounts.map((a) => (
        <tr key={a.code} className="border-b border-soft text-[13px]">
          <td className="py-2 pr-3" style={{ paddingLeft: 44 + r.level * 18 }}>
            <button type="button" className="text-left text-accent hover:underline" onClick={() => onAccount(a.code)}>
              <span className="num text-muted">{a.code}</span> {a.name}
            </button>
          </td>
          <td className="num py-2 pr-3 text-right">{eur(a.amount)}</td>
          <td />
        </tr>
      ))}
    </>
  );
}

function Trial({ tb, onAccount, onExport }) {
  if (!tb) return <Loading />;
  const rows = tb.rows.filter((r) => r.level === 3);
  return (
    <Card title="Bilancio di verifica" subtitle={tb.totals.balanced ? "Totale dare = totale avere" : "Attenzione: dare e avere non coincidono"}
      actions={<Button variant="secondary" onClick={onExport}>Scarica Excel</Button>} padded={false}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="table-head text-left">
              <th className="px-5 py-3">Conto</th>
              <th className="py-3 pr-3 text-right">Dare</th>
              <th className="py-3 pr-3 text-right">Avere</th>
              <th className="py-3 pr-3 text-right">Saldo dare</th>
              <th className="py-3 pr-5 text-right">Saldo avere</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.code} className="border-b border-soft">
                <td className="px-5 py-2.5">
                  <button type="button" className="text-left hover:underline" onClick={() => onAccount(r.code)}>
                    <span className="num text-muted">{r.code}</span> {r.name}
                  </button>
                </td>
                <td className="num py-2.5 pr-3 text-right text-muted">{eur(r.dare)}</td>
                <td className="num py-2.5 pr-3 text-right text-muted">{eur(r.avere)}</td>
                <td className="num py-2.5 pr-3 text-right font-semibold">{r.saldo > 0 ? eur(r.saldo) : ""}</td>
                <td className="num py-2.5 pr-5 text-right font-semibold">{r.saldo < 0 ? eur(-r.saldo) : ""}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-ink font-bold">
              <td className="px-5 py-3">Totali</td>
              <td className="num py-3 pr-3 text-right">{eur(tb.totals.dare)}</td>
              <td className="num py-3 pr-3 text-right">{eur(tb.totals.avere)}</td>
              <td className="num py-3 pr-3 text-right">{eur(tb.saldi.dare)}</td>
              <td className="num py-3 pr-5 text-right">{eur(tb.saldi.avere)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  );
}

function CostCenterTable({ rows }) {
  if (!rows.length) return <Card><Empty title="Nessun centro di costo usato" text="Assegna i centri di costo a fatture, cespiti e registrazioni." /></Card>;
  return (
    <Card title="Ricavi, costi e margine per centro di costo" padded={false}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm">
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
  );
}
