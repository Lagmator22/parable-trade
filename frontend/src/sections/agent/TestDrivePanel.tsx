import { useEffect, useState } from 'react';
import { fetchPopular, testDrive, type PublicListing, type SymbolInfo, type TestDriveResult } from '../../api';
import { pct } from '../../format';
import { Button } from '../../components/ui/Button';
import { ProofChart } from '../../components/ProofChart';
import { MetricsGrid } from '../../components/MetricsGrid';

const BASE_INTERVALS = ['1h', '4h', '1d'];
export const intervalChoices = (own: string) => (BASE_INTERVALS.includes(own) ? BASE_INTERVALS : [own, ...BASE_INTERVALS]);
const seconds = (day: string) => (day ? Math.floor(new Date(`${day}T00:00:00Z`).getTime() / 1000) : undefined);

export function TestDrivePanel({ listing }: { listing: PublicListing }) {
  const [symbol, setSymbol] = useState(listing.symbol);
  const [interval, setInterval] = useState(listing.interval);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [popular, setPopular] = useState<SymbolInfo[]>([]);
  const [result, setResult] = useState<TestDriveResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { fetchPopular(listing.kind).then(list => setPopular(list.slice(0, 6))).catch(() => setPopular([])); }, [listing.kind]);

  async function run() {
    setBusy(true);
    setError('');
    try {
      setResult(await testDrive(listing.id, { symbol, interval, start: seconds(from), end: seconds(to) }));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Test-drive failed');
    }
    setBusy(false);
  }

  const tested = result?.proof;
  return <section className="box agent-block" aria-label="Test-drive">
    <div className="box-head"><strong>Test-drive</strong><span>try other dates or another market, free</span></div>
    <div className="block-body">
      <div className="chip-row" aria-label="Markets">
        {[listing.symbol, ...popular.map(p => p.symbol).filter(s => s !== listing.symbol)].map(s => <button key={s} type="button" className="chip" aria-pressed={symbol === s} onClick={() => setSymbol(s)}><b>{s.split(':').pop()}</b></button>)}
      </div>
      <div className="td-form">
        <div className="toggle" role="group" aria-label="Interval">
          {intervalChoices(listing.interval).map(i => <button key={i} type="button" aria-pressed={interval === i} onClick={() => setInterval(i)}>{i}</button>)}
        </div>
        <label className="field"><span className="field-label">From</span><input type="date" value={from} onChange={e => setFrom(e.target.value)}/></label>
        <label className="field"><span className="field-label">To</span><input type="date" value={to} onChange={e => setTo(e.target.value)}/></label>
        <Button variant="solid" disabled={busy} onClick={run}>{busy ? 'Running' : 'Test-drive'}</Button>
      </div>
      {error && <p className="say bad" role="alert">{error}</p>}
      {tested && result && <div aria-live="polite">
        <p className="say mono">{tested.symbol} · {tested.interval}: {pct(tested.metrics.total_return_pct)} vs claim {pct(result.claim.metrics.total_return_pct)}</p>
        <ProofChart curve={tested.curve} quote={tested.data.quote} label="Test-drive" percent/>
        <MetricsGrid metrics={tested.metrics} quote={tested.data.quote} compact/>
      </div>}
    </div>
  </section>;
}
