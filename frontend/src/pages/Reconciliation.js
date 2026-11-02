import { useCallback, useEffect, useState } from "react";
import CompanyPicker from "../components/CompanyPicker";
import NotesDrawer from "../components/NotesDrawer";
import { Amount, Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { eur, fmtDate } from "../lib/format";

const CONF = { alta: ["Affidabilità alta", "blue"], media: ["Affidabilità media", "gray"], bassa: ["Da verificare", "orange"] };

export default function Reconciliation() {
  const { anyCan, refreshCounts } = useAuth();
  const toast = useToast();
  const [companyId, setCompanyId] = useState("");
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [manualFor, setManualFor] = useState(null);
  const [excludeFor, setExcludeFor] = useState(null);
  const [notesFor, setNotesFor] = useState(null);
  const [aiEnabled, setAiEnabled] = useState(false);

  useEffect(() => {
    api.get("/assistant/status").then((r) => setAiEnabled(r.data.enabled)).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    try {
      const res = await api.get("/reconciliation", { params: { company_id: companyId || undefined } });
      setItems(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [companyId]);

  useEffect(() => {
    load();
  }, [load]);

  const after = (text) => {
    toast(text);
    load();
    refreshCounts();
  };

  const confirm = async (tx, suggestion) => {
    setBusy(tx.id);
    try {
      await api.post(`/transactions/${tx.id}/match`, { targets: suggestion.targets.map((t) => ({ type: t.type, id: t.id })) });
      after("Movimento riconciliato");
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
    }
  };

  const confirmIntercompany = async (tx) => {
    const sug = tx.intercompany_suggestion;
    setBusy(tx.id);
    try {
      await api.post("/intercompany/confirm", {
        tx_ids: [tx.id, sug.pair?.id].filter(Boolean),
        other_company_id: sug.pair ? null : sug.other_company_id,
      });
      after("Trasferimento interno registrato");
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
    }
  };

  const askAi = async (tx) => {
    setBusy(`ai-${tx.id}`);
    try {
      const res = await api.post(`/transactions/${tx.id}/ai-suggest`);
      const r = res.data;
      if (r.targets?.length) {
        setItems((list) => list.map((t) => (t.id === tx.id ? {
          ...t, suggestions: [{ targets: r.targets, confidence: r.confidence || "bassa", reasons: [r.explanation], ai: true }],
        } : t)));
      } else {
        toast(r.explanation || "Nessun suggerimento", "orange");
      }
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
    }
  };

  const auto = async () => {
    setBusy("auto");
    try {
      const res = await api.post("/reconciliation/auto", null, { params: { company_id: companyId || undefined } });
      after(res.data.reconciled ? `${res.data.reconciled} movimenti riconciliati in automatico` : "Nessuna proposta abbastanza sicura da confermare in automatico");
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
    }
  };

  const canAny = anyCan("reconcile");

  return (
    <>
      <PageHeader title="Riconciliazione" subtitle="Abbina ogni movimento bancario alla fattura o alla scadenza che salda"
        actions={
          <>
            <CompanyPicker value={companyId} onChange={setCompanyId} allowAll />
            {canAny && <Button loading={busy === "auto"} onClick={auto}>Conferma le proposte sicure</Button>}
          </>
        } />
      {!canAny && <Notice tone="orange">Con il tuo ruolo puoi consultare i movimenti e chiedere chiarimenti, ma non confermare gli abbinamenti.</Notice>}
      <ErrorBox>{error}</ErrorBox>
      {!items ? <Loading /> : items.length === 0 ? (
        <Card><Empty title="Tutto riconciliato" text="Non ci sono movimenti in attesa di abbinamento." /></Card>
      ) : (
        <Card padded={false}>
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <h2 className="text-base font-semibold">Movimenti da abbinare</h2>
            <span className="text-[13px] text-muted">{items.length} in attesa</span>
          </div>
          <ul className="divide-y divide-line">
            {items.map((tx) => (
              <li key={tx.id} className="flex flex-col gap-4 px-5 py-4 lg:flex-row lg:items-start">
                <div className="flex min-w-0 flex-1 flex-col gap-1 lg:max-w-[340px]">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-muted">{fmtDate(tx.date, { year: true })}</span>
                    <Badge>{tx.company_name}</Badge>
                    {tx.open_question && <Badge tone="orange">Domanda aperta</Badge>}
                  </span>
                  <span className="break-words font-mono text-[13px] font-semibold">{tx.description}</span>
                  <Amount cents={tx.amount_cents} className="text-base" />
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-2">
                  <span className="text-xs text-muted">{tx.suggestions.length || tx.intercompany_suggestion ? "Abbinamenti proposti" : "Nessuna fattura o scadenza corrispondente"}</span>
                  {tx.intercompany_suggestion && (
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-accent-mid bg-accent-soft/50 p-3">
                      <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <span className="text-sm font-semibold">
                          {tx.intercompany_suggestion.kind === "giroconto" ? "Giroconto tra conti dell'azienda" : `Trasferimento con ${tx.intercompany_suggestion.other_company_name}`}
                        </span>
                        {tx.intercompany_suggestion.pair && (
                          <span className="text-xs text-muted">Controparte: {tx.intercompany_suggestion.pair.company_name} · {fmtDate(tx.intercompany_suggestion.pair.date)} · {tx.intercompany_suggestion.pair.description}</span>
                        )}
                        <span className="text-xs text-muted">{tx.intercompany_suggestion.reasons.join(" · ")} · escluso dai totali di gruppo</span>
                      </div>
                      {tx.can_reconcile && (
                        <Button loading={busy === tx.id} onClick={() => confirmIntercompany(tx)}>Conferma</Button>
                      )}
                    </div>
                  )}
                  {tx.suggestions.map((s, n) => (
                    <div key={n} className={`flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 ${s.ai ? "border-dashed border-accent-mid" : "border-line"}`}>
                      <div className="flex min-w-0 flex-1 flex-col gap-1">
                        {s.targets.map((t) => (
                          <span key={t.id} className="text-sm">{t.label} <span className="num text-muted">· {eur(t.amount_cents)}</span></span>
                        ))}
                        <span className="flex flex-wrap items-center gap-2">
                          <Badge tone={CONF[s.confidence][1]}>{CONF[s.confidence][0]}</Badge>
                          <span className="text-xs text-muted">{s.ai ? `Assistente: ${s.reasons[0]}` : s.reasons.join(" · ")}</span>
                        </span>
                      </div>
                      {tx.can_reconcile && <Button loading={busy === tx.id} onClick={() => confirm(tx, s)}>Conferma</Button>}
                    </div>
                  ))}
                  <div className="flex flex-wrap gap-2">
                    {tx.can_reconcile && <Button variant="secondary" onClick={() => setManualFor(tx)}>Cerca a mano</Button>}
                    {tx.can_reconcile && <Button variant="secondary" onClick={() => setExcludeFor(tx)}>Senza fattura</Button>}
                    {tx.can_reconcile && aiEnabled && !tx.suggestions.length && (
                      <Button variant="secondary" loading={busy === `ai-${tx.id}`} onClick={() => askAi(tx)}>Chiedi all'assistente</Button>
                    )}
                    <Button variant="secondary" onClick={() => setNotesFor({ type: "transaction", id: tx.id, companyId: tx.company_id, title: "Chiarimenti sul movimento", subtitle: `${fmtDate(tx.date, { year: true })} · ${tx.description} · ${eur(tx.amount_cents)}` })}>
                      {tx.notes_count ? `Note (${tx.notes_count})` : "Chiedi chiarimento"}
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <ManualMatchModal tx={manualFor} onClose={() => setManualFor(null)} onDone={() => { setManualFor(null); after("Movimento riconciliato"); }} />
      <ExcludeModal tx={excludeFor} onClose={() => setExcludeFor(null)} onDone={() => { setExcludeFor(null); after("Movimento segnato come senza fattura"); }} />
      <NotesDrawer target={notesFor} onClose={() => setNotesFor(null)} onChanged={load} />
    </>
  );
}

function ManualMatchModal({ tx, onClose, onDone }) {
  const [items, setItems] = useState(null);
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!tx) return;
    setItems(null);
    setPicked({});
    setError("");
    const direction = tx.amount_cents > 0 ? "attiva" : "passiva";
    api.get(`/companies/${tx.company_id}/open-items`, { params: { direction } })
      .then((r) => setItems(r.data)).catch((e) => setError(errorMessage(e)));
  }, [tx]);

  if (!tx) return null;
  const visible = (items || []).filter((i) => !q || i.label.toLowerCase().includes(q.toLowerCase()));
  const chosen = (items || []).filter((i) => picked[i.id]);
  const sum = chosen.reduce((s, i) => s + i.amount_cents, 0);
  const diff = Math.abs(tx.amount_cents) - sum;

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post(`/transactions/${tx.id}/match`, { targets: chosen.map((i) => ({ type: i.type, id: i.id })) });
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} wide title="Abbinamento manuale"
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={submit} loading={busy} disabled={!chosen.length}>Abbina {chosen.length || ""}</Button></>}>
      <div className="flex flex-col gap-4">
        <p className="text-sm"><span className="font-mono font-semibold">{tx.description}</span> · <Amount cents={tx.amount_cents} /></p>
        <ErrorBox>{error}</ErrorBox>
        <label htmlFor="mm-q" className="sr-only">Cerca</label>
        <input id="mm-q" className="input" placeholder="Cerca per numero o controparte…" value={q} onChange={(e) => setQ(e.target.value)} />
        {!items ? <Loading /> : visible.length === 0 ? <p className="text-sm text-muted">Nessuna fattura o scadenza aperta.</p> : (
          <ul className="flex max-h-[320px] flex-col divide-y divide-soft overflow-y-auto">
            {visible.map((i) => (
              <li key={i.id}>
                <label className="flex min-h-[48px] cursor-pointer items-center gap-3 py-2 text-sm">
                  <input type="checkbox" className="h-[18px] w-[18px]" checked={Boolean(picked[i.id])}
                    onChange={(e) => setPicked((p) => ({ ...p, [i.id]: e.target.checked }))} />
                  <span className="flex-1">{i.label}<span className="block text-xs text-muted">Scadenza {fmtDate(i.due_date, { year: true })}</span></span>
                  <span className="num font-semibold">{eur(i.amount_cents)}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {chosen.length > 0 && (
          <Notice tone={diff === 0 ? "blue" : "orange"}>
            Selezionato {eur(sum)}. {diff === 0 ? "L'importo corrisponde esattamente." : diff > 0 ? `Restano ${eur(diff)} del movimento non abbinati.` : `Le fatture superano il movimento di ${eur(-diff)}: l'ultima risulterà pagata in parte.`}
          </Notice>
        )}
      </div>
    </Modal>
  );
}

function ExcludeModal({ tx, onClose, onDone }) {
  const [categories, setCategories] = useState([]);
  const [reason, setReason] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!tx) return;
    setReason("");
    setCategory(tx.category);
    setError("");
    api.get("/categories").then((r) => setCategories(r.data)).catch(() => {});
  }, [tx]);

  if (!tx) return null;
  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`/transactions/${tx.id}/exclude`, { reason, category });
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="Movimento senza fattura"
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={submit} loading={busy} disabled={!reason.trim()}>Conferma</Button></>}>
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted">Per stipendi, commissioni, giroconti o spese con scontrino che non hanno una fattura da abbinare.</p>
        <ErrorBox>{error}</ErrorBox>
        <Field label="Motivo" htmlFor="ex-reason">
          <input id="ex-reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Es. scontrino ferramenta" />
        </Field>
        <Field label="Categoria" htmlFor="ex-cat">
          <select id="ex-cat" className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
      </div>
    </Modal>
  );
}
