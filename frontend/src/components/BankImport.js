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

/** Import dell'estratto conto: anteprima, eventuale scelta delle colonne, conferma. */
export function ImportStatementModal({ account, onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState(null);
  const [editMapping, setEditMapping] = useState(false);
  const [balance, setBalance] = useState("");
  const [balanceDate, setBalanceDate] = useState("");
  const [invert, setInvert] = useState(false);
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
    setError("");
  }, [account]);

  if (!account) return null;

  const form = (withBalance) => {
    const fd = new FormData();
    fd.append("file", file);
    if (mapping) fd.append("mapping", JSON.stringify(mapping));
    if (invert) fd.append("invert", "true");
    if (withBalance && balance.trim()) {
      fd.append("closing_balance", balance);
      fd.append("closing_balance_date", balanceDate);
    }
    return fd;
  };

  const runPreview = async (f = file, m = mapping, inv = invert) => {
    if (!f) return;
    setBusy("preview");
    setError("");
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
      const res = await api.post(`/bank-accounts/${account.id}/statement/import`, form(true));
      onDone(res.data);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

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

  return (
    <Modal open wide onClose={onClose} title={`Importa estratto conto · ${account.bank_name} ${account.iban_masked}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Annulla</Button>
          <Button onClick={submit} loading={busy === "import"} disabled={!hasRows || preview.new_count === 0}>
            {hasRows ? `Importa ${preview.new_count} movimenti` : "Importa"}
          </Button>
        </>
      }>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <input ref={fileRef} id="st-file" type="file" className="sr-only"
            accept=".pdf,.csv,.txt,.xlsx,.xml,application/pdf,text/csv,application/xml,text/xml,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => pickFile(e.target.files?.[0] || null)} />
          <Button variant="secondary" onClick={() => fileRef.current?.click()}>{file ? "Cambia file" : "Scegli il file"}</Button>
          <span className="text-sm text-muted">{file ? file.name : "PDF, Excel (.xlsx), CSV, CAMT.053 (.xml) o CBI (.txt)"}</span>
        </div>
        {!file && (
          <Notice>
            {account.account_type === "carta"
              ? "Carica l'estratto mensile della carta, anche in PDF. Gli importi senza segno sono spese; rimborsi e pagamento del saldo diventano entrate della carta."
              : "Va bene anche il PDF dell'estratto conto. Se l'home banking lo permette, il file Excel o CSV («Lista movimenti» o «Esporta movimenti») è ancora più preciso; per i conti aziendali anche CAMT.053 o CBI."}
            {" "}Puoi caricare anche periodi che si sovrappongono: i movimenti già presenti non vengono duplicati.
          </Notice>
        )}
        <ErrorBox>{error}</ErrorBox>
        {busy === "preview" && <Loading text="Leggo il file…" />}

        {preview && busy !== "preview" && (
          <>
            {preview.needs_mapping ? (
              <Notice tone="orange">{preview.error} Indica qui sotto quali colonne contengono data, importo e descrizione.</Notice>
            ) : (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone="blue">{preview.format_label}</Badge>
                <span>{preview.count} movimenti dal {fmtDate(preview.date_from, { year: true })} al {fmtDate(preview.date_to, { year: true })}</span>
                <span className="text-muted">· entrate {eur(preview.total_in_cents)} · uscite {eur(preview.total_out_cents)}</span>
                {preview.duplicate_count > 0 && <Badge>{preview.duplicate_count} già presenti</Badge>}
              </div>
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
                <div className="overflow-x-auto rounded-xl border border-line">
                  <table className="w-full min-w-[560px] text-sm">
                    <thead>
                      <tr className="table-head text-left">
                        <th className="px-3 py-2">Data</th><th className="py-2 pr-3">Descrizione</th><th className="py-2 pr-3 text-right">Importo</th><th className="py-2 pr-3" />
                      </tr>
                    </thead>
                    <tbody>
                      {preview.sample.map((m, n) => (
                        <tr key={n} className={`border-b border-soft ${m.duplicate ? "opacity-50" : ""}`}>
                          <td className="whitespace-nowrap px-3 py-2 text-muted">{fmtDate(m.date, { year: true })}</td>
                          <td className="py-2 pr-3">{m.description}</td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right"><Amount cents={m.amount_cents} /></td>
                          <td className="py-2 pr-3">{m.duplicate && <Badge>Già presente</Badge>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {preview.count > preview.sample.length && (
                    <p className="px-3 py-2 text-xs text-muted">…e altri {preview.count - preview.sample.length} movimenti</p>
                  )}
                </div>

                {preview.closing_balance_cents !== null && preview.closing_balance_cents !== undefined ? (
                  <Notice>Saldo letto dal file: <strong>{eur(preview.closing_balance_cents)}</strong> al {fmtDate(preview.closing_balance_date, { year: true })}. Verrà aggiornato il saldo del conto.</Notice>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Saldo finale dell'estratto conto" htmlFor="st-bal" hint="Il file non contiene il saldo: scrivilo per tenere aggiornata la liquidità.">
                      <input id="st-bal" inputMode="decimal" className="input" value={balance} onChange={(e) => setBalance(e.target.value)} placeholder="12.725,20" />
                    </Field>
                    <Field label="Alla data" htmlFor="st-bal-date">
                      <input id="st-bal-date" type="date" className="input" value={balanceDate} onChange={(e) => setBalanceDate(e.target.value)} />
                    </Field>
                  </div>
                )}
                {preview.new_count === 0 && <Notice tone="orange">Tutti i movimenti di questo file sono già stati importati.</Notice>}
              </>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
