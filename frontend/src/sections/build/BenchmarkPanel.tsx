import { useEffect, useMemo, useState } from 'react';
import { adoptBenchmark, fetchModels, pollJob, startBenchmark, type Benchmark, type BenchmarkRow, type ModelInfo } from '../../api';
import { hasOwnKey, loadAiSettings } from '../../aiSettings';
import { Button } from '../../components/ui/Button';
import { LiveChart } from '../../components/ui/LiveChart';
import type { Build } from './useBuild';

const COLORS = ['--orange', '--blue', '--green', '--ink', '--grey'];
type Live = Partial<Benchmark> & { rows: BenchmarkRow[] };
const pct = (v: number | undefined) => (v === undefined ? '-' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`);

export function BenchmarkPanel({ build }: { build: Build }) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [bench, setBench] = useState<Live | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const own = hasOwnKey(loadAiSettings());

  useEffect(() => {
    fetchModels().then(m => {
      const list = (own ? m.own : m.platform).filter(x => x.available);
      setModels(list);
      setPicked(list.slice(0, 3).map(x => x.id));
    }).catch(() => setModels([]));
  }, [own]);

  const series = useMemo(() => {
    if (!bench) return [];
    const rows = (bench.rows ?? []).filter(r => r.ok && r.curve.length).map((r, i) => ({
      id: r.model, kind: 'line' as const, name: r.model, color: COLORS[i % COLORS.length], data: r.curve.map(p => [p[0], p[1]] as [number, number]),
    }));
    return bench.buy_and_hold ? [...rows, { id: 'hold', kind: 'line' as const, name: 'Buy and hold', color: '--grey', dashed: true, data: bench.buy_and_hold.curve }] : rows;
  }, [bench]);

  async function run() {
    if (!build.spec || !build.data) return;
    setBusy(true);
    setError('');
    setBench(null);
    try {
      const agent = await build.ensureAgent();
      const { job_id } = await startBenchmark(agent, { steps: build.steps, models: picked, symbol: build.data.symbol, interval: build.data.interval, dataset_id: build.data.dataset_id });
      const done = await pollJob<Benchmark>(job_id, j => {
        setNote(`${Math.round(j.progress * 100)}% ${j.message}`);
        const partial = j.result as Partial<Benchmark> | null;
        if (partial && Array.isArray(partial.rows)) setBench({ ...partial, rows: partial.rows });
      });
      setBench(done);
    } catch (e) { setError(e instanceof Error ? e.message : 'Benchmark failed'); }
    setNote('');
    setBusy(false);
  }

  async function adopt(model: string) {
    if (!bench?.id || !bench.agent_id) return;
    try {
      const version = await adoptBenchmark(bench.id, model);
      build.adopt(version.spec, version.id, bench.agent_id);
      setNote(`Using ${model}.`);
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not use this model'); }
  }

  const toggle = (id: string) => setPicked(p => (p.includes(id) ? p.filter(x => x !== id) : p.length >= 6 ? p : [...p, id]));

  return <div className="panel">
    <div className="chip-row" aria-label="Models">
      {models.map(m => <button key={m.id} type="button" className="chip" aria-pressed={picked.includes(m.id)} onClick={() => toggle(m.id)}><b>{m.label}</b></button>)}
      {models.length === 0 && <span className="say">No models available.</span>}
    </div>
    <div className="actions">
      <Button variant="solid" disabled={!build.spec || !build.steps.trim() || picked.length === 0 || busy} onClick={run}>{busy ? 'Running' : 'Benchmark models'}</Button>
      {!build.steps.trim() && <span className="say">Describe your steps first.</span>}
      {note && <span className="mono say">{note}</span>}
    </div>
    {error && <p className="say bad" role="alert">{error}</p>}
    {bench && <>
      <LiveChart label="Model comparison" percent series={series}/>
      <div className="scroll-x"><table className="table">
        <thead><tr><th>Model</th><th>Return</th><th>Drop</th><th>Sharpe</th><th>Trades</th><th></th></tr></thead>
        <tbody>
          {bench.buy_and_hold && <tr className="base"><td>Buy and hold</td><td>{pct(bench.buy_and_hold.metrics.total_return_pct)}</td><td>-{bench.buy_and_hold.metrics.max_drawdown_pct.toFixed(1)}%</td><td>-</td><td>-</td><td/></tr>}
          {bench.rows.map(r => <tr key={r.model}>
            <td>{r.model}</td>
            {r.ok && r.metrics ? <>
              <td className={r.metrics.total_return_pct >= 0 ? 'up' : 'down'}>{pct(r.metrics.total_return_pct)}</td>
              <td>-{r.metrics.max_drawdown_pct.toFixed(1)}%</td><td>{r.metrics.sharpe.toFixed(2)}</td><td>{r.metrics.trades}</td>
              <td>{bench.id && <Button variant="quiet" onClick={() => adopt(r.model)}>Use</Button>}</td>
            </> : <td colSpan={5} className="down">{r.error || 'failed'}</td>}
          </tr>)}
        </tbody>
      </table></div>
    </>}
  </div>;
}
