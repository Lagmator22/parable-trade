export type Line = { name: string; color: string; dashed?: boolean; points: [number, number][] };

const W = 820, H = 260, LEFT = 68, RIGHT = 190, TOP = 14, BOTTOM = 28;

export function Chart({ lines, yFormat, xFormat, label, zero = false }: {
  lines: Line[]; yFormat: (v: number) => string; xFormat: (x: number) => string; label: string; zero?: boolean;
}) {
  const drawn = lines.filter(l => l.points.length > 0);
  if (drawn.length === 0) return null;
  const xs = drawn.flatMap(l => l.points.map(p => p[0]));
  const ys = drawn.flatMap(l => l.points.map(p => p[1]));
  if (zero) ys.push(0);
  let [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  if (x1 === x0) x1 = x0 + 1;
  const padY = (y1 - y0) * 0.12 || Math.max(Math.abs(y1) * 0.01, 1);
  y0 -= padY; y1 += padY;
  const sx = (x: number) => LEFT + ((x - x0) / (x1 - x0)) * (W - LEFT - RIGHT);
  const sy = (y: number) => TOP + (1 - (y - y0) / (y1 - y0)) * (H - TOP - BOTTOM);
  const ticks = [0, 1, 2, 3].map(i => y0 + ((y1 - y0) * i) / 3);
  const ends = drawn.map(l => ({ l, y: sy(l.points[l.points.length - 1][1]) })).sort((a, b) => a.y - b.y);
  ends.forEach((e, i) => { if (i > 0 && e.y - ends[i - 1].y < 15) e.y = ends[i - 1].y + 15; });

  return <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ height: 'auto' }}>
    {ticks.map(t => <g key={t}><line className="grid" x1={LEFT} x2={W - RIGHT} y1={sy(t)} y2={sy(t)}/>
      <text x={LEFT - 8} y={sy(t) + 4} textAnchor="end">{yFormat(t)}</text></g>)}
    {zero && y0 < 0 && y1 > 0 && <line className="zero" x1={LEFT} x2={W - RIGHT} y1={sy(0)} y2={sy(0)}/>}
    <text x={LEFT} y={H - 8}>{xFormat(x0)}</text>
    <text x={W - RIGHT} y={H - 8} textAnchor="end">{xFormat(x1)}</text>
    {drawn.map(l => <path key={l.name} d={l.points.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(' ')}
      style={{ stroke: l.color, strokeDasharray: l.dashed ? '5 4' : undefined }}/>)}
    {ends.map(({ l, y }) => <text key={l.name} x={W - RIGHT + 8} y={y + 4} style={{ fill: l.color }}>
      {l.name.length > 18 ? `${l.name.slice(0, 17)}…` : l.name} {yFormat(l.points[l.points.length - 1][1])}</text>)}
  </svg>;
}

export const PALETTE = ['var(--ink)', 'var(--orange)', 'var(--blue)', 'var(--green)', 'var(--grey)'];
