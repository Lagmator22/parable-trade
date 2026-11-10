import { useState } from 'react';
import type { LedgerEntry, License } from '../api';
import { brainName, cents, clockTime, mask, priceFromRaw, shortHash, signedBps, strategyName, usdFloat, usdMicro, bpsShort, dateTime } from '../format';
import { buildSteps, kindLabel, type StepState } from '../steps';
import type { Purchase } from '../purchase';
import { Copy } from '../components/ui/Glyphs';

const stateText: Record<StepState, string> = { done: 'Done', now: 'In progress', todo: 'Waiting', bad: 'Stopped' };

export function Timeline({ status }: { status: Purchase['status'] }) {
  return <ol className="steps five-steps" aria-label="Purchase progress">
    {buildSteps(status).map((step, index) => <li key={step.label} className={step.state}>
      <span>{index + 1} · {stateText[step.state]}</span>{step.label}
    </li>)}
  </ol>;
}

const asNumber = (value: unknown) => (typeof value === 'number' ? value : 0);

export function TradeRow({ entry }: { entry: LedgerEntry }) {
  const refused = entry.kind === 'run.refused';
  const side = String(entry.data.side ?? '').toUpperCase();
  const reason = String(entry.data.reason ?? entry.data.error ?? '');
  return <div className={`row trade ${refused ? 'refused' : ''}`}>
    <time>{clockTime(entry.at)}</time>
    <span>{refused ? `REFUSED ${side}`.trim() : side}</span>
    <span>{usdMicro(asNumber(entry.data.amount_usd))}{entry.data.price ? ` @ ${usdFloat(priceFromRaw(asNumber(entry.data.price)))}` : ''}</span>
    <span className="reason">{reason}</span>
  </div>;
}

export function TradesFeed({ trades }: { trades: LedgerEntry[] }) {
  const newestFirst = [...trades].sort((a, b) => b.seq - a.seq);
  return <div className="box">
    <div className="box-head"><span>Trades and refusals, with the bot’s reason</span><span>{trades.length} shown</span></div>
    {newestFirst.length === 0 && <p className="empty">The bot has not traded yet.</p>}
    <div className="trades">{newestFirst.map(entry => <TradeRow key={entry.seq} entry={entry}/>)}</div>
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

export function Money({ purchase }: { purchase: Purchase }) {
  return <div className="box">
    <div className="box-head"><span>Money and PayPal references</span></div>
    <dl className="kv">
      <div><dt>Price</dt><dd>{cents(purchase.amountCents)}</dd></div>
      <div><dt>Platform fee</dt><dd>{cents(purchase.feeCents)}</dd></div>
      <div><dt>Seller payout</dt><dd>{cents(purchase.payoutCents)}</dd></div>
      <IdRow label="PayPal order" value={purchase.orderId}/>
      <IdRow label="Authorization" value={purchase.authorizationId}/>
      <IdRow label="Capture" value={purchase.captureId}/>
      <IdRow label="Payout batch" value={purchase.payoutBatchId}/>
      <IdRow label="Payout status" value={purchase.payoutStatus}/>
    </dl>
  </div>;
}

export function VerdictBox({ purchase }: { purchase: Purchase }) {
  const verdict = purchase.verdict;
  if (!verdict) return null;
  return <div className={`box verdict ${verdict.passed ? 'passed' : 'failed'}`}>
    <div className="box-head"><strong>{verdict.passed ? 'Passed' : 'Failed'}</strong><span>decided by a fixed rule, never by AI</span></div>
    <p className="verdict-text">{verdict.explanation}</p>
    <dl className="kv">
      <div><dt>Ended by</dt><dd>{verdict.cause.replace('_', ' ')}</dd></div>
      <div><dt>Return</dt><dd>{signedBps(verdict.return_bps)}</dd></div>
      <div><dt>Required</dt><dd>{signedBps(verdict.min_return_bps)}</dd></div>
      <div><dt>Trades</dt><dd>{verdict.trades}</dd></div>
      <div><dt>Refusals</dt><dd>{verdict.refusals}</dd></div>
    </dl>
  </div>;
}

export function LicenseBox({ license }: { license: License }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(license.key);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return <div className="box license">
    <div className="box-head"><strong>Your license</strong><span>unlocked because the bot survived</span></div>
    <div className="license-key mono">
      <code>{license.key}</code>
      <button type="button" className="link-btn" onClick={copy}><Copy size={16}/>{copied ? 'Copied' : 'Copy'}</button>
    </div>
    <dl className="kv">
      <div><dt>Brain</dt><dd>{brainName(license.bot.brain)}</dd></div>
      <div><dt>Strategy</dt><dd>{strategyName(license.bot.strategy)}</dd></div>
      <div><dt>Loss limit</dt><dd>{bpsShort(license.bot.max_loss_bps)}</dd></div>
      <div><dt>Max trade</dt><dd>{usdMicro(license.bot.max_trade_usd)}</dd></div>
      <div><dt>Fingerprint</dt><dd>{license.fingerprint}</dd></div>
    </dl>
    <p className="say">{license.instructions}</p>
  </div>;
}

