import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, getToken, setToken } from "./api";
import { IDLE_MINUTES, idleExpired, markActivity, useIdleLogout } from "./idle";

const AuthContext = createContext(null);
const SELECTED_KEY = "tesoreria_company";

function readSelected() {
  try {
    return localStorage.getItem(SELECTED_KEY);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(Boolean(getToken()));
  const [selectedId, setSelectedIdState] = useState(readSelected());
  const [counts, setCounts] = useState({ to_reconcile: 0, open_questions: 0 });

  const loadSession = useCallback(async () => {
    if (getToken() && idleExpired()) setToken(null);
    if (!getToken()) {
      setUser(null);
      setCompanies([]);
      setLoading(false);
      return;
    }
    try {
      const [me, list] = await Promise.all([api.get("/auth/me"), api.get("/companies")]);
      setUser(me.data.user);
      setCompanies(list.data);
    } catch {
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshCounts = useCallback(async () => {
    if (!getToken()) return;
    try {
      const res = await api.get("/dashboard/group");
      setCounts(res.data.totals);
    } catch {
      /* il conteggio nel menu non è essenziale */
    }
  }, []);

  useEffect(() => {
    loadSession();
  }, [loadSession]);

  useEffect(() => {
    if (user) refreshCounts();
  }, [user, refreshCounts]);

  const login = useCallback(async (token) => {
    markActivity();
    setToken(token);
    setLoading(true);
    await loadSession();
  }, [loadSession]);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setCompanies([]);
  }, []);

  const idleTimeout = useCallback(() => {
    logout();
    window.location.assign("/login?scaduta=1");
  }, [logout]);
  const idleSecondsLeft = useIdleLogout(Boolean(user), idleTimeout);

  const setSelectedId = useCallback((id) => {
    setSelectedIdState(id);
    try {
      localStorage.setItem(SELECTED_KEY, id);
    } catch {
      /* ignora */
    }
  }, []);

  const value = useMemo(() => {
    const byId = Object.fromEntries(companies.map((c) => [c.id, c]));
    const selected = byId[selectedId] || companies[0] || null;
    const can = (companyId, perm) => Boolean(byId[companyId]?.permissions?.includes(perm));
    const anyCan = (perm) => companies.some((c) => c.permissions.includes(perm));
    const companiesWith = (perm) => companies.filter((c) => c.permissions.includes(perm));
    const roles = [...new Set(companies.map((c) => c.role))];
    return {
      user, companies, byId, loading, selected, setSelectedId, can, anyCan, companiesWith, roles,
      login, logout, reload: loadSession, counts, refreshCounts,
    };
  }, [user, companies, loading, selectedId, setSelectedId, login, logout, loadSession, counts, refreshCounts]);

  return (
    <AuthContext.Provider value={value}>
      {children}
      {idleSecondsLeft !== null && (
        <div role="alert" data-testid="idle-warning"
          className="fixed bottom-4 left-1/2 z-[100] w-[min(92vw,420px)] -translate-x-1/2 rounded-xl border border-line bg-white px-4 py-3 text-sm shadow-lg">
          <p className="font-semibold">Sei ancora lì?</p>
          <p className="text-muted">
            Per sicurezza, dopo {IDLE_MINUTES} minuti di inattività verrai disconnesso tra <span data-testid="idle-seconds">{idleSecondsLeft}</span> secondi.
            Muovi il mouse o premi un tasto per restare collegato.
          </p>
        </div>
      )}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
