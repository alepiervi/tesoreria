import { useEffect, useState } from "react";
import { Button, ErrorBox, Field, Modal } from "../../components/ui";

export const STATUS = {
  in_lavorazione: ["In lavorazione", "gray"],
  attiva: ["Attiva", "blue"],
  ko: ["KO / annullata", "orange"],
  cessata: ["Cessata / stornata", "dark"],
};

export const KIND = { struttura: "Struttura", dipendente: "Dipendente" };

export function monthOptions(back = 12) {
  const out = [];
  const d = new Date();
  d.setDate(15);
  for (let i = 0; i < back; i += 1) {
    out.push(d.toISOString().slice(0, 7));
    d.setMonth(d.getMonth() - 1);
  }
  return out;
}

const MONTHS = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"];
export const monthLabel = (m) => `${MONTHS[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}`;

/** Scelta delle colonne del file quando il programma non le riconosce da solo. */
export function MappingModal({ value, onClose, onConfirm, busy }) {
  const [mapping, setMapping] = useState({});
  const [error, setError] = useState("");
  useEffect(() => { if (value) { setMapping(value.mapping || {}); setError(""); } }, [value]);
  if (!value) return null;
  const confirm = () => {
    const missing = (value.required || []).filter((k) => !mapping[k]);
    if (missing.length) {
      setError(`Indica la colonna per: ${missing.map((k) => value.fields[k]).join(", ")}.`);
      return;
    }
    onConfirm(mapping);
  };
  return (
    <Modal open wide onClose={onClose} title={`Colonne del file · ${value.title || ""}`}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={confirm} loading={busy}>Importa con queste colonne</Button></>}>
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted">Il programma non ha riconosciuto tutte le colonne. Indicale una volta: la prossima volta il file di questo formato si legge da solo.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {Object.entries(value.fields).map(([k, label]) => (
            <Field key={k} label={`${label}${(value.required || []).includes(k) ? " *" : ""}`} htmlFor={`map-${k}`}>
              <select id={`map-${k}`} className="input" value={mapping[k] || ""} onChange={(e) => setMapping({ ...mapping, [k]: e.target.value || null })}>
                <option value="">— non presente —</option>
                {value.headers.map((h, i) => <option key={`${h}-${i}`} value={h}>{h || `Colonna ${i + 1}`}</option>)}
              </select>
            </Field>
          ))}
        </div>
        {value.sample?.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-xs">
              <thead><tr className="table-head text-left">{value.headers.map((h, i) => <th key={i} className="whitespace-nowrap px-2 py-1.5">{h}</th>)}</tr></thead>
              <tbody>
                {value.sample.map((r, i) => (
                  <tr key={i} className="border-t border-soft">{r.map((c, j) => <td key={j} className="whitespace-nowrap px-2 py-1.5">{c}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <ErrorBox>{error}</ErrorBox>
      </div>
    </Modal>
  );
}
