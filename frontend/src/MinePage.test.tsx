import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { Me } from './api';
import { MinePage } from './sections/MinePage';
import { license, purchase } from './test/fixtures';
import { mount } from './test/mount';
import { flush, stubFetch, type Call } from './test/net';

vi.mock('lightweight-charts', async () => await import('./test/chartMock'));

const me: Me = { seller: { id: 's_1', name: 'Ada', verified: true, email_masked: 'a***' }, paypal_mode: 'mock' };
const mine = {
  built: [
    { id: 'a_draft', name: 'Draft Dog', symbol: 'binance:ETHUSDT', interval: '1h', status: 'draft', latest_version_id: 'v_1', listing_id: null, updated_at: 1, headline: null },
    { id: 'a_live', name: 'Listed Lynx', symbol: 'binance:BTCUSDT', interval: '1d', status: 'listed', latest_version_id: 'v_2', listing_id: 'l_9', updated_at: 2, headline: { total_return_pct: 8.2 } },
  ],
  bought: [
    { purchase_id: 'p_1', listing_id: 'l_5', title: 'Bought Bear', mode: 'instant', status: 'paid_out', spec_hash: 'c'.repeat(64), symbol: 'binance:BTCUSDT', interval: '1h', entitled: true },
    { purchase_id: 'p_2', listing_id: 'l_6', title: 'Held Hare', mode: 'hold', status: 'probation', spec_hash: 'd'.repeat(64), symbol: 'binance:BTCUSDT', interval: '1h', entitled: false },
  ],
};
let calls: Call[] = [];

beforeEach(() => {
  calls = stubFetch((method, path) => {
    if (path === '/api/me/agents') return mine;
    if (path === '/api/me/sales') return [{ listing_id: 'l_9', title: 'Listed Lynx', mode: 'hold', purchases: 3, captured_cents: 5000, paid_out_cents: 4500 }];
    if (path === '/api/purchases/p_1/run' && method === 'POST') return { id: 11, status: 'alive' };
    if (path.startsWith('/api/runs/11/points')) return { run_id: 11, quote: 'USDT', start_cash: 1_000_000_000, points: [[1, 1_000_000_000, 100_00000000]] };
    if (path === '/api/purchases/p_1') return purchase({ license });
    throw new Error(`unrouted ${method} ${path}`);
  });
});
afterEach(() => vi.unstubAllGlobals());

const press = (host: HTMLElement, text: string) => [...host.querySelectorAll('button, a')].find(b => b.textContent === text) as HTMLElement;

test('signed out visitors are asked to sign in', async () => {
  const view = await mount(<MinePage me={{ seller: null, paypal_mode: 'mock' }}/>);
  expect(view.host.textContent).toContain('Sign in');
  expect(calls).toHaveLength(0);
  await view.unmount();
});

test('built shows drafts and listed agents with sales and links', async () => {
  const view = await mount(<MinePage me={me}/>);
  await flush();
  const text = view.host.textContent ?? '';
  expect(text).toContain('Draft Dog');
  expect(text).toContain('Draft');
  expect(text).toContain('Listed Lynx');
  expect(text).toContain('+8.2%');
  expect(text).toContain('3 sold');
  const opens = [...view.host.querySelectorAll('a')].filter(a => a.textContent === 'Open in Build').map(a => a.getAttribute('href'));
  expect(opens).toEqual(['#build/a_draft', '#build/a_live']);
  expect(view.host.querySelector('a[href="#agent/l_9"]')).not.toBeNull();
  await view.unmount();
});

test('bought lets an entitled buyer go live and download', async () => {
  const view = await mount(<MinePage me={me}/>);
  await flush();
  await view.click(press(view.host, 'Bought 2'));
  const text = view.host.textContent ?? '';
  expect(text).toContain('Bought Bear');
  expect(text).toContain('Held Hare');
  expect(view.host.querySelectorAll('.mine-row')).toHaveLength(2);
  expect([...view.host.querySelectorAll('button')].filter(b => b.textContent === 'Go live')).toHaveLength(1);
  await view.click(press(view.host, 'Go live'));
  await flush();
  expect(calls.some(c => c.method === 'POST' && c.path === '/api/purchases/p_1/run')).toBe(true);
  expect(calls.some(c => c.path.startsWith('/api/runs/11/points'))).toBe(true);
  expect(press(view.host, 'Stop')).toBeDefined();
  await view.unmount();
});
