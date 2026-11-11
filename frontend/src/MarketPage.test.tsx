import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { MarketPage } from './sections/MarketPage';
import { instantListing, listing } from './test/fixtures';
import { mount } from './test/mount';
import { flush, stubFetch, type Call } from './test/net';

const stats = { listings: 2, sellers: 1, runs_alive: 3, probations_running: 0, passed: 0, failed: 0, held_cents: 0, captured_cents: 0, voided_cents: 0, paid_out_cents: 4500, ledger_head: 'h', agents: 5, proofs: 9, reruns: 11 };
let calls: Call[] = [];

beforeEach(() => {
  calls = stubFetch((method, path, body) => {
    if (path.startsWith('/api/stats')) return stats;
    if (path.startsWith('/api/listings')) return [listing, instantListing];
    if (path === '/api/shopper') return { listing_id: instantListing.id, reason: 'Fits your budget.', alternatives: [], by: 'rules', echo: body };
    throw new Error(`unrouted ${method} ${path}`);
  });
});
afterEach(() => vi.unstubAllGlobals());

const press = (host: HTMLElement, text: string) => [...host.querySelectorAll('button')].find(b => b.textContent === text) as HTMLButtonElement;
const lastListings = () => calls.filter(c => c.path.startsWith('/api/listings')).pop()!.path;

test('shows live stats and the agent cards', async () => {
  const view = await mount(<MarketPage onBuy={() => {}}/>);
  await flush();
  const text = view.host.textContent ?? '';
  expect(text).toContain('Momentum Mule');
  expect(text).toContain('Instant Fox');
  expect(view.host.querySelector('.hero-stats')?.textContent).toContain('11');
  await view.unmount();
});

test('asset, mode and sort filters query the server', async () => {
  const view = await mount(<MarketPage onBuy={() => {}}/>);
  await flush();
  expect(lastListings()).toBe('/api/listings?sort=return');
  await view.click(press(view.host, 'Crypto'));
  await flush();
  expect(lastListings()).toBe('/api/listings?kind=crypto&sort=return');
  await view.click(press(view.host, 'Instant'));
  await flush();
  expect(lastListings()).toBe('/api/listings?kind=crypto&mode=instant&sort=return');
  await view.click(press(view.host, 'Cheapest'));
  await flush();
  expect(lastListings()).toBe('/api/listings?kind=crypto&mode=instant&sort=price');
  expect(press(view.host, 'Crypto').getAttribute('aria-pressed')).toBe('true');
  await view.unmount();
});

test('the buy button hands the listing to the checkout', async () => {
  const onBuy = vi.fn();
  const view = await mount(<MarketPage onBuy={onBuy}/>);
  await flush();
  await view.click([...view.host.querySelectorAll('button')].find(b => b.textContent?.startsWith('Buy'))!);
  expect(onBuy).toHaveBeenCalledWith(listing);
  await view.unmount();
});

test('the AI shopper recommends a listing from the market', async () => {
  const view = await mount(<MarketPage onBuy={() => {}}/>);
  await flush();
  const input = view.host.querySelector<HTMLInputElement>('.shopper-form input')!;
  const { act } = await import('react');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'something calm');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await view.click(press(view.host, 'Ask'));
  await flush();
  expect(calls.find(c => c.path === '/api/shopper')?.body).toMatchObject({ query: 'something calm' });
  expect(view.host.querySelector('.shopper-result')?.textContent).toContain('Fits your budget.');
  await view.unmount();
});
