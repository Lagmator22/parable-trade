import { useMemo } from 'react';
import type { BenchmarkPublic } from '../../api';
import { pct } from '../../format';
import { LiveChart } from '../../components/ui/LiveChart';

const COLORS = ['--orange', '--blue', '--green', '--ink'];

export function BenchmarkTable({ benchmark }: { benchmark: BenchmarkPublic }) {
  const rows = benchmark.rows.filter(r => r.ok && r.metrics);
  const series = useMemo(() => [
    ...rows.filter(r => r.curve.length).map((r, i) => ({ id: r.model, kind: 'line' as const, name: r.model, color: COLORS[i % COLORS.length], data: r.curve.map(p => [p[0], p[1]] as [number, number]) })),
    { id: 'hold', kind: 'line' as const, name: 'Buy and hold', color: '--grey', dashed: true, data: benchmark.buy_and_hold.curve },
  ], [benchmark]);
  const hold = benchmark.buy_and_hold.metrics;
  return <section className="box agent-block" aria-label="Model benchmark">
    <div className="box-head"><strong>Same strategy, different AI models</strong><span>{benchmark.data.bars} bars</span></div>
    <div className="block-body">
      <LiveChart label="Model benchmark equity curves" percent series={series}/>
      <div className="scroll-x"><table className="table">
        <thead><tr><th>Model</th><th>Return</th><th>Worst drop</th><th>Sharpe</th></tr></thead>
        <tbody>
          <tr className="base"><td>Buy and hold</td><td>{pct(hold.total_return_pct)}</td><td>-{hold.max_drawdown_pct.toFixed(1)}%</td><td>-</td></tr>
          {benchmark.rows.map(r => <tr key={r.model}>
            <td>{r.model}</td>
            {r.ok && r.metrics
              ? <><td className={r.metrics.total_return_pct >= 0 ? 'up' : 'down'}>{pct(r.metrics.total_return_pct)}</td><td>-{r.metrics.max_drawdown_pct.toFixed(1)}%</td><td>{r.metrics.sharpe.toFixed(2)}</td></>
              : <td colSpan={3} className="down">failed</td>}
          </tr>)}
        </tbody>
      </table></div>
    </div>
  </section>;
}
