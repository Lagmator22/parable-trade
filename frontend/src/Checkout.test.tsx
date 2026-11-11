import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { Me } from './api';
import { Checkout } from './sections/Checkout';
import { instantListing, listing, mockInfo } from './test/fixtures';
import { failure, stubFetch } from './test/net';
import { mount } from './test/mount';
import { takeReturn } from './signIn';

const created = { purchase_id: 'p_test', paypal_order_id: 'MOCK-ORDER-1', approve_url: '/paypal/mock-approve?order=MOCK-ORDER-1' };
const buyer: Me = { seller: { id: 's_buyer', name: 'Bo', verified: true, email_masked: 'b***' }, paypal_mode: 'mock' };
const signedOut: Me = { seller: null, paypal_mode: 'mock' };
const labels = (host: HTMLElement) => [...host.querySelectorAll('button')].map(button => button.textContent);

beforeEach(() => { sessionStorage.clear(); document.querySelectorAll('script[data-parable-paypal]').forEach(node => node.remove()); });
afterEach(() => vi.unstubAllGlobals());

test('hold mode in mock shows the simulated button, the hold and no SDK', async () => {
  const view = await mount(<Checkout listing={listing} info={mockInfo} me={buyer} onClose={() => {}}/>);
  expect(labels(view.host)).toContain('Pay with PayPal (simulated)');
  const text = view.host.textContent ?? '';
  expect(text).toContain('Charged now$0.00');
  expect(text).toContain('Held in PayPal');
  expect(text).toContain('Pay if proven');
  expect(document.querySelector('script[src*="paypal.com/sdk"]')).toBeNull();
  await view.unmount();
});

test('instant mode in mock charges now and creates the purchase then opens the approve url', async () => {
  const calls = stubFetch(() => created);
  const navigate = vi.fn();
  const view = await mount(<Checkout listing={instantListing} info={mockInfo} me={buyer} onClose={() => {}} navigate={navigate}/>);
  const text = view.host.textContent ?? '';
  expect(text).toContain('Charged now$25.00');
  expect(text).not.toContain('Held in PayPal');
  expect(text).toContain('Instant');
  await view.click([...view.host.querySelectorAll('button')].find(b => b.textContent === 'Pay with PayPal (simulated)')!);
  expect(calls[0]).toMatchObject({ method: 'POST', path: '/api/purchases', body: { listing_id: instantListing.id } });
  expect(navigate).toHaveBeenCalledWith(created.approve_url);
  await view.unmount();
});

test('signed out visitors are sent to PayPal login and come back', async () => {
  window.location.hash = '#agent/l_abc1234567';
  const navigate = vi.fn();
  const view = await mount(<Checkout listing={listing} info={mockInfo} me={signedOut} onClose={() => {}} navigate={navigate}/>);
  expect(labels(view.host)).not.toContain('Pay with PayPal (simulated)');
  await view.click([...view.host.querySelectorAll('button')].find(b => b.textContent === 'Sign in with PayPal')!);
  expect(navigate).toHaveBeenCalledWith('/paypal/login');
  expect(takeReturn()).toBe('#agent/l_abc1234567');
  await view.unmount();
});

test('the seller cannot buy their own listing', async () => {
  const owner: Me = { ...buyer, seller: { ...buyer.seller!, id: listing.seller.id } };
  const view = await mount(<Checkout listing={listing} info={mockInfo} me={owner} onClose={() => {}}/>);
  expect(labels(view.host)).not.toContain('Pay with PayPal (simulated)');
  expect(view.host.querySelector('[role=alert]')?.textContent).toContain('your own');
  await view.unmount();
});

test('real mode loads the SDK with authorize for hold and capture for instant', async () => {
  const live = { ...mockInfo, paypal_mode: 'sandbox' as const, paypal_client_id: 'CLIENT' };
  const hold = await mount(<Checkout listing={listing} info={live} me={buyer} onClose={() => {}}/>);
  expect(document.querySelector<HTMLScriptElement>('script[data-parable-paypal]')?.src).toContain('intent=authorize');
  await hold.unmount();
  const instant = await mount(<Checkout listing={instantListing} info={live} me={buyer} onClose={() => {}}/>);
  const scripts = document.querySelectorAll<HTMLScriptElement>('script[data-parable-paypal]');
  expect(scripts).toHaveLength(1);
  expect(scripts[0].src).toContain('intent=capture');
  await instant.unmount();
});

test('shows the server error when the purchase cannot start', async () => {
  stubFetch(() => { throw failure(404, 'listing is paused'); });
  const navigate = vi.fn();
  const view = await mount(<Checkout listing={listing} info={mockInfo} me={buyer} onClose={() => {}} navigate={navigate}/>);
  await view.click([...view.host.querySelectorAll('button')].find(b => b.textContent === 'Pay with PayPal (simulated)')!);
  expect(view.host.querySelector('[role=alert]')?.textContent).toBe('listing is paused');
  expect(navigate).not.toHaveBeenCalled();
  await view.unmount();
});
