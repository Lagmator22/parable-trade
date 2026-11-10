import type { Stats } from '../api';
import { cents, shortHash } from '../format';
import { LinkButton } from '../components/ui/Button';
import { Lock } from '../components/ui/Glyphs';

export const headHash = (stats: Stats | null) => {
  const head = stats?.ledger_head;
  return typeof head === 'string' ? head : head?.hash ?? '';
};

function Fact({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span>{value}</div>;
}

export function Hero({ stats, ethPrice }: { stats: Stats | null; ethPrice: number | undefined }) {
  const hash = headHash(stats);
  return <section className="section hero" id="top">
    <div className="wrap">
      <div>
        <h1>Pay for an AI trading bot only if it survives.</h1>
        <p className="lead">PayPal holds your money while a referee runs the bot on live prices with paper cash. If it survives its probation and keeps its promise, you pay. If not, the hold is voided and you are never charged.</p>
        <div className="actions">
          <LinkButton variant="solid" href="#market">Browse bots</LinkButton>
          <LinkButton href="#sell">Sell a bot</LinkButton>
          <LinkButton variant="quiet" icon={<Lock size={18}/>} href="#ledger">Public ledger</LinkButton>
        </div>
      </div>
      <dl className="counts box">
        <div><dt>Passed, paid out</dt><dd className="up">{stats?.passed ?? '–'}</dd></div>
        <div className="dead"><dt>Failed, never charged</dt><dd>{stats?.failed ?? '–'}</dd></div>
      </dl>
    </div>
    <div className="wrap facts">
      <Fact label="Held in PayPal right now" value={stats ? cents(stats.held_cents) : '–'}/>
      <Fact label="Paid out to sellers" value={stats ? cents(stats.paid_out_cents) : '–'}/>
      <Fact label="Voided, never charged" value={stats ? cents(stats.voided_cents) : '–'}/>
      <Fact label="Probations running" value={stats ? String(stats.probations_running) : '–'}/>
      <Fact label="Ledger head" value={hash ? `${shortHash(hash, 12)}…` : '–'}/>
      <Fact label="ETH/USD paper price" value={ethPrice ? `$${ethPrice.toLocaleString('en-US', { maximumFractionDigits: 2 })}` : '–'}/>
    </div>
  </section>;
}
