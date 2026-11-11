import type { ProofView } from '../../api';
import { ago, pct, shortHash } from '../../format';

const KIND: Record<string, string> = { rerun: 'Re-run', testdrive: 'Test-drive', backtest: 'Backtest', benchmark: 'Benchmark' };

export function RecentProofs({ proofs }: { proofs: ProofView[] }) {
  return <section className="box agent-block" aria-label="Recent re-runs">
    <div className="box-head"><strong>Recent re-runs</strong><span>{proofs.length} shown</span></div>
    {proofs.length === 0 && <p className="empty">Nobody has re-run this yet. Be the first.</p>}
    {proofs.map(p => <div className="row proof-row" key={p.id}>
      <span>{KIND[p.kind] ?? p.kind}</span>
      <span className={p.matched === null ? 'muted' : p.matched ? 'up' : 'down'}>{p.matched === null ? '-' : p.matched ? '✓ match' : '✗ mismatch'}</span>
      <span>{pct(p.metrics.total_return_pct)}</span>
      <span className="muted" title={p.result_hash}>{shortHash(p.result_hash, 8)}</span>
      <span className="muted">{p.by} · {ago(p.created_at)}</span>
    </div>)}
  </section>;
}
