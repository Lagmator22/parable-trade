import { useEffect, useMemo, useState } from 'react';
import { Button } from '../../components/ui/Button';
import { LiveChart } from '../../components/ui/LiveChart';
import type { Build } from './useBuild';

const SPEEDS = [1, 4, 16];

export function ReplayPanel({ build }: { build: Build }) {
  const { result } = build;
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);
  const curve = result?.curve ?? [];
  const total = curve.length;
  const shown = Math.min(index, total);

  useEffect(() => { setIndex(0); setPlaying(false); }, [result?.result_hash]);

  useEffect(() => {
    if (!playing || total === 0) return;
    const timer = window.setInterval(() => {
      setIndex(i => {
        const step = Math.max(1, Math.round((Math.ceil(total / 120) * speed) / 4));
        const next = Math.min(i + step, total);
        if (next >= total) setPlaying(false);
        return next;
      });
    }, 80);
    return () => window.clearInterval(timer);
  }, [playing, speed, total]);

  const equity = useMemo(() => curve.slice(0, shown).map(p => [p[0], p[1]] as [number, number]), [curve, shown]);
  const hold = useMemo(() => curve.slice(0, shown).map(p => [p[0], p[2]] as [number, number]), [curve, shown]);
  const last = curve[shown - 1];
  const cutoff = last ? last[0] : -Infinity;
  const marks = useMemo(() => (result?.markers ?? []).filter(m => m.t <= cutoff).map(m => ({ t: m.t, side: m.side, text: m.text || undefined, seriesId: 'equity' })), [result, cutoff]);

  if (!result) return <div className="panel"><p className="empty">Run a backtest first, then replay it.</p></div>;
  const ret = last ? (last[1] / result.start_cash - 1) * 100 : 0;
  return <div className="panel">
    <div className="actions">
      <Button variant="solid" onClick={() => { if (shown >= total) setIndex(0); setPlaying(p => !p); }}>{playing ? 'Pause' : shown >= total ? 'Replay' : 'Play'}</Button>
      <Button onClick={() => { setIndex(0); setPlaying(false); }}>Restart</Button>
      <div className="toggle" role="group" aria-label="Speed">{SPEEDS.map(s => <button key={s} type="button" aria-pressed={s === speed} onClick={() => setSpeed(s)}>{s}x</button>)}</div>
    </div>
    <dl className="metrics-grid compact">
      <div><dt>Equity</dt><dd>{last ? last[1].toFixed(2) : result.start_cash.toFixed(2)} {result.quote}</dd></div>
      <div><dt>Return</dt><dd className={ret >= 0 ? 'up' : 'down'}>{ret >= 0 ? '+' : ''}{ret.toFixed(1)}%</dd></div>
      <div><dt>Trades so far</dt><dd>{marks.filter(m => m.side === 'sell').length}</dd></div>
      <div><dt>Progress</dt><dd>{total ? Math.round((shown / total) * 100) : 0}%</dd></div>
    </dl>
    <LiveChart label="Replay" markers={marks} series={[
      { id: 'equity', kind: 'area', name: 'Strategy', color: '--ink', data: equity },
      { id: 'hold', kind: 'line', name: 'Buy and hold', color: '--grey', dashed: true, data: hold },
    ]}/>
  </div>;
}
