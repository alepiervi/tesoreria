import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../lib/api";
import { Badge, Card, ErrorBox, Loading } from "./ui";

const usd = (v) => (v > 0 && v < 0.01 ? "< $ 0,01" : `$ ${v.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const num = (v) => v.toLocaleString("it-IT");
const monthLabel = (m) => new Date(`${m}-01T12:00:00`).toLocaleDateString("it-IT", { month: "long", year: "numeric" });
const shortMonth = (m) => new Date(`${m}-01T12:00:00`).toLocaleDateString("it-IT", { month: "short" });

function Bar({ pct, warn }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-soft">
      <div className={`h-full rounded-full ${warn ? "bg-warn" : "bg-accent"}`} style={{ width: `${Math.min(100, pct)}%` }} />
    </div>
  );
}

function History({ history }) {
  const max = Math.max(...history.map((h) => h.cost_usd), 0.01);
  return (
    <div className="flex h-28 items-end gap-2" data-testid="ai-usage-history">
      {history.map((h) => (
        <div key={h.month} className="flex flex-1 flex-col items-center gap-1">
          <span className="text-[11px] text-muted">{h.requests ? usd(h.cost_usd) : ""}</span>
          <div className={`w-full rounded-t-md ${h.requests ? "bg-accent/80" : "bg-soft"}`} style={{ height: `${h.requests ? Math.max(4, (h.cost_usd / max) * 64) : 2}px` }} />
          <span className="text-[11px] capitalize text-muted">{shortMonth(h.month)}</span>
        </div>
      ))}
    </div>
  );
}

export function AiUsage() {
  const [data, setData] = useState(null);
  const [month, setMonth] = useState("");
  const [error, setError] = useState("");
  const load = useCallback((m) => {
    setError("");
    api.get("/settings/ai-usage", { params: m ? { month: m } : {} })
      .then((r) => { setData(r.data); setMonth(r.data.month); })
      .catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (error) return <Card title="Consumo dell'assistente"><ErrorBox>{error}</ErrorBox></Card>;
  if (!data) return <Card title="Consumo dell'assistente"><Loading /></Card>;
  const t = data.total;
  const over = data.budget_used_pct !== null && data.budget_used_pct >= 80;
  return (
    <Card title="Consumo dell'assistente" subtitle={`Claude (${data.model}) · stima in base ai token usati`}
      actions={
        <select className="input min-h-[36px] w-auto py-1 capitalize" value={month} onChange={(e) => load(e.target.value)} data-testid="ai-usage-month">
          {data.months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
        </select>
      }>
      <div className="flex flex-col gap-5" data-testid="ai-usage-card">
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs text-muted">Costo stimato del mese</p>
            <p className="text-2xl font-bold tabular-nums" data-testid="ai-usage-cost">{usd(t.cost_usd)}</p>
          </div>
          <div>
            <p className="text-xs text-muted">Richieste</p>
            <p className="text-2xl font-bold tabular-nums" data-testid="ai-usage-requests">{num(t.requests)}</p>
          </div>
          <div>
            <p className="text-xs text-muted">Token (entrata / uscita)</p>
            <p className="text-lg font-semibold tabular-nums">{num(t.input_tokens)} / {num(t.output_tokens)}</p>
          </div>
        </div>
        {data.budget_usd > 0 && (
          <div className="flex flex-col gap-1" data-testid="ai-usage-budget">
            <div className="flex justify-between text-xs">
              <span>Budget mensile {usd(data.budget_usd)}</span>
              <span className={over ? "font-semibold text-warn-text" : "text-muted"}>{data.budget_used_pct}% usato</span>
            </div>
            <Bar pct={data.budget_used_pct} warn={over} />
          </div>
        )}
        {t.requests === 0 ? (
          <p className="text-sm text-muted">Nessun utilizzo in questo mese.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Per tipo</p>
              <ul className="flex flex-col gap-2" data-testid="ai-usage-by-kind">
                {data.by_kind.map((k) => (
                  <li key={k.kind} className="flex flex-col gap-1 text-sm">
                    <div className="flex justify-between"><span>{k.label} <span className="text-muted">· {k.requests}</span></span><span className="tabular-nums">{usd(k.cost_usd)}</span></div>
                    <Bar pct={t.cost_usd ? Math.max(2, (k.cost_usd / t.cost_usd) * 100) : 2} />
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Per persona</p>
              <ul className="divide-y divide-soft" data-testid="ai-usage-by-user">
                {data.by_user.map((u) => (
                  <li key={u.name} className="flex justify-between py-1.5 text-sm">
                    <span>{u.name} <span className="text-muted">· {u.requests}</span></span><span className="tabular-nums">{usd(u.cost_usd)}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Ultimi 6 mesi</p>
          <History history={data.history} />
        </div>
        <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <Badge tone="gray">stima</Badge>
          Calcolata con ${data.prices.input_per_mtok} / ${data.prices.output_per_mtok} per milione di token (entrata / uscita).
          Il saldo effettivo della chiave universale e la ricarica sono su Emergent: Profilo → Manage plan → Universal Key.
        </p>
      </div>
    </Card>
  );
}
