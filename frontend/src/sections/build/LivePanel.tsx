import { useEffect, useRef, useState } from 'react';
import { fetchRunPoints, runVersion, type Run } from '../../api';
import { Button } from '../../components/ui/Button';
import { LiveChart, type LiveChartHandle } from '../../components/ui/LiveChart';
import type { Build } from './useBuild';

const MICRO = 1_000_000;

export function LivePanel({ build }: { build: Build }) {
  const chart = useRef<LiveChartHandle>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [initial, setInitial] = useState<[number, number][]>([]);
  const [last, setLast] = useState<{ equity: number; price: number; n: number } | null>(null);
  const [startCash, setStartCash] = useState(0);
  const [quote, setQuote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const since = useRef(0);

  async function start() {
    const saved = build.saved;
    if (!saved?.versionId) return;
    setBusy(true);
    setError('');
    try {
      since.current = 0;
      setInitial([]);
      setLast(null);
      setRun(await runVersion(saved.agentId, saved.versionId, {}));
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not start'); }
    setBusy(false);
  }

  useEffect(() => {
    if (!run) return;
    let live = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const res = await fetchRunPoints(run.id, since.current);
        if (!live) return;
        setStartCash(res.start_cash / MICRO);
        setQuote(res.quote);
        const fresh = res.points.filter(p => p[0] > since.current);
        if (fresh.length) {
          const points = fresh.map(p => [p[0], p[1] / MICRO] as [number, number]);
          if (since.current === 0) setInitial(points);
          else points.forEach(p => chart.current?.append('equity', p));
          since.current = fresh[fresh.length - 1][0];
          const tail = fresh[fresh.length - 1];
          setLast(prev => ({ equity: tail[1] / MICRO, price: tail[2] / 1e8, n: (prev?.n ?? 0) + fresh.length }));
        }
      } catch (e) { if (live) setError(e instanceof Error ? e.message : 'Stream interrupted'); }
      if (live) timer = window.setTimeout(tick, 2000);
    };
    tick();
    return () => { live = false; window.clearTimeout(timer); };
  }, [run?.id]);

  const ret = last && startCash ? (last.equity / startCash - 1) * 100 : 0;
  return <div className="panel">
    <div className="actions">
      <Button variant="solid" disabled={!build.live || busy || Boolean(run)} onClick={start}>{busy ? 'Starting' : run ? 'Running' : 'Go live'}</Button>
      {!build.live && <span className="say">Save first.</span>}
      {run && <span className="badge">practice run {run.id}</span>}
    </div>
    {error && <p className="say bad" role="alert">{error}</p>}
    {run && <>
      <dl className="metrics-grid compact">
        <div><dt>Equity</dt><dd>{last ? last.equity.toFixed(2) : '-'} {quote}</dd></div>
        <div><dt>Return</dt><dd className={ret >= 0 ? 'up' : 'down'}>{ret >= 0 ? '+' : ''}{ret.toFixed(2)}%</dd></div>
        <div><dt>Price</dt><dd>{last ? last.price.toLocaleString(undefined, { maximumFractionDigits: 6 }) : '-'}</dd></div>
        <div><dt>Points</dt><dd>{last?.n ?? 0}</dd></div>
      </dl>
      <LiveChart ref={chart} label="Live equity" series={[{ id: 'equity', kind: 'area', name: 'Equity', color: '--ink', data: initial }]}/>
    </>}
  </div>;
}
