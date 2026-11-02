import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, getToken, setToken } from "./api";

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
    setToken(token);
    setLoading(true);
    await loadSession();
  }, [loadSession]);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setCompanies([]);
  }, []);

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

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
