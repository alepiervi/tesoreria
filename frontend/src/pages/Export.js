import { useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Button, Card, Empty, ErrorBox, Field, Modal, Notice, PageHeader, useToast } from "../components/ui";
import { api, blobErrorMessage, downloadFile, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";

function monthRange(offset) {
  const now = new Date();
  const first = new Date(now.getFullYear(), now.getMonth() + offset, 1);
  const last = new Date(now.getFullYear(), now.getMonth() + offset + 1, 0);
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return [iso(first), iso(last)];
}

function quarterRange() {
  const now = new Date();
  const q = Math.floor(now.getMonth() / 3) - 1;
  const year = q < 0 ? now.getFullYear() - 1 : now.getFullYear();
  const startMonth = ((q + 4) % 4) * 3;
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return [iso(new Date(year, startMonth, 1)), iso(new Date(year, startMonth + 3, 0))];
}

const PRESETS = {
  this_month: ["Mese in corso", () => monthRange(0)],
  last_month: ["Mese scorso", () => monthRange(-1)],
  last_quarter: ["Trimestre scorso", quarterRange],
  year: ["Anno in corso", () => [`${new Date().getFullYear()}-01-01`, `${new Date().getFullYear()}-12-31`]],
};

const FORMATS = [
  ["xlsx", "Excel", "Prima nota, fatture, scadenze e note in un unico file"],
  ["csv", "CSV", "Prima nota da importare nel gestionale dello studio"],
  ["xml", "XML fatture", "Archivio .zip con le fatture elettroniche originali"],
];

export default function Export() {
  const [company, setCompany] = usePageCompany("export");
  const [preset, setPreset] = useState("last_month");
  const [range, setRange] = useState(monthRange(-1));
  const [format, setFormat] = useState("xlsx");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");

  if (!company) return <Empty title="Nessuna azienda esportabile" text="Il tuo ruolo non permette di esportare dati." />;

  const choosePreset = (key) => {
    setPreset(key);
    if (PRESETS[key]) setRange(PRESETS[key][1]());
  };

  const run = async () => {
    setBusy(true);
    setError("");
    setDone("");
    try {
      await downloadFile(`/companies/${company.id}/export`, { format, date_from: range[0], date_to: range[1] });
      setDone("Export scaricato.");
    } catch (e) {
      setError(await blobErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Export e report" subtitle="Report mensile in PDF e dati pronti per il gestionale del commercialista"
        actions={<CompanyPicker value={company.id} onChange={setCompany} permission="export" />} />
      <MonthlyReport companyId={company.id} />
      <AccountantExport companyId={company.id} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Card title="Cosa esportare">
          <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <span className="label">Periodo</span>
              <div className="flex flex-wrap gap-2">
                {[...Object.entries(PRESETS), ["custom", ["Personalizzato"]]].map(([key, [label]]) => (
                  <button key={key} type="button" aria-pressed={preset === key} onClick={() => choosePreset(key)}
                    className={`min-h-[44px] rounded-full border px-4 text-[13px] font-semibold ${preset === key ? "border-accent bg-accent text-white" : "border-[#C9CDD4] bg-white"}`}>
                    {label}
                  </button>
                ))}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Dal" htmlFor="ex-from"><input id="ex-from" type="date" className="input" value={range[0]} onChange={(e) => { setPreset("custom"); setRange([e.target.value, range[1]]); }} /></Field>
                <Field label="Al" htmlFor="ex-to"><input id="ex-to" type="date" className="input" value={range[1]} onChange={(e) => { setPreset("custom"); setRange([range[0], e.target.value]); }} /></Field>
              </div>
            </div>
            <fieldset className="flex flex-col gap-2">
              <legend className="label mb-2">Formato</legend>
              {FORMATS.map(([id, label, desc]) => (
                <label key={id} className={`flex min-h-[56px] cursor-pointer items-center gap-3 rounded-lg border px-4 py-2 ${format === id ? "border-accent bg-accent-soft" : "border-line"}`}>
                  <input type="radio" name="format" value={id} checked={format === id} onChange={() => setFormat(id)} className="h-[18px] w-[18px]" />
                  <span><span className="block text-sm font-semibold">{label}</span><span className="block text-xs text-muted">{desc}</span></span>
                </label>
              ))}
            </fieldset>
            <ErrorBox>{error}</ErrorBox>
            {done && <Notice>{done}</Notice>}
            <div><Button onClick={run} loading={busy}>Scarica export</Button></div>
          </div>
        </Card>
        <Card title="Cosa contiene">
          <ul className="flex list-disc flex-col gap-2 pl-5 text-sm leading-relaxed">
            <li>Prima nota con i movimenti bancari del periodo, divisi tra entrate e uscite e categorizzati</li>
            <li>Per ogni movimento: la fattura o la scadenza abbinata, oppure il motivo se è senza fattura</li>
            <li>Fatture attive e passive con totale, pagato e residuo</li>
            <li>Scadenze del periodo con il loro stato</li>
            <li>Le note e i chiarimenti scambiati sui movimenti</li>
          </ul>
          <p className="mt-4 text-xs text-muted">Ogni export viene registrato nel registro attività.</p>
        </Card>
      </div>
    </>
  );
}

function MonthlyReport({ companyId }) {
  const { companiesWith } = useAuth();
  const multi = companiesWith("export").length > 1;
  const prev = monthRange(-1)[0].slice(0, 7);
  const [month, setMonth] = useState(prev);
  const [scope, setScope] = useState("company");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async () => {
    setBusy(true);
    setError("");
    try {
      await downloadFile("/reports/monthly", { month, company_id: scope === "company" ? companyId : undefined }, `report_${month}.pdf`);
    } catch (e) {
      setError(await blobErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Report mensile in PDF" subtitle="Liquidità, entrate e uscite per categoria, budget, crediti e debiti, previsione, finanziamenti">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Mese" htmlFor="rep-month"><input id="rep-month" type="month" className="input" value={month} onChange={(e) => setMonth(e.target.value)} /></Field>
        {multi && (
          <Field label="Di chi" htmlFor="rep-scope">
            <select id="rep-scope" className="input" value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="company">Azienda selezionata</option>
              <option value="group">Tutto il gruppo</option>
            </select>
          </Field>
        )}
        <Button onClick={run} loading={busy} disabled={!month}>Scarica il report</Button>
      </div>
      {error && <div className="mt-3"><ErrorBox>{error}</ErrorBox></div>}
      <p className="mt-3 text-xs text-muted">Puoi riceverlo anche via email il primo di ogni mese: Impostazioni → Notifiche.</p>
    </Card>
  );
}

function AccountantExport({ companyId }) {
  const { can } = useAuth();
  const toast = useToast();
  const [range, setRange] = useState(monthRange(-1));
  const [cfg, setCfg] = useState(null);
  const [fields, setFields] = useState({});
  const [open, setOpen] = useState(false);
  const [mapText, setMapText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const allowed = can(companyId, "view_accounting");

  useEffect(() => {
    if (!allowed) return;
    api.get(`/companies/${companyId}/export-settings`).then((r) => { setCfg(r.data.settings); setFields(r.data.fields); }).catch(() => {});
  }, [companyId, allowed]);
  if (!allowed) return null;

  const download = async () => {
    setBusy(true);
    setError("");
    try {
      await downloadFile(`/companies/${companyId}/journal-export`, { date_from: range[0], date_to: range[1] }, "prima_nota.csv");
    } catch (e) {
      setError(await blobErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const saveCfg = async () => {
    try {
      const accountMap = Object.fromEntries(mapText.split("\n").map((l) => l.split("=").map((x) => x.trim())).filter((p) => p[0] && p[1]));
      await api.put(`/companies/${companyId}/export-settings`, { ...cfg, account_map: accountMap });
      setCfg({ ...cfg, account_map: accountMap });
      toast("Formato salvato");
      setOpen(false);
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const toggleCol = (c) => setCfg((x) => ({ ...x, columns: x.columns.includes(c) ? x.columns.filter((y) => y !== c) : [...x.columns, c] }));
  const move = (c, d) => setCfg((x) => {
    const cols = [...x.columns];
    const i = cols.indexOf(c);
    const j = i + d;
    if (j < 0 || j >= cols.length) return x;
    [cols[i], cols[j]] = [cols[j], cols[i]];
    return { ...x, columns: cols };
  });

  return (
    <Card title="Prima nota per il gestionale del commercialista" subtitle="La contabilità in partita doppia nel formato che serve allo studio (CSV o Excel)"
      actions={<Button variant="secondary" disabled={!cfg} onClick={() => {
        setMapText(Object.entries(cfg.account_map || {}).map(([k, v]) => `${k} = ${v}`).join("\n"));
        setOpen(true);
      }}>Imposta il formato</Button>}>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Dal" htmlFor="ae-from"><input id="ae-from" type="date" className="input" value={range[0]} onChange={(e) => setRange([e.target.value, range[1]])} /></Field>
        <Field label="Al" htmlFor="ae-to"><input id="ae-to" type="date" className="input" value={range[1]} onChange={(e) => setRange([range[0], e.target.value])} /></Field>
        <Button onClick={download} loading={busy}>Scarica la prima nota</Button>
        <Button variant="ghost" onClick={() => downloadFile(`/companies/${companyId}/parties-export`, {}, "anagrafica.csv").catch(async (e) => setError(await blobErrorMessage(e)))}>
          Anagrafica clienti e fornitori
        </Button>
      </div>
      {error && <div className="mt-3"><ErrorBox>{error}</ErrorBox></div>}
      <p className="mt-3 text-xs text-muted">
        Ogni gestionale (TeamSystem, Zucchetti, Profis, Passepartout…) ha il suo tracciato di importazione: chiedi allo studio quali colonne,
        separatore e codici conto vuole e impostali una volta sola. La colonna «Conto nel gestionale» usa la tabella di corrispondenza dei conti.
      </p>
      <Modal open={open && Boolean(cfg)} onClose={() => setOpen(false)} wide title="Formato dell'export"
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Annulla</Button><Button onClick={saveCfg}>Salva</Button></>}>
        {cfg && (
          <div className="flex flex-col gap-4">
            <div className="grid gap-3 sm:grid-cols-4">
              <Field label="File" htmlFor="ef-f"><select id="ef-f" className="input" value={cfg.format} onChange={(e) => setCfg({ ...cfg, format: e.target.value })}>
                <option value="csv">CSV</option><option value="xlsx">Excel</option></select></Field>
              <Field label="Separatore" htmlFor="ef-s"><select id="ef-s" className="input" value={cfg.separator} onChange={(e) => setCfg({ ...cfg, separator: e.target.value })}>
                <option value=";">Punto e virgola</option><option value=",">Virgola</option><option value="tab">Tabulazione</option><option value="|">Barra |</option></select></Field>
              <Field label="Decimali" htmlFor="ef-d"><select id="ef-d" className="input" value={cfg.decimal} onChange={(e) => setCfg({ ...cfg, decimal: e.target.value })}>
                <option value=",">1234,56</option><option value=".">1234.56</option></select></Field>
              <Field label="Date" htmlFor="ef-dt"><select id="ef-dt" className="input" value={cfg.date_format} onChange={(e) => setCfg({ ...cfg, date_format: e.target.value })}>
                <option value="gg/mm/aaaa">31/12/2026</option><option value="aaaa-mm-gg">2026-12-31</option><option value="ggmmaaaa">31122026</option><option value="aaaammgg">20261231</option></select></Field>
            </div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4" checked={cfg.header} onChange={(e) => setCfg({ ...cfg, header: e.target.checked })} /> Prima riga con i nomi delle colonne</label>
            <div>
              <span className="label">Colonne (nell'ordine del file)</span>
              <ol className="mt-2 flex flex-col gap-1">
                {cfg.columns.map((c, i) => (
                  <li key={c} className="flex items-center justify-between gap-2 rounded-lg border border-line px-3 py-1.5 text-sm">
                    <span><span className="num mr-2 text-muted">{i + 1}.</span>{fields[c]}</span>
                    <span className="flex gap-1">
                      <Button variant="ghost" className="min-h-[32px] px-2" aria-label="Su" onClick={() => move(c, -1)}>↑</Button>
                      <Button variant="ghost" className="min-h-[32px] px-2" aria-label="Giù" onClick={() => move(c, 1)}>↓</Button>
                      <Button variant="ghost" className="min-h-[32px] px-2 text-warn-text" aria-label="Togli" onClick={() => toggleCol(c)}>✕</Button>
                    </span>
                  </li>
                ))}
              </ol>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(fields).filter(([c]) => !cfg.columns.includes(c)).map(([c, l]) => (
                  <button key={c} type="button" onClick={() => toggleCol(c)} className="min-h-[34px] rounded-full border border-line px-3 text-xs font-semibold hover:bg-soft">+ {l}</button>
                ))}
              </div>
            </div>
            <Field label="Corrispondenza dei conti" htmlFor="ef-map" hint="Una riga per conto: codice nel programma = codice nel gestionale (es. 60.02.02 = 6200010)">
              <textarea id="ef-map" rows={6} className="input py-2 font-mono text-xs"
                value={mapText} onChange={(e) => setMapText(e.target.value)} />
            </Field>
          </div>
        )}
      </Modal>
    </Card>
  );
}
