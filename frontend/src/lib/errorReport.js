import { api, getToken } from "./api";

let sent = 0;

function report(message, stack) {
  if (!getToken() || sent >= 20) return;
  sent += 1;
  api.post("/client-errors", { message: String(message || "").slice(0, 300), stack: String(stack || "").slice(0, 2000), path: window.location.pathname }).catch(() => {});
}

// Invia allo sviluppatore solo tipo di errore e posizione nel codice, mai i dati mostrati a schermo
export function installErrorReporting() {
  window.addEventListener("error", (e) => report(e.message, e.error?.stack));
  window.addEventListener("unhandledrejection", (e) => {
    if (e.reason?.isAxiosError) return;
    report(e.reason?.message || "Promise rifiutata", e.reason?.stack);
  });
}
