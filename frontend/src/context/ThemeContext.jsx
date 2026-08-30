import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

const KEY = 'moodlens_theme';
const ThemeContext = createContext(null);

/** 'light' | 'dark' | 'system' — 'system' leaves the attribute off so the
 *  prefers-color-scheme media query in global.css decides. */
export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => localStorage.getItem(KEY) || 'system');

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
    localStorage.setItem(KEY, theme);
  }, [theme]);

  const cycle = useCallback(() => {
    setTheme((t) => (t === 'system' ? 'dark' : t === 'dark' ? 'light' : 'system'));
  }, []);

  const value = useMemo(() => ({ theme, setTheme, cycle }), [theme, cycle]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider');
  return ctx;
}
