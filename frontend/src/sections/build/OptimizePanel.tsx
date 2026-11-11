import { useState } from 'react';
import { labOptimize, pollJob, type Job, type OptimizeResult, type OptimizeRow } from '../../api';
import { Button } from '../../components/ui/Button';
import type { Build } from './useBuild';

const pct = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;

export function OptimizePanel({ build }: { build: Build }) {
  const [job, setJob] = useState<Job<OptimizeResult> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const { spec, data } = build;
  const result: Partial<OptimizeResult> | null = job?.result ?? null;

  async function run() {
    if (!spec || !data) return;
    setBusy(true);
    setError('');
    setJob(null);
    try {
      const { job_id } = await labOptimize(spec, data, 8);
      await pollJob<OptimizeResult>(job_id, setJob);
    } catch (e) { setError(e instanceof Error ? e.message : 'Search failed'); }
    setBusy(false);
  }

  function use(row: OptimizeRow) {
    if (!spec) return;
    const params = { ...spec.params };
    for (const [k, v] of Object.entries(row.params)) if (params[k]) params[k] = { ...params[k], value: v };
    build.setSpec({ ...spec, params });
  }

  return <div className="panel">
    <div className="actions">
      <Button variant="solid" disabled={!spec || !data || build.validation?.ok !== true || busy} onClick={run}>{busy ? 'Searching' : 'Find best'}</Button>
      {job && <span className="mono say">{Math.round(job.progress * 100)}% {job.message}</span>}
    </div>
    {job && busy && <div className="lease"><span style={{ width: `${Math.round(job.progress * 100)}%` }}/></div>}
    {error && <p className="say bad" role="alert">{error}</p>}
    {result && Array.isArray(result.rows) && <div className="scroll-x"><table className="table leaderboard">
      <thead><tr><th>#</th><th>Settings</th><th>Train</th><th>Test</th><th>Drop</th><th></th></tr></thead>
      <tbody>
        {result.base && <tr className="base"><td>-</td><td>Current</td><td>{pct(result.base.train.total_return_pct)}</td><td>{pct(result.base.test.total_return_pct)}</td><td>-{result.base.test.max_drawdown_pct.toFixed(1)}%</td><td/></tr>}
        {result.rows.map((r, i) => <tr key={i}>
          <td>{i + 1}</td>
          <td>{Object.entries(r.params).map(([k, v]) => `${k} ${v}`).join(', ')}{r.overfit && <span className="badge warn">overfit</span>}</td>
          <td className={r.train.total_return_pct >= 0 ? 'up' : 'down'}>{pct(r.train.total_return_pct)}</td>
          <td className={r.test.total_return_pct >= 0 ? 'up' : 'down'}>{pct(r.test.total_return_pct)}</td>
          <td>-{r.test.max_drawdown_pct.toFixed(1)}%</td>
          <td><Button variant="quiet" onClick={() => use(r)}>Use</Button></td>
        </tr>)}
      </tbody>
    </table>
    {result.grid_size !== undefined && <p className="chart-note mono">{result.evaluated ?? result.rows.length}/{result.grid_size} tried. Train {result.train_bars ?? '-'} bars, test {result.test_bars ?? '-'} bars. Test is data the search never saw.</p>}</div>}
  </div>;
}
