import { expect, test } from 'vitest';
import { normalizePurchase, receiptsOf, tradesOf } from './purchase';
import { equityLines } from './equity';
import { listing, run } from './test/fixtures';
import type { LedgerEntry } from './api';

const entry = (seq: number, kind: string, data: Record<string, unknown> = {}): LedgerEntry => ({ seq, at: 1_700_000_100 + seq, kind, subject: 'run:7', data, prev_hash: '', hash: 'f'.repeat(64) });

test('normalizes flat and nested purchase fields', () => {
  const flat = normalizePurchase({ id: 'p_1', status: 'probation', listing, amount_cents: 2500, fee_cents: 250, paypal_order_id: 'O1', threshold: -100, timeline: [] });
  expect(flat).toMatchObject({ id: 'p_1', listingTitle: 'Momentum Mule', sellerName: 'Ada Seller', payoutCents: 2250, orderId: 'O1', minReturnBps: -100 });
  const nested = normalizePurchase({ purchase_id: 'p_2', status: 'paid_out', paypal: { capture_id: 'C1' }, payout_cents: 2000, threshold: { min_return_bps: 50 } });
  expect(nested).toMatchObject({ id: 'p_2', captureId: 'C1', payoutCents: 2000, minReturnBps: 50, listingTitle: 'Trading bot' });
});

test('splits the timeline into trades and receipts', () => {
  const timeline = [entry(1, 'purchase.created'), entry(2, 'run.trade'), entry(3, 'run.refused'), entry(4, 'purchase.authorized')];
  expect(tradesOf(timeline).map(item => item.seq)).toEqual([2, 3]);
  expect(receiptsOf(timeline).map(item => item.seq)).toEqual([1, 4]);
});

test('builds equity, start, minimum return and loss limit lines', () => {
  const timeline = [entry(2, 'run.trade', { equity_after: 1_004_000_000 })];
  const lines = equityLines(run, timeline, -100, 1_700_000_200);
  expect(lines.map(line => line.name)).toEqual(['Equity', 'Start', 'Min return', 'Loss limit']);
  expect(lines[0].points).toHaveLength(3);
  expect(lines[1].points[0][1]).toBe(1000);
  expect(lines[2].points[0][1]).toBeCloseTo(990, 5);
  expect(lines[3].points[0][1]).toBeCloseTo(979.7, 5);
});
