import { useEffect, useRef, useState } from "react";
import CompanyPicker from "../components/CompanyPicker";
import { Button, Card, ErrorBox, Notice, PageHeader, Spinner } from "../components/ui";
import { api, errorMessage } from "../lib/api";

export default function Assistant() {
  const [status, setStatus] = useState(null);
  const [companyId, setCompanyId] = useState("");
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef(null);

  useEffect(() => {
    api.get("/assistant/status").then((r) => setStatus(r.data)).catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  const ask = async (text) => {
    const q = (text ?? question).trim();
    if (!q || busy) return;
    setQuestion("");
    setError("");
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((m) => [...m, { role: "user", content: q }]);
    setBusy(true);
    try {
      const res = await api.post("/assistant/ask", { question: q, company_id: companyId || undefined, history });
      setMessages((m) => [...m, { role: "assistant", content: res.data.answer }]);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Assistente" subtitle="Fai domande sui conti delle tue aziende, in italiano"
        actions={<CompanyPicker value={companyId} onChange={setCompanyId} allowAll permission="use_assistant" />} />
      {status && status.provider === "demo" && (
        <Notice>
          Modalità di base: l'assistente capisce le domande più comuni (saldi, spese per categoria, crediti, scadenze, previsione, IVA, budget)
          e risponde con i dati veri. Collegandolo a Claude capisce qualsiasi domanda e legge le foto degli scontrini.
        </Notice>
      )}
      {status && !status.enabled && <Notice tone="orange">L'assistente è disattivato dall'amministratore del sistema.</Notice>}
      <Card padded={false} className="flex min-h-[420px] flex-col">
        <div className="flex flex-1 flex-col gap-4 p-5" aria-live="polite">
          {messages.length === 0 && status?.examples && (
            <div className="flex flex-col gap-3">
              <span className="text-sm text-muted">Prova a chiedere:</span>
              <div className="flex flex-wrap gap-2">
                {status.examples.map((ex) => (
                  <button key={ex} type="button" onClick={() => ask(ex)}
                    className="min-h-[44px] rounded-full border border-[#C9CDD4] bg-white px-4 text-left text-sm hover:border-accent hover:bg-accent-soft">
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, n) => (
            <div key={n} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                m.role === "user" ? "bg-accent text-white" : "border border-line bg-page text-ink"}`}>
                {m.content}
              </div>
            </div>
          ))}
          {busy && <div className="flex items-center gap-2 text-sm text-muted"><Spinner small /> Sto guardando i dati…</div>}
          <div ref={endRef} />
        </div>
        <form onSubmit={(e) => { e.preventDefault(); ask(); }} className="flex flex-wrap gap-2 border-t border-line p-4">
          <label htmlFor="ask" className="sr-only">Domanda</label>
          <input id="ask" className="input min-w-[220px] flex-1" placeholder="Es. quanto abbiamo speso di utenze il mese scorso?"
            value={question} onChange={(e) => setQuestion(e.target.value)} disabled={!status?.enabled} />
          <Button type="submit" loading={busy} disabled={!question.trim() || !status?.enabled}>Chiedi</Button>
        </form>
      </Card>
      <ErrorBox>{error}</ErrorBox>
      <p className="text-xs text-muted">L'assistente legge solo i dati delle aziende che puoi vedere e non modifica nulla. Su IVA e imposte dà stime da verificare con il commercialista.</p>
    </>
  );
}
