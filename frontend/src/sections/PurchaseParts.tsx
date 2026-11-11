import type { LedgerEntry, PurchaseView } from '../api';
import { cents, clockTime, dateTime, mask, shortHash, signedBps } from '../format';
import { buildSteps, kindLabel, type StepState } from '../steps';

const stateText: Record<StepState, string> = { done: 'Done', now: 'Now', todo: 'Next', bad: 'Stopped' };

export function Timeline({ purchase }: { purchase: PurchaseView }) {
  const steps = buildSteps(purchase.status, purchase.mode, Boolean(purchase.paypal_capture_id));
  return <ol className={`steps n${steps.length}`} aria-label="Purchase progress">
    {steps.map((step, index) => <li key={step.label} className={step.state}>
      <span>{index + 1} · {stateText[step.state]}</span>{step.label}
    </li>)}
  </ol>;
}

const asNumber = (value: unknown) => (typeof value === 'number' ? value : 0);

export function TradeRow({ entry, quote }: { entry: LedgerEntry; quote: string }) {
  const refused = entry.kind === 'run.refused';
  const side = String(entry.data.side ?? '').toUpperCase();
  const reason = String(entry.data.reason ?? entry.data.error ?? '');
  const amount = asNumber(entry.data.amount) / 1_000_000;
  const price = asNumber(entry.data.price) / 1e8;
  return <div className={`row trade ${refused ? 'refused' : ''}`}>
    <time>{clockTime(entry.at)}</time>
    <span>{refused ? `REFUSED ${side}`.trim() : side}</span>
    <span>{amount.toLocaleString(undefined, { maximumFractionDigits: 2 })} {quote}{price ? ` @ ${price.toLocaleString(undefined, { maximumFractionDigits: 4 })}` : ''}</span>
    <span className="reason">{reason}</span>
  </div>;
}

export function TradesFeed({ trades, quote }: { trades: LedgerEntry[]; quote: string }) {
  const newestFirst = [...trades].sort((a, b) => b.seq - a.seq);
  return <div className="box">
    <div className="box-head"><span>Trades and refusals, with reasons</span><span>{trades.length} shown</span></div>
    {newestFirst.length === 0 && <p className="empty">No trades yet.</p>}
    <div className="trades">{newestFirst.map(entry => <TradeRow key={entry.seq} entry={entry} quote={quote}/>)}</div>
  </div>;
}

export function Receipts({ entries }: { entries: LedgerEntry[] }) {
  return <div className="box">
    <div className="box-head"><span>On the public ledger</span><a href="#ledger" className="out-link">Verify chain</a></div>
    <div className="receipts">
      {entries.map(entry => <div className="row receipt" key={entry.seq}>
        <time>{dateTime(entry.at)}</time>
        <span>{kindLabel(entry.kind)}</span>
        <span className="mono muted">#{entry.seq} {shortHash(entry.hash, 8)}</span>
      </div>)}
    </div>
  </div>;
}

function IdRow({ label, value }: { label: string; value: string }) {
  return value ? <div><dt>{label}</dt><dd title={value}>{mask(value)}</dd></div> : null;
}

export function Money({ purchase }: { purchase: PurchaseView }) {
  return <div className="box">
    <div className="box-head"><span>Money</span></div>
    <dl className="kv">
      <div><dt>Price</dt><dd>{cents(purchase.amount_cents)}</dd></div>
      <div><dt>Platform fee</dt><dd>{cents(purchase.fee_cents)}</dd></div>
      <div><dt>Seller payout</dt><dd>{cents(purchase.payout_cents)}</dd></div>
      <IdRow label="PayPal order" value={purchase.paypal_order_id}/>
      <IdRow label="Authorization" value={purchase.paypal_authorization_id}/>
      <IdRow label="Capture" value={purchase.paypal_capture_id}/>
      <IdRow label="Payout batch" value={purchase.paypal_payout_batch_id}/>
      <IdRow label="Payout status" value={purchase.payout_status}/>
    </dl>
  </div>;
}

export function VerdictBox({ purchase }: { purchase: PurchaseView }) {
  const verdict = purchase.verdict;
  if (!verdict) return null;
  return <div className={`box verdict ${verdict.passed ? 'passed' : 'failed'}`}>
    <div className="box-head"><strong>{verdict.passed ? 'Passed' : 'Failed'}</strong><span>a fixed rule decides, never AI</span></div>
    <p className="verdict-text">{verdict.explanation}</p>
    <dl className="kv">
      <div><dt>Ended by</dt><dd>{String(verdict.cause).replace('_', ' ')}</dd></div>
      <div><dt>Return</dt><dd>{signedBps(verdict.return_bps)}</dd></div>
      <div><dt>Needed</dt><dd>{signedBps(verdict.min_return_bps)}</dd></div>
      <div><dt>Trades</dt><dd>{verdict.trades}</dd></div>
      <div><dt>Refusals</dt><dd>{verdict.refusals}</dd></div>
    </dl>
  </div>;
}
