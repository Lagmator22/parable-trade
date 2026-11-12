import { useEffect, useRef, useState } from 'react';
import type { Info, Me } from '../../api';
import { Button } from '../../components/ui/Button';
import {
  fetchDeal, fundDeal, orderDeal, refundDeal, releaseDeal, submitWork,
  type ChecklistKind, type Deal, type DealEvent, type DealStatus, type Verdict,
} from '../../dealsApi';
import { cents, clockTime, shortHash } from '../../format';
import { usePoll } from '../../hooks/usePoll';
import { loadPayPalSdk } from '../../paypalSdk';
import { DealStatusBadge } from './DealsPage';
import { MoneyFlow } from './MoneyFlow';

type Props = { id: string; me: Me | null; info: Info | null };
type StepState = 'done' | 'now' | 'todo' | 'bad';

const STEP_LABELS = ['Agent built', 'Money held', 'Work submitted', 'Agent check', 'Money moved'];
const KIND_BADGE: Record<ChecklistKind, string> = { ai: 'AI check', min_words: 'Min words', must_include: 'Must include' };
const EVENT_NAMES: Record<string, string> = {
  'deal.created': 'Agent checklist created', 'deal.funded': 'Money held by PayPal',
  'deal.submitted': 'Work submitted by freelancer', 'deal.checked': 'Agent checked the work',
  'deal.released': 'PayPal captured and paid freelancer', 'deal.returned': 'PayPal voided hold and returned money',
};

function stepStates(status: DealStatus, verdict: Verdict | null): StepState[] {
  if (status === 'draft') return ['done', 'now', 'todo', 'todo', 'todo'];
  if (status === 'funded') return ['done', 'done', 'now', 'todo', 'todo'];
  if (status === 'submitted') return ['done', 'done', 'done', verdict && !verdict.passed ? 'bad' : 'now', 'todo'];
  if (status === 'released') return ['done', 'done', 'done', 'done', 'done'];
  if (status === 'returned') return ['done', 'done', 'todo', 'todo', 'bad'];
  return ['done', 'done', 'done', 'done', 'bad'];
}

function CheckRun({ verdict, payoutCents, attempt }: { verdict: Verdict; payoutCents: number; attempt: number }) {
  return <div className={`box check-run ${verdict.passed ? 'passed' : 'failed'}`} key={attempt}>
    <div className="box-head"><strong>Agent check · Attempt {attempt}</strong><span className="mono">{verdict.summary}</span></div>
    <ul className="check-run-list" aria-label="Agent check results">
      {verdict.items.map((item, idx) => (
        <li key={item.id} className={`check-run-item ${item.pass ? 'is-pass' : 'is-fail'}`} style={{ animationDelay: `${idx * 350}ms` }}>
          <span className={`check-mark ${item.pass ? 'tick' : 'cross'}`} aria-label={item.pass ? 'Passed' : 'Failed'}>{item.pass ? '✓' : '✗'}</span>
          <div className="check-run-copy"><strong>{item.text}</strong><p className="mono muted">{item.reason}</p></div>
        </li>
      ))}
    </ul>
    <div className={`deal-stamp ${verdict.passed ? 'stamp-good' : 'stamp-bad'}`} role="status" style={{ animationDelay: `${verdict.items.length * 350}ms` }}>
      {verdict.passed ? `PAID ${cents(payoutCents)}` : `NOT YET — ${verdict.summary}`}
    </div>
  </div>;
}

function DealTimeline({ events }: { events: DealEvent[] }) {
  return <div className="box deal-timeline">
    <div className="box-head"><strong>Deal ledger</strong><a className="out-link" href="#ledger">Verify the ledger →</a></div>
    {events.length === 0 ? <p className="empty">No ledger events yet.</p> : (
      <div className="receipts">
        {events.map(ev => (
          <div key={ev.seq} className="row receipt">
            <time className="mono muted">{clockTime(ev.at)}</time>
            <span>{EVENT_NAMES[ev.kind] ?? ev.kind}</span>
            <span className="mono muted">#{ev.seq} {shortHash(ev.hash, 8)}</span>
          </div>
        ))}
      </div>
    )}
  </div>;
}

