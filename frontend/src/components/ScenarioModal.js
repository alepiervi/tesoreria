import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, errorMessage } from "../lib/api";
import { eur, eurK, fmtDate, todayIso } from "../lib/format";
import { Button, ErrorBox, Field, Loading, Modal, Notice } from "./ui";

const AXIS = { fontSize: 12, fill: "#5B6170" };

function Compare({ base, scenario }) {
  const data = base.weeks.map((w, i) => ({
    label: `S${w.week}`, tooltip: `Settimana dal ${fmtDate(w.start)}`,
    base: w.balance_end_cents, scenario: scenario.weeks[i].balance_end_cents,
  }));
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="#EEF0F2" />
          <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={eurK} tick={AXIS} axisLine={false} tickLine={false} width={56} />
          <ReferenceLine y={0} stroke="#A8480F" strokeDasharray="4 4" />
          <Tooltip formatter={(v) => eur(v)} labelFormatter={(l, p) => p?.[0]?.payload?.tooltip || l} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line type="monotone" dataKey="base" name="Situazione attuale" stroke="#8FA2EE" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="scenario" name="Con lo scenario" stroke="#E8772E" strokeWidth={2.5} dot={{ r: 3 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** "Cosa succede se...": sposta incassi o pagamenti, toglili, aggiungi entrate o uscite ipotetiche. Non modifica i dati. */
export default function ScenarioModal({ open, companyId, title, onClose }) {
  const [items, setItems] = useState([]);
  const [adjustments, setAdjustments] = useState([]);
  const [weeks, setWeeks] = useState(12);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ type: "delay", deadline_id: "", days: 30, date: todayIso(), amount: "", sign: "-", description: "", name: "" });

  useEffect(() => {
    if (!open) return;
    setAdjustments([]);
    setResult(null);
    api.get("/forecast/open-items", { params: { company_id: companyId || undefined } })
      .then((r) => setItems(r.data)).catch((e) => setError(errorMessage(e)));
  }, [open, companyId]);

  useEffect(() => {
    if (!open) return;
    setBusy(true);
    api.post("/forecast/scenario", { company_id: companyId || null, weeks, adjustments })
      .then((r) => { setResult(r.data); setError(""); })
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setBusy(false));
  }, [open, companyId, weeks, adjustments]);

  if (!open) return null;
  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.value }));
  const label = (a) => {
    const it = items.find((i) => i.id === a.deadline_id);
    if (a.type === "delay") return `Sposta di ${a.days} giorni: ${it?.description || ""}`;
    if (a.type === "skip") return `Togli: ${it?.description || ""}`;
    if (a.type === "delay_party") return `Tutti gli incassi da "${a.name}" arrivano ${a.days} giorni dopo`;
    return `${a.amount_cents > 0 ? "Entrata" : "Uscita"} il ${fmtDate(a.date, { year: true })}: ${a.description || ""} ${eur(Math.abs(a.amount_cents))}`;
  };
  const add = () => {
    const d = draft;
    let a;
    if (d.type === "extra") {
      const cents = Math.round(parseFloat(String(d.amount).replace(/\./g, "").replace(",", ".")) * 100);
      if (!cents || !d.date) return setError("Indica data e importo.");
      a = { type: "extra", date: d.date, amount_cents: d.sign === "-" ? -cents : cents, description: d.description, company_id: companyId || null };
    } else if (d.type === "delay_party") {
      if (!d.name.trim()) return setError("Indica il nome del cliente.");
      a = { type: "delay_party", name: d.name.trim(), days: Number(d.days) || 30, kind: "incasso" };
    } else {
      if (!d.deadline_id) return setError("Scegli l'incasso o il pagamento.");
      a = { type: d.type, deadline_id: d.deadline_id, days: Number(d.days) || 30 };
    }
    setError("");
    setAdjustments((list) => [...list, a]);
  };

  const diffEnd = result ? result.scenario.weeks.at(-1).balance_end_cents - result.base.weeks.at(-1).balance_end_cents : 0;

  return (
    <Modal open wide onClose={onClose} title={`Prova uno scenario${title ? ` · ${title}` : ""}`}>
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted">Simula cosa succede alla cassa se un cliente paga in ritardo, se rimandi un pagamento o se arriva una spesa. I dati veri non cambiano.</p>
        <ErrorBox>{error}</ErrorBox>
        <div className="flex flex-col gap-3 rounded-xl border border-line p-4">
          <div className="grid gap-3 sm:grid-cols-[220px_1fr]">
            <Field label="Cosa vuoi provare" htmlFor="sc-type">
              <select id="sc-type" className="input" value={draft.type} onChange={set("type")}>
                <option value="delay">Spostare un incasso o pagamento</option>
                <option value="delay_party">Un cliente paga in ritardo</option>
                <option value="skip">Togliere un incasso o pagamento</option>
                <option value="extra">Aggiungere un'entrata o una spesa</option>
              </select>
            </Field>
            {(draft.type === "delay" || draft.type === "skip") && (
              <Field label="Quale" htmlFor="sc-item">
                <select id="sc-item" className="input" value={draft.deadline_id} onChange={set("deadline_id")}>
                  <option value="">Scegli…</option>
                  {items.map((i) => (
                    <option key={i.id} value={i.id}>{fmtDate(i.due_date)} · {i.kind === "incasso" ? "+" : "−"}{eur(i.amount_cents)} · {i.description}</option>
                  ))}
                </select>
              </Field>
            )}
            {draft.type === "delay_party" && (
              <Field label="Nome del cliente (anche parziale)" htmlFor="sc-name"><input id="sc-name" className="input" value={draft.name} onChange={set("name")} placeholder="Es. Delta" /></Field>
            )}
            {draft.type === "extra" && (
              <div className="grid gap-3 sm:grid-cols-[110px_1fr_140px]">
                <Field label="Tipo" htmlFor="sc-sign"><select id="sc-sign" className="input" value={draft.sign} onChange={set("sign")}><option value="-">Uscita</option><option value="+">Entrata</option></select></Field>
                <Field label="Descrizione" htmlFor="sc-desc"><input id="sc-desc" className="input" value={draft.description} onChange={set("description")} placeholder="Es. nuovo macchinario" /></Field>
                <Field label="Importo (€)" htmlFor="sc-amt"><input id="sc-amt" inputMode="decimal" className="input" value={draft.amount} onChange={set("amount")} /></Field>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            {(draft.type === "delay" || draft.type === "delay_party") && (
              <Field label="Di quanti giorni" htmlFor="sc-days"><input id="sc-days" type="number" min={1} className="input w-28" value={draft.days} onChange={set("days")} /></Field>
            )}
            {draft.type === "extra" && (
              <Field label="Quando" htmlFor="sc-date"><input id="sc-date" type="date" className="input" value={draft.date} onChange={set("date")} /></Field>
            )}
            <Button variant="secondary" onClick={add}>Aggiungi allo scenario</Button>
          </div>
        </div>

        {adjustments.length > 0 && (
          <ul className="flex flex-col gap-2">
            {adjustments.map((a, n) => (
              <li key={n} className="flex items-center justify-between gap-3 rounded-lg bg-page px-3 py-2 text-sm">
                <span>{label(a)}</span>
                <Button variant="ghost" className="min-h-[36px] px-2" onClick={() => setAdjustments((l) => l.filter((_, i) => i !== n))}>Togli</Button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex items-center justify-between gap-3">
          <span className="label">Saldo previsto</span>
          <select aria-label="Orizzonte" className="input w-auto" value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
            <option value={8}>8 settimane</option><option value={12}>12 settimane</option><option value={26}>6 mesi</option>
          </select>
        </div>
        {!result || busy ? <Loading /> : (
          <>
            <Compare base={result.base} scenario={result.scenario} />
            {adjustments.length > 0 && (
              <Notice tone={result.scenario.goes_negative || diffEnd < 0 ? "orange" : "blue"}>
                Con lo scenario il saldo a fine periodo è {eur(result.scenario.weeks.at(-1).balance_end_cents)} ({eur(diffEnd, { signed: true })} rispetto a oggi).
                Punto più basso: {eur(result.scenario.lowest.balance_cents)}
                {result.scenario.lowest.week ? ` nella settimana ${result.scenario.lowest.week}` : ""}.
                {result.scenario.goes_negative && (result.scenario.credit_available_cents
                  ? ` Il saldo va sotto zero: i fidi disponibili (${eur(result.scenario.credit_available_cents)}) ${result.scenario.uses_credit_lines ? "bastano a coprirlo" : "non bastano"}.`
                  : " Il saldo va sotto zero.")}
              </Notice>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
