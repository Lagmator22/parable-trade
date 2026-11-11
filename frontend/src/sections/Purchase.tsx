import { useState } from 'react';
import { fetchPurchase, retryPurchase, type PurchaseView } from '../api';
import { cents, countdown, signedBps } from '../format';
import { receiptsOf, thresholdLines, tradesOf } from '../purchase';
import { isSettled, passedOf, stampOf, STATUS_LABEL } from '../steps';
import { Button } from '../components/ui/Button';
import { Refresh } from '../components/ui/Glyphs';
import { ModePill, Stamp } from '../components/Pills';
import { useNow } from '../hooks/useNow';
import { usePoll } from '../hooks/usePoll';
import { RunChart } from './agent/RunChart';
import { LicensePanel } from './PurchaseLicense';
import { Money, Receipts, Timeline, TradesFeed, VerdictBox } from './PurchaseParts';

export function StatusBadge({ status }: { status: PurchaseView['status'] }) {
  const passed = passedOf(status);
  const tone = status === 'error' || status === 'cancelled' || passed === false ? 'bad' : passed === true ? 'good' : 'neutral';
  return <span className={`badge status-${tone}`}>{STATUS_LABEL[status]}</span>;
}

function LiveRun({ purchase, updatedAt }: { purchase: PurchaseView; updatedAt: number }) {
  const now = useNow();
  const run = purchase.run;
  if (!run) return null;
  const alive = run.status === 'alive';
  const left = alive ? Math.max(0, run.seconds_left - (now - updatedAt) / 1000) : 0;
  const total = run.lifetime_s || run.seconds_left || 1;
  const progress = alive ? Math.min(100, Math.max(0, (1 - left / total) * 100)) : 100;
  return <div className="box">
    <div className="box-head">
      <span>{alive ? <><span className="live"/> Live trial on paper money</> : 'Trial finished'}</span>
      <span>{alive ? `${countdown(left)} left` : String(run.cause ?? '').replace('_', ' ')}</span>
    </div>
    <dl className="stats run-stats">
      <div><dt>Return</dt><dd className={run.pnl_bps < 0 ? 'down' : 'up'}>{signedBps(run.pnl_bps)}</dd></div>
      <div><dt>Needs</dt><dd>{signedBps(purchase.threshold.min_return_bps)}</dd></div>
      <div><dt>Drop</dt><dd>{signedBps(-run.drawdown_bps)}</dd></div>
      <div><dt>Trades</dt><dd>{run.trades}</dd></div>
      <div><dt>Refused</dt><dd className={run.refusals ? 'down' : ''}>{run.refusals}</dd></div>
    </dl>
    <div className="lease" aria-hidden="true"><span style={{ width: `${progress}%` }}/></div>
    <div className="block-body">
      <RunChart runId={run.id} alive={alive} label="Agent equity during the trial" lines={thresholdLines(purchase)} every={2000}/>
    </div>
  </div>;
}

function Waiting({ purchase }: { purchase: PurchaseView }) {
  return <div className="box waiting">
    <div className="box-head"><span>Waiting for your PayPal approval</span></div>
    <p className="verdict-text">Nothing has been charged. An order that is never approved is cancelled.</p>
    <div className="actions"><a className="btn btn-solid" href={`#agent/${purchase.listing.id}`}><span>Back to the agent</span></a></div>
  </div>;
}

function BackLink() {
  return <a className="out-link" href="#purchases">← My purchases</a>;
}

export function PurchasePage({ id }: { id: string }) {
  const [retrying, setRetrying] = useState(false);
  const { data, error, updatedAt, reload } = usePoll(() => fetchPurchase(id), { every: 3000, deps: [id], stopWhen: purchase => isSettled(purchase.status) });

  async function retry() {
    setRetrying(true);
    try { await retryPurchase(id); } finally { setRetrying(false); }
    await reload();
  }

  if (!data) return <section className="wrap page"><BackLink/>{error ? <p className="say bad" role="alert">{error}</p> : <p className="say">Loading</p>}</section>;
  const stamp = stampOf(data.status);
  const quote = data.listing.quote;
  return <section className="wrap page stack">
    <BackLink/>
    <div className="purchase-head">
      <div><h1 className="page-title">{data.listing.title}</h1><p className="mono muted">by {data.listing.seller.name} · {cents(data.amount_cents)}</p></div>
      <div className="pill-row"><ModePill mode={data.mode}/><StatusBadge status={data.status}/></div>
    </div>
    <Timeline purchase={data}/>
    {stamp && <Stamp tone={stamp.tone}>{stamp.text}</Stamp>}
    {data.status === 'created' && <Waiting purchase={data}/>}
    {data.status === 'error' && <div className="box failed">
      <div className="box-head"><strong>Needs a retry</strong></div>
      <p className="verdict-text">{data.error || 'PayPal did not confirm the last step.'}</p>
      <div className="actions"><Button variant="solid" icon={<Refresh size={18}/>} disabled={retrying} onClick={retry}>Retry</Button></div>
    </div>}
    <LiveRun purchase={data} updatedAt={updatedAt}/>
    <VerdictBox purchase={data}/>
    <LicensePanel purchase={data}/>
    <div className="purchase-cols">
      <Money purchase={data}/>
      <TradesFeed trades={tradesOf(data.timeline)} quote={quote}/>
    </div>
    <Receipts entries={receiptsOf(data.timeline)}/>
  </section>;
}