export function DealPage({ id, info }: Props) {
  const dot = id.indexOf('.');
  const dealId = dot === -1 ? id : id.slice(0, dot);
  const urlToken = dot === -1 ? '' : id.slice(dot + 1);

  const [override, setOverride] = useState<Deal | null>(null);
  const [workText, setWorkText] = useState('');
  const [workUrl, setWorkUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [copied, setCopied] = useState(false);
  const [confirmAction, setConfirmAction] = useState<'release' | 'refund' | null>(null);
  const [sdkReady, setSdkReady] = useState(false);
  const paypalHost = useRef<HTMLDivElement>(null);

  const polled = usePoll(() => fetchDeal(dealId, urlToken || undefined), {
    every: 2000, deps: [dealId, urlToken],
    stopWhen: d => d.status === 'released' || d.status === 'returned',
  });

  useEffect(() => { setOverride(null); }, [id]);

  const deal = override && (!polled.data || override.updated_at >= polled.data.updated_at) ? override : polled.data;
  const mocked = !info || info.paypal_mode === 'mock';
  const isClient = Boolean(deal && deal.role === 'client' && !urlToken);
  const isFreelancer = Boolean(deal && (Boolean(urlToken) || deal.role === 'freelancer'));
  const shareToken = urlToken || deal?.share_token || '';

  useEffect(() => {
    if (!deal || deal.status !== 'draft' || !isClient || mocked || !info?.paypal_client_id || !paypalHost.current) return;
    let cancelled = false;
    const host = paypalHost.current;
    loadPayPalSdk(info.paypal_client_id, 'authorize')
      .then(paypal => {
        if (cancelled) return;
        host.replaceChildren();
        return paypal.Buttons({
          style: { layout: 'vertical', shape: 'rect', label: 'pay' },
          createOrder: async () => (await orderDeal(dealId)).paypal_order_id,
          onApprove: async data => {
            const funded = await fundDeal(dealId, data.orderID);
            if (!cancelled) setOverride(funded);
          },
          onCancel: () => setActionError('PayPal checkout was cancelled.'),
          onError: () => setActionError('PayPal could not complete authorization.'),
        }).render(host).then(() => { if (!cancelled) setSdkReady(true); });
      })
      .catch(err => { if (!cancelled) setActionError(err instanceof Error ? err.message : 'PayPal SDK unavailable'); });
    return () => { cancelled = true; };
  }, [deal?.status, isClient, mocked, info?.paypal_client_id, dealId]);

  if (!deal) {
    return <section className="wrap page">
      <a className="out-link" href="#deals">← Deals</a>
      {polled.error ? <p className="say bad" role="alert">{polled.error}</p> : <p className="say">Loading deal…</p>}
    </section>;
  }

  const states = stepStates(deal.status, deal.verdict);
  const shareHash = `#deal/${deal.id}.${deal.share_token ?? ''}`;
  const shareUrl = `${window.location.origin}/${shareHash}`;
  const canSettle = deal.status === 'funded' || deal.status === 'submitted' || deal.status === 'error';
  const canSubmit = (deal.status === 'funded' || deal.status === 'submitted') && deal.attempts_left > 0;

  async function runAction(task: () => Promise<Deal>) {
    setBusy(true);
    setActionError('');
    try {
      setOverride(await task());
      setConfirmAction(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Action failed.');
    } finally {
      setBusy(false);
    }
  }

  function copyLink() {
    navigator.clipboard?.writeText(shareUrl).catch(() => undefined);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return <section className="wrap page stack deal-page">
    <a className="out-link" href="#deals">← Deals</a>

    <div className="purchase-head">
      <div>
        <h1 className="page-title">{deal.title}</h1>
        <p className="mono muted">{cents(deal.amount_cents)} · {cents(deal.payout_cents)} to freelancer ({cents(deal.fee_cents)} fee)</p>
      </div>
      <div className="pill-row"><DealStatusBadge status={deal.status}/></div>
    </div>

    <MoneyFlow status={deal.status} amountCents={deal.amount_cents} payoutCents={deal.payout_cents}/>

    <ol className="steps n5 deal-steps" aria-label="Deal progress">
      {STEP_LABELS.map((label, idx) => (
        <li key={label} className={states[idx]}>
          <span>{idx + 1} · {states[idx] === 'done' ? 'Done' : states[idx] === 'now' ? 'Now' : states[idx] === 'bad' ? 'Stopped' : 'Next'}</span>
          {label}
        </li>
      ))}
    </ol>

    {isClient && deal.status === 'draft' && (
      <div className="box deal-action-box">
        <div className="box-head"><strong>Hold the money with PayPal</strong><span>authorized, not captured yet</span></div>
        <div className="deal-box-body">
          <p>PayPal places a hold of {cents(deal.amount_cents)}. It only pays out when every check below passes.</p>
          {mocked ? (
            <div className="actions">
              <Button variant="solid" disabled={busy} onClick={() => runAction(async () => fundDeal(dealId, (await orderDeal(dealId)).paypal_order_id))}>
                {`Hold ${cents(deal.amount_cents)} with PayPal (simulated)`}
              </Button>
            </div>
          ) : (
            <div>
              {!sdkReady && <p className="say">Loading PayPal…</p>}
              <div ref={paypalHost} className="paypal-buttons" aria-label="PayPal checkout"/>
            </div>
          )}
        </div>
      </div>
    )}

    {isClient && deal.status !== 'draft' && deal.share_token && (
      <div className="box deal-share-box">
        <div className="box-head"><strong>Freelancer link</strong><span>send this to {deal.freelancer_email}</span></div>
        <div className="deal-box-body">
          <div className="share-url-row">
            <code className="share-url">{shareUrl}</code>
            <div className="actions">
              <Button variant="line" onClick={copyLink}>{copied ? 'Copied' : 'Copy link'}</Button>
              <a className="btn btn-quiet" href={shareHash} target="_blank" rel="noreferrer">Open as freelancer</a>
            </div>
          </div>
          {canSettle && (
            <div className="client-overrides">
              {confirmAction === null && (
                <div className="actions">
                  <Button variant="quiet" disabled={busy} onClick={() => setConfirmAction('release')}>Release anyway</Button>
                  <Button variant="quiet" disabled={busy} onClick={() => setConfirmAction('refund')}>Cancel and return money</Button>
                </div>
              )}
              {confirmAction === 'release' && (
                <div className="actions confirm-bar">
                  <span className="mono">Pay {cents(deal.payout_cents)} to {deal.freelancer_email} now?</span>
                  <Button variant="solid" disabled={busy} onClick={() => runAction(() => releaseDeal(dealId))}>Confirm release</Button>
                  <Button variant="quiet" disabled={busy} onClick={() => setConfirmAction(null)}>Back</Button>
                </div>
              )}
              {confirmAction === 'refund' && (
                <div className="actions confirm-bar">
                  <span className="mono">Void the PayPal hold and return {cents(deal.amount_cents)}?</span>
                  <Button variant="solid" disabled={busy} onClick={() => runAction(() => refundDeal(dealId))}>Confirm return</Button>
                  <Button variant="quiet" disabled={busy} onClick={() => setConfirmAction(null)}>Back</Button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    )}

    {isFreelancer && (
      <div className="box freelancer-panel">
        <div className="box-head">
          <strong>{cents(deal.amount_cents)} is held by PayPal for this job</strong>
          <span className="mono">{deal.attempts_left} {deal.attempts_left === 1 ? 'attempt' : 'attempts'} left</span>
        </div>
        <div className="deal-box-body">
          {deal.brief && <p className="deal-brief">{deal.brief}</p>}
          <ul className="deal-checklist-view">
            {deal.checklist.map(item => (
              <li key={item.id} className="deal-checklist-row">
                <span className={`kind-badge kind-${item.kind}`}>{KIND_BADGE[item.kind]}</span>
                <span>{item.text}</span>
                {item.value !== null && <code className="mono muted">({String(item.value)})</code>}
              </li>
            ))}
          </ul>
          {canSubmit && (
            <div className="deals-form">
              <label className="field">
                <span className="field-label">Your delivered work</span>
                <textarea rows={6} aria-label="Delivered work" value={workText} onChange={e => setWorkText(e.target.value)}
                  placeholder="Paste the finished work here for the agent to check..."/>
              </label>
              <label className="field">
                <span className="field-label">Optional link (https://)</span>
                <input type="url" aria-label="Optional link" value={workUrl} onChange={e => setWorkUrl(e.target.value)} placeholder="https://..."/>
              </label>
              <div className="actions">
                <Button variant="solid" disabled={busy || !workText.trim()}
                  onClick={() => runAction(() => submitWork(dealId, shareToken, workText, workUrl.trim() || undefined))}>
                  {busy ? 'Checking work…' : 'Submit work'}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    )}

    {!isFreelancer && (
      <div className="box">
        <div className="box-head"><strong>Acceptance checklist</strong><span className="mono muted">built by {deal.built_by || 'rules'}</span></div>
        <ul className="deal-checklist-view">
          {deal.checklist.map(item => (
            <li key={item.id} className="deal-checklist-row">
              <span className={`kind-badge kind-${item.kind}`}>{KIND_BADGE[item.kind]}</span>
              <span>{item.text}</span>
              {item.value !== null && <code className="mono muted">({String(item.value)})</code>}
            </li>
          ))}
        </ul>
      </div>
    )}

    {deal.verdict && <CheckRun verdict={deal.verdict} payoutCents={deal.payout_cents} attempt={deal.attempts}/>}

    {(deal.error || actionError) && <p className="say bad" role="alert">{actionError || deal.error}</p>}

    <DealTimeline events={deal.timeline ?? []}/>
  </section>;
}
