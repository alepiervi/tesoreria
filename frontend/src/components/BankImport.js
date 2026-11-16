import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../lib/api";
import { eur, fmtDate, todayIso } from "../lib/format";
import { Amount, Badge, Button, ErrorBox, Field, Loading, Modal, Notice } from "./ui";

/** Nuovo conto senza collegamento automatico (i movimenti arrivano dall'estratto conto). */
export function ManualAccountModal({ open, companyId, accounts = [], onClose, onDone }) {
  const empty = { account_type: "conto", bank_name: "", label: "Conto corrente", iban: "", balance: "", balance_date: todayIso(),
    card_last4: "", linked_account_id: "", card_debit_day: "" };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const isCard = form.account_type === "carta";
  const banks = accounts.filter((a) => a.account_type !== "carta" && a.status !== "scollegato");

  const setType = (t) => setForm((f) => ({ ...f, account_type: t, label: t === "carta" ? "Carta di credito" : "Conto corrente",
    linked_account_id: t === "carta" ? (f.linked_account_id || banks[0]?.id || "") : "" }));

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const body = { ...form, linked_account_id: form.linked_account_id || null, card_debit_day: form.card_debit_day ? Number(form.card_debit_day) : null };
      const res = await api.post(`/companies/${companyId}/bank-accounts/manual`, body);
      setForm(empty);
      onDone(res.data);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={isCard ? "Aggiungi una carta di credito" : "Aggiungi un conto manuale"}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={submit} loading={busy} disabled={!form.bank_name.trim()}>Aggiungi</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex gap-2 sm:col-span-2" role="radiogroup" aria-label="Tipo">
          {[["conto", "Conto corrente"], ["carta", "Carta di credito"]].map(([k, l]) => (
            <button key={k} type="button" role="radio" aria-checked={form.account_type === k} onClick={() => setType(k)}
              className={`min-h-[44px] flex-1 rounded-lg border text-sm font-semibold ${form.account_type === k ? "border-accent bg-accent-soft text-accent-dark" : "border-line"}`}>{l}</button>
          ))}
        </div>
        <p className="text-sm text-muted sm:col-span-2">
          {isCard
            ? "Le spese della carta arrivano importando l'estratto mensile (PDF, Excel o CSV). Il saldo della carta è il debito che verrà addebitato sul conto: il bonifico di addebito e il pagamento sull'estratto carta si riconoscono come giroconto, così le spese non contano due volte."
            : "I movimenti di questo conto si caricano importando l'estratto conto scaricato dall'home banking (PDF, Excel, CSV, CAMT o CBI). Potrai renderlo automatico in seguito, senza perdere i dati."}
        </p>
        {error && <div className="sm:col-span-2"><ErrorBox>{error}</ErrorBox></div>}
        <Field label={isCard ? "Emittente" : "Banca"} htmlFor="ma-bank"><input id="ma-bank" className="input" value={form.bank_name} onChange={set("bank_name")} placeholder={isCard ? "Es. Nexi, American Express" : "Es. Intesa Sanpaolo"} /></Field>
        <Field label={isCard ? "Nome della carta" : "Nome del conto"} htmlFor="ma-label"><input id="ma-label" className="input" value={form.label} onChange={set("label")} /></Field>
        {isCard ? (
          <>
            <Field label="Ultime 4 cifre" htmlFor="ma-last4"><input id="ma-last4" inputMode="numeric" maxLength={4} className="input font-mono" value={form.card_last4} onChange={set("card_last4")} /></Field>
            <Field label="Giorno di addebito sul conto" htmlFor="ma-day"><input id="ma-day" inputMode="numeric" className="input" value={form.card_debit_day} onChange={set("card_debit_day")} placeholder="15" /></Field>
            <div className="sm:col-span-2">
              <Field label="Conto su cui si addebita" htmlFor="ma-link">
                <select id="ma-link" className="input" value={form.linked_account_id} onChange={set("linked_account_id")}>
                  <option value="">— non indicato —</option>
                  {banks.map((b) => <option key={b.id} value={b.id}>{b.bank_name} · {b.label} {b.iban_masked}</option>)}
                </select>
              </Field>
            </div>
            <Field label="Da addebitare oggi (facoltativo)" htmlFor="ma-bal"><input id="ma-bal" inputMode="decimal" className="input" value={form.balance} onChange={set("balance")} placeholder="1.250,00" /></Field>
          </>
        ) : (
          <>
            <div className="sm:col-span-2">
              <Field label="IBAN" htmlFor="ma-iban" hint="Serve per controllare che l'estratto conto caricato sia di questo conto.">
                <input id="ma-iban" className="input font-mono" value={form.iban} onChange={set("iban")} placeholder="IT60 X054 2811 1010 0000 0123 456" />
              </Field>
            </div>
            <Field label="Saldo attuale (facoltativo)" htmlFor="ma-bal"><input id="ma-bal" inputMode="decimal" className="input" value={form.balance} onChange={set("balance")} placeholder="10.000,00" /></Field>
          </>
        )}
        <Field label="Alla data" htmlFor="ma-date"><input id="ma-date" type="date" className="input" value={form.balance_date} onChange={set("balance_date")} /></Field>
      </div>
    </Modal>
  );
}

