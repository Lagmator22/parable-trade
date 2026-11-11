import type { Stats } from '../api';
import { cents } from '../format';

export const headHash = (stats: Stats | null) => {
  const head = stats?.ledger_head;
  return typeof head === 'string' ? head : head?.hash ?? '';
};

const num = (value: number | undefined) => (value === undefined ? '-' : String(value));

export function Hero({ stats }: { stats: Stats | null }) {
  return <section className="mk-hero">
    <div className="wrap">
      <h1>Trading agents that show their proof.</h1>
      <p className="lead">Re-run the backtest yourself. Watch the live track. Pay only when you are sure.</p>
      <dl className="hero-stats">
        <div><dt>Agents</dt><dd>{num(stats?.agents ?? stats?.listings)}</dd></div>
        <div><dt>Proofs re-run</dt><dd>{num(stats?.reruns)}</dd></div>
        <div><dt>Live now</dt><dd>{num(stats?.runs_alive)}</dd></div>
        <div><dt>Paid out</dt><dd>{stats ? cents(stats.paid_out_cents) : '-'}</dd></div>
      </dl>
    </div>
  </section>;
}
