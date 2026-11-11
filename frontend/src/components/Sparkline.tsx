import type { CurvePoint } from '../api';

const W = 160;
const H = 48;

function rebased(values: number[]): number[] {
  const base = values[0] || 1;
  return values.map(v => (v / base - 1) * 100);
}

export function sparkPaths(points: CurvePoint[]): { strategy: string; hold: string } {
  if (points.length < 2) return { strategy: '', hold: '' };
  const a = rebased(points.map(p => p[1]));
  const b = rebased(points.map(p => p[2]));
  const all = [...a, ...b];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo || 1;
  const path = (values: number[]) => values.map((v, i) => `${i ? 'L' : 'M'}${((i / (values.length - 1)) * W).toFixed(1)} ${(H - 3 - ((v - lo) / span) * (H - 6)).toFixed(1)}`).join('');
  return { strategy: path(a), hold: path(b) };
}

export function Sparkline({ points, label }: { points: CurvePoint[]; label: string }) {
  const { strategy, hold } = sparkPaths(points);
  if (!strategy) return <div className="spark spark-empty" role="img" aria-label={label}/>;
  return <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label}>
    <path className="spark-hold" d={hold}/>
    <path className="spark-line" d={strategy}/>
  </svg>;
}
