import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { PurchaseView } from './api';
import { PurchasePage } from './sections/Purchase';
import { charts } from './test/chartMock';
import { entry, instantListing, license, purchase } from './test/fixtures';
import { mount } from './test/mount';
import { flush, stubFetch, type Call } from './test/net';

vi.mock('lightweight-charts', async () => await import('./test/chartMock'));

let calls: Call[] = [];
let current: PurchaseView = purchase();
let points: number[][] = [[1_700_000_000, 1_000_000_000, 42_000_00000000]];

beforeEach(() => {
  charts.length = 0;
  calls = stubFetch((_m, path) => {
    if (path.startsWith('/api/purchases/')) return current;
    if (path.startsWith('/api/runs/7/points')) return { run_id: 7, quote: 'USDT', start_cash: 1_000_000_000, points };
    throw new Error(`unrouted ${path}`);
  });
});
afterEach(() => vi.unstubAllGlobals());

const steps = (host: HTMLElement) => [...host.querySelectorAll('.steps li')].map(li => `${li.className}:${li.textContent}`);

test('a hold purchase shows the five step timeline, live trial and a streaming chart', async () => {
  current = purchase();
  const view = await mount(<PurchasePage id="p_1"/>);
  await flush(6);
  expect(steps(view.host)).toHaveLength(5);
  expect(view.host.querySelector('.steps')?.className).toContain('n5');
  expect(view.host.textContent).toContain('Live trial on paper money');
  expect(view.host.querySelector('.stamp')).toBeNull();
  const equity = charts[0].series.find(s => s.kind === 'area')!;
  expect(equity.data).toHaveLength(1);
  expect(equity.lines.map(l => (l as { title: string }).title).sort()).toEqual(['Loss limit', 'Needs', 'Start']);
  expect(calls.some(c => c.path === '/api/purchases/p_1' && !c.body)).toBe(true);
  await view.unmount();
});

test('a failed trial is stamped VOIDED and never charged', async () => {
  current = purchase({ status: 'voided', run: { ...purchase().run!, status: 'dead', cause: 'loss_limit' }, verdict: { passed: false, cause: 'loss_limit', return_bps: -320, min_return_bps: -100, lifetime_s: 120, trades: 3, refusals: 0, explanation: 'It fell below the loss limit.' } });
  const view = await mount(<PurchasePage id="p_1"/>);
  await flush(6);
  expect(view.host.querySelector('.stamp-bad')?.textContent).toBe('VOIDED');
  expect(view.host.textContent).toContain('Voided, never charged');
  expect(view.host.textContent).toContain('It fell below the loss limit.');
  expect(view.host.querySelector('.license')).toBeNull();
  await view.unmount();
});

test('a passed hold purchase is stamped PAID and unlocks the license panel', async () => {
  current = purchase({ status: 'paid_out', paypal_capture_id: '…CAP123', license, run: { ...purchase().run!, status: 'dead', cause: 'expired' } });
  const view = await mount(<PurchasePage id="p_1"/>);
  await flush(6);
  expect(view.host.querySelector('.stamp-good')?.textContent).toBe('PAID');
  const license$ = view.host.querySelector('.license')!;
  expect(license$.textContent).toContain('PARABLE-AAAA-BBBB');
  const labels = [...license$.querySelectorAll('button')].map(b => b.textContent);
  expect(labels).toContain('Download JSON');
  expect(labels).toContain('Run on Parable');
  await view.unmount();
});

test('an instant purchase shows the short timeline: created, captured, paid out', async () => {
  current = purchase({ mode: 'instant', status: 'paid_out', listing: instantListing, run: null, paypal_capture_id: '…CAP123', license, threshold: { min_return_bps: 0, max_loss_bps: 0 } });
  const view = await mount(<PurchasePage id="p_1"/>);
  await flush(6);
  expect(steps(view.host)).toEqual(['done:1 · DoneOrder created', 'done:2 · DonePayment captured', 'done:3 · DoneSeller paid out']);
  expect(view.host.querySelector('.steps')?.className).toContain('n3');
  expect(view.host.querySelector('.stamp-good')?.textContent).toBe('PAID');
  expect(view.host.textContent).not.toContain('Live trial');
  await view.unmount();
});

test('an instant order that errored after capture offers a retry', async () => {
  current = purchase({ mode: 'instant', status: 'error', listing: instantListing, run: null, paypal_capture_id: '…CAP123', error: 'payout failed', timeline: [entry(1, 'payment.captured')] });
  const view = await mount(<PurchasePage id="p_1"/>);
  await flush(6);
  expect(steps(view.host).map(s => s.split(':')[0])).toEqual(['done', 'done', 'bad']);
  expect(view.host.textContent).toContain('payout failed');
  expect([...view.host.querySelectorAll('button')].some(b => b.textContent === 'Retry')).toBe(true);
  await view.unmount();
});

test('a purchase left in created sends the buyer back to PayPal', async () => {
  current = purchase({ status: 'created', run: null, approve_url: 'https://paypal.test/approve?order=O1' });
  const view = await mount(<PurchasePage id="p_1"/>);
  await flush(6);
  const link = [...view.host.querySelectorAll('a')].find(a => a.textContent === 'Continue in PayPal') as HTMLAnchorElement;
  expect(link.getAttribute('href')).toBe('https://paypal.test/approve?order=O1');
  current = purchase({ status: 'created', run: null });
  await view.unmount();
  const again = await mount(<PurchasePage id="p_1"/>);
  await flush(6);
  expect([...again.host.querySelectorAll('a')].some(a => a.textContent === 'Continue in PayPal')).toBe(false);
  await again.unmount();
});
