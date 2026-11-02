const eurFmt = new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR", useGrouping: "always" });
const eurShort = new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR", maximumFractionDigits: 0, useGrouping: "always" });
const MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];

export function eur(cents, { signed = false, short = false } = {}) {
  const value = (cents || 0) / 100;
  const text = (short ? eurShort : eurFmt).format(Math.abs(value));
  if (value < 0) return `− ${text}`;
  if (signed && value > 0) return `+ ${text}`;
  return text;
}

export function eurK(cents) {
  const k = (cents || 0) / 100000;
  return `${k.toLocaleString("it-IT", { maximumFractionDigits: 1 })}k`;
}

export function fmtDate(iso, { year = false } = {}) {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}${year ? ` ${y}` : ""}`;
}

export function fmtDateTime(iso) {
  if (!iso) return "";
  const dt = new Date(iso);
  return dt.toLocaleString("it-IT", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export function addDays(iso, days) {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export const ROLE_LABELS = {
  titolare: "Titolare",
  amministrazione: "Amministrazione",
  commercialista: "Commercialista",
  lettura: "Sola lettura",
};

export const KIND_LABELS = { incasso: "Incasso", pagamento: "Pagamento", f24: "F24", altro: "Altro" };

export const DEADLINE_STATUS = {
  aperta: ["Da incassare", "blue"],
  da_pagare: ["Da pagare", "gray"],
  in_attesa_autorizzazione: ["In attesa di autorizzazione", "orange"],
  inviato: ["Bonifico inviato", "blue"],
  pagato: ["Pagato", "green"],
  incassato: ["Incassato", "green"],
};

export const TX_STATUS = {
  da_riconciliare: ["Da riconciliare", "orange"],
  riconciliato: ["Riconciliato", "blue"],
  escluso: ["Senza fattura", "gray"],
};

export const INVOICE_STATUS = {
  aperta: ["Aperta", "orange"],
  parziale: ["Pagata in parte", "orange"],
  pagata: ["Pagata", "blue"],
};
