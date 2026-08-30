import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import client, { getToken, setToken } from '../api/client';

const USER_KEY = 'moodlens_user';
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const raw = localStorage.getItem(USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(Boolean(getToken()));

  // A stored user could be stale (role changed, account deleted), so confirm
  // it against the API on first load.
  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    client
      .get('/me')
      .then(({ data }) => {
        setUser(data);
        localStorage.setItem(USER_KEY, JSON.stringify(data));
      })
      .catch(() => {
        setToken(null);
        localStorage.removeItem(USER_KEY);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const persist = useCallback((data) => {
    setToken(data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    setUser(data.user);
    return data.user;
  }, []);

  const login = useCallback(
    async (email, password) => {
      const { data } = await client.post('/login', { email, password });
      return persist(data);
    },
    [persist]
  );

  const register = useCallback(
    async (username, email, password) => {
      const { data } = await client.post('/register', { username, email, password });
      return persist(data);
    },
    [persist]
  );

  const logout = useCallback(() => {
    setToken(null);
    localStorage.removeItem(USER_KEY);
    setUser(null);
  }, []);

  const refresh = useCallback(async () => {
    const { data } = await client.get('/me');
    localStorage.setItem(USER_KEY, JSON.stringify(data));
    setUser(data);
    return data;
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout, refresh, isAdmin: user?.role === 'admin' }),
    [user, loading, login, register, logout, refresh]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
