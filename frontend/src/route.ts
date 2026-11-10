import { useEffect, useState } from 'react';

export type Page = 'build' | 'market' | 'agent' | 'mine' | 'purchases' | 'purchase' | 'ledger';
export type Route = { page: Page; id: string };

export function parseRoute(hash: string): Route {
  const [page, id = ''] = hash.replace(/^#\/?/, '').split('/');
  if (page === 'build' || page === 'sell') return { page: 'build', id: page === 'build' ? id : '' };
  if (page === 'mine' || page === 'purchases' || page === 'ledger') return { page, id: '' };
  if ((page === 'agent' || page === 'purchase') && id) return { page, id };
  return { page: 'market', id: '' };
}

export function useRoute(): Route & { hash: string } {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  useEffect(() => {
    if (/^#\/?sell\/?$/.test(hash)) window.location.replace('#build');
  }, [hash]);
  return { ...parseRoute(hash), hash };
}
