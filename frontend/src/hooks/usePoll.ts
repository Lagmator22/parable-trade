import { useCallback, useEffect, useRef, useState } from 'react';

type Options<T> = { every?: number; deps?: unknown[]; stopWhen?: (data: T) => boolean };

export function usePoll<T>(load: () => Promise<T>, { every = 4000, deps = [], stopWhen }: Options<T> = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState(0);
  const loader = useRef(load);
  const stopper = useRef(stopWhen);
  loader.current = load;
  stopper.current = stopWhen;

  const tick = useCallback(async () => {
    try {
      const next = await loader.current();
      setData(next);
      setError(null);
      setUpdatedAt(Date.now());
      return next;
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Request failed');
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const schedule = () => { timer = window.setTimeout(run, every); };
    const run = async () => {
      if (cancelled) return;
      if (document.hidden) { schedule(); return; }
      const next = await tick();
      if (cancelled) return;
      if (next !== null && stopper.current?.(next)) return;
      schedule();
    };
    const wake = () => { if (!document.hidden) { window.clearTimeout(timer); run(); } };
    run();
    document.addEventListener('visibilitychange', wake);
    return () => { cancelled = true; window.clearTimeout(timer); document.removeEventListener('visibilitychange', wake); };
  }, [every, tick, ...deps]);

  return { data, error, updatedAt, reload: tick };
}
