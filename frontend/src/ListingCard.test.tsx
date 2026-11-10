import { afterEach, expect, test, vi } from 'vitest';
import { ListingCard } from './sections/ListingCard';
import { listing, record } from './test/fixtures';
import { mount } from './test/mount';

afterEach(() => vi.unstubAllGlobals());

test('shows the listing terms, record and promise', async () => {
  const view = await mount(<ListingCard listing={listing} onBuy={() => {}}/>);
  const text = view.host.textContent ?? '';
  expect(text).toContain('Momentum Mule');
  expect(text).toContain('$25.00');
  expect(text).toContain('Ada Seller');
  expect(text).toContain('PayPal verified');
  expect(text).toContain('Gemini 3.5 Flash Lite');
  expect(text).toContain('Pays only if it survives 10 min and loses no more than 1.0%.');
  expect(text).toContain('75%');
  expect(text).toContain('-2.90%');
  expect(text).not.toContain('thin record');
  await view.unmount();
});

test('flags a thin record and hands the listing to the buy handler', async () => {
  const onBuy = vi.fn();
  const thin = { ...listing, seller_record: { ...record, runs: 1, ended: 1, survived: 1 } };
  const view = await mount(<ListingCard listing={thin} onBuy={onBuy}/>);
  expect(view.host.textContent).toContain('thin record');
  const buy = [...view.host.querySelectorAll('button')].find(button => button.textContent === 'Buy with PayPal');
  await view.click(buy!);
  expect(onBuy).toHaveBeenCalledWith(thin);
  await view.unmount();
});

test('loads the AI due diligence report when expanded', async () => {
  const report = { risk: 'medium', headline: 'Short record', findings: ['Only 8 runs'], red_flags: ['Pitch says guaranteed'], facts: {}, by: 'rules' };
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => JSON.stringify(report) });
  vi.stubGlobal('fetch', fetchMock);
  const view = await mount(<ListingCard listing={listing} onBuy={() => {}}/>);
  const toggle = [...view.host.querySelectorAll('button')].find(button => button.textContent === 'AI due diligence');
  await view.click(toggle!);
  expect(fetchMock).toHaveBeenCalledWith(`/api/listings/${listing.id}/diligence`, expect.anything());
  expect(view.host.textContent).toContain('medium risk');
  expect(view.host.textContent).toContain('Pitch says guaranteed');
  await view.unmount();
});
