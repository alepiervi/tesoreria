import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { eur, eurK, fmtDate } from "../lib/format";

const AXIS = { fontSize: 12, fill: "#5B6170" };

function MoneyTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2 text-xs shadow-md">
      <div className="mb-1 font-semibold">{payload[0].payload.tooltipLabel || label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex justify-between gap-4">
          <span style={{ color: p.color }}>{p.name}</span>
          <span className="num font-semibold">{eur(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

export function MonthlyChart({ data }) {
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer>
        <BarChart data={data} barGap={4} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="#EEF0F2" />
          <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis domain={[(m) => Math.min(m, 0), (m) => Math.max(m, 100000)]} tickFormatter={eurK} tick={AXIS} axisLine={false} tickLine={false} width={52} />
          <Tooltip content={<MoneyTooltip />} cursor={{ fill: "#F5F6F4" }} />
          <Legend iconType="square" wrapperStyle={{ fontSize: 12, color: "#5B6170" }} />
          <Bar dataKey="inflow_cents" name="Entrate" fill="#2346D8" radius={[4, 4, 0, 0]} maxBarSize={28} />
          <Bar dataKey="outflow_cents" name="Uscite" fill="#E8772E" radius={[4, 4, 0, 0]} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ForecastChart({ forecast }) {
  if (!forecast) return null;
  const threshold = forecast.opening_balance_cents * 0.5;
  const data = forecast.weeks.map((w) => ({
    label: `S${w.week}`,
    tooltipLabel: `Settimana dal ${fmtDate(w.start)}`,
    balance: w.balance_end_cents,
    low: w.balance_end_cents < threshold,
  }));
  return (
    <div className="h-[200px] w-full">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="#EEF0F2" />
          <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis domain={[(m) => Math.min(m, 0), (m) => Math.max(m, 100000)]} tickFormatter={eurK} tick={AXIS} axisLine={false} tickLine={false} width={52} />
          <Tooltip content={<MoneyTooltip />} cursor={{ fill: "#F5F6F4" }} />
          <Bar dataKey="balance" name="Saldo previsto" radius={[4, 4, 0, 0]} maxBarSize={36}>
            {data.map((d) => <Cell key={d.label} fill={d.balance < 0 ? "#A8480F" : d.low ? "#E8772E" : "#8FA2EE"} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function forecastNote(forecast) {
  if (!forecast) return null;
  const low = forecast.lowest;
  if (forecast.goes_negative) {
    return { tone: "orange", text: `Attenzione: nella settimana ${low.week} il saldo previsto va in negativo (${eur(low.balance_cents)}). Serve anticipare incassi o spostare pagamenti.` };
  }
  if (low.week && low.balance_cents < forecast.opening_balance_cents * 0.5) {
    return { tone: "orange", text: `Il saldo scende fino a ${eur(low.balance_cents)} nella settimana ${low.week}, meno della metà della liquidità attuale.` };
  }
  return { tone: "blue", text: `Situazione stabile: il punto più basso previsto è ${eur(low.balance_cents)}.` };
}
