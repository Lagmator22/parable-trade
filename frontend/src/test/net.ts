import { vi } from 'vitest';

export type Call = { method: string; path: string; body: unknown };

export function stubFetch(route: (method: string, path: string, body: unknown) => unknown) {
  const calls: Call[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET';
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined;
    calls.push({ method, path, body });
    try {
      return new Response(JSON.stringify(route(method, path, body)), { status: 200 });
    } catch (failure) {
      const status = (failure as { status?: number }).status ?? 500;
      return new Response(JSON.stringify({ detail: (failure as Error).message, code: (failure as { code?: string }).code ?? '' }), { status });
    }
  }));
  return calls;
}

export const failure = (status: number, message: string, code = '') => Object.assign(new Error(message), { status, code });

export const flush = async (times = 4) => {
  const { act } = await import('react');
  for (let i = 0; i < times; i += 1) await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
};
