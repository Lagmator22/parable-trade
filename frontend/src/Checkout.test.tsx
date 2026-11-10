import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { Checkout } from './sections/Checkout';
import { listing, mockInfo } from './test/fixtures';
import { mount } from './test/mount';
import { savedPurchases } from './storage';

const created = { purchase_id: 'p_test', buyer_token: 'tok', paypal_order_id: 'MOCK-ORDER-1', approve_url: '/paypal/mock-approve?order=MOCK-ORDER-1' };

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

test('mock mode shows the simulated PayPal button and no SDK', async () => {
  const view = await mount(<Checkout listing={listing} info={mockInfo} onClose={() => {}}/>);
  const labels = [...view.host.querySelectorAll('button')].map(button => button.textContent);
  expect(labels).toContain('Pay with PayPal (simulated)');
  expect(view.host.textContent).toContain('Charged now');
  expect(document.querySelector('script[src*="paypal.com/sdk"]')).toBeNull();
  await view.unmount();
});

test('the simulated button creates the purchase and navigates to the approve url', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => JSON.stringify(created) });
  vi.stubGlobal('fetch', fetchMock);
  const navigate = vi.fn();
  const view = await mount(<Checkout listing={listing} info={mockInfo} onClose={() => {}} navigate={navigate}/>);
  const pay = [...view.host.querySelectorAll('button')].find(button => button.textContent === 'Pay with PayPal (simulated)');
  await view.click(pay!);
  expect(fetchMock).toHaveBeenCalledWith('/api/purchases', expect.objectContaining({ method: 'POST', body: JSON.stringify({ listing_id: listing.id }) }));
  expect(navigate).toHaveBeenCalledWith(created.approve_url);
  expect(savedPurchases()[0]).toMatchObject({ purchase_id: 'p_test', buyer_token: 'tok', listing_title: 'Momentum Mule' });
  await view.unmount();
});

test('shows the server error when the purchase cannot start', async () => {
  const failure = { ok: false, status: 404, text: async () => JSON.stringify({ detail: 'listing is paused' }) };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(failure));
  const navigate = vi.fn();
  const view = await mount(<Checkout listing={listing} info={mockInfo} onClose={() => {}} navigate={navigate}/>);
  const pay = [...view.host.querySelectorAll('button')].find(button => button.textContent === 'Pay with PayPal (simulated)');
  await view.click(pay!);
  expect(view.host.querySelector('[role=alert]')?.textContent).toBe('listing is paused');
  expect(navigate).not.toHaveBeenCalled();
  await view.unmount();
});
