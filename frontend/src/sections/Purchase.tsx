import { useState } from 'react';
import { fetchPurchase, retryPurchase } from '../api';
import { countdown, cents, signedBps, usdMicro } from '../format';
import { equityLines } from '../equity';
import { normalizePurchase, receiptsOf, tradesOf, type Purchase as PurchaseData } from '../purchase';
import { savedPurchase } from '../storage';
import { isSettled, passedOf, STATUS_LABEL } from '../steps';
import { Chart } from '../components/ui/Chart';
import { Button, LinkButton } from '../components/ui/Button';
import { Section } from '../components/ui/Section';
import { Refresh } from '../components/ui/Glyphs';
import { useNow } from '../hooks/useNow';
import { usePoll } from '../hooks/usePoll';
import { LicenseBox, Money, Receipts, Timeline, TradesFeed, VerdictBox } from './PurchaseParts';

export function StatusBadge({ status }: { status: PurchaseData['status'] }) {
  const passed = passedOf(status);
  const tone = status === 'error' || status === 'cancelled' || passed === false ? 'bad' : passed === true ? 'good' : 'neutral';
  return <span className={`badge status-${tone}`}>{STATUS_LABEL[status]}</span>;
}

type LiveRunProps = { purchase: PurchaseData; updatedAt: number };

function LiveRun({ purchase, updatedAt }: LiveRunProps) {
  const now = useNow();
  const run = purchase.run;
  if (!run) return null;
  const alive = run.status === 'alive';
  const left = alive ? Math.max(0, run.seconds_left - (now - updatedAt) / 1000) : 0;
  const total = run.rules.lease_seconds || purchase.probationS || 1;
  const progress = alive ? Math.min(100, Math.max(0, (1 - left / total) * 100)) : 100;
  const lines = equityLines(run, purchase.timeline, purchase.minReturnBps, now / 1000);
  return <div className="box">
    <div className="box-head">
      <span>{alive ? <><span className="live"/> Live probation on paper money</> : 'Probation finished'}</span>
      <span>{alive ? `${countdown(left)} left` : run.cause?.replace('_', ' ')}</span>
    </div>
    <dl className="stats run-stats">
      <div><dt>Equity</dt><dd>{usdMicro(run.final_equity_usd ?? run.equity_usd)}</dd></div>
      <div><dt>Return</dt><dd className={run.pnl_bps < 0 ? 'down' : 'up'}>{signedBps(run.pnl_bps)}</dd></div>
      <div><dt>Drawdown</dt><dd>{signedBps(-run.drawdown_bps)}</dd></div>
      <div><dt>Trades</dt><dd>{run.trades}</dd></div>
      <div><dt>Refusals</dt><dd className={run.refusals ? 'down' : ''}>{run.refusals}</dd></div>
    </dl>
    <div className="lease" aria-hidden="true"><span style={{ width: `${progress}%` }}/></div>
    <div className="chart-scroll">
      <Chart label="Bot equity against the start, the minimum return and the loss limit" lines={lines} zero={false}
        yFormat={value => `$${value.toFixed(2)}`} xFormat={x => new Date(x * 1000).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit' })}/>
    </div>
    <p className="chart-note">Passes if it survives to the end and finishes at {signedBps(purchase.minReturnBps)} or better. The referee ends it early if it falls below the loss limit.</p>
  </div>;
}

function Waiting({ purchase }: { purchase: PurchaseData }) {
  const approveUrl = savedPurchase(purchase.id)?.approve_url;
  return <div className="box waiting">
    <div className="box-head"><span>Waiting for your PayPal approval</span></div>
    <p className="verdict-text">PayPal has not confirmed this order yet. Nothing has been charged, and an order that is never approved is cancelled after three hours.</p>
    {approveUrl && <div className="actions"><LinkButton variant="solid" href={approveUrl}>Continue in PayPal</LinkButton></div>}
  </div>;
}

export function PurchasePage({ id }: { id: string }) {
  const token = savedPurchase(id)?.buyer_token;
  const [retrying, setRetrying] = useState(false);
  const { data, error, updatedAt, reload } = usePoll(
    async () => normalizePurchase(await fetchPurchase(id, token)),
    { every: 3000, deps: [id], stopWhen: purchase => isSettled(purchase.status) },
  );

  async function retry() {
    setRetrying(true);
    try { await retryPurchase(id); } finally { setRetrying(false); }
    await reload();
  }

  if (!data) return <Section id="purchase" label="Purchase"><BackLink/>{error ? <p className="say bad" role="alert">{error}</p> : <p className="say">Loading purchase…</p>}</Section>;
  const trades = tradesOf(data.timeline);
  return <Section id="purchase" label="Purchase">
    <BackLink/>
    <div className="purchase-head">
      <div><h2>{data.listingTitle}</h2><p className="mono muted">{data.sellerName && `by ${data.sellerName} · `}{cents(data.amountCents)}</p></div>
      <StatusBadge status={data.status}/>
    </div>
    <Timeline status={data.status}/>
    {data.status === 'created' && <Waiting purchase={data}/>}
    {data.status === 'error' && <div className="box failed">
      <div className="box-head"><strong>Settlement needs a retry</strong></div>
      <p className="verdict-text">{data.error || 'PayPal did not confirm the last step.'}</p>
      <div className="actions"><Button variant="solid" icon={<Refresh size={18}/>} disabled={retrying} onClick={retry}>Retry settlement</Button></div>
    </div>}
    <LiveRun purchase={data} updatedAt={updatedAt}/>
    <VerdictBox purchase={data}/>
    {data.license && <LicenseBox license={data.license}/>}
    {!data.license && !token && passedOf(data.status) && <p className="say">Open this page in the browser where you bought the bot to see the license key.</p>}
    <div className="purchase-cols">
      <Money purchase={data}/>
      <TradesFeed trades={trades}/>
    </div>
    <Receipts entries={receiptsOf(data.timeline)}/>
  </Section>;
}

function BackLink() {
  return <a className="out-link" href="#purchases">← My purchases</a>;
}
