import axios from "axios";

const BASE = (process.env.REACT_APP_BACKEND_URL || "") + "/api";
const TOKEN_KEY = "tesoreria_token";

export const api = axios.create({ baseURL: BASE });

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* browser senza storage: la sessione dura finché la pagina resta aperta */
  }
}

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

const PUBLIC_PATHS = ["/auth/login", "/invites/token"];

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url = error.config?.url || "";
    if (error.response?.status === 401 && !PUBLIC_PATHS.some((p) => url.includes(p))) {
      setToken(null);
      if (!window.location.pathname.startsWith("/login")) window.location.assign("/login");
    }
    return Promise.reject(error);
  }
);

export function errorMessage(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Controlla i dati inseriti.";
  if (!error?.response) return "Il server non risponde. Controlla la connessione.";
  return "Si è verificato un errore. Riprova.";
}

/** Scarica un file da un endpoint protetto e lo salva sul computer. */
export async function downloadFile(url, params, fallbackName = "download") {
  const res = await api.get(url, { params, responseType: "blob" });
  const disposition = res.headers["content-disposition"] || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const name = match ? match[1] : fallbackName;
  const href = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

/** Legge l'errore di una risposta blob (download fallito). */
export async function blobErrorMessage(error) {
  try {
    const text = await error.response.data.text();
    const json = JSON.parse(text);
    if (typeof json.detail === "string") return json.detail;
  } catch {
    /* ignora */
  }
  return errorMessage(error);
}