const MAP_FIELDS = [
  ["date", "Data del movimento", true],
  ["value_date", "Data valuta", false],
  ["amount", "Importo (con segno)", false],
  ["debit", "Uscite / Dare", false],
  ["credit", "Entrate / Avere", false],
  ["balance", "Saldo", false],
];

/** Correzione a mano del saldo di un conto manuale. */
export function BalanceModal({ account, onClose, onDone }) {
  const [balance, setBalance] = useState("");
  const [date, setDate] = useState(todayIso());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!account) return;
    setBalance((Math.abs(account.balance_cents) / 100 * (account.balance_cents < 0 && account.account_type !== "carta" ? -1 : 1)).toLocaleString("it-IT", { minimumFractionDigits: 2 }));
    setDate(todayIso());
    setError("");
  }, [account]);

  if (!account) return null;

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api.put(`/bank-accounts/${account.id}/balance`, { balance, balance_date: date });
      onDone(res.data);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={`Correggi saldo · ${account.bank_name} · ${account.label}`}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button loading={busy} onClick={save} disabled={!balance.trim()} data-testid="balance-save">Salva saldo</Button></>}>
      <div className="flex flex-col gap-4" data-testid="balance-modal">
        <ErrorBox>{error}</ErrorBox>
        <p className="text-sm text-muted">Saldo attuale: <Amount cents={account.balance_cents} /></p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={account.account_type === "carta" ? "Debito della carta" : "Saldo giusto del conto"} htmlFor="bal-new" hint="Usa il meno per un saldo negativo, es. -1.250,00">
            <input id="bal-new" inputMode="decimal" className="input" value={balance} onChange={(e) => setBalance(e.target.value)} data-testid="balance-input" />
          </Field>
          <Field label="Alla data" htmlFor="bal-date">
            <input id="bal-date" type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} data-testid="balance-date-input" />
          </Field>
        </div>
        <Notice>I prossimi estratti che caricherai aggiungeranno i loro movimenti a questo saldo.</Notice>
      </div>
    </Modal>
  );
}

export const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

const rowCounts = (r, include) => !r.duplicate && (!r.similar || include.has(r.index));

