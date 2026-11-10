import type { LedgerEntry, License, PurchaseStatus, Run, Verdict } from './api';

export type Purchase = {
  id: string;
  status: PurchaseStatus;
  listingId: string;
  listingTitle: string;
  sellerName: string;
  amountCents: number;
  feeCents: number;
  payoutCents: number;
  minReturnBps: number;
  probationS: number;
  orderId: string;
  authorizationId: string;
  captureId: string;
  payoutBatchId: string;
  payoutStatus: string;
  error: string;
  run: Run | null;
  verdict: Verdict | null;
  timeline: LedgerEntry[];
  license: License | null;
  createdAt: number;
};

type Raw = Record<string, any>;

const text = (...values: unknown[]) => values.find(value => typeof value === 'string' && value) as string | undefined ?? '';
const number = (...values: unknown[]) => values.find(value => typeof value === 'number' && Number.isFinite(value)) as number | undefined ?? 0;

function thresholdOf(raw: Raw, listing: Raw): number {
  const threshold = raw.threshold;
  if (typeof threshold === 'number') return threshold;
  return number(threshold?.min_return_bps, raw.min_return_bps, listing.min_return_bps, raw.verdict?.min_return_bps);
}

function payoutOf(raw: Raw, amount: number, fee: number): number {
  return number(raw.payout_cents, raw.seller_payout_cents, raw.payout?.amount_cents, amount - fee);
}

export function normalizePurchase(raw: unknown): Purchase {
  const data = raw as Raw;
  const listing: Raw = data.listing ?? {};
  const paypal: Raw = data.paypal ?? {};
  const amount = number(data.amount_cents, data.amount);
  const fee = number(data.fee_cents, data.fee);
  return {
    id: text(data.id, data.purchase_id),
    status: (text(data.status) || 'created') as PurchaseStatus,
    listingId: text(listing.id, data.listing_id),
    listingTitle: text(listing.title, data.listing_title, 'Trading bot'),
    sellerName: text(listing.seller?.name, listing.seller_name, data.seller_name),
    amountCents: amount,
    feeCents: fee,
    payoutCents: payoutOf(data, amount, fee),
    minReturnBps: thresholdOf(data, listing),
    probationS: number(listing.probation_s, data.probation_s),
    orderId: text(data.paypal_order_id, paypal.order_id),
    authorizationId: text(data.paypal_authorization_id, paypal.authorization_id),
    captureId: text(data.paypal_capture_id, paypal.capture_id),
    payoutBatchId: text(data.paypal_payout_batch_id, paypal.payout_batch_id),
    payoutStatus: text(data.payout_status, paypal.payout_status),
    error: text(data.error, data.error_message),
    run: data.run ?? null,
    verdict: data.verdict ?? null,
    timeline: Array.isArray(data.timeline) ? data.timeline : [],
    license: data.license ?? null,
    createdAt: number(data.created_at),
  };
}

export const tradesOf = (timeline: LedgerEntry[]) => timeline.filter(entry => entry.kind === 'run.trade' || entry.kind === 'run.refused');

export const receiptsOf = (timeline: LedgerEntry[]) => timeline.filter(entry => entry.kind !== 'run.trade' && entry.kind !== 'run.refused');
