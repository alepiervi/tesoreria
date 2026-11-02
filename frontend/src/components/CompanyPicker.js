import { useAuth } from "../lib/auth";

/**
 * Selettore azienda. Con allowAll mostra anche "Tutte le aziende" (valore "").
 * permission: mostra solo le aziende su cui l'utente ha quel permesso.
 */
export default function CompanyPicker({ value, onChange, allowAll = false, permission = "view", id = "company-picker", label = "Azienda" }) {
  const { companiesWith } = useAuth();
  const list = companiesWith(permission);
  if (list.length <= 1 && !allowAll) {
    return list[0] ? <span className="text-sm font-semibold">{list[0].name}</span> : null;
  }
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="sr-only">{label}</label>
      <select id={id} className="input min-w-[220px] font-semibold" value={value || ""} onChange={(e) => onChange(e.target.value)}>
        {allowAll && <option value="">Tutte le aziende</option>}
        {list.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
    </div>
  );
}

/** Restituisce l'azienda da usare in una pagina "per azienda", rispettando il permesso richiesto. */
export function usePageCompany(permission = "view") {
  const { selected, setSelectedId, companiesWith } = useAuth();
  const list = companiesWith(permission);
  const company = list.find((c) => c.id === selected?.id) || list[0] || null;
  return [company, setSelectedId];
}
