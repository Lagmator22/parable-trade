import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchRunPoints } from '../../api';
import { LiveChart, type LiveChartHandle, type PriceLine } from '../../components/ui/LiveChart';

const MICRO = 1_000_000;
type Pair = [number, number];
type Boot = { equity: Pair[]; hold: Pair[]; quote: string; start: number };

type Props = { runId: number; alive: boolean; label: string; lines?: PriceLine[]; showHold?: boolean; every?: number; onCount?: (n: number) => void };

export function RunChart({ runId, alive, label, lines = [], showHold = true, every = 3000, onCount }: Props) {
  const chart = useRef<LiveChartHandle>(null);
  const since = useRef(0);
  const anchor = useRef({ cash: 0, price: 0, booted: false, count: 0 });
  const [boot, setBoot] = useState<Boot | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    since.current = 0;
    anchor.current = { cash: 0, price: 0, booted: false, count: 0 };
    setBoot(null);
    async function pull() {
      try {
        const result = await fetchRunPoints(runId, since.current);
        if (!live) return;
        const a = anchor.current;
        const first = !a.booted;
        if (first) { a.booted = true; a.cash = result.start_cash; }
        const equity: Pair[] = [];
        const hold: Pair[] = [];
        for (const [t, e, p] of result.points) {
          if (!a.price && p > 0) a.price = p;
          equity.push([t, e / MICRO]);
          if (a.price && p > 0) hold.push([t, (a.cash / MICRO) * (p / a.price)]);
        }
        a.count += result.points.length;
        onCount?.(a.count);
        if (result.points.length) since.current = result.points[result.points.length - 1][0];
        if (first) { setBoot({ equity, hold, quote: result.quote, start: a.cash / MICRO }); return; }
        const wasEmpty = a.count === result.points.length;
        equity.forEach(point => chart.current?.append('equity', point));
        hold.forEach(point => chart.current?.append('hold', point));
        if (wasEmpty && equity.length) chart.current?.fit();
        setError('');
      } catch (failure) {
        if (live) setError(failure instanceof Error ? failure.message : 'No data');
      }
    }
    pull();
    const timer = alive ? window.setInterval(() => { if (!document.hidden) pull(); }, every) : undefined;
    return () => { live = false; window.clearInterval(timer); };
  }, [runId, alive, every]);

  const series = useMemo(() => (boot ? [
    { id: 'equity', kind: 'area' as const, name: 'Agent', color: '--ink', data: boot.equity },
    ...(showHold ? [{ id: 'hold', kind: 'line' as const, name: 'Buy and hold', color: '--grey', dashed: true, data: boot.hold }] : []),
  ] : []), [boot, showHold]);

  if (!boot) return <p className="say">{error || 'Loading the live curve'}</p>;
  const fmt = (v: number) => `${v.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${boot.quote}`;
  const marks: PriceLine[] = [{ price: boot.start, label: 'Start', seriesId: 'equity' }, ...lines];
  return <div className="run-chart">
    <LiveChart ref={chart} label={label} series={series} priceLines={marks} yFormat={fmt} xFormat={t => new Date(t * 1000).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit' })}/>
    {boot.equity.length === 0 && <p className="say">Waiting for the first point. The curve fills in live.</p>}
    {error && <p className="say bad" role="alert">{error}</p>}
  </div>;
}
