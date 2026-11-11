import { useState } from 'react';
import { ApiError, rerunProof, type Metrics, type PublicListing, type RerunResult } from '../../api';
import { pct, shortHash } from '../../format';
import { Button } from '../../components/ui/Button';
import { Stamp } from '../../components/Pills';

const ROWS: [keyof Metrics, string, (v: number) => string][] = [
  ['total_return_pct', 'Return', v => pct(v, 2)],
  ['max_drawdown_pct', 'Worst drop', v => `-${v.toFixed(2)}%`],
  ['sharpe', 'Sharpe', v => v.toFixed(2)],
  ['trades', 'Trades', v => String(v)],
  ['win_rate_pct', 'Win rate', v => `${v.toFixed(0)}%`],
];

function Side({ title, view }: { title: string; view: RerunResult['claim'] }) {
  return <div className="rerun-side">
    <h4>{title}</h4>
    <dl>
      {ROWS.map(([key, label, fmt]) => <div key={key}><dt>{label}</dt><dd>{fmt(view.metrics[key] as number)}</dd></div>)}
      <div><dt>Result hash</dt><dd title={view.result_hash}>{shortHash(view.result_hash, 12)}</dd></div>
      <div><dt>Data hash</dt><dd title={view.data.data_hash}>{shortHash(view.data.data_hash, 12)}</dd></div>
    </dl>
  </div>;
}

export function RerunPanel({ listing, onDone }: { listing: PublicListing; onDone?: () => void }) {
  const [result, setResult] = useState<RerunResult | null>(null);
  const [fresh, setFresh] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const canRefetch = !listing.symbol.startsWith('upload:') && !listing.symbol.startsWith('sample:');

  async function run() {
    setBusy(true);
    setError('');
    try {
      setResult(await rerunProof(listing.id, fresh && canRefetch));
      onDone?.();
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 429 ? 'Too many re-runs this hour. Try later.' : failure instanceof Error ? failure.message : 'Re-run failed');
    }
    setBusy(false);
  }

  const mismatched = result ? Object.entries(result.diff).filter(([, d]) => d.claim !== d.rerun) : [];
  return <section className="box agent-block" aria-label="Re-run the proof">
    <div className="box-head"><strong>Re-run the proof</strong><span>free, no key, nothing is trusted</span></div>
    <div className="block-body">
      <div className="actions">
        <Button variant="solid" disabled={busy} onClick={run}>{busy ? 'Running' : 'Re-run the proof'}</Button>
        {canRefetch && <label className="check"><input type="checkbox" checked={fresh} onChange={e => setFresh(e.target.checked)}/> Fetch the data again</label>}
      </div>
      {error && <p className="say bad" role="alert">{error}</p>}
      {result && <div className="rerun" aria-live="polite">
        <Stamp tone={result.match ? 'good' : 'bad'}>{result.match ? '✓ MATCH' : '✗ MISMATCH'}</Stamp>
        <div className="rerun-cols">
          <Side title="Seller's claim" view={result.claim}/>
          <Side title="Your re-run" view={result.rerun}/>
        </div>
        {result.data_hash_match !== null && <p className={`say ${result.data_hash_match ? '' : 'bad'}`}>
          {result.data_hash_match ? 'Fresh data is identical to the proof data.' : 'Fresh data differs from the proof data, so numbers can differ.'}
        </p>}
        {mismatched.length > 0 && <p className="say bad">Differs: {mismatched.map(([k]) => k.replace(/_/g, ' ')).join(', ')}</p>}
      </div>}
    </div>
  </section>;
}
