import { useEffect, useState } from 'react';

export type Route = { page: 'market' | 'sell' | 'purchases' | 'purchase' | 'ledger'; id: string };

export function parseRoute(hash: string): Route {
  const [page, id = ''] = hash.replace(/^#\/?/, '').split('/');
  if (page === 'sell' || page === 'purchases' || page === 'ledger') return { page, id: '' };
  if (page === 'purchase' && id) return { page, id };
  return { page: 'market', id: '' };
}

export function useRoute(): Route & { hash: string } {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  return { ...parseRoute(hash), hash };
}
