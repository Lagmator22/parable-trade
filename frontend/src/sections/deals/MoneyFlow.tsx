import type { DealStatus } from '../../dealsApi';
import { cents } from '../../format';

type Props = {
  status: DealStatus;
  amountCents?: number;
  payoutCents?: number;
  amount_cents?: number;
  payout_cents?: number;
};

export function MoneyFlow({ status, amountCents, payoutCents, amount_cents, payout_cents }: Props) {
  const amount = amountCents ?? amount_cents ?? 0;
  const payout = payoutCents ?? payout_cents ?? amount;
  const held = status === 'funded' || status === 'submitted' || status === 'error';
  const stage = status === 'released' ? 'released' : status === 'returned' ? 'returned' : held ? 'held' : 'draft';
  const label =
    status === 'released'
      ? `PAID ${cents(payout)}`
      : status === 'returned'
        ? 'RETURNED'
        : held
          ? `HELD ${cents(amount)}`
          : `READY ${cents(amount)}`;

  return (
    <div className={`box money-flow status-${status} flow-${stage}`} data-status={status}>
      <div className="money-nodes">
        <div className={`money-node node-client ${status === 'draft' || status === 'returned' ? 'active' : ''}`}>
          <span className="node-role">01</span>
          <strong>Client</strong>
          <span className="mono muted">{status === 'returned' ? 'Refunded' : cents(amount)}</span>
        </div>
        <div className={`money-node node-paypal ${held ? 'active' : ''}`}>
          <span className="node-role">02</span>
          <strong>PayPal</strong>
          <span className="mono muted">{held ? `Holding ${cents(amount)}` : 'Escrow hold'}</span>
        </div>
        <div className={`money-node node-freelancer ${status === 'released' ? 'active' : ''}`}>
          <span className="node-role">03</span>
          <strong>Freelancer</strong>
          <span className="mono muted">{ cents(payout) } payout</span>
        </div>
      </div>
      <div className="money-track" aria-label="Payment state track">
        <div className="money-rail"/>
        <div className={`money-dot dot-${status} dot-${stage}`}>
          <span className="money-dot-core"/>
          <span className="money-dot-label mono">{label}</span>
        </div>
      </div>
    </div>
  );
}