/** Elenco completo dei movimenti letti: i possibili doppioni si spuntano per importarli comunque. */
function PreviewRows({ rows, include, onToggle }) {
  return (
    <div className="max-h-[420px] overflow-auto rounded-xl border border-line" data-testid="import-preview-rows">
      <table className="w-full min-w-[620px] text-sm">
        <thead className="sticky top-0 bg-white">
          <tr className="table-head text-left">
            <th className="px-3 py-2">Data</th><th className="py-2 pr-3">Descrizione</th><th className="py-2 pr-3 text-right">Importo</th><th className="py-2 pr-3" />
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.index} className={`border-b border-soft align-top ${m.duplicate || (m.similar && !include.has(m.index)) ? "opacity-60" : ""}`}
              data-testid={`import-row-${m.index}`}>
              <td className="whitespace-nowrap px-3 py-2 text-muted">{fmtDate(m.date, { year: true })}</td>
              <td className="py-2 pr-3">
                <span data-testid={`import-row-desc-${m.index}`}>{m.description}</span>
                {m.similar && <span className="block text-xs text-warn-text">Simile a un movimento già presente del {fmtDate(m.similar.date, { year: true })}: {m.similar.description}</span>}
              </td>
              <td className="whitespace-nowrap py-2 pr-3 text-right"><Amount cents={m.amount_cents} /></td>
              <td className="whitespace-nowrap py-2 pr-3">
                {m.duplicate && <Badge>Già presente</Badge>}
                {m.similar && (
                  <label className="flex min-h-[36px] items-center gap-2 text-xs font-semibold">
                    <input type="checkbox" className="h-[18px] w-[18px]" checked={include.has(m.index)} onChange={() => onToggle(m.index)}
                      data-testid={`import-include-${m.index}`} />
                    Importa comunque
                  </label>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Saldo dopo l'import: base + movimenti scelti, con eventuale correzione a mano. */
function BalanceBox({ preview, include, balance, setBalance, balanceDate, setBalanceDate }) {
  const plan = preview.balance_plan;
  const [manual, setManual] = useState(false);
  const sum = preview.rows.filter((r) => rowCounts(r, include) && (!plan.after_date || r.date > plan.after_date))
    .reduce((t, r) => t + r.amount_cents, 0);
  const after = plan.mode === "file" ? plan.base_cents : plan.base_cents + sum;
  const fileClosing = preview.closing_balance_cents;
  const laterMovements = plan.account_balance_date && plan.account_balance_date > preview.date_to;
  const differs = plan.mode === "sum" && !laterMovements && fileClosing !== null && fileClosing !== undefined && fileClosing !== after;
  return (
    <div className="flex flex-col gap-3">
      {preview.balance_check === "ok" && <Notice>I conti tornano: saldo iniziale + movimenti letti = saldo finale del file.</Notice>}
      <Notice>
        <span data-testid="import-balance-after">Saldo del conto dopo l'import: <strong>{eur(after)}</strong></span>
        {plan.mode === "sum" ? ` (${plan.base_label} ${eur(plan.base_cents)} ${sum < 0 ? "−" : "+"} movimenti importati ${eur(Math.abs(sum))}${plan.after_date ? `, solo quelli dopo il ${fmtDate(plan.after_date, { year: true })}` : ""}).` : " (letto dall'estratto)."}
      </Notice>
      {differs && <Notice tone="orange">Il saldo finale scritto nel file è {eur(fileClosing)}: differenza di {eur(fileClosing - after)}. Controlla i movimenti o correggi il saldo qui sotto.</Notice>}
      {!manual ? (
        <button type="button" className="min-h-[40px] self-start text-sm font-semibold text-accent" onClick={() => setManual(true)} data-testid="import-balance-manual-toggle">
          Il saldo non è giusto? Scrivilo a mano
        </button>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Saldo corretto del conto" htmlFor="st-bal" hint="Se lo scrivi, sostituisce il calcolo automatico.">
            <input id="st-bal" inputMode="decimal" className="input" value={balance} onChange={(e) => setBalance(e.target.value)} placeholder="12.725,20" data-testid="import-balance-input" />
          </Field>
          <Field label="Alla data" htmlFor="st-bal-date">
            <input id="st-bal-date" type="date" className="input" value={balanceDate} onChange={(e) => setBalanceDate(e.target.value)} />
          </Field>
        </div>
      )}
    </div>
  );
}

/** Caricamenti fatti su un conto, con la possibilità di annullarli. */
export function ImportsHistoryModal({ account, onClose, onDone }) {
  const [list, setList] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [ask, setAsk] = useState(null);

  useEffect(() => {
    if (!account) return;
    setList(null);
    setAsk(null);
    setError("");
    api.get(`/bank-accounts/${account.id}/imports`).then((r) => setList(r.data)).catch((e) => setError(errorMessage(e)));
  }, [account]);

  if (!account) return null;

  const undo = async (rec) => {
    setBusy(rec.id);
    setError("");
    try {
      const res = await api.delete(`/statement-imports/${rec.id}`);
      setAsk(null);
      onDone(res.data);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <Modal open wide onClose={onClose} title={`Caricamenti · ${account.bank_name} · ${account.label} · ${account.iban_masked}`}
      footer={<Button variant="secondary" onClick={onClose}>Chiudi</Button>}>
      <div className="flex flex-col gap-3" data-testid="imports-history">
        <ErrorBox>{error}</ErrorBox>
        {!list ? <Loading /> : list.length === 0 ? <p className="text-sm text-muted">Nessun estratto conto caricato.</p> : (
          <ul className="divide-y divide-soft">
            {list.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 py-3" data-testid={`import-history-${r.id}`}>
                <span className="min-w-[200px] flex-1 text-sm">
                  <span className="font-semibold">{r.filename}</span>
                  <span className="block text-xs text-muted">
                    {plural(r.imported, "movimento", "movimenti")} dal {fmtDate(r.date_from, { year: true })} al {fmtDate(r.date_to, { year: true })} · caricato il {fmtDate(r.at?.slice(0, 10), { year: true })}{r.imported_by_name ? ` da ${r.imported_by_name}` : ""}
                  </span>
                </span>
                {r.undone_at ? <Badge>Annullato · {plural(r.removed, "movimento tolto", "movimenti tolti")}</Badge> : ask === r.id ? (
                  <span className="flex flex-wrap items-center gap-2 text-sm">
                    Tolgo i movimenti di questo caricamento?
                    <Button variant="secondary" onClick={() => setAsk(null)}>No</Button>
                    <Button loading={busy === r.id} onClick={() => undo(r)} data-testid={`import-undo-confirm-${r.id}`}>Sì, annulla</Button>
                  </span>
                ) : (
                  <Button variant="secondary" onClick={() => setAsk(r.id)} data-testid={`import-undo-${r.id}`}>Annulla import</Button>
                )}
              </li>
            ))}
          </ul>
        )}
        <Notice>Annullando un caricamento tolgo i suoi movimenti e correggo il saldo: poi puoi ricaricare il file giusto.</Notice>
      </div>
    </Modal>
  );
}

/** Import dell'estratto conto: anteprima completa, possibili doppioni da confermare, saldo calcolato. */
export function ImportStatementModal({ account, onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState(null);
  const [editMapping, setEditMapping] = useState(false);
  const [balance, setBalance] = useState("");
  const [balanceDate, setBalanceDate] = useState("");
  const [invert, setInvert] = useState(false);
  const [include, setInclude] = useState(new Set());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const fileRef = useRef(null);

  useEffect(() => {
    setFile(null);
    setPreview(null);
    setMapping(null);
    setEditMapping(false);
    setBalance("");
    setBalanceDate("");
    setInvert(false);
    setInclude(new Set());
    setError("");
  }, [account]);

  if (!account) return null;

  const form = () => {
    const fd = new FormData();
    fd.append("file", file);
    if (mapping) fd.append("mapping", JSON.stringify(mapping));
    if (invert) fd.append("invert", "true");
    if (include.size) fd.append("include", JSON.stringify([...include]));
    if (balance.trim()) {
      fd.append("closing_balance", balance);
      fd.append("closing_balance_date", balanceDate);
    }
    return fd;
  };

  const runPreview = async (f = file, m = mapping, inv = invert) => {
    if (!f) return;
    setBusy("preview");
    setError("");
    setInclude(new Set());
    try {
      const fd = new FormData();
      fd.append("file", f);
      if (m) fd.append("mapping", JSON.stringify(m));
      if (inv) fd.append("invert", "true");
      const res = await api.post(`/bank-accounts/${account.id}/statement/preview`, fd);
      setPreview(res.data);
      if (res.data.mapping && !m) setMapping(res.data.mapping);
      if (res.data.needs_mapping) {
        setEditMapping(true);
        setMapping(res.data.detected_mapping || { description: [] });
      }
      setBalanceDate(res.data.closing_balance_date || res.data.date_to || todayIso());
    } catch (e) {
      setError(errorMessage(e));
      setPreview(null);
    } finally {
      setBusy("");
    }
  };

  const pickFile = (f) => {
    setFile(f);
    setMapping(null);
    setEditMapping(false);
    setPreview(null);
    setInvert(false);
    if (f) runPreview(f, null, false);
  };

  const submit = async () => {
    setBusy("import");
    setError("");
    try {
      const res = await api.post(`/bank-accounts/${account.id}/statement/import`, form());
      onDone(res.data);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const toggleInclude = (i) => setInclude((s) => {
    const next = new Set(s);
    next.has(i) ? next.delete(i) : next.add(i);
    return next;
  });

  const setMap = (field, value) => {
    setMapping((m) => {
      const next = { ...(m || { description: [] }) };
      if (value === "") delete next[field];
      else next[field] = Number(value);
      if (field === "amount" && value !== "") { delete next.debit; delete next.credit; }
      if ((field === "debit" || field === "credit") && value !== "") delete next.amount;
      return next;
    });
  };
  const toggleDesc = (idx) => {
    setMapping((m) => {
      const list = new Set(m?.description || []);
      list.has(idx) ? list.delete(idx) : list.add(idx);
      return { ...(m || {}), description: [...list].sort((a, b) => a - b) };
    });
  };

  const hasRows = preview && !preview.needs_mapping && preview.count > 0;
  const toImport = hasRows ? preview.new_count + include.size : 0;

  return (
    <Modal open wide onClose={onClose} title={`Importa estratto conto · ${account.bank_name} · ${account.label} · ${account.iban_masked}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Annulla</Button>
          <Button onClick={submit} loading={busy === "import"} disabled={!hasRows || (toImport === 0 && !balance.trim())} data-testid="import-submit">
            {hasRows ? `Importa ${plural(toImport, "movimento", "movimenti")}` : "Importa"}
          </Button>
        </>
      }>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <input ref={fileRef} id="st-file" type="file" className="sr-only" data-testid="import-file-input"
            accept=".pdf,.csv,.txt,.xlsx,.xls,.xml,application/pdf,text/csv,application/xml,text/xml,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => pickFile(e.target.files?.[0] || null)} />
          <Button variant="secondary" onClick={() => fileRef.current?.click()}>{file ? "Cambia file" : "Scegli il file"}</Button>
          <span className="text-sm text-muted">{file ? file.name : "PDF, Excel (.xlsx o .xls), CSV, CAMT.053 (.xml) o CBI (.txt)"}</span>
        </div>
        {!file && (
          <Notice>
            {account.account_type === "carta"
              ? "Carica l'estratto mensile della carta, anche in PDF. Gli importi senza segno sono spese; rimborsi e pagamento del saldo diventano entrate della carta."
              : "Va bene anche il PDF dell'estratto conto. Se l'home banking lo permette, il file Excel o CSV («Lista movimenti» o «Esporta movimenti») è ancora più preciso; per i conti aziendali anche CAMT.053 o CBI."}
            {" "}Puoi caricare anche periodi che si sovrappongono: i movimenti già presenti non vengono duplicati e quelli simili te li faccio confermare.
          </Notice>
        )}
        <ErrorBox>{error}</ErrorBox>
        {busy === "preview" && <Loading text="Leggo il file…" />}

        {preview && busy !== "preview" && (
          <>
            {preview.needs_mapping ? (
              <Notice tone="orange">{preview.error} Indica qui sotto quali colonne contengono data, importo e descrizione.</Notice>
            ) : (
              <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="import-preview-summary">
                <Badge tone="blue">{preview.format_label}</Badge>
                <span>{plural(preview.count, "movimento", "movimenti")} dal {fmtDate(preview.date_from, { year: true })} al {fmtDate(preview.date_to, { year: true })}</span>
                <span className="text-muted">· entrate {eur(preview.total_in_cents)} · uscite {eur(preview.total_out_cents)}</span>
                {preview.duplicate_count > 0 && <Badge>{preview.duplicate_count} già presenti</Badge>}
                {preview.similar_count > 0 && <Badge tone="orange">{plural(preview.similar_count, "possibile doppione", "possibili doppioni")}</Badge>}
              </div>
            )}
            {preview.similar_count > 0 && (
              <Notice tone="orange">{preview.similar_count === 1 ? "1 movimento ha" : `${preview.similar_count} movimenti hanno`} lo stesso importo e una data vicina a movimenti già presenti sul conto: non {preview.similar_count === 1 ? "lo" : "li"} importo, a meno che tu non spunti «Importa comunque».</Notice>
            )}
            {preview.warnings?.map((w) => <Notice key={w} tone="orange">{w}</Notice>)}
            {!preview.needs_mapping && (
              <label className="flex min-h-[40px] items-center gap-2 text-sm">
                <input type="checkbox" className="h-[18px] w-[18px]" checked={invert}
                  onChange={(e) => { setInvert(e.target.checked); runPreview(file, mapping, e.target.checked); }} />
                Inverti i segni (se le entrate risultano uscite e viceversa)
              </label>
            )}

            {preview.headers && (
              <div className="flex flex-col gap-3">
                {!editMapping ? (
                  <button type="button" className="min-h-[40px] self-start text-sm font-semibold text-accent" onClick={() => setEditMapping(true)}>
                    Le colonne non sono giuste? Sceglile a mano
                  </button>
                ) : (
                  <div className="flex flex-col gap-3 rounded-xl border border-line p-4">
                    <span className="label">Quale colonna è quale</span>
                    <div className="grid gap-3 sm:grid-cols-3">
                      {MAP_FIELDS.map(([field, label, required]) => (
                        <Field key={field} label={label + (required ? " *" : "")} htmlFor={`map-${field}`}>
                          <select id={`map-${field}`} className="input" value={mapping?.[field] ?? ""} onChange={(e) => setMap(field, e.target.value)}>
                            <option value="">— nessuna —</option>
                            {preview.headers.map((h, i) => <option key={i} value={i}>{h}</option>)}
                          </select>
                        </Field>
                      ))}
                    </div>
                    <fieldset>
                      <legend className="label mb-2">Descrizione (anche più colonne)</legend>
                      <div className="flex flex-wrap gap-x-4">
                        {preview.headers.map((h, i) => (
                          <label key={i} className="flex min-h-[40px] items-center gap-2 text-sm">
                            <input type="checkbox" className="h-[18px] w-[18px]" checked={(mapping?.description || []).includes(i)} onChange={() => toggleDesc(i)} />
                            {h}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                    {preview.raw_rows?.length > 0 && (
                      <div className="overflow-x-auto rounded-lg bg-page p-2">
                        <table className="text-xs">
                          <thead><tr>{preview.headers.map((h, i) => <th key={i} className="px-2 py-1 text-left font-semibold">{h}</th>)}</tr></thead>
                          <tbody>{preview.raw_rows.map((r, n) => <tr key={n}>{r.map((c, i) => <td key={i} className="whitespace-nowrap px-2 py-1">{c}</td>)}</tr>)}</tbody>
                        </table>
                      </div>
                    )}
                    <div>
                      <Button variant="secondary" loading={busy === "preview"} disabled={mapping?.date === undefined}
                        onClick={() => runPreview(file, mapping)}>Aggiorna anteprima</Button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {hasRows && (
              <>
                <PreviewRows rows={preview.rows} include={include} onToggle={toggleInclude} />
                {preview.count > preview.rows.length && <p className="text-xs text-muted">Mostro i primi {preview.rows.length} movimenti su {preview.count}.</p>}
                <BalanceBox preview={preview} include={include} balance={balance} setBalance={setBalance} balanceDate={balanceDate} setBalanceDate={setBalanceDate} />
                {toImport === 0 && <Notice tone="orange">Nessun movimento nuovo da importare in questo file.</Notice>}
              </>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
