import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { ListingDetail } from './api';
import { AgentPage } from './sections/AgentPage';
import { instantListing, listing, proof } from './test/fixtures';
import { mount } from './test/mount';
import { flush, stubFetch, type Call } from './test/net';

vi.mock('lightweight-charts', async () => await import('./test/chartMock'));

const detail = (base = listing): ListingDetail => ({ ...base, proof, benchmark: null, proofs: [{ ...proof, id: 'pf_9', kind: 'rerun', matched: true, by: 'visitor' }], recent_runs: [] });
let calls: Call[] = [];
let current: ListingDetail = detail();

beforeEach(() => {
  calls = stubFetch((_m, path) => {
    if (path.startsWith('/api/listings/')) return current;
    if (path.startsWith('/api/runs/9/points')) return { run_id: 9, quote: 'USDT', start_cash: 1_000_000_000, points: [[1_700_000_000, 1_000_000_000, 42_000_00000000], [1_700_000_060, 1_010_000_000, 42_100_00000000]] };
    if (path.startsWith('/api/markets/popular')) return [];
    throw new Error(`unrouted ${path}`);
  });
});
afterEach(() => vi.unstubAllGlobals());

test('shows the proof, live track, re-run, test-drive and recent re-runs', async () => {
  current = detail();
  const onBuy = vi.fn();
  const view = await mount(<AgentPage id={listing.id} me={null} onBuy={onBuy}/>);
  await flush(6);
  const text = view.host.textContent ?? '';
  expect(text).toContain('Backtest proof');
  expect(text).toContain('Live track vs market');
  expect(text).toContain('1 of 2');
  expect(text).toContain('Re-run the proof');
  expect(text).toContain('Test-drive');
  expect(text).toContain('Recent re-runs');
  expect(view.host.querySelectorAll('[data-metric]').length).toBe(20);
  expect(calls.some(c => c.path.startsWith('/api/runs/9/points'))).toBe(true);
  await view.click([...view.host.querySelectorAll('button')].find(b => b.textContent === 'Buy')!);
  expect(onBuy).toHaveBeenCalled();
  await view.unmount();
});

test('sample and upload listings show no live track and no test-drive for uploads', async () => {
  current = detail({ ...instantListing, symbol: 'upload:d_ab12cd34ef', track: listing.track, data: { ...proof.data, source_kind: 'creator' } });
  const view = await mount(<AgentPage id={instantListing.id} me={null} onBuy={() => {}}/>);
  await flush(6);
  const text = view.host.textContent ?? '';
  expect(text).not.toContain('Live track vs market');
  expect(text).not.toContain('Test-drive');
  expect(text).toContain('Seller data');
  expect(calls.some(c => c.path.includes('/points'))).toBe(false);
  await view.unmount();
});

test('the owner sees their listing instead of a buy button', async () => {
  current = detail();
  const me = { seller: { id: listing.seller.id, name: 'Ada', verified: true, email_masked: 'a***' }, paypal_mode: 'mock' as const };
  const view = await mount(<AgentPage id={listing.id} me={me} onBuy={() => {}}/>);
  await flush(6);
  expect(view.host.textContent).toContain('Your listing');
  expect([...view.host.querySelectorAll('button')].some(b => b.textContent === 'Buy')).toBe(false);
  await view.unmount();
});
