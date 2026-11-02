import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export const KIND_LABELS = { attivo: "Attività", passivo: "Passività e netto", costo: "Costi", ricavo: "Ricavi", chiusura: "Chiusura" };

export const SOURCE_LABELS = {
  auto: ["Automatica", "blue"],
  manuale: ["Manuale", "gray"],
  rettifica: ["Rettifica", "orange"],
  paghe: ["Paghe", "blue"],
  chiusura: ["Chiusura", "dark"],
  apertura: ["Apertura", "dark"],
};

/** "1.234,56" o "1234.56" -> centesimi (intero). Restituisce null se non è un numero. */
export function parseEuro(text) {
  if (text === null || text === undefined) return null;
  let s = String(text).trim().replace(/[€\s]/g, "");
  if (!s) return 0;
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  const n = Number(s);
  if (!Number.isFinite(n)) return null;
  return Math.round(n * 100);
}

export function centsToInput(cents) {
  if (!cents) return "";
  return (cents / 100).toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function yearOptions() {
  const y = new Date().getFullYear();
  return [y + 1, y, y - 1, y - 2];
}

/** Piano dei conti dell'azienda (con saldi dell'anno). */
export function useAccounts(companyId, year) {
  const [accounts, setAccounts] = useState(null);
  const reload = useCallback(async () => {
    if (!companyId) return;
    const res = await api.get(`/companies/${companyId}/accounts`, { params: { year } });
    setAccounts(res.data);
  }, [companyId, year]);
  useEffect(() => {
    setAccounts(null);
    reload().catch(() => setAccounts([]));
  }, [reload]);
  return [accounts, reload];
}

export function useCostCenters(companyId) {
  const [items, setItems] = useState([]);
  const reload = useCallback(async () => {
    if (!companyId) return;
    const res = await api.get(`/companies/${companyId}/cost-centers`);
    setItems(res.data);
  }, [companyId]);
  useEffect(() => { reload().catch(() => setItems([])); }, [reload]);
  return [items, reload];
}

/** Selettore di un sottoconto (solo conti su cui si può registrare), raggruppato per mastro. */
export function AccountSelect({ accounts, value, onChange, id, kinds, allowEmpty = false, emptyLabel = "— scegli il conto —", className = "" }) {
  const list = (accounts || []).filter((a) => a.postable && a.active !== false && (!kinds || kinds.includes(a.kind)));
  const groups = {};
  const top = Object.fromEntries((accounts || []).filter((a) => a.level === 1).map((a) => [a.code, a.name]));
  list.forEach((a) => {
    const g = a.code.split(".")[0];
    (groups[g] = groups[g] || []).push(a);
  });
  return (
    <select id={id} className={`input ${className}`} value={value || ""} onChange={(e) => onChange(e.target.value)}>
      <option value="" disabled={!allowEmpty}>{emptyLabel}</option>
      {Object.keys(groups).sort().map((g) => (
        <optgroup key={g} label={`${g} · ${top[g] || ""}`}>
          {groups[g].map((a) => <option key={a.code} value={a.code}>{a.code} · {a.name}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

export function YearSelect({ value, onChange, id = "year" }) {
  return (
    <>
      <label htmlFor={id} className="sr-only">Esercizio</label>
      <select id={id} className="input w-auto" value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {yearOptions().map((y) => <option key={y} value={y}>Esercizio {y}</option>)}
      </select>
    </>
  );
}
