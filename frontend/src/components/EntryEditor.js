import { useEffect, useMemo, useState } from "react";
import { AccountSelect, centsToInput, parseEuro } from "../lib/accounting";
import { api, errorMessage } from "../lib/api";
import { eur, todayIso } from "../lib/format";
import { Button, ErrorBox, Field, Modal } from "./ui";

const blankLine = () => ({ account: "", dare: "", avere: "", party_name: "", cost_center_id: "", description: "" });

/** Finestra per creare o modificare una registrazione di prima nota. */
export default function EntryEditor({ open, onClose, companyId, accounts, costCenters, entry, onSaved }) {
  const [templates, setTemplates] = useState([]);
  const [causali, setCausali] = useState({});
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || !companyId) return;
    api.get(`/companies/${companyId}/entry-templates`).then((r) => {
      setTemplates(r.data.templates);
      setCausali(r.data.causali);
    }).catch(() => {});
  }, [open, companyId]);

  useEffect(() => {
    if (!open) return;
    setError("");
    if (entry) {
      setForm({
        date: entry.date, causale: entry.causale, description: entry.description || "", doc_number: entry.doc_number || "",
        lines: entry.lines.map((l) => ({
          account: l.account, dare: centsToInput(l.dare), avere: centsToInput(l.avere), party_name: l.party_name || "",
          cost_center_id: l.cost_center_id || "", description: l.description || "",
        })),
      });
    } else {
      setForm({ date: todayIso(), causale: "GEN", description: "", doc_number: "", lines: [blankLine(), blankLine()] });
    }
  }, [open, entry]);

  const totals = useMemo(() => {
    if (!form) return { dare: 0, avere: 0, invalid: false };
    let dare = 0, avere = 0, invalid = false;
    form.lines.forEach((l) => {
      const d = parseEuro(l.dare), a = parseEuro(l.avere);
      if (d === null || a === null) invalid = true;
      dare += d || 0;
      avere += a || 0;
    });
    return { dare, avere, invalid };
  }, [form]);

  if (!open || !form) return null;

  const setLine = (i, patch) => setForm((f) => ({ ...f, lines: f.lines.map((l, n) => (n === i ? { ...l, ...patch } : l)) }));
  const partyAccount = (code) => (accounts || []).find((a) => a.code === code)?.party;

  const applyTemplate = (id) => {
    const t = templates.find((x) => x.id === id);
    if (!t) return;
    setForm((f) => ({
      ...f, causale: t.causale, description: f.description || (t.id === "generica" ? "" : t.label.replace(/ \(.*\)$/, "")),
      lines: t.lines.length ? t.lines.map((l) => ({ ...blankLine(), account: l.account, dare: l.side === "D" && l.amount ? centsToInput(l.amount) : "",
        avere: l.side === "A" && l.amount ? centsToInput(l.amount) : "" })) : [blankLine(), blankLine()],
    }));
  };

  const balanceLine = (i) => {
    const l = form.lines[i];
    const diff = totals.dare - totals.avere - ((parseEuro(l.dare) || 0) - (parseEuro(l.avere) || 0));
    setLine(i, diff > 0 ? { dare: "", avere: centsToInput(diff) } : { dare: centsToInput(-diff), avere: "" });
  };

  const save = async () => {
    setError("");
    if (totals.invalid) return setError("Controlla gli importi: usa numeri come 1.234,56.");
    const lines = form.lines.filter((l) => l.account && (parseEuro(l.dare) || parseEuro(l.avere)))
      .map((l) => ({ account: l.account, dare: parseEuro(l.dare) || 0, avere: parseEuro(l.avere) || 0,
        party_name: l.party_name || null, cost_center_id: l.cost_center_id || null, description: l.description || null }));
    if (lines.length < 2) return setError("Servono almeno due righe con conto e importo.");
    if (totals.dare !== totals.avere) return setError("Dare e avere non quadrano.");
    setBusy(true);
    try {
      const body = { date: form.date, causale: form.causale, description: form.description, doc_number: form.doc_number || null, lines };
      if (entry) await api.put(`/entries/${entry.id}`, body);
      else await api.post(`/companies/${companyId}/entries`, body);
      onSaved();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const diff = totals.dare - totals.avere;
  return (
    <Modal open={open} onClose={onClose} wide title={entry ? `Modifica registrazione n. ${entry.number || ""}` : "Nuova registrazione"}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Annulla</Button>
        <Button onClick={save} loading={busy} disabled={diff !== 0 || !totals.dare}>Registra</Button>
      </>}>
      <div className="flex flex-col gap-4">
        {!entry && templates.length > 0 && (
          <Field label="Parti da un modello" htmlFor="tpl" hint="Precompila i conti: poi inserisci gli importi.">
            <select id="tpl" className="input" defaultValue="" onChange={(e) => applyTemplate(e.target.value)}>
              <option value="" disabled>— scegli un modello —</option>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </Field>
        )}
        <div className="grid gap-3 sm:grid-cols-[150px_1fr_150px]">
          <Field label="Data" htmlFor="e-date"><input id="e-date" type="date" className="input" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></Field>
          <Field label="Causale" htmlFor="e-caus">
            <select id="e-caus" className="input" value={form.causale} onChange={(e) => setForm({ ...form, causale: e.target.value })}>
              {Object.entries(causali).map(([k, v]) => <option key={k} value={k}>{k} · {v}</option>)}
            </select>
          </Field>
          <Field label="N. documento" htmlFor="e-doc"><input id="e-doc" className="input" value={form.doc_number} onChange={(e) => setForm({ ...form, doc_number: e.target.value })} /></Field>
        </div>
        <Field label="Descrizione" htmlFor="e-desc"><input id="e-desc" className="input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>

        <div className="flex flex-col gap-3">
          {form.lines.map((l, i) => (
            <div key={i} className="flex flex-col gap-2 rounded-lg border border-line p-3">
              <div className="grid gap-2 md:grid-cols-[1fr_130px_130px_auto]">
                <AccountSelect accounts={accounts} value={l.account} onChange={(v) => setLine(i, { account: v })} id={`l-acc-${i}`} />
                <input aria-label="Dare" inputMode="decimal" placeholder="Dare" className="input num text-right" value={l.dare}
                  onChange={(e) => setLine(i, { dare: e.target.value, avere: e.target.value ? "" : l.avere })} />
                <input aria-label="Avere" inputMode="decimal" placeholder="Avere" className="input num text-right" value={l.avere}
                  onChange={(e) => setLine(i, { avere: e.target.value, dare: e.target.value ? "" : l.dare })} />
                <div className="flex gap-1">
                  <Button variant="ghost" className="px-2" onClick={() => balanceLine(i)} title="Metti qui la differenza">Pareggia</Button>
                  <Button variant="ghost" className="px-2 text-warn-text" aria-label="Togli riga" disabled={form.lines.length <= 2}
                    onClick={() => setForm((f) => ({ ...f, lines: f.lines.filter((_, n) => n !== i) }))}>✕</Button>
                </div>
              </div>
              <div className="grid gap-2 md:grid-cols-3">
                {partyAccount(l.account) && (
                  <input aria-label="Cliente o fornitore" placeholder={partyAccount(l.account) === "fornitore" ? "Fornitore" : "Cliente / società"} className="input"
                    value={l.party_name} onChange={(e) => setLine(i, { party_name: e.target.value })} />
                )}
                {costCenters?.length > 0 && (
                  <select aria-label="Centro di costo" className="input" value={l.cost_center_id} onChange={(e) => setLine(i, { cost_center_id: e.target.value })}>
                    <option value="">Nessun centro di costo / commessa</option>
                    {costCenters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                )}
                <input aria-label="Nota di riga" placeholder="Nota di riga (facoltativa)" className="input" value={l.description}
                  onChange={(e) => setLine(i, { description: e.target.value })} />
              </div>
            </div>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button variant="secondary" onClick={() => setForm((f) => ({ ...f, lines: [...f.lines, blankLine()] }))}>Aggiungi riga</Button>
            <div className="num flex flex-wrap gap-4 text-sm">
              <span>Dare <b>{eur(totals.dare)}</b></span>
              <span>Avere <b>{eur(totals.avere)}</b></span>
              <span className={diff ? "font-bold text-warn-amount" : "font-semibold text-accent-dark"}>
                {diff ? `Differenza ${eur(Math.abs(diff))}` : "In pareggio"}
              </span>
            </div>
          </div>
        </div>
        <ErrorBox>{error}</ErrorBox>
      </div>
    </Modal>
  );
}
