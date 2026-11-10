import { useEffect, useState } from 'react';

export type Theme = 'dark' | 'light';

function savedTheme(): Theme {
  try { return localStorage.getItem('parable-theme') === 'dark' ? 'dark' : 'light'; } catch { return 'light'; }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(savedTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('parable-theme', theme); } catch { return; }
  }, [theme]);
  return { theme, toggle: () => setTheme(current => (current === 'dark' ? 'light' : 'dark')) };
}
