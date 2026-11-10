import { useEffect, useState } from 'react';
import { fetchCandles, labBacktest, type Bar } from '../../api';
import { MetricsGrid } from '../../components/MetricsGrid';
import { ProofChart } from '../../components/ProofChart';
import { Button } from '../../components/ui/Button';
import type { Build } from './useBuild';

export function BacktestPanel({ build }: { build: Build }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [bars, setBars] = useState<Bar[]>([]);
  const { spec, data, result } = build;
  const valid = build.validation?.ok === true;

  useEffect(() => {
    if (!result || !data?.symbol || !data.interval) return;
    fetchCandles(data.symbol, data.interval, data.limit ?? 2000).then(c => setBars(c.bars)).catch(() => setBars([]));
  }, [result?.result_hash]);

  async function run() {
    if (!spec || !data) return;
    setBusy(true);
    setError('');
    try { build.setResult(await labBacktest(spec, data)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Backtest failed'); }
    setBusy(false);
  }

  return <div className="panel">
    <div className="actions">
      <Button variant="solid" disabled={!spec || !data || !valid || busy} onClick={run}>{busy ? 'Running' : 'Backtest'}</Button>
      {!valid && spec && <span className="say bad">Fix the formulas first.</span>}
    </div>
    {error && <p className="say bad" role="alert">{error}</p>}
    {result && <>
      <MetricsGrid metrics={result.metrics} quote={result.quote}/>
      <ProofChart curve={result.curve} markers={result.markers} bars={bars} quote={result.quote} label="Backtest"/>
      <p className="chart-note mono">{result.data.bars} bars, {result.trades.length} trades, {result.data.source_kind} data, hash {result.result_hash.slice(0, 10)}</p>
    </>}
  </div>;
}
